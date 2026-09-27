"""The row `scripts.add_company` writes, and how it merges into the archive."""
from __future__ import annotations

import json

import pytest

from scripts import add_company


@pytest.fixture
def raw():
    return {
        "ticker": "600066.SS",
        "ts_code": "600066.SH",
        "stock_basic": [{"name": "宇通客车", "industry": "汽车整车"}],
        "daily_basic": [{"trade_date": "20260924", "total_mv": 5758455.8592}],
    }


@pytest.fixture
def offline(monkeypatch):
    """No network: yfinance profile unavailable, prices stubbed."""
    monkeypatch.setattr(add_company, "_yf_profile", lambda t: {})
    monkeypatch.setattr(add_company, "fetch_price_history",
                        lambda t: {"period": "10y", "interval": "1mo",
                                   "data": [{"date": "2026-09-01", "close": 26.01}]})


def test_row_is_marked_non_sec_and_cny_quoted(raw, offline):
    row = add_company.build_row("600066.SS", raw=raw)
    assert row["source"] == "ashare"
    assert row["cik"] is None                       # nothing to fetch from EDGAR
    assert row["quote_currency"] == "CNY"           # drives app/tools/fx.quote_fx
    assert row["ts_code"] == "600066.SH"
    assert row["market_cap"] == 57584558592.0       # 万元 → yuan
    assert row["price_history"]["data"][0]["close"] == 26.01


def test_a_given_name_wins_so_chinese_search_works(raw, offline):
    assert add_company.build_row("600066.SS", name="宇通客车 Yutong Bus", raw=raw)["name"] \
        == "宇通客车 Yutong Bus"
    # Without one, Tushare's 简称 is the fallback.
    assert add_company.build_row("600066.SS", raw=raw)["name"] == "宇通客车"


def test_yfinance_identity_is_preferred_when_available(raw, monkeypatch):
    monkeypatch.setattr(add_company, "_yf_profile", lambda t: {
        "name": "Yutong Bus Co.,Ltd.", "sector": "Industrials",
        "industry": "Farm & Heavy Construction Machinery", "exchange": "SHH",
        "country": "China", "quote_currency": "CNY", "market_cap": 1.0})
    monkeypatch.setattr(add_company, "fetch_price_history", lambda t: None)
    row = add_company.build_row("600066.SS", raw=raw)
    assert row["industry"] == "Farm & Heavy Construction Machinery"   # the app groups by this
    assert row["exchange"] == "SHH"
    assert row["market_cap"] == 57584558592.0        # Tushare's still wins for the figure


def test_upsert_appends_then_refreshes_in_place(tmp_path, monkeypatch, raw, offline):
    path = tmp_path / "companies_analyzed.json"
    path.write_text(json.dumps([{"ticker": "QDEL", "name": "Quidel"}]))
    monkeypatch.setattr(add_company, "COMPANIES_ANALYZED", path)

    row = add_company.build_row("600066.SS", name="宇通客车", raw=raw)
    assert add_company.upsert_analyzed(row) is False          # appended
    rows = json.loads(path.read_text())
    assert [r["ticker"] for r in rows] == ["QDEL", "600066.SS"]

    row2 = {**row, "market_cap": 60_000_000_000.0, "name": None}
    assert add_company.upsert_analyzed(row2) is True          # refreshed
    rows = json.loads(path.read_text())
    assert len(rows) == 2
    saved = next(r for r in rows if r["ticker"] == "600066.SS")
    assert saved["market_cap"] == 60_000_000_000.0
    assert saved["name"] == "宇通客车"                        # None never overwrites


def test_only_a_share_symbols_are_accepted(monkeypatch):
    monkeypatch.setattr("sys.argv", ["add_company", "--ticker", "QDEL"])
    with pytest.raises(SystemExit):
        add_company.main()
