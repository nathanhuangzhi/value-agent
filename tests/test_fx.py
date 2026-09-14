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
        {"sec": "CNY", "yfinance": "HKD", "6k": "HKD", "derived": "CNY"}


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


def test_sixk_overlay_wins_over_yfinance_and_keeps_its_tag():
    from app.tools.report.sec_adapter import _merge_period_dicts, overlay_source_row
    from app.tools.sec_6k import sixk_as_source_row
    store = {"ticker": "PDD", "filings": [
        {"filed": "2026-08-25", "extracted": {"period_type": "quarter", "period_end": "2026-06-30",
                                               "currency": "CNY", "cash_flow_period_type": "quarter",
                                               "standard": {"revenue": 112.0, "net_income": 27.0, "operating_cf": 25.0,
                                                            "diluted_eps_per_ads": 18.45, "capex": None}}},
        {"filed": "2026-03-26", "extracted": {"period_type": "full_year", "period_end": "2025-12-31",
                                               "currency": "CNY", "standard": {"revenue": 431.0}}},   # not quarterly → ignored
        {"filed": "2026-02-01", "skipped": "not a results release", "extracted": None},
    ]}
    six = sixk_as_source_row(store)
    assert six["financial_currency"] == "CNY"
    assert set(six["quarterly"]) == {"revenue", "net_income", "operating_cf", "diluted_eps"}
    assert six["quarterly"]["revenue"]["2026-06-30"] == {"val": 112.0, "end": "2026-06-30", "source": "6k", "filed": "2026-08-25"}

    yf = {"financial_currency": "CNY", "annual": {}, "quarterly": {
        "revenue": {"2026-06-30": {"val": 111.0}, "2026-03-31": {"val": 95.0}}}}
    merged_row = overlay_source_row(yf, six)
    assert merged_row["quarterly"]["revenue"]["2026-06-30"]["val"] == 112.0      # 6-K wins
    assert merged_row["quarterly"]["revenue"]["2026-03-31"]["val"] == 95.0       # yfinance kept
    assert yf["quarterly"]["revenue"]["2026-06-30"]["val"] == 111.0              # input untouched

    merged, sources = _merge_period_dicts({"revenue": {"2026-06-30": {"val": 113.0}}},
                                          merged_row["quarterly"])
    assert sources["revenue"]["2026-06-30"] == "sec"                              # SEC still first
    assert sources["net_income"]["2026-06-30"] == "6k"
    assert sources["revenue"]["2026-03-31"] == "yfinance"
    # currency mismatch → overlay refused
    assert overlay_source_row({"financial_currency": "USD", "quarterly": {}}, six)["quarterly"] == {}
