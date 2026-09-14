from app.tools.report.ratios import _top_liability_keys


def test_top_liability_keys_ranks_latest_balance_sheet():
    annual = [{"period": "2024-12-31", "items": {"Long Term Debt": 900, "Accounts Payable": 50}}]
    quarterly = [
        {"period": "2025-06-30", "items": {"Long Term Debt": 100, "Accounts Payable": 300,
                                            "Deferred Revenue": 200, "Lease Obligations": 10,
                                            "Current Debt": 0}},
        {"period": "2025-03-31", "items": {"Long Term Debt": 999}},
    ]
    # newest quarter wins; zero / missing values are skipped; top 3 by value
    assert _top_liability_keys(annual, quarterly) == ["Accounts Payable", "Deferred Revenue", "Long Term Debt"]
    # falls back to annual when quarterly has no liability lines
    assert _top_liability_keys(annual, [{"period": "2025-06-30", "items": {"Cash And Cash Equivalents": 5}}]) \
        == ["Long Term Debt", "Accounts Payable"]
    assert _top_liability_keys([], []) == []
