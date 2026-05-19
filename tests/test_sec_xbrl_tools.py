"""Unit tests for the pure period/concept-extraction logic in
`app/tools/sec_xbrl_tools.py`. The network-bound `fetch_companyfacts` is
not covered here (per the project convention for network code).
"""

from __future__ import annotations

import pytest

from app.tools.sec_xbrl_tools import (
    _fiscal_year_from_end,
    is_annual_period,
    is_quarterly_period,
    is_instant_at_fy_end,
    is_instant_any,
    extract_period_values,
    extract_quarterly_cash_flow,
    extract_quarterly_values,
    detect_mna_jumps,
)


# ===== _fiscal_year_from_end =====

def test_fiscal_year_calendar_year_end_dec_31():
    assert _fiscal_year_from_end("2024-12-31") == 2024


def test_fiscal_year_52_week_january_end_maps_to_prior_year():
    """QDEL/QuidelOrtho-style: 52-week year ending Sunday near Dec 31 →
    end falls in early January of next calendar year."""
    assert _fiscal_year_from_end("2022-01-02") == 2021  # QDEL FY2021
    assert _fiscal_year_from_end("2023-01-01") == 2022  # QDEL FY2022 (post-Ortho)


def test_fiscal_year_late_december_end_unchanged():
    assert _fiscal_year_from_end("2024-12-29") == 2024  # 53-week year
    assert _fiscal_year_from_end("2025-12-28") == 2025


def test_fiscal_year_september_end_for_apple_style():
    assert _fiscal_year_from_end("2024-09-28") == 2024


def test_fiscal_year_returns_none_for_unparseable():
    assert _fiscal_year_from_end("") is None
    assert _fiscal_year_from_end("garbage") is None
    assert _fiscal_year_from_end(None) is None


# ===== is_annual_period / is_quarterly_period / is_instant_at_fy_end =====

def test_annual_period_recognizes_calendar_year():
    assert is_annual_period({"start": "2024-01-01", "end": "2024-12-31"})


def test_annual_period_recognizes_52_week_fiscal_year():
    # Many companies use a 52- or 53-week fiscal year that doesn't align with calendar.
    assert is_annual_period({"start": "2024-01-29", "end": "2025-01-26"})


def test_annual_period_rejects_quarter():
    assert not is_annual_period({"start": "2024-01-01", "end": "2024-03-31"})


def test_annual_period_rejects_instant_record():
    # Instant records (balance-sheet items) have no `start`.
    assert not is_annual_period({"end": "2024-12-31"})


def test_annual_period_rejects_malformed_dates():
    assert not is_annual_period({"start": "not-a-date", "end": "2024-12-31"})


def test_quarterly_period_recognizes_typical_quarter():
    assert is_quarterly_period({"start": "2024-01-01", "end": "2024-03-31"})


def test_quarterly_period_rejects_full_year():
    assert not is_quarterly_period({"start": "2024-01-01", "end": "2024-12-31"})


def test_instant_recognizes_balance_sheet_record():
    # No `start` → it's a point-in-time snapshot.
    assert is_instant_at_fy_end({"end": "2024-12-31"})
    assert is_instant_any({"end": "2024-09-30"})


def test_instant_rejects_period_record():
    assert not is_instant_at_fy_end({"start": "2024-01-01", "end": "2024-12-31"})


# ===== extract_period_values =====

def _facts(concept_data: dict, unit: str = "USD") -> dict:
    """Build a minimal SEC-shape facts dict for testing."""
    return {
        "us-gaap": {
            concept: {"units": {unit: records}}
            for concept, records in concept_data.items()
        }
    }


def test_extract_period_values_returns_empty_for_unknown_concepts():
    facts = _facts({"Revenues": []})
    assert extract_period_values(facts, ["NonExistentConcept"]) == {}


def test_extract_period_values_filters_to_annual_records():
    facts = _facts({
        "Revenues": [
            # Annual record
            {"start": "2023-01-01", "end": "2023-12-31", "val": 1000.0, "filed": "2024-02-01", "fy": 2023, "form": "10-K"},
            # Quarterly record (should be excluded under default is_annual_period)
            {"start": "2023-01-01", "end": "2023-03-31", "val": 250.0, "filed": "2023-05-01", "fy": 2023, "form": "10-K"},
        ],
    })
    result = extract_period_values(facts, ["Revenues"])
    assert set(result.keys()) == {2023}
    assert result[2023]["val"] == 1000.0
    assert result[2023]["concept"] == "Revenues"


def test_extract_period_values_uses_end_date_not_filing_fy():
    """The `fy` field reflects the filing context, not the data point's
    period. The extractor must derive the fiscal year from the period's
    end date (via `_fiscal_year_from_end`), not from `fy`."""
    facts = _facts({
        "Revenues": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 1000.0,
             "filed": "2025-02-01", "fy": 2024, "form": "10-K"},  # fy=2024 but data is for FY2023
            {"start": "2024-01-01", "end": "2024-12-31", "val": 1200.0,
             "filed": "2025-02-01", "fy": 2024, "form": "10-K"},
        ],
    })
    result = extract_period_values(facts, ["Revenues"])
    assert result[2023]["val"] == 1000.0
    assert result[2024]["val"] == 1200.0


def test_extract_period_values_keys_52week_january_ends_to_prior_fy():
    """QDEL-style 52-week fiscal year: FY2021 ends 2022-01-02 — must be
    keyed under 2021, not 2022, so the FY2022 closing balance (end
    2023-01-01) doesn't collide and stays under 2022."""
    facts = _facts({
        "LongTermDebt": [
            # FY2021 closing (pre-Ortho-merger Quidel)
            {"end": "2022-01-02", "val": 300_000.0,
             "filed": "2023-02-23", "fy": 2022, "form": "10-K"},
            # FY2022 closing (post-Ortho-merger combined entity)
            {"end": "2023-01-01", "val": 2_648_900_000.0,
             "filed": "2023-02-23", "fy": 2022, "form": "10-K"},
        ],
    }, unit="USD")
    result = extract_period_values(facts, ["LongTermDebt"], period_filter=is_instant_at_fy_end)
    # The small pre-merger value lands under FY2021, the post-merger value under FY2022.
    assert result[2021]["val"] == 300_000.0
    assert result[2022]["val"] == 2_648_900_000.0


def test_extract_period_values_dedupes_keeping_latest_filed():
    """Same period appears in multiple filings (original 10-K + later amendments).
    Latest-filed should win."""
    facts = _facts({
        "Revenues": [
            {"start": "2022-01-01", "end": "2022-12-31", "val": 900.0,
             "filed": "2023-02-15", "fy": 2022, "form": "10-K"},
            # Later amendment with restated value
            {"start": "2022-01-01", "end": "2022-12-31", "val": 950.0,
             "filed": "2024-08-01", "fy": 2022, "form": "10-K/A"},
        ],
    })
    result = extract_period_values(facts, ["Revenues"])
    assert result[2022]["val"] == 950.0
    assert result[2022]["filed"] == "2024-08-01"


def test_extract_period_values_merges_concepts_for_asc_606_cutover():
    """Companies often switch from 'Revenues' (pre-2018) to
    'RevenueFromContractWithCustomerExcludingAssessedTax' (post-2018).
    Passing both concepts in order should stitch into continuous coverage."""
    facts = _facts({
        "Revenues": [
            {"start": "2016-01-01", "end": "2016-12-31", "val": 100.0,
             "filed": "2017-02-01", "fy": 2016, "form": "10-K"},
            {"start": "2017-01-01", "end": "2017-12-31", "val": 110.0,
             "filed": "2018-02-01", "fy": 2017, "form": "10-K"},
        ],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [
            {"start": "2018-01-01", "end": "2018-12-31", "val": 130.0,
             "filed": "2019-02-01", "fy": 2018, "form": "10-K"},
            {"start": "2019-01-01", "end": "2019-12-31", "val": 145.0,
             "filed": "2020-02-01", "fy": 2019, "form": "10-K"},
        ],
    })
    result = extract_period_values(facts, [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    ])
    assert set(result.keys()) == {2016, 2017, 2018, 2019}
    assert result[2016]["concept"] == "Revenues"
    assert result[2018]["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_extract_period_values_with_instant_filter_for_balance_sheet():
    facts = _facts({
        "Assets": [
            # Instant: no `start`
            {"end": "2023-12-31", "val": 500.0, "filed": "2024-02-01", "fy": 2023, "form": "10-K"},
            {"end": "2024-12-31", "val": 600.0, "filed": "2025-02-01", "fy": 2024, "form": "10-K"},
        ],
    })
    result = extract_period_values(
        facts, ["Assets"], period_filter=is_instant_at_fy_end,
    )
    assert result[2023]["val"] == 500.0
    assert result[2024]["val"] == 600.0


def test_extract_period_values_filters_by_form_prefix():
    facts = _facts({
        "Revenues": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 1000.0,
             "filed": "2024-02-01", "fy": 2023, "form": "10-K"},
            # 8-K (interim release) — should be excluded
            {"start": "2023-01-01", "end": "2023-12-31", "val": 999.0,
             "filed": "2024-01-15", "fy": 2023, "form": "8-K"},
        ],
    })
    result = extract_period_values(facts, ["Revenues"], form_prefix="10-K")
    assert result[2023]["val"] == 1000.0


# ===== extract_quarterly_values =====

def test_extract_quarterly_values_keys_by_end_date_string():
    facts = _facts({
        "Revenues": [
            {"start": "2024-01-01", "end": "2024-03-31", "val": 250.0,
             "filed": "2024-05-01", "fy": 2024, "fp": "Q1", "form": "10-Q"},
            {"start": "2024-04-01", "end": "2024-06-30", "val": 260.0,
             "filed": "2024-08-01", "fy": 2024, "fp": "Q2", "form": "10-Q"},
        ],
    })
    result = extract_quarterly_values(facts, ["Revenues"])
    assert set(result.keys()) == {"2024-03-31", "2024-06-30"}
    assert result["2024-03-31"]["val"] == 250.0


def test_extract_quarterly_values_accepts_10k_filings_too():
    """10-K filings sometimes include quarterly breakouts (especially Q4)."""
    facts = _facts({
        "Revenues": [
            {"start": "2024-10-01", "end": "2024-12-31", "val": 280.0,
             "filed": "2025-02-01", "fy": 2024, "fp": "Q4", "form": "10-K"},
        ],
    })
    result = extract_quarterly_values(facts, ["Revenues"])
    assert result["2024-12-31"]["val"] == 280.0


# ===== detect_mna_jumps =====

def test_mna_jumps_detects_large_isolated_spike():
    # 100, 110, 5000, 120 → 2022 is a clear spike (50x neighbors)
    values = {2020: 100, 2021: 110, 2022: 5000, 2023: 120}
    flagged = detect_mna_jumps(values, ratio_threshold=2.0)
    assert flagged == [2022]


def test_mna_jumps_ignores_smooth_growth():
    # 100, 110, 121, 133 → smooth ~10% growth, nothing flagged
    values = {2020: 100, 2021: 110, 2022: 121, 2023: 133}
    assert detect_mna_jumps(values, ratio_threshold=2.0) == []


def test_mna_jumps_skips_endpoints():
    # Endpoints can't be flagged (no neighbor on one side)
    values = {2020: 5000, 2021: 100, 2022: 110, 2023: 5000}
    assert detect_mna_jumps(values, ratio_threshold=2.0) == []


def test_mna_jumps_handles_zero_neighbors_gracefully():
    values = {2020: 0, 2021: 1000, 2022: 0}
    # Doesn't crash on division-by-zero
    detect_mna_jumps(values)


# ===== extract_quarterly_cash_flow (YTD differencing) =====

def _cf_record(start, end, val, filed="2025-04-30", form="10-Q"):
    return {"start": start, "end": end, "val": float(val), "filed": filed, "form": form, "fy": int(end[:4])}


def test_cash_flow_q1_only_passes_through():
    """A fiscal year with just Q1 filed → discrete Q1, no derivation needed."""
    facts = _facts({"NetCashProvidedByUsedInOperatingActivities": [
        _cf_record("2025-01-01", "2025-03-31", 100),  # Q1 only
    ]})
    out = extract_quarterly_cash_flow(facts, ["NetCashProvidedByUsedInOperatingActivities"])
    assert list(out.keys()) == ["2025-03-31"]
    assert out["2025-03-31"]["val"] == 100.0
    assert out["2025-03-31"]["derived_from_ytd"] is False


def test_cash_flow_derives_q2_q3_q4_from_ytd():
    """Q1=100, H1=250 → Q2=150; 9M=420 → Q3=170; annual=600 → Q4=180."""
    facts = _facts({"NetCashProvidedByUsedInOperatingActivities": [
        _cf_record("2025-01-01", "2025-03-31", 100),  # Q1
        _cf_record("2025-01-01", "2025-06-30", 250),  # H1
        _cf_record("2025-01-01", "2025-09-30", 420),  # 9M
        _cf_record("2025-01-01", "2025-12-31", 600, form="10-K"),  # annual
    ]})
    out = extract_quarterly_cash_flow(facts, ["NetCashProvidedByUsedInOperatingActivities"])
    assert out["2025-03-31"]["val"] == 100.0
    assert out["2025-06-30"]["val"] == 150.0
    assert out["2025-09-30"]["val"] == 170.0
    assert out["2025-12-31"]["val"] == 180.0
    # Discrete quarters derived from longer-than-90-day YTD records should be flagged
    assert out["2025-03-31"]["derived_from_ytd"] is False
    assert out["2025-06-30"]["derived_from_ytd"] is True


def test_cash_flow_skips_fiscal_year_without_q1_anchor():
    """If only H1 + annual are filed but no Q1, we can't derive discrete
    quarters safely. Skip that fiscal year entirely."""
    facts = _facts({"NetCashProvidedByUsedInOperatingActivities": [
        _cf_record("2025-01-01", "2025-06-30", 250),  # H1 only
        _cf_record("2025-01-01", "2025-12-31", 600, form="10-K"),
    ]})
    out = extract_quarterly_cash_flow(facts, ["NetCashProvidedByUsedInOperatingActivities"])
    assert out == {}


def test_cash_flow_handles_multiple_fiscal_years_independently():
    facts = _facts({"NetCashProvidedByUsedInOperatingActivities": [
        # FY2024 — Q1 and H1 only
        _cf_record("2024-01-01", "2024-03-31", 50),
        _cf_record("2024-01-01", "2024-06-30", 130),
        # FY2025 — Q1, H1, 9M
        _cf_record("2025-01-01", "2025-03-31", 100),
        _cf_record("2025-01-01", "2025-06-30", 250),
        _cf_record("2025-01-01", "2025-09-30", 420),
    ]})
    out = extract_quarterly_cash_flow(facts, ["NetCashProvidedByUsedInOperatingActivities"])
    # FY2024
    assert out["2024-03-31"]["val"] == 50.0
    assert out["2024-06-30"]["val"] == 80.0   # 130 - 50
    # FY2025
    assert out["2025-03-31"]["val"] == 100.0
    assert out["2025-06-30"]["val"] == 150.0  # 250 - 100
    assert out["2025-09-30"]["val"] == 170.0  # 420 - 250


def test_cash_flow_dedupes_amendments_keeps_latest_filed():
    """Same (start, end) reported twice (10-Q then 10-Q/A amendment)
    keeps the latest-filed value."""
    facts = _facts({"NetCashProvidedByUsedInOperatingActivities": [
        _cf_record("2025-01-01", "2025-03-31", 100, filed="2025-04-30"),
        _cf_record("2025-01-01", "2025-03-31", 105, filed="2025-05-15"),  # amendment
    ]})
    out = extract_quarterly_cash_flow(facts, ["NetCashProvidedByUsedInOperatingActivities"])
    assert out["2025-03-31"]["val"] == 105.0
