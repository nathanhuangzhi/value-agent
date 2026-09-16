"""Cache earnings-call transcripts (Alpha Vantage) for the watchlist —
see app/tools/earnings_calls.py. Free key: 25 requests/day, so the run
spends at most `--budget` requests (default 15) and picks up where it
left off tomorrow.

Run:
    ./venv/bin/python -m scripts.fetch_earnings_calls                 # watchlist
    ./venv/bin/python -m scripts.fetch_earnings_calls --ticker VIPS --budget 8
"""
from __future__ import annotations

import argparse

from app.tools.earnings_calls import NoApiKey, sync_ticker
from app.tools.watchlist import load_watchlist


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker")
    ap.add_argument("--budget", type=int, default=15, help="max Alpha Vantage requests this run")
    args = ap.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else load_watchlist()
    print(f"=== earnings calls: {len(tickers)} tickers, budget {args.budget} requests ===")
    left = args.budget
    for t in tickers:
        if left <= 0:
            print("  budget spent — the rest continues tomorrow")
            break
        try:
            left -= sync_ticker(t, budget=left)
        except NoApiKey as e:
            print(f"  skipped: {e}")
            return
        except Exception as e:
            print(f"  {t}: stopped — {e}")
            break
    print(f"  requests used: {args.budget - left}")


if __name__ == "__main__":
    main()
