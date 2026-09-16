"""Cache the last few annual reports (20-F / 10-K) as filed, for the AI
chat's raw-document tools (see app/tools/sec_annual_reports.py).

Targets: the watchlist by default (their pages are the ones the chat is
used on); `--ticker` for one company. No LLM, ~1 request per new filing.

Run:
    ./venv/bin/python -m scripts.fetch_annual_reports              # watchlist, 3 newest each
    ./venv/bin/python -m scripts.fetch_annual_reports --ticker VIPS --keep 5
    ./venv/bin/python -m scripts.fetch_annual_reports --reparse        # after a text/TOC change
"""
from __future__ import annotations

import argparse

from app.tools.json_io import read_jsonl
from app.tools.paths import COMPANIES_JSONL
from app.tools.sec_annual_reports import ANNUAL_DIR, DEFAULT_KEEP, load_index, reparse_ticker, sync_ticker
from app.tools.watchlist import load_watchlist


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="newest N annual reports per ticker")
    ap.add_argument("--reparse", action="store_true", help="rebuild text + table of contents from the cached HTML, no network")
    args = ap.parse_args()

    if args.reparse:
        tickers = [args.ticker.upper()] if args.ticker else sorted(p.stem for p in ANNUAL_DIR.glob("*.json"))
        for t in tickers:
            if load_index(t).get("filings"):
                reparse_ticker(t)
        return

    ciks = {r["ticker"]: r.get("cik") for r in read_jsonl(COMPANIES_JSONL) if r.get("ticker")}
    tickers = [args.ticker.upper()] if args.ticker else load_watchlist()
    print(f"=== annual reports: {len(tickers)} tickers, keep {args.keep} ===")
    for t in tickers:
        cik = ciks.get(t)
        if not cik:
            print(f"  {t}: no CIK on file — skipped")
            continue
        try:
            sync_ticker(t, cik, keep=args.keep)
        except Exception as e:
            print(f"  {t}: FAILED {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
