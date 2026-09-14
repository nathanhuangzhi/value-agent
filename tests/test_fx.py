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


def test_results_release_detection_tolerates_split_headings():
    from app.tools.sec_6k import looks_like_results_release
    doc = ("Weibo Announces Second Quarter 2026 Unaudited Financial Results\n"
           "... prose ...\nUNAUDITED CONDENSED CONSOLIDATED STATEMENTS\nOF OPERATIONS\nRevenues | 1 | 2")
    assert looks_like_results_release(doc)
    assert not looks_like_results_release("Reconciliation between U.S. GAAP and IFRS\nbalance sheets")  # no results announcement
    assert not looks_like_results_release("Weibo Announces Second Quarter Financial Results\nno tables here")


def test_merge_units_prefers_native_over_usd_convenience_year_by_year():
    from app.tools.sec_xbrl_tools import merge_units
    per_unit = {
        "CNY": {2019: {"val": 700.0}, 2020: {"val": 770.0}},                      # native until 2020
        "USD": {2020: {"val": 110.0}, 2021: {"val": 120.0}, 2022: {"val": 130.0}},  # convenience 2020, native after
    }
    m = merge_units(per_unit)
    assert {y: (e["val"], e["ccy"]) for y, e in m.items()} == {
        2019: (700.0, "CNY"), 2020: (770.0, "CNY"), 2021: (120.0, "USD"), 2022: (130.0, "USD")}


def test_per_cell_currency_tags_drive_conversion():
    fx = {"CNY": {"per_usd": 7.0}}
    periods = [{"period": "FY2020", "items": {"Total Revenue": 770.0, "Net Income": 70.0},
                "sources": {"Total Revenue": "sec", "Net Income": "sec"},
                "currencies": {"Total Revenue": "CNY", "Net Income": "CNY"}},
               {"period": "FY2021", "items": {"Total Revenue": 120.0},
                "sources": {"Total Revenue": "sec"}, "currencies": {"Total Revenue": "USD"}}]
    # row-level currency says CNY, but the FY2021 cell is tagged USD → left alone
    out = to_usd_periods(periods, {"sec": "CNY", "yfinance": "CNY", "derived": "CNY"}, fx)
    assert out[0]["items"] == {"Total Revenue": 110.0, "Net Income": 10.0}
    assert out[1]["items"] == {"Total Revenue": 120.0}


def test_sec_row_to_usd_uses_entry_tags():
    from app.tools.fx import sec_row_to_usd
    row = {"currency": "CNY", "annual": {
        "revenue": {2020: {"val": 700.0, "ccy": "CNY"}, 2021: {"val": 120.0, "ccy": "USD"}},
        "diluted_shares": {2021: {"val": 5.0}}}, "quarterly": {}}
    out = sec_row_to_usd(row, {"CNY": {"per_usd": 7.0}})
    assert out["annual"]["revenue"][2020]["val"] == 100.0 and out["annual"]["revenue"][2021]["val"] == 120.0
    assert out["annual"]["diluted_shares"][2021]["val"] == 5.0
    assert row["annual"]["revenue"][2020]["val"] == 700.0


def test_derive_asset_lines_from_6k_balance_sheet():
    from app.tools.sec_6k import derive_asset_lines
    bs = [{"label": "Cash and cash equivalents", "value": 29.0}, {"label": "Restricted cash", "value": 0.6},
          {"label": "Short term investments", "value": 3.6},
          {"label": "Accounts receivable, net", "value": 0.56}, {"label": "Other receivables and prepayments,net", "value": 3.1},
          {"label": "Inventories", "value": 4.33}, {"label": "Total current assets", "value": 43.8},
          {"label": "Property and equipment, net", "value": 16.4}, {"label": "Deposits for property and equipment", "value": 0.01},
          {"label": "Land use rights, net", "value": 9.9}, {"label": "Intangible assets, net", "value": 0.32},
          {"label": "Investment in equity method investees", "value": 7.62}, {"label": "Other investments", "value": 4.98},
          {"label": "Goodwill", "value": 0.65}, {"label": "Total non-current assets", "value": 42.06},
          {"label": "TOTAL ASSETS", "value": 85.86}, {"label": "Short term loans", "value": 10.97},
          {"label": "Investment payable", "value": 1.0}]  # liabilities section: ignored
    out = derive_asset_lines(bs)
    assert round(out.pop("receivables"), 2) == round(0.56 + 3.1, 2)     # total receivables
    assert out.pop("cash") == 29.0 and out.pop("short_term_investments") == 3.6
    assert out.pop("restricted_cash") == 0.6
    assert out == {"inventory": 4.33, "ppe_net": 16.4,
                   "intangibles": 9.9 + 0.32, "long_term_investments": 7.62 + 4.98, "goodwill": 0.65}


def test_top_asset_keys_returns_every_class_largest_first():
    from app.tools.report.ratios import _top_asset_keys
    q = [{"period": "2026-06-30", "items": {"Net PPE": 16.4, "Other Intangible Assets": 10.2, "Long Term Investments": 12.6,
                                            "Inventory": 4.33, "Receivables": 6.0, "Goodwill": 0.65}}]
    assert _top_asset_keys([], q) == ["Net PPE", "Long Term Investments", "Other Intangible Assets",
                                      "Receivables", "Inventory", "Goodwill"]
    assert _top_asset_keys([], q, top_n=2) == ["Net PPE", "Long Term Investments"]


def test_cash_plus_short_term_investments_is_derived():
    from app.tools.report.sec_adapter import sec_to_yfinance_annual
    sec = {"currency": "USD", "annual": {
        "cash": {2025: {"val": 100.0, "ccy": "USD"}},
        "short_term_investments": {2025: {"val": 40.0, "ccy": "USD"}},
        "total_assets": {2025: {"val": 500.0, "ccy": "USD"}}}, "quarterly": {}}
    bs = sec_to_yfinance_annual(sec)["balance_sheet"][0]
    assert bs["items"]["Cash Cash Equivalents And Short Term Investments"] == 140.0
    assert bs["sources"]["Cash Cash Equivalents And Short Term Investments"] == "sec"
    # components beat a pre-summed yfinance line; restricted cash is included
    sec["annual"]["restricted_cash"] = {2025: {"val": 5.0, "ccy": "USD"}}
    yf = {"financial_currency": "USD", "annual": {"cash_and_st_investments": {"2025": {"val": 999.0}}}, "quarterly": {}}
    bs = sec_to_yfinance_annual(sec, yf)["balance_sheet"][0]
    assert bs["items"]["Cash Cash Equivalents And Short Term Investments"] == 145.0
    assert bs["sources"]["Cash Cash Equivalents And Short Term Investments"] == "sec"
    # without an STI line the total is cash + restricted cash
    sec["annual"].pop("short_term_investments")
    bs = sec_to_yfinance_annual(sec)["balance_sheet"][0]
    assert bs["items"]["Cash Cash Equivalents And Short Term Investments"] == 105.0


def test_partial_sec_value_yields_to_fuller_gap_fill():
    from app.tools.report.sec_adapter import _merge_period_dicts
    sec = {"receivables": {"2025": {"val": 0.89, "concept": "AccountsReceivableNetCurrent", "partial": True},
                           "2024": {"val": 0.80, "concept": "AccountsReceivableNetCurrent", "partial": True}},
           "cash": {"2025": {"val": 29.0}}}
    yf = {"receivables": {"2025": {"val": 4.52, "source": "6k"}}, "cash": {"2025": {"val": 28.0}}}
    merged, sources = _merge_period_dicts(sec, yf)
    assert merged["receivables"]["2025"]["val"] == 4.52 and sources["receivables"]["2025"] == "6k"
    assert merged["receivables"]["2024"]["val"] == 0.80 and sources["receivables"]["2024"] == "sec"  # nothing fuller
    assert merged["cash"]["2025"]["val"] == 29.0 and sources["cash"]["2025"] == "sec"           # not partial
