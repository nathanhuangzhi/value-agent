"""Three-source reconciliation: tolerances, exclusions, valuation checks."""
from __future__ import annotations

from app.tools.ashare_xcheck import (
    as_issues,
    build_report,
    compare_rows,
    reconcile_valuation,
    severity_for,
    worst_severity,
)


def _row(**metrics):
    """Source row carrying one annual period (2025) per metric."""
    return {"annual": {m: {"2025": {"val": v}} for m, v in metrics.items()}, "quarterly": {}}


def test_severity_thresholds():
    assert severity_for(None) == "ok"
    assert severity_for(0.0) == "ok"
    assert severity_for(0.001) == "ok"           # rounding between sources
    assert severity_for(0.0011) == "info"
    assert severity_for(0.01) == "info"
    assert severity_for(0.011) == "warn"
    assert severity_for(0.05) == "warn"
    assert severity_for(0.051) == "error"
    assert severity_for(0.0, sign_flip=True) == "error"


def test_agreeing_sources_produce_ok_cells():
    cells = compare_rows({"ashare": _row(revenue=100.0), "eastmoney": _row(revenue=100.0)})
    assert [c["severity"] for c in cells] == ["ok"]
    assert cells[0]["values"] == {"ashare": 100.0, "eastmoney": 100.0}


def test_a_real_disagreement_is_flagged_with_its_spread():
    cells = compare_rows({"ashare": _row(net_income=100.0), "eastmoney": _row(net_income=120.0)})
    assert cells[0]["severity"] == "error"
    assert cells[0]["spread_pct"] == (120.0 - 100.0) / 120.0


def test_opposite_signs_are_always_an_error():
    cells = compare_rows({"ashare": _row(operating_cf=5.0), "eastmoney": _row(operating_cf=-5.0)})
    assert cells[0]["severity"] == "error"


def test_a_cell_only_one_source_reports_is_not_compared():
    assert compare_rows({"ashare": _row(revenue=100.0), "eastmoney": _row()}) == []


def test_yfinance_cost_lines_are_excluded_by_definition():
    """yfinance's A-share 成本/营业利润 use a different base — comparing them
    would raise a permanent false alarm on a cell the blend never shows."""
    rows = {"ashare": _row(gross_profit=100.0, operating_income=50.0, revenue=200.0),
            "yfinance": _row(gross_profit=15.0, operating_income=40.0, revenue=200.0)}
    cells = compare_rows(rows)
    assert {c["metric"] for c in cells} == {"revenue"}


def test_valuation_reconciliation_converts_our_usd_market_cap():
    v = reconcile_valuation({"market_cap": 1_000.0, "ttm_pe": 10.4959, "pb": 4.4377},
                            {"total_mv": 671.25, "pe_ttm": 10.4959, "pb": 4.4377,
                             "trade_date": "20260924"},
                            per_usd=6.7125)
    by = {c["metric"]: c for c in v}
    assert by["market_cap"]["ours"] == 6712.5 and by["market_cap"]["tushare"] == 6712500.0
    assert by["market_cap"]["severity"] == "error"     # a real 1000x mistake shows up
    assert by["ttm_pe"]["severity"] == "ok" and by["pb"]["severity"] == "ok"


def test_missing_counterpart_is_skipped_not_guessed():
    assert reconcile_valuation({"ttm_pe": 10.0}, {}) == []
    assert reconcile_valuation({}, {"pe_ttm": 10.0}) == []


def test_report_rolls_up_the_worst_finding_and_lists_disagreements():
    report = build_report("600066.SS",
                          {"ashare": _row(revenue=100.0, net_income=50.0),
                           "eastmoney": _row(revenue=100.0, net_income=80.0)},
                          today="2026-09-27")
    assert report["worst"] == "error"
    assert report["sources"] == ["ashare", "eastmoney"]
    assert [c["metric"] for c in report["disagreements"]] == ["net_income"]
    assert worst_severity(report) == "error"


def test_issues_carry_the_numbers_into_the_validation_banner():
    report = build_report("600066.SS",
                          {"ashare": _row(net_income=50.0), "eastmoney": _row(net_income=80.0)})
    issues = as_issues(report)
    assert issues[0]["severity"] == "error" and issues[0]["rule"] == "source_disagreement"
    assert "net_income" in issues[0]["detail"] and "ashare=50" in issues[0]["detail"]


def test_a_clean_report_adds_no_issues():
    report = build_report("600066.SS", {"ashare": _row(revenue=100.0), "eastmoney": _row(revenue=100.0)})
    assert report["worst"] == "ok"
    assert as_issues(report) == []
