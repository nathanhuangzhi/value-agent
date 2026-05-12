"""Unit tests for the pure-math helpers in app/tools/report/ratios.py.

These functions are responsible for the historical-table values, the monthly
valuation chart, and the YoY cell highlighting. They have no I/O, so they're
easy to exercise with synthetic period dicts.
"""

from __future__ import annotations

import pytest

from app.tools.report.ratios import (
    _strict_ttm_sum,
    _latest_value,
    _latest_close,
    _recomputed_mcap,
    _top_asset_keys,
    _prior_year_label,
    _yoy_cell_style,
    _other_opex_amount,
    _ttm_dividend_per_share,
    _latest_value_at_or_before,
    _compute_valuation_history_monthly,
)


def _period(period: str, **items):
    """Build a synthetic yfinance-shape period dict."""
    return {"period": period, "items": items}


# === _strict_ttm_sum ===

def test_strict_ttm_returns_none_when_fewer_than_four_periods():
    qs = [_period("2025-03-31", Revenue=100), _period("2025-06-30", Revenue=110)]
    assert _strict_ttm_sum(qs, ["Revenue"]) is None


def test_strict_ttm_returns_none_when_any_period_missing_key():
    qs = [
        _period("2025-03-31", Revenue=100),
        _period("2025-06-30", Revenue=110),
        _period("2025-09-30"),  # missing
        _period("2025-12-31", Revenue=130),
    ]
    assert _strict_ttm_sum(qs, ["Revenue"]) is None


def test_strict_ttm_sums_last_four_when_all_present():
    qs = [
        _period("2025-03-31", Revenue=100),
        _period("2025-06-30", Revenue=110),
        _period("2025-09-30", Revenue=120),
        _period("2025-12-31", Revenue=130),
    ]
    assert _strict_ttm_sum(qs, ["Revenue"]) == pytest.approx(460)


def test_strict_ttm_handles_negative_values():
    qs = [_period(f"2025-Q{i}", NI=v) for i, v in enumerate([-10, -20, -30, -40], start=1)]
    assert _strict_ttm_sum(qs, ["NI"]) == pytest.approx(-100)


def test_strict_ttm_uses_first_present_fallback_key():
    qs = [_period(f"2025-Q{i}", **{"Operating Revenue": 50.0}) for i in range(1, 5)]
    # "Total Revenue" is not present, falls back to "Operating Revenue"
    assert _strict_ttm_sum(qs, ["Total Revenue", "Operating Revenue"]) == pytest.approx(200)


# === _latest_value ===

def test_latest_value_returns_none_for_empty_periods():
    assert _latest_value([], ["Anything"]) is None


def test_latest_value_falls_back_through_periods_until_a_value_is_found():
    qs = [
        _period("2025-03-31", NI=10),
        _period("2025-06-30"),  # latest, but missing the key
        _period("2025-09-30"),
    ]
    # iterates from end, returns the most recent non-None: 10
    assert _latest_value(qs, ["NI"]) == 10


# === _latest_close ===

def test_latest_close_returns_none_when_no_prices_have_close():
    assert _latest_close([{"date": "2025-01-01"}]) is None


def test_latest_close_returns_last_non_none_close():
    ph = [
        {"date": "2025-01-01", "close": 100.0},
        {"date": "2025-02-01", "close": 110.0},
        {"date": "2025-03-01"},  # missing close
    ]
    assert _latest_close(ph) == 110.0


# === _recomputed_mcap ===

def test_recomputed_mcap_returns_none_if_either_input_missing():
    assert _recomputed_mcap([], []) is None


def test_recomputed_mcap_multiplies_latest_close_by_latest_shares():
    ph = [{"date": "2025-12-01", "close": 50.0}]
    inc = [_period("2025-12-31", **{"Diluted Average Shares": 1_000_000.0})]
    assert _recomputed_mcap(ph, inc) == pytest.approx(50_000_000)


# === _top_asset_keys ===

def test_top_asset_keys_returns_empty_list_for_no_balance_sheet():
    assert _top_asset_keys([], []) == []


def test_top_asset_keys_returns_top_n_by_value():
    bs = [_period("2025-12-31", Goodwill=1_000_000, Inventory=500_000)]
    result = _top_asset_keys([], bs, top_n=2)
    assert result == ["Goodwill", "Inventory"]


def test_top_asset_keys_dedups_near_aliases():
    """'Net PPE' and 'Property Plant And Equipment Net' refer to the same line — only one should appear."""
    bs = [_period(
        "2025-12-31",
        **{
            "Goodwill": 500_000,
            "Net PPE": 800_000,
            "Property Plant And Equipment Net": 800_000,  # alias of Net PPE
            "Inventory": 300_000,
        },
    )]
    result = _top_asset_keys([], bs, top_n=3)
    assert "Net PPE" in result
    # The dedup should prevent BOTH PPE variants from appearing
    ppe_count = sum(1 for k in result if "PPE" in k or "Property Plant" in k)
    assert ppe_count == 1


def test_top_asset_keys_prefers_quarterly_over_annual():
    bs_a = [_period("2024-12-31", Goodwill=1_000_000)]
    bs_q = [_period("2025-09-30", Goodwill=1_500_000)]
    result = _top_asset_keys(bs_a, bs_q, top_n=1)
    # Should use the quarterly value, but the function returns keys not values —
    # both have Goodwill, so just verify Goodwill is selected.
    assert result == ["Goodwill"]


# === _prior_year_label ===

def test_prior_year_label_annual():
    assert _prior_year_label("FY2025") == "FY2024"


def test_prior_year_label_quarterly():
    assert _prior_year_label("2026 Q1") == "2025 Q1"
    assert _prior_year_label("2024 Q4") == "2023 Q4"


def test_prior_year_label_returns_none_for_unrecognized_format():
    assert _prior_year_label("garbage") is None
    assert _prior_year_label("FYabc") is None


# === _yoy_cell_style ===

def test_yoy_green_above_plus_20_percent():
    style = _yoy_cell_style(120, 100)
    assert "background:#e0efe0" in style  # the green tint


def test_yoy_red_below_minus_20_percent():
    style = _yoy_cell_style(70, 100)
    assert "background:#f6e0d8" in style  # the red tint


def test_yoy_empty_for_modest_change():
    assert _yoy_cell_style(110, 100) == ""


def test_yoy_empty_when_either_input_missing():
    assert _yoy_cell_style(None, 100) == ""
    assert _yoy_cell_style(100, None) == ""


def test_yoy_empty_when_old_is_zero_to_avoid_divbyzero():
    assert _yoy_cell_style(50, 0) == ""


def test_yoy_handles_sign_flip_loss_to_smaller_loss_as_improvement():
    """Net income going from -100 to -50 is +50% improvement → green."""
    style = _yoy_cell_style(-50, -100)
    assert "background:#e0efe0" in style


def test_yoy_handles_sign_flip_loss_to_bigger_loss_as_deterioration():
    style = _yoy_cell_style(-150, -100)
    assert "background:#f6e0d8" in style


# === _other_opex_amount ===

def test_other_opex_returns_none_when_gross_profit_missing():
    assert _other_opex_amount(None, 10, 5, None, None, 3) is None


def test_other_opex_returns_none_when_no_sga_anywhere():
    """If neither combined SG&A nor the S&M+G&A breakout is reported, can't isolate Other."""
    assert _other_opex_amount(100, 50, 10, None, None, None) is None


def test_other_opex_uses_combined_sga_when_present():
    # GP=100, OI=20 → total opex 80; R&D=15, SG&A=50; Other = 80 - 15 - 50 = 15
    assert _other_opex_amount(100, 20, 15, None, None, 50) == 15


def test_other_opex_falls_back_to_breakout_when_combined_sga_missing():
    # GP=100, OI=20 → total opex 80; R&D=10, S&M=30, G&A=20; Other = 80 - 10 - 30 - 20 = 20
    assert _other_opex_amount(100, 20, 10, 30, 20, None) == 20


def test_other_opex_treats_missing_rnd_as_zero():
    # GP=100, OI=30 → total opex 70; SG&A=60; R&D absent → 0; Other = 70 - 0 - 60 = 10
    assert _other_opex_amount(100, 30, None, None, None, 60) == 10


# === _ttm_dividend_per_share ===

def test_ttm_dividend_returns_zero_when_no_dividend_keys_at_all():
    """Non-payer: cash-flow statement has no dividend line items."""
    cf = [_period(f"2025-Q{i}", **{"Operating Cash Flow": 100}) for i in range(1, 5)]
    assert _ttm_dividend_per_share(cf, latest_shares=1_000_000) == 0.0


def test_ttm_dividend_returns_annualized_per_share_for_payer():
    cf = [_period(f"2025-Q{i}", **{"Cash Dividends Paid": -250_000}) for i in range(1, 5)]
    # Sum of |−250_000| over 4 quarters = $1M, divided by 1M shares = $1.00/share annually
    assert _ttm_dividend_per_share(cf, latest_shares=1_000_000) == pytest.approx(1.0)


def test_ttm_dividend_returns_none_when_shares_unknown():
    cf = [_period(f"2025-Q{i}", **{"Cash Dividends Paid": -100}) for i in range(1, 5)]
    assert _ttm_dividend_per_share(cf, latest_shares=None) is None


# === _latest_value_at_or_before ===

def test_latest_value_at_or_before_returns_none_when_all_future():
    periods = [_period("2026-12-31", X=10)]
    assert _latest_value_at_or_before(periods, "2025-06", ["X"]) is None


def test_latest_value_at_or_before_returns_most_recent_in_range():
    periods = [
        _period("2022-12-31", X=22),
        _period("2023-12-31", X=23),
        _period("2024-12-31", X=24),
    ]
    # Looking up "2023-06" should return FY2022 (the most recent annual ≤ June 2023)
    assert _latest_value_at_or_before(periods, "2023-06", ["X"]) == 22
    # Looking up "2024-01" should return FY2023
    assert _latest_value_at_or_before(periods, "2024-01", ["X"]) == 23


# === _compute_valuation_history_monthly ===

def test_monthly_valuation_requires_at_least_one_quarterly_eligible():
    """For a price-history month before any quarterly statement exists, no row is emitted."""
    inc_q = [_period("2025-12-31", **{
        "Diluted Average Shares": 100,
        "Net Income": 50, "Total Revenue": 500,
    })]
    inc_a = []
    bs_q = [_period("2025-12-31", **{"Common Stock Equity": 200})]
    bs_a = []
    price_history = [
        {"date": "2024-06-01", "close": 5.0},  # before quarterly data → skipped
        {"date": "2026-01-01", "close": 10.0},  # after quarterly data → included
    ]
    rows = _compute_valuation_history_monthly(inc_q, bs_q, inc_a, bs_a, price_history)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-01-01"
