from app.tools.fx import currency_meta, reporting_currency, to_usd_periods, to_usd_statements

FX = {"CNY": {"per_usd": 7.0, "as_of": "2026-09-14"}}


def test_reporting_currency_defaults_to_usd():
    assert reporting_currency(None) == "USD"
    assert reporting_currency({}) == "USD"
    assert reporting_currency({"financial_currency": "cny"}) == "CNY"


def test_to_usd_scales_money_but_not_share_counts():
    periods = [{"period": "2025-12-31",
                "items": {"Total Revenue": 700.0, "Diluted EPS": 14.0,
                          "Diluted Average Shares": 50.0, "Net Income": None},
                "sources": {"Total Revenue": "yfinance"}}]
    out = to_usd_periods(periods, "CNY", FX)
    assert out[0]["items"] == {"Total Revenue": 100.0, "Diluted EPS": 2.0,
                               "Diluted Average Shares": 50.0, "Net Income": None}
    assert out[0]["sources"] == {"Total Revenue": "yfinance"}
    # input untouched (deep copy)
    assert periods[0]["items"]["Total Revenue"] == 700.0


def test_to_usd_is_identity_for_usd_or_unknown_rate():
    periods = [{"period": "p", "items": {"Total Revenue": 700.0}}]
    assert to_usd_periods(periods, "USD", FX) is periods
    assert to_usd_periods(periods, "HKD", FX) is periods   # no HKD rate → native


def test_to_usd_statements_converts_each_statement():
    stmts = {"income_statement": [{"period": "p", "items": {"Total Revenue": 70.0}}],
             "balance_sheet": [], "cash_flow": [{"period": "p", "items": {"Capital Expenditure": -7.0}}]}
    out = to_usd_statements(stmts, "CNY", FX)
    assert out["income_statement"][0]["items"]["Total Revenue"] == 10.0
    assert out["cash_flow"][0]["items"]["Capital Expenditure"] == -1.0


def test_currency_meta():
    assert currency_meta("USD", FX) is None
    assert currency_meta("CNY", FX) == {"code": "CNY", "per_usd": 7.0, "as_of": "2026-09-14"}
    assert currency_meta("HKD", FX) == {"code": "HKD", "per_usd": None, "as_of": None}
