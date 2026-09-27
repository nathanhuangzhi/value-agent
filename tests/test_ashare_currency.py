"""A CNY-quoted company must produce the same ratios as its USD twin.

Statements are converted to USD at the blend sites while `price_history`
stays in the currency the stock trades in, so anything that multiplies a
price by a statement figure has to divide the price first — the bug this
guards against made 600066's P/E 1.56 instead of 10.50.
"""
from __future__ import annotations

import pytest

from app.tools.fx import quote_fx
from app.tools.report.ratios import compute_snapshot_ratios, quarterly_multiples, to_usd_prices
from app.tools.validation import validate_ticker, worst_severity

FX = {"CNY": {"per_usd": 6.7125, "as_of": "2026-09-26"}}


def _quarter(period, **items):
    return {"period": period, "items": items, "sources": {k: "ashare" for k in items}}


def _statements(scale=1.0):
    """Four quarters of a simple company, in USD."""
    inc = [_quarter(p, **{"Total Revenue": 1_000.0 * scale, "Net Income": 100.0 * scale,
                          "Gross Profit": 250.0 * scale, "Operating Income": 150.0 * scale,
                          "Diluted Average Shares": 1_000.0})
           for p in ("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")]
    bs = [_quarter(p, **{"Common Stock Equity": 2_000.0 * scale, "Total Assets": 3_000.0 * scale})
          for p in ("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")]
    cf = [_quarter(p, **{"Cash Flow From Continuing Operating Activities": 120.0 * scale,
                         "Free Cash Flow": 90.0 * scale})
          for p in ("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")]
    return inc, bs, cf


def test_quote_fx_reads_the_quote_currency_not_the_reporting_one():
    assert quote_fx({"quote_currency": "CNY"}, FX) == 6.7125
    assert quote_fx({"quote_currency": "USD"}, FX) == 1.0
    assert quote_fx({}, FX) == 1.0                       # unknown → no conversion
    # An ADR reports CNY but trades in USD: its prices must NOT be divided.
    assert quote_fx({"quote_currency": "USD", "currency": "CNY"}, FX) == 1.0
    assert quote_fx({"quote_currency": "JPY"}, FX) == 1.0   # no rate on file


def test_to_usd_prices_is_a_no_op_for_usd():
    ph = [{"date": "2026-09-01", "close": 26.01}]
    assert to_usd_prices(ph, 1.0) is ph
    assert to_usd_prices([], 6.7125) == []
    assert to_usd_prices(None, 6.7125) is None


def test_none_closes_survive_conversion():
    out = to_usd_prices([{"date": "2026-09-01", "close": None}], 6.7125)
    assert out[0]["close"] is None


def test_cny_quoted_company_matches_its_usd_twin():
    inc, bs, cf = _statements()
    usd_prices = [{"date": "2026-09-01", "close": 2.0}]
    cny_prices = [{"date": "2026-09-01", "close": 2.0 * 6.7125}]

    usd = compute_snapshot_ratios(inc, bs, cf, usd_prices, inc_annual=inc)
    cny = compute_snapshot_ratios(inc, bs, cf, to_usd_prices(cny_prices, quote_fx({"quote_currency": "CNY"}, FX)),
                                  inc_annual=inc)
    for key in ("market_cap", "ttm_pe", "static_pe", "pb", "ps", "p_fcf", "ttm_pocf"):
        assert cny[key] == pytest.approx(usd[key]), key
    assert cny["ttm_pe"] == pytest.approx(2_000.0 / 400.0)      # mcap / TTM NI

    # …and the quarterly bars the industry rows draw.
    usd_bars = quarterly_multiples(inc, cf, usd_prices)
    cny_bars = quarterly_multiples(inc, cf, to_usd_prices(cny_prices, 6.7125))
    assert [b["pqe"] for b in cny_bars] == pytest.approx([b["pqe"] for b in usd_bars])


def test_unconverted_prices_would_be_wrong_by_the_fx_rate():
    """The regression itself: skipping the conversion inflates market cap."""
    inc, bs, cf = _statements()
    cny_prices = [{"date": "2026-09-01", "close": 2.0 * 6.7125}]
    wrong = compute_snapshot_ratios(inc, bs, cf, cny_prices, inc_annual=inc)
    right = compute_snapshot_ratios(inc, bs, cf, to_usd_prices(cny_prices, 6.7125), inc_annual=inc)
    assert wrong["ttm_pe"] == pytest.approx(right["ttm_pe"] * 6.7125)


def test_a_company_with_no_sec_row_is_not_flagged():
    """A-shares have complete statements and no XBRL; the presence tier would
    call every headline metric missing and paint a red banner."""
    row = {"ticker": "600066.SS", "source": "ashare", "market_cap": 8.5e9,
           "price_history": {"data": [{"date": "2026-09-01", "close": 26.01}]}}
    assert worst_severity(validate_ticker(None, row)) == "error"          # the old behaviour
    assert validate_ticker(None, row, sec_expected=False) == []           # the new one


def test_a_real_filer_still_gets_every_rule():
    row = {"ticker": "QDEL", "market_cap": 1e9}
    issues = validate_ticker(None, row, sec_expected=True)
    assert any(i["rule"] == "missing_annual_revenue" for i in issues)


def test_the_chat_block_quotes_a_company_in_its_own_currency(monkeypatch):
    """The AI must see statements *and* prices in one unit. Before, an A-share's
    statements were USD while its price history was raw CNY — enough for the
    model to compute a P/E 6.7x out."""
    from app.ai import context

    payload = {
        "ticker": "600066.SS", "name": "宇通客车", "exchange": "SHH", "sector": "Industrials",
        "industry": "Farm & Heavy Construction Machinery", "country": "China",
        "analyzed_date": "2026-09-27", "business_overview": "", "classification": {},
        "classification_meta": {}, "validation": {"status": "ok", "issues": []},
        "currency": {"code": "CNY", "per_usd": 6.7125, "as_of": "2026-09-26"},
        "quote_currency": "CNY",
        "snapshot": {"market_cap": 1_000_000_000.0, "ttm_pe": 10.5, "dividend_rate": 0.372},
        "annual": {"income_statement": [{"period": "2025-12-31", "items": {
            "Total Revenue": 1_000_000_000.0, "Diluted Average Shares": 2_213_939_223.0,
            "Diluted EPS": 0.374}, "sources": {}}], "balance_sheet": [], "cash_flow": []},
        "quarterly": {"income_statement": [], "balance_sheet": [], "cash_flow": []},
    }
    monkeypatch.setattr(context, "ticker_detail", lambda t: payload)
    monkeypatch.setattr(context.repo, "analyzed", lambda: {"600066.SS": {
        "price_history": {"data": [{"date": "2026-09-01", "close": 26.01}]}}})

    block = context.company_block("600066.SS")
    assert "**Currency:** CNY" in block and "Divide by 6.7125 for USD" in block
    assert "**Annual (CNY" in block and "**Price (CNY):**" in block
    assert "Market cap 6.71B" in block                    # 1.0B USD → ¥6.71B
    assert "| Revenue | 6.71B |" in block
    assert "| Diluted shares | 2.21B |" in block          # a count is never scaled
    assert "Dividend rate (per share) 2.50" in block      # $0.372 → ¥2.50

    # An ADR reports CNY but trades in USD: it stays converted, as before.
    payload["quote_currency"] = "USD"
    block = context.company_block("600066.SS")
    assert "converted to USD at 6.7125" in block
    assert "**Annual (USD" in block and "| Revenue | 1.00B |" in block
