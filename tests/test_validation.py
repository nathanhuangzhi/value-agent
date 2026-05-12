"""Unit tests for the validation rules. Each rule is pure, so we exercise
them with synthetic SEC-shape dicts."""

from __future__ import annotations

from datetime import date

import pytest

from app.tools.validation import (
    ALL_RULES,
    rule_annual_revenue_present,
    rule_balance_sheet_present,
    rule_diluted_shares_present,
    rule_eps_consistent,
    rule_gross_margin_in_range,
    rule_gross_profit_derivable,
    rule_latest_filing_fresh,
    rule_mcap_reconcile,
    rule_net_income_present,
    rule_ni_magnitude_vs_revenue,
    rule_operating_income_present,
    rule_price_history_present,
    rule_q_sum_vs_annual,
    rule_shares_in_range,
    rule_yoy_revenue_plausible,
    validate_ticker,
    worst_severity,
)


TODAY = date(2026, 5, 11)


def _entry(val, *, start=None, end=None):
    e = {"val": val}
    if start: e["start"] = start
    if end: e["end"] = end
    return e


def _sec(**annual_kwargs):
    """Convenience: pass annual sub-keys directly."""
    annual = {}
    for k, v in annual_kwargs.items():
        annual[k] = v
    return {"annual": annual, "quarterly": {}, "mna_flagged_years": []}


# ============ Presence ============

def test_revenue_missing_emits_error():
    issues = rule_annual_revenue_present(_sec(), None, TODAY)
    assert len(issues) == 1
    assert issues[0]["severity"] == "error"
    assert issues[0]["rule"] == "missing_annual_revenue"


def test_revenue_present_passes():
    sec = _sec(revenue={"2025": _entry(1e9)})
    assert rule_annual_revenue_present(sec, None, TODAY) == []


def test_revenue_negative_emits_warn():
    """Negative revenue is suspicious (returns dominating sales?) — warn."""
    sec = _sec(revenue={"2025": _entry(-1)})
    issues = rule_annual_revenue_present(sec, None, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "warn"


def test_revenue_zero_emits_info_not_error():
    """$0 reported revenue is legitimate for pre-revenue dev-stage filers;
    downgrade to info so the report doesn't show a red error banner."""
    sec = _sec(revenue={"2025": _entry(0)})
    issues = rule_annual_revenue_present(sec, None, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "info"
    assert issues[0]["rule"] == "zero_annual_revenue"


def test_net_income_missing_annual_and_quarterly_different_severities():
    issues = rule_net_income_present({"annual": {}, "quarterly": {}}, None, TODAY)
    severities = {i["severity"] for i in issues}
    assert "error" in severities  # annual
    assert "warn" in severities  # quarterly


def test_operating_income_missing_blocks_margins():
    issues = rule_operating_income_present(_sec(), None, TODAY)
    assert issues and issues[0]["severity"] == "error"


def test_diluted_shares_missing_emits_error():
    issues = rule_diluted_shares_present(_sec(), None, TODAY)
    assert issues and issues[0]["severity"] == "error"


def test_balance_sheet_missing_both_concepts():
    issues = rule_balance_sheet_present(_sec(), None, TODAY)
    rules = {i["rule"] for i in issues}
    assert "missing_total_assets" in rules
    assert "missing_stockholders_equity" in rules


def test_gross_profit_warn_when_neither_gp_nor_cor():
    sec = _sec(revenue={"2025": _entry(1e9)})
    issues = rule_gross_profit_derivable(sec, None, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "warn"


def test_gross_profit_ok_when_only_cost_of_revenue_present():
    sec = _sec(revenue={"2025": _entry(1e9)}, cost_of_revenue={"2025": _entry(5e8)})
    assert rule_gross_profit_derivable(sec, None, TODAY) == []


def test_gross_profit_ok_when_only_gross_profit_present():
    sec = _sec(gross_profit={"2025": _entry(5e8)})
    assert rule_gross_profit_derivable(sec, None, TODAY) == []


def test_price_history_stale_emits_warn():
    analyzed = {"price_history": {"data": [{"date": "2025-01-01", "close": 50.0}]}}
    issues = rule_price_history_present(None, analyzed, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "warn"
    assert "old" in issues[0]["detail"]


def test_price_history_missing_emits_error():
    issues = rule_price_history_present(None, {"price_history": {"data": []}}, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "error"


def test_price_history_recent_passes():
    analyzed = {"price_history": {"data": [{"date": "2026-05-01", "close": 50.0}]}}
    assert rule_price_history_present(None, analyzed, TODAY) == []


# ============ Sanity ranges ============

def test_gross_margin_over_100pct_flagged():
    """Test at $10M revenue so the $1M-revenue floor doesn't suppress it."""
    sec = _sec(revenue={"2025": _entry(10_000_000)}, gross_profit={"2025": _entry(20_000_000)})
    issues = rule_gross_margin_in_range(sec, None, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "warn"
    assert "200%" in issues[0]["detail"]


def test_gross_margin_skipped_for_sub_million_revenue():
    """Below $1M, COGS/Rev ratios are dominated by noise; rule should skip."""
    sec = _sec(revenue={"2025": _entry(100)}, gross_profit={"2025": _entry(200)})
    assert rule_gross_margin_in_range(sec, None, TODAY) == []


def test_gross_margin_normal_passes():
    sec = _sec(revenue={"2025": _entry(1000)}, gross_profit={"2025": _entry(450)})
    assert rule_gross_margin_in_range(sec, None, TODAY) == []


def test_gross_margin_derived_from_cor():
    """GM derived as (Rev − COR) / Rev when no GP reported."""
    sec = _sec(revenue={"2025": _entry(1000)}, cost_of_revenue={"2025": _entry(500)})
    assert rule_gross_margin_in_range(sec, None, TODAY) == []


def test_ni_exceeds_revenue_flagged():
    """Test at $100M revenue so the $10M-revenue floor doesn't suppress it."""
    sec = _sec(revenue={"2025": _entry(100_000_000)}, net_income={"2025": _entry(500_000_000)})
    issues = rule_ni_magnitude_vs_revenue(sec, None, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "warn"


def test_ni_exceeds_revenue_skipped_for_small_filer():
    """For dev-stage filers losing 5× revenue, the rule should skip rather
    than fire — small filers losing more than they sell is normal, not a
    unit mismatch."""
    sec = _sec(revenue={"2025": _entry(1_000_000)}, net_income={"2025": _entry(-50_000_000)})
    assert rule_ni_magnitude_vs_revenue(sec, None, TODAY) == []


def test_ni_loss_within_revenue_passes():
    sec = _sec(revenue={"2025": _entry(1000)}, net_income={"2025": _entry(-500)})
    assert rule_ni_magnitude_vs_revenue(sec, None, TODAY) == []


def test_shares_zero_flagged():
    sec = _sec(diluted_shares={"2025": _entry(0)})
    issues = rule_shares_in_range(sec, None, TODAY)
    assert len(issues) == 1


# ============ Cross-period ============

def test_yoy_revenue_jump_flagged_when_no_mna():
    sec = _sec(revenue={"2024": _entry(1e8), "2025": _entry(1e9)})
    issues = rule_yoy_revenue_plausible(sec, None, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "warn"


def test_yoy_revenue_jump_skipped_below_min_revenue():
    """When either period is below $1M, ratio is meaningless noise."""
    sec = _sec(revenue={"2024": _entry(50_000), "2025": _entry(500_000)})
    assert rule_yoy_revenue_plausible(sec, None, TODAY) == []


def test_yoy_revenue_jump_suppressed_when_mna_flagged():
    sec = _sec(revenue={"2024": _entry(1e8), "2025": _entry(1e9)})
    sec["mna_flagged_years"] = [2025]
    assert rule_yoy_revenue_plausible(sec, None, TODAY) == []


def test_yoy_revenue_normal_growth_passes():
    sec = _sec(revenue={"2024": _entry(1e9), "2025": _entry(1.2e9)})
    assert rule_yoy_revenue_plausible(sec, None, TODAY) == []


def test_q_sum_matches_annual_passes():
    sec = _sec(revenue={"2025": _entry(400, start="2025-01-01", end="2025-12-31")})
    sec["quarterly"] = {
        "revenue": {
            "2025-03-31": _entry(100, start="2025-01-01", end="2025-03-31"),
            "2025-06-30": _entry(100, start="2025-04-01", end="2025-06-30"),
            "2025-09-30": _entry(100, start="2025-07-01", end="2025-09-30"),
            "2025-12-31": _entry(100, start="2025-10-01", end="2025-12-31"),
        }
    }
    assert rule_q_sum_vs_annual(sec, None, TODAY) == []


def test_q_sum_mismatches_annual_flagged():
    sec = _sec(revenue={"2025": _entry(1000, start="2025-01-01", end="2025-12-31")})
    sec["quarterly"] = {
        "revenue": {
            "2025-03-31": _entry(100, start="2025-01-01", end="2025-03-31"),
            "2025-06-30": _entry(100, start="2025-04-01", end="2025-06-30"),
            "2025-09-30": _entry(100, start="2025-07-01", end="2025-09-30"),
            "2025-12-31": _entry(100, start="2025-10-01", end="2025-12-31"),
        }
    }
    issues = rule_q_sum_vs_annual(sec, None, TODAY)
    assert len(issues) == 1 and "60%" in issues[0]["detail"]


def test_q_sum_skips_when_fewer_than_4_quarters():
    sec = _sec(revenue={"2025": _entry(400, start="2025-01-01", end="2025-12-31")})
    sec["quarterly"] = {
        "revenue": {
            "2025-03-31": _entry(100, start="2025-01-01", end="2025-03-31"),
        }
    }
    assert rule_q_sum_vs_annual(sec, None, TODAY) == []


def test_eps_mismatch_emits_info():
    sec = _sec(
        net_income={"2025": _entry(100e6)},
        diluted_shares={"2025": _entry(50e6)},
        diluted_eps={"2025": _entry(1.50)},  # reported 1.50, computed 2.00 → 33% mismatch
    )
    issues = rule_eps_consistent(sec, None, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "info"


def test_eps_consistent_passes():
    sec = _sec(
        net_income={"2025": _entry(100e6)},
        diluted_shares={"2025": _entry(50e6)},
        diluted_eps={"2025": _entry(2.00)},  # computed = 2.00 → 0% mismatch
    )
    assert rule_eps_consistent(sec, None, TODAY) == []


def test_latest_filing_fresh_passes_recent():
    sec = {"quarterly": {"revenue": {"2026-03-31": _entry(100)}}, "annual": {}}
    assert rule_latest_filing_fresh(sec, None, TODAY) == []


def test_latest_filing_stale_warns():
    sec = {"quarterly": {"revenue": {"2025-01-01": _entry(100)}}, "annual": {}}
    issues = rule_latest_filing_fresh(sec, None, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "warn"


# ============ Cross-source ============

def test_mcap_reconcile_within_tolerance():
    sec = _sec(diluted_shares={"2025": _entry(50e6)})
    analyzed = {
        "market_cap": 500e6,
        "price_history": {"data": [{"date": "2026-05-01", "close": 11.0}]},  # 11 * 50M = 550M, 10% off
    }
    assert rule_mcap_reconcile(sec, analyzed, TODAY) == []


def test_mcap_reconcile_drifted_emits_info():
    sec = _sec(diluted_shares={"2025": _entry(50e6)})
    analyzed = {
        "market_cap": 500e6,
        "price_history": {"data": [{"date": "2026-05-01", "close": 50.0}]},  # 2.5B, 400% drift
    }
    issues = rule_mcap_reconcile(sec, analyzed, TODAY)
    assert len(issues) == 1 and issues[0]["severity"] == "info"


# ============ Driver ============

def test_worst_severity():
    assert worst_severity([]) == "ok"
    assert worst_severity([{"severity": "info", "rule": "x", "detail": ""}]) == "info"
    assert worst_severity([
        {"severity": "info", "rule": "x", "detail": ""},
        {"severity": "warn", "rule": "y", "detail": ""},
    ]) == "warn"
    assert worst_severity([
        {"severity": "warn", "rule": "x", "detail": ""},
        {"severity": "error", "rule": "y", "detail": ""},
    ]) == "error"


def test_validate_ticker_runs_all_rules_without_exceptions():
    # Empty input → every rule should run, no rule_exception issues
    issues = validate_ticker(None, None, TODAY)
    exceptions = [i for i in issues if i["rule"].startswith("rule_exception")]
    assert exceptions == []


def test_validate_ticker_collects_multiple_issues():
    sec = _sec()  # missing everything
    issues = validate_ticker(sec, None, TODAY)
    severities = {i["severity"] for i in issues}
    assert "error" in severities
    assert len(issues) >= 5  # presence rules alone should fire 5+


def test_all_rules_registered():
    """If you add a new rule, register it in ALL_RULES so it actually runs."""
    assert len(ALL_RULES) >= 10
