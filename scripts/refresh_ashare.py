"""Daily refresh for the companies the rotating scan can't reach.

`daily_scan` builds its batch from `companies.jsonl` (SEC's universe), so an
A-share is never picked up by it — which is exactly what keeps these
companies out of the daily digest. Their data still has to be kept current,
so this stage does for them what `daily_scan` does for everyone else: fresh
price history and market cap, fresh statements, fresh cross-check.

Run:
    ./venv/bin/python -m scripts.refresh_ashare            # every A-share on file
    ./venv/bin/python -m scripts.refresh_ashare --ticker 600066.SS
    ./venv/bin/python -m scripts.refresh_ashare --dry-run  # list what it would do
"""
from __future__ import annotations

import argparse

from app.log import get_logger
from app.tools.ashare_tools import TushareError, fetch
from app.tools.json_io import atomic_write_json
from app.tools.paths import ASHARE_XCHECK_DIR
from scripts.add_company import build_row, upsert_analyzed
from scripts.fetch_ashare_statements import ashare_tickers, fetch_one
from scripts.xcheck_ashare import report_for

log = get_logger(__name__)


def refresh_one(ticker: str) -> dict:
    """Prices + market cap + statements + reconciliation for one company."""
    raw = fetch(ticker)                       # one network round-trip, reused below
    row = build_row(ticker, name=None, raw=raw)
    # Keep the display name (and anything else already curated) — only the
    # market-moving fields are refreshed.
    row.pop("name", None)
    upsert_analyzed(row)
    stmt = fetch_one(ticker)
    report = report_for(ticker)
    ASHARE_XCHECK_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(ASHARE_XCHECK_DIR / f"{ticker.upper()}.json", report)
    return {
        "ticker": ticker.upper(),
        "prices": len(((row.get("price_history") or {}).get("data")) or []),
        "market_cap": row.get("market_cap"),
        "annual": len((stmt or {}).get("annual", {}).get("revenue") or {}),
        "quarterly": len((stmt or {}).get("quarterly", {}).get("revenue") or {}),
        "xcheck": report.get("worst"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh non-SEC (A-share) companies")
    ap.add_argument("--ticker")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else ashare_tickers()
    if not tickers:
        print("No A-share companies on file — nothing to refresh")
        return
    if args.dry_run:
        print(f"would refresh {len(tickers)} A-share(s): {', '.join(tickers)}")
        return
    for t in tickers:
        try:
            out = refresh_one(t)
        except TushareError as e:
            log.error("%s: %s", t, e)
            print(f"  {t}: FAILED ({e})")
            continue
        print(f"  {t}: {out['prices']} price points, mcap {out['market_cap']:,.0f}, "
              f"{out['annual']} annual / {out['quarterly']} quarterly periods, "
              f"cross-check {out['xcheck']}")


if __name__ == "__main__":
    main()
