"""Tushare → source-row mapping: restatements, YTD differencing, derivations."""
from __future__ import annotations

import pytest

from app.tools.ashare_adapter import (
    ashare_source_row,
    dedupe,
    dividend_cash,
    latest_daily_basic,
    main_business,
    market_cap,
    ytd_to_quarter,
)
from app.tools.ashare_tools import is_ashare, ts_code

INCOME_FIELDS_SAMPLE = {"total_revenue": None, "oper_cost": None}


def _inc(end, rt="1", *, rev, cost, oi=None, ni=None, ann=None, flag="0", ebit=None):
    return {"end_date": end, "report_type": rt, "ann_date": ann or "20260101",
            "f_ann_date": ann or "20260101", "update_flag": flag,
            "total_revenue": rev, "oper_cost": cost, "operate_profit": oi,
            "n_income_attr_p": ni, "ebit": ebit}


def test_ts_code_and_detection():
    assert ts_code("600066.SS") == "600066.SH"
    assert ts_code("000625.SZ") == "000625.SZ"
    assert ts_code("600066") == "600066.SH"      # bare Shanghai code
    assert ts_code("000625") == "000625.SZ"
    assert is_ashare("600066.SS") and not is_ashare("VIPS")


def test_restated_rows_merge_cell_by_cell():
    """The later announcement wins, but must not blank a field it omits — the
    first publication of 600066's 2025Q1 carried no `ebit`, the adjustment did."""
    rows = [
        _inc("20250331", rev=100.0, cost=60.0, ann="20250420", ebit=None),
        _inc("20250331", rev=101.0, cost=60.0, ann="20250815", flag="1", ebit=9.0),
    ]
    merged = dedupe(rows)["2025-03-31"]
    assert merged["total_revenue"] == 101.0      # restatement wins
    assert merged["ebit"] == 9.0                 # filled by the later row
    assert merged["oper_cost"] == 60.0


def test_ytd_differencing_recovers_single_quarters():
    ytd = dedupe([
        _inc("20250331", rev=10.0, cost=6.0),
        _inc("20250630", rev=25.0, cost=15.0),
        _inc("20250930", rev=40.0, cost=24.0),
        _inc("20251231", rev=60.0, cost=36.0),
    ])
    q = ytd_to_quarter(ytd, {"revenue": ("total_revenue",), "cost_of_revenue": ("oper_cost",)})
    assert [q[k]["total_revenue"] for k in sorted(q)] == [10.0, 15.0, 15.0, 20.0]
    assert [q[k]["oper_cost"] for k in sorted(q)] == [6.0, 9.0, 9.0, 12.0]


def test_ytd_differencing_skips_a_period_with_no_predecessor():
    """Differencing 三季报 against Q1 would invent a six-month "quarter"."""
    ytd = {"2025-03-31": {"total_revenue": 10.0}, "2025-09-30": {"total_revenue": 40.0}}
    q = ytd_to_quarter(ytd, {"revenue": ("total_revenue",)})
    assert q["2025-03-31"]["total_revenue"] == 10.0
    assert "total_revenue" not in q["2025-09-30"]


def _raw():
    return {
        "ticker": "600066.SS",
        "ts_code": "600066.SH",
        "stock_basic": [{"name": "宇通客车", "industry": "汽车整车"}],
        "income": [_inc("20251231", rev=41426173982.34, cost=31425443228.88,
                        oi=6478302794.06, ni=5554481970.9)],
        "income_q": [_inc("20251231", "2", rev=15060256188.8, cost=11000000000.0,
                          ni=2262131944.09)],
        "balancesheet": [{"end_date": "20251231", "total_assets": 32990246148.33,
                          "total_hldr_eqy_exc_min_int": 15601987989.32,
                          "total_share": 2213939223.0, "money_cap": 6367991239.76}],
        "cashflow": [{"end_date": "20251231", "report_type": "1",
                      "n_cashflow_act": 3196679778.25,
                      "c_pay_acq_const_fiolta": 729488117.06}],
        "cashflow_q": [],
        "daily_basic": [{"trade_date": "20260923", "total_mv": 5590196.48, "pe_ttm": 10.06},
                        {"trade_date": "20260924", "total_mv": 5758455.8592, "pe_ttm": 10.4959}],
        "dividend": [
            # FY2025 final: ¥2.00/share paid 2026-05-15 → Q2 2026
            {"end_date": "20251231", "div_proc": "实施", "cash_div": 2.0, "cash_div_tax": 2.0,
             "ex_date": "20260515", "pay_date": "20260515"},
            # the board's proposal for the next one — not yet paid
            {"end_date": "20260630", "div_proc": "预案", "cash_div": 0.0, "cash_div_tax": 0.6,
             "ex_date": None, "pay_date": None},
        ],
        "fina_mainbz": [
            {"end_date": "20251231", "bz_item": "海外销售", "bz_code": "D",
             "bz_sales": 21107906300.0, "bz_cost": 14855650600.0, "bz_profit": 6252255700.0,
             "curr_type": "CNY"},
            {"end_date": "20251231", "bz_item": "地区", "bz_code": "D",
             "bz_sales": 41426173982.34, "bz_cost": 31425443228.88,
             "bz_profit": 10000730753.46, "curr_type": "CNY"},
        ],
    }


def test_source_row_shape_and_currency():
    row = ashare_source_row(_raw())
    assert row["source"] == "ashare" and row["financial_currency"] == "CNY"
    assert row["ticker"] == "600066.SS" and row["name"] == "宇通客车"
    rev = row["annual"]["revenue"]["2025"]
    assert rev["val"] == 41426173982.34
    assert rev["source"] == "ashare" and rev["end"] == "2025-12-31"


def test_gross_profit_is_derived_from_the_filing_not_left_to_yfinance():
    """毛利 = 营业收入 − 营业成本 = ¥10.00B for 600066 FY2025, which matches
    主营业务构成 exactly; yfinance publishes ¥1.49B off a different cost base."""
    row = ashare_source_row(_raw())
    assert row["annual"]["gross_profit"]["2025"]["val"] == pytest.approx(10000730753.46)
    assert row["annual"]["gross_profit"]["2025"]["source"] == "ashare"


def test_capex_is_negated_to_match_the_pipeline_convention():
    row = ashare_source_row(_raw())
    assert row["annual"]["capex"]["2025"]["val"] == -729488117.06
    assert row["annual"]["operating_cf"]["2025"]["val"] == 3196679778.25


def test_single_quarter_series_is_used_for_the_quarterly_grid():
    row = ashare_source_row(_raw())
    assert row["quarterly"]["revenue"]["2025-12-31"]["val"] == 15060256188.8
    # Balance-sheet items are point-in-time, so they appear on both grids.
    assert row["quarterly"]["total_assets"]["2025-12-31"]["val"] == 32990246148.33


def test_market_cap_converts_from_wan_yuan():
    raw = _raw()
    assert latest_daily_basic(raw)["trade_date"] == "20260924"
    assert market_cap(raw) == 57584558592.0        # 5,758,455.8592 万元


def test_main_business_drops_the_rollup_rows():
    rows = main_business(_raw(), "2025")
    assert [r["item"] for r in rows] == ["海外销售"]
    assert rows[0]["kind"] == "region" and rows[0]["revenue"] == 21107906300.0


def test_no_payload_is_not_an_error():
    assert ashare_source_row(None) is None
    assert market_cap(None) is None


def test_dividends_come_from_the_executed_records_only():
    """Chinese cash flow bundles dividends with interest, so the payout is
    read from the 分红 records; 预案 (proposed) must not count as paid."""
    raw = _raw()
    shares = {"2025-12-31": 2213939223.0}
    div = dividend_cash(raw, shares)
    assert div == {"2026-06-30": pytest.approx(-2.0 * 2213939223.0)}   # booked to the pay quarter


def test_dividend_lands_on_both_grids():
    row = ashare_source_row(_raw())
    q = row["quarterly"]["cash_dividends_paid"]["2026-06-30"]
    assert q["val"] == pytest.approx(-4427878446.0)
    assert q["source"] == "ashare"
    # …and the fiscal year it was paid in, so an annual column shows it too.
    assert row["annual"]["cash_dividends_paid"]["2026"]["val"] == pytest.approx(-4427878446.0)


def test_no_dividend_records_is_not_an_error():
    raw = {**_raw(), "dividend": []}
    assert dividend_cash(raw, {"2025-12-31": 100.0}) == {}
    assert "cash_dividends_paid" not in ashare_source_row(raw)["quarterly"]
