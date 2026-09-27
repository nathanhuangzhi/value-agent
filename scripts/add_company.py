"""Add a company the discovery funnel can't reach — today: A-shares.

The funnel starts at SEC's ticker file, so `companies.jsonl` (and therefore
every batch, filter and digest) only knows US filers. A Shanghai or Shenzhen
listing has no SEC presence at all: saving `600066.SS` in the app does
nothing, because `watchlist_rows()` can't find it in the universe.

This script writes the one row that unlocks the rest of the pipeline — an
entry in `companies_analyzed.json` marked `source: "ashare"` — and puts the
ticker on a named watchlist. Everything downstream keys off that file:
`fetch_ashare_statements` and `fetch_yfinance_statements` pick the ticker up,
`bake_api` bakes `/api/tickers/<T>.json`, and the app can search, save,
chart and chat about it.

What it deliberately does NOT do is make the company part of the daily
digest: `watchlist_rows()` still skips tickers missing from
`companies.jsonl`, so an A-share never joins a rotating batch. Its data is
refreshed by `scripts.refresh_ashare` instead.

Run:
    ./venv/bin/python -m scripts.add_company --ticker 600066.SS --list Red \
        --name "宇通客车 Yutong Bus"
    ./venv/bin/python -m scripts.add_company --ticker 000625.SZ   # no watchlist
"""
from __future__ import annotations

import argparse
from datetime import date

from app.db import connect
from app.log import get_logger
from app.tools import watchlist as wl
from app.tools.ashare_adapter import market_cap
from app.tools.ashare_tools import fetch, is_ashare, ts_code
from app.tools.financials_tools import fetch_price_history
from app.tools.fx import load_fx
from app.tools.json_io import atomic_write_json, read_json_array
from app.tools.paths import COMPANIES_ANALYZED

log = get_logger(__name__)

# Tushare's 所属行业 is a Chinese industry name; the app groups companies by
# the yfinance-style industry string its industry pages use, so prefer
# yfinance's when we can get it and fall back to Tushare's.
_SECTOR_FALLBACK = "Industrials"


def _yf_profile(ticker: str) -> dict:
    """yfinance identity for the ticker (best-effort — it's a second source,
    not a requirement)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).get_info() or {}
    except Exception as e:                       # network/parse — keep going
        log.warning("yfinance profile failed for %s: %s", ticker, e)
        return {}
    return {
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "exchange": info.get("exchange"),
        "country": info.get("country"),
        "business_overview": info.get("longBusinessSummary"),
        "market_cap": info.get("marketCap"),
        "quote_currency": (info.get("currency") or "").upper() or None,
    }


def build_row(ticker: str, *, name: str | None = None, raw: dict | None = None) -> dict:
    """The `companies_analyzed.json` row for one non-SEC company."""
    ticker = ticker.upper()
    raw = raw if raw is not None else fetch(ticker)
    basic = (raw.get("stock_basic") or [{}])[0]
    yfp = _yf_profile(ticker)
    prices = fetch_price_history(ticker)
    # Market cap is stored in USD like every other row's — the search index,
    # the industry tables and the snapshot fallback all assume that. The
    # quoted figure is kept beside it for reference.
    mcap_native = market_cap(raw) or yfp.get("market_cap")
    quote_ccy = yfp.get("quote_currency") or "CNY"
    per_usd = (load_fx().get(quote_ccy) or {}).get("per_usd")
    mcap = (mcap_native / per_usd) if (mcap_native and per_usd) else mcap_native
    return {
        "ticker": ticker,
        "ts_code": ts_code(ticker),
        "analyzed_date": date.today().isoformat(),
        "name": name or yfp.get("name") or basic.get("name") or ticker,
        "sector": yfp.get("sector") or _SECTOR_FALLBACK,
        "industry": yfp.get("industry") or basic.get("industry") or "Uncategorized",
        "market_cap": mcap,
        "market_cap_native": mcap_native,
        "country": yfp.get("country") or "China",
        "exchange": yfp.get("exchange") or ts_code(ticker).rpartition(".")[2],
        "business_overview": yfp.get("business_overview") or "",
        # No SEC facts, and prices are quoted in the local currency — both
        # flags are read downstream (blend source, validation tier, FX of
        # price-derived ratios). See app/tools/fx.quote_fx.
        "source": "ashare",
        "cik": None,
        "quote_currency": quote_ccy,
        "classification": None,
        "classification_meta": None,
        "price_history": prices,
        "narrative": None,
        "narrative_model": None,
        "narrative_provider": None,
        "narrative_sources": None,
        "usage": None,
        "analysis_error": None,
    }


def upsert_analyzed(row: dict) -> bool:
    """Merge the row into companies_analyzed.json. Returns True when it
    replaced an existing row (a refresh) rather than appending a new one."""
    rows = read_json_array(COMPANIES_ANALYZED)
    ticker = row["ticker"]
    existing = [i for i, r in enumerate(rows) if (r.get("ticker") or "").upper() == ticker]
    if existing:
        keep = existing[-1]
        # A None value means "not fetched this time" — never overwrite a
        # curated field (the display name) with it.
        rows[keep] = {**rows[keep], **{k: v for k, v in row.items() if v is not None}}
        # Collapse any historical duplicates of this ticker.
        rows = [r for i, r in enumerate(rows) if i == keep or i not in set(existing)]
    else:
        rows.append(row)
    atomic_write_json(COMPANIES_ANALYZED, rows)
    return bool(existing)


def _user_id(email: str | None) -> int | None:
    """The account whose watchlist to touch: the one named, else the only one."""
    with connect() as cx:
        if email:
            r = cx.execute("SELECT id FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
            return r["id"] if r else None
        rows = cx.execute("SELECT id FROM users ORDER BY id").fetchall()
        return rows[0]["id"] if len(rows) == 1 else None


def add_to_list(ticker: str, list_name: str, email: str | None = None) -> str:
    """Put the ticker on the named watchlist, creating the list if needed."""
    uid = _user_id(email)
    if uid is None:
        return "no account matched — skipped the watchlist (pass --email)"
    lists = wl.user_lists(uid)
    target = next((li for li in lists if (li["name"] or "").lower() == list_name.lower()), None)
    if target is None:
        target = wl.create_list(uid, list_name)
    wl.add_tickers(uid, target["id"], [ticker])
    return f"added to watchlist {target['name']!r}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Add a non-SEC company (A-share) to the pipeline")
    ap.add_argument("--ticker", required=True, help="yfinance-style symbol, e.g. 600066.SS")
    ap.add_argument("--name", help="display name (use it for a Chinese name so search finds it)")
    ap.add_argument("--list", dest="list_name", help="watchlist to add it to, e.g. Red")
    ap.add_argument("--email", help="account owning that watchlist (default: the only account)")
    args = ap.parse_args()

    ticker = args.ticker.upper()
    if not is_ashare(ticker):
        raise SystemExit(f"{ticker}: not an A-share symbol (expected .SS/.SZ/.BJ)")

    row = build_row(ticker, name=args.name)
    refreshed = upsert_analyzed(row)
    points = len(((row.get("price_history") or {}).get("data")) or [])
    print(f"{'refreshed' if refreshed else 'added'} {ticker} {row['name']}")
    if row["market_cap"]:
        print(f"  industry={row['industry']!r} mcap=${row['market_cap']:,.0f} "
              f"({row['market_cap_native']:,.0f} {row['quote_currency']})")
    else:
        print(f"  industry={row['industry']!r} mcap=?")
    print(f"  price history: {points} points")
    if args.list_name:
        print(f"  {add_to_list(ticker, args.list_name, args.email)}")
    print("next: ./venv/bin/python -m scripts.fetch_ashare_statements --ticker " + ticker)


if __name__ == "__main__":
    main()
