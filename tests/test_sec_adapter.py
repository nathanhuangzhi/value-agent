"""Unit tests for `app/tools/report/sec_adapter.py` — converts SEC EDGAR's
year-keyed dict-of-dicts into the period-list shape that the report
renderer expects, and blends yfinance values into the gaps.
"""

from __future__ import annotations

from app.tools.report.sec_adapter import (
    SEC_TO_YFINANCE_INCOME,
    SEC_TO_YFINANCE_CASHFLOW,
    SEC_TO_YFINANCE_BALANCE,
    sec_to_yfinance_annual,
    sec_to_yfinance_quarterly,
    load_sec_by_ticker,
)


def _sec_entry(val, end=None, concept="X", filed="2024-02-01"):
    """Build a SEC-shape entry as emitted by extract_period_values."""
    return {"val": val, "end": end, "concept": concept, "filed": filed, "fy": None, "form": "10-K"}


def _yf_entry(val, end=None, concept="X"):
    """Build a yfinance-shape entry as emitted by fetch_yfinance_statements."""
    return {"val": val, "end": end, "concept": concept, "source": "yfinance"}


def _sec_row(**annual):
    """Convenience: pass `annual` sub-keys as kwargs."""
    return {"annual": annual}


def _yf_row(**annual):
    return {"annual": annual}


# ===== sec_to_yfinance_annual (basic shape) =====

def test_returns_three_statement_lists():
    sec_row = _sec_row(
        revenue={2023: _sec_entry(1_000, end="2023-12-31")},
        operating_cf={2023: _sec_entry(200, end="2023-12-31")},
        total_assets={2023: _sec_entry(5_000, end="2023-12-31")},
        long_term_debt={2023: _sec_entry(2_000, end="2023-12-31")},
    )
    result = sec_to_yfinance_annual(sec_row)
    assert set(result.keys()) == {"income_statement", "balance_sheet", "cash_flow"}
    assert result["income_statement"][0]["items"]["Total Revenue"] == 1_000
    assert result["cash_flow"][0]["items"]["Cash Flow From Continuing Operating Activities"] == 200
    assert result["balance_sheet"][0]["items"]["Total Assets"] == 5_000
    assert result["balance_sheet"][0]["items"]["Total Debt"] == 2_000


def test_emits_period_list_sorted_by_year():
    sec_row = _sec_row(
        revenue={
            2022: _sec_entry(1_000_000, end="2022-12-31"),
            2023: _sec_entry(1_200_000, end="2023-12-31"),
        },
        net_income={2022: _sec_entry(100_000, end="2022-12-31")},
    )
    out = sec_to_yfinance_annual(sec_row)["income_statement"]
    assert len(out) == 2
    assert out[0]["period"] == "2022-12-31"
    assert out[1]["period"] == "2023-12-31"
    assert out[0]["items"]["Total Revenue"] == 1_000_000
    assert out[0]["items"]["Net Income"] == 100_000
    assert "Net Income" not in out[1]["items"]


def test_empty_input_returns_empty_lists():
    result = sec_to_yfinance_annual({"annual": {}})
    assert result["income_statement"] == []
    assert result["balance_sheet"] == []
    assert result["cash_flow"] == []


def test_renderer_label_compatibility():
    """The yfinance labels in the mappings must match what the renderer's
    _pick_first() looks up. Spot-check a few critical labels."""
    assert SEC_TO_YFINANCE_INCOME["revenue"] == "Total Revenue"
    assert SEC_TO_YFINANCE_INCOME["net_income"] == "Net Income"
    assert SEC_TO_YFINANCE_INCOME["diluted_eps"] == "Diluted EPS"
    assert SEC_TO_YFINANCE_INCOME["diluted_shares"] == "Diluted Average Shares"
    assert SEC_TO_YFINANCE_CASHFLOW["operating_cf"] == "Cash Flow From Continuing Operating Activities"
    assert SEC_TO_YFINANCE_CASHFLOW["capex"] == "Capital Expenditure"
    assert SEC_TO_YFINANCE_BALANCE["cash"] == "Cash And Cash Equivalents"
    assert SEC_TO_YFINANCE_BALANCE["total_assets"] == "Total Assets"
    assert SEC_TO_YFINANCE_BALANCE["stockholders_equity"] == "Common Stock Equity"


# ===== derived values =====

def test_derives_free_cash_flow_from_ocf_and_capex():
    sec_row = _sec_row(
        operating_cf={2025: _sec_entry(1000, end="2025-12-31")},
        capex={2025: _sec_entry(200, end="2025-12-31")},
    )
    items = sec_to_yfinance_annual(sec_row)["cash_flow"][0]["items"]
    assert items["Free Cash Flow"] == 800


def test_fcf_takes_abs_of_capex():
    """Some filers report capex as a negative outflow; subtract magnitude either way."""
    sec_row = _sec_row(
        operating_cf={2025: _sec_entry(1000, end="2025-12-31")},
        capex={2025: _sec_entry(-200, end="2025-12-31")},
    )
    items = sec_to_yfinance_annual(sec_row)["cash_flow"][0]["items"]
    assert items["Free Cash Flow"] == 800


def test_defaults_capex_to_zero_when_only_ocf_reported():
    """Small-cap filers commonly report a cash flow statement but omit the
    capex line entirely (immaterial spend). Treat absence as $0."""
    sec_row = _sec_row(operating_cf={2025: _sec_entry(1000, end="2025-12-31")})
    items = sec_to_yfinance_annual(sec_row)["cash_flow"][0]["items"]
    assert items["Capital Expenditure"] == 0
    assert items["Free Cash Flow"] == 1000


def test_skips_fcf_when_no_cash_flow_statement():
    """When neither OCF nor capex is reported, don't fabricate a CF row."""
    sec_row = _sec_row(revenue={2025: _sec_entry(1000, end="2025-12-31")})
    assert sec_to_yfinance_annual(sec_row)["cash_flow"] == []


def test_defaults_total_debt_to_zero_when_bs_filed_but_no_debt():
    """Debt-free companies report a balance sheet but no debt concept."""
    sec_row = _sec_row(
        total_assets={2025: _sec_entry(5_000, end="2025-12-31")},
        stockholders_equity={2025: _sec_entry(5_000, end="2025-12-31")},
    )
    bs = sec_to_yfinance_annual(sec_row)["balance_sheet"]
    assert len(bs) == 1
    assert bs[0]["items"]["Total Debt"] == 0


def test_legacy_debt_concept_not_double_counted():
    """When a filer reports both `LongTermDebt` (legacy bucket) and
    `LongTermDebtCurrent` (short_term_debt bucket), the legacy total must
    be ignored to avoid double-counting the current portion."""
    sec_row = _sec_row(
        long_term_debt={2025: _sec_entry(800, end="2025-12-31")},
        short_term_debt={2025: _sec_entry(200, end="2025-12-31")},
        debt_total_legacy={2025: _sec_entry(1_000, end="2025-12-31")},
    )
    bs = sec_to_yfinance_annual(sec_row)["balance_sheet"]
    assert bs[0]["items"]["Total Debt"] == 1_000  # 800 + 200, NOT 1000 + 200


def test_uses_legacy_debt_when_split_unavailable():
    """When a filer reports only legacy `LongTermDebt` (no current/
    noncurrent split), use that value as Total Debt."""
    sec_row = _sec_row(
        debt_total_legacy={2025: _sec_entry(500, end="2025-12-31")},
        total_assets={2025: _sec_entry(5_000, end="2025-12-31")},
    )
    bs = sec_to_yfinance_annual(sec_row)["balance_sheet"]
    assert bs[0]["items"]["Total Debt"] == 500


def test_defaults_zero_revenue_when_10k_filed_without_revenue_tag():
    """Dev-stage biotechs (AEMD/CTSO/MODD) file 10-Ks with no Revenue tag
    when revenue is $0. Default to $0 when both operating_income AND
    net_income are present."""
    sec_row = _sec_row(
        operating_income={2024: _sec_entry(-9_000_000, end="2024-12-31")},
        net_income={2024: _sec_entry(-13_000_000, end="2024-12-31")},
    )
    inc = sec_to_yfinance_annual(sec_row)["income_statement"]
    assert len(inc) == 1
    assert inc[0]["items"]["Total Revenue"] == 0


def test_does_not_fabricate_revenue_when_only_ni():
    """If only net_income is present (no operating_income), don't assume
    revenue was $0 — could be a partial-year adjustment, not a full 10-K."""
    sec_row = _sec_row(net_income={2024: _sec_entry(-100, end="2024-12-31")})
    inc = sec_to_yfinance_annual(sec_row)["income_statement"]
    assert "Total Revenue" not in inc[0]["items"]


# ===== yfinance blending =====

def test_yfinance_fills_gap_where_sec_has_no_data():
    """When SEC has nothing for a year but yfinance does, yfinance fills the
    cell and the source is marked accordingly."""
    sec_row = _sec_row()  # SEC has nothing
    yf_row = _yf_row(revenue={"2024": _yf_entry(1_000, end="2024-12-31")})
    inc = sec_to_yfinance_annual(sec_row, yfinance_row=yf_row)["income_statement"]
    assert len(inc) == 1
    assert inc[0]["items"]["Total Revenue"] == 1_000
    assert inc[0]["sources"]["Total Revenue"] == "yfinance"


def test_sec_wins_when_both_sources_have_value():
    """SEC is the authoritative source; conflicts resolve to SEC."""
    sec_row = _sec_row(revenue={2024: _sec_entry(1_000, end="2024-12-31")})
    yf_row = _yf_row(revenue={"2024": _yf_entry(999_999, end="2024-12-31")})
    inc = sec_to_yfinance_annual(sec_row, yfinance_row=yf_row)["income_statement"]
    assert inc[0]["items"]["Total Revenue"] == 1_000
    assert inc[0]["sources"]["Total Revenue"] == "sec"


def test_yfinance_fills_per_metric_independently():
    """Even within one period, the merge is per-metric: SEC may provide
    revenue while yfinance provides net_income."""
    sec_row = _sec_row(revenue={2024: _sec_entry(1_000, end="2024-12-31")})
    yf_row = _yf_row(net_income={"2024": _yf_entry(-500, end="2024-12-31")})
    inc = sec_to_yfinance_annual(sec_row, yfinance_row=yf_row)["income_statement"]
    assert inc[0]["items"]["Total Revenue"] == 1_000
    assert inc[0]["items"]["Net Income"] == -500
    assert inc[0]["sources"]["Total Revenue"] == "sec"
    assert inc[0]["sources"]["Net Income"] == "yfinance"


def test_derived_gross_profit_inherits_yfinance_source():
    """When Gross Profit is derived from yfinance Revenue and SEC CoR,
    the GP cell is marked yfinance because at least one input is yfinance."""
    sec_row = _sec_row(cost_of_revenue={2024: _sec_entry(400, end="2024-12-31")})
    yf_row = _yf_row(revenue={"2024": _yf_entry(1_000, end="2024-12-31")})
    inc = sec_to_yfinance_annual(sec_row, yfinance_row=yf_row)["income_statement"]
    assert inc[0]["items"]["Gross Profit"] == 600
    assert inc[0]["sources"]["Gross Profit"] == "yfinance"


def test_yfinance_only_year_fills_full_row():
    """Recent-IPO case: SEC has only FY2024; yfinance has FY2022-FY2024.
    The earlier yfinance years should appear in the period list."""
    sec_row = _sec_row(revenue={2024: _sec_entry(100, end="2024-12-31")})
    yf_row = _yf_row(revenue={
        "2022": _yf_entry(50, end="2022-12-31"),
        "2023": _yf_entry(75, end="2023-12-31"),
        "2024": _yf_entry(200, end="2024-12-31"),  # would lose to SEC's 100
    })
    inc = sec_to_yfinance_annual(sec_row, yfinance_row=yf_row)["income_statement"]
    assert len(inc) == 3
    assert inc[0]["items"]["Total Revenue"] == 50   # yfinance fills 2022
    assert inc[1]["items"]["Total Revenue"] == 75   # yfinance fills 2023
    assert inc[2]["items"]["Total Revenue"] == 100  # SEC wins 2024
    assert inc[0]["sources"]["Total Revenue"] == "yfinance"
    assert inc[2]["sources"]["Total Revenue"] == "sec"


def test_quarterly_blends_period_end_date_keys():
    sec_row = {"quarterly": {"revenue": {"2024-09-30": _sec_entry(100, end="2024-09-30")}}}
    yf_row = {"quarterly": {"revenue": {"2024-06-30": _yf_entry(80, end="2024-06-30")}}}
    inc = sec_to_yfinance_quarterly(sec_row, yfinance_row=yf_row)["income_statement"]
    assert [p["period"] for p in inc] == ["2024-06-30", "2024-09-30"]
    assert inc[0]["sources"]["Total Revenue"] == "yfinance"
    assert inc[1]["sources"]["Total Revenue"] == "sec"


# ===== load_sec_by_ticker =====

def test_load_sec_by_ticker_returns_empty_for_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert load_sec_by_ticker(missing) == {}


def test_load_sec_by_ticker_keys_by_ticker(tmp_path):
    import json
    path = tmp_path / "companies_sec.json"
    path.write_text(json.dumps([
        {"ticker": "AAA", "annual": {}},
        {"ticker": "BBB", "annual": {}},
    ]))
    result = load_sec_by_ticker(path)
    assert set(result.keys()) == {"AAA", "BBB"}
    assert result["AAA"]["ticker"] == "AAA"
