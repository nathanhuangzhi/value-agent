from app.tools.fx import currency_meta, reporting_currency, source_currencies, to_usd_periods, to_usd_statements

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


def test_reporting_currency_prefers_sec_row_with_data():
    sec = {"currency": "CNY", "annual": {"revenue": {"2025": {"val": 1}}}}
    assert reporting_currency({"financial_currency": "USD"}, sec) == "CNY"
    # SEC row without statements → yfinance decides
    assert reporting_currency({"financial_currency": "HKD"}, {"currency": "USD", "annual": {}}) == "HKD"


def test_per_source_conversion_scales_each_cell_by_its_own_currency():
    fx = {"CNY": {"per_usd": 7.0}, "HKD": {"per_usd": 8.0}}
    periods = [{"period": "p",
                "items": {"Total Revenue": 700.0, "Net Income": 80.0, "Total Debt": 70.0},
                "sources": {"Total Revenue": "sec", "Net Income": "yfinance", "Total Debt": "derived"}}]
    out = to_usd_periods(periods, {"sec": "CNY", "yfinance": "HKD", "derived": "CNY"}, fx)
    assert out[0]["items"] == {"Total Revenue": 100.0, "Net Income": 10.0, "Total Debt": 10.0}
    assert source_currencies({"financial_currency": "hkd"}, {"currency": "CNY"}) == \
        {"sec": "CNY", "yfinance": "HKD", "derived": "CNY"}


def test_infer_ads_ratio_from_overlapping_share_counts():
    from app.tools.report.sec_adapter import infer_ads_ratio, _ads_normalized
    sec = {"annual": {"diluted_shares": {2024: {"val": 5.6e9}, 2025: {"val": 5.93e9}},
                      "diluted_eps": {2025: {"val": 19.0}}},
           "quarterly": {}}
    yf = {"annual": {"diluted_shares": {"2024": {"val": 1.4e9}, "2025": {"val": 1.482e9}}}}
    assert infer_ads_ratio(sec, yf) == 4.0
    out = _ads_normalized(sec, yf)
    assert out["ads_ratio"] == 4.0
    assert round(out["annual"]["diluted_shares"][2025]["val"] / 1e9, 3) == 1.482  # 5.93B / 4 ≈ 1.48B
    assert out["annual"]["diluted_eps"][2025]["val"] == 76.0
    assert sec["annual"]["diluted_eps"][2025]["val"] == 19.0                   # input untouched
    # a domestic filer (ratio ≈ 1) is left alone
    assert infer_ads_ratio(sec, {"annual": {"diluted_shares": {"2025": {"val": 5.9e9}}}}) is None
    assert infer_ads_ratio(sec, None) is None
