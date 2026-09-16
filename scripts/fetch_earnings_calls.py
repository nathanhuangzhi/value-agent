"""Cache earnings-call transcripts (Alpha Vantage) for the watchlist —
see app/tools/earnings_calls.py. Each free key allows 25 requests/day, so
the run spends at most `--budget` requests (default 15 per configured key)
and picks up where it left off tomorrow.

Run:
    ./venv/bin/python -m scripts.fetch_earnings_calls                 # watchlist
    ./venv/bin/python -m scripts.fetch_earnings_calls --ticker VIPS --budget 8
"""
from __future__ import annotations

import argparse

from app.tools.earnings_calls import NoApiKey, RateLimited, daily_budget, sync_ticker
from app.tools.watchlist import load_watchlist


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker")
    ap.add_argument("--budget", type=int, default=None, help="max Alpha Vantage requests this run (default 15 per key)")
    args = ap.parse_args()
    if args.budget is None:
        args.budget = daily_budget()

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
        except RateLimited as e:
            print(f"  {e} — continuing tomorrow")
            break
        except Exception as e:
            print(f"  {t}: stopped — {e}")
            break
    print(f"  requests used: {args.budget - left}")


if __name__ == "__main__":
    main()
