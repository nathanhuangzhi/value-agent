"""Stage 4b': pull yfinance annual + quarterly statements for each analyzed
ticker. Writes a sidecar file `data/companies_yfinance.json` keyed by ticker,
shaped like `companies_sec.json` so the report adapter can blend the two
sources cell-by-cell.

The blend policy lives in `app.tools.report.sec_adapter`:
- SEC wins when both sources have a value for the same metric+period
- yfinance fills gaps where SEC has no value
- Each merged cell carries a source tag (`sec` or `yfinance`); the
  renderer marks yfinance cells visibly so the reader knows which
  numbers came from which authority.

Run:
    ./venv/bin/python -m scripts.fetch_yfinance_statements                  # full run
    ./venv/bin/python -m scripts.fetch_yfinance_statements --ticker AEMD    # one ticker
    ./venv/bin/python -m scripts.fetch_yfinance_statements --limit 5        # smoke test
    ./venv/bin/python -m scripts.fetch_yfinance_statements --workers 4      # tune concurrency
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.tools.json_io import atomic_write_json
from app.tools.paths import COMPANIES_ANALYZED, COMPANIES_YFINANCE
from app.tools.yfinance_statements import fetch_yfinance_statements

CHECKPOINT_EVERY = 20  # rows between full-file rewrites


def _fetch_one(ticker: str) -> tuple[str, dict | None, str | None]:
    """Wrapper that catches exceptions per-ticker so one bad fetch doesn't
    kill the run. Returns (ticker, row_or_None, error_str_or_None)."""
    try:
        return ticker, fetch_yfinance_statements(ticker), None
    except Exception as e:
        return ticker, None, f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", help="One ticker to fetch (else: all in companies_analyzed.json).")
    ap.add_argument("--limit", type=int, help="Process only the first N tickers.")
    ap.add_argument("--workers", type=int, default=2,
                    help="Concurrent yfinance workers (default 2). Match build_company_db.")
    ap.add_argument("--output", type=Path, default=COMPANIES_YFINANCE)
    args = ap.parse_args()

    analyzed = json.loads(COMPANIES_ANALYZED.read_text())
    targets = sorted({r["ticker"] for r in analyzed if r.get("ticker")})
    if args.ticker:
        targets = [args.ticker.upper()]
    if args.limit:
        targets = targets[: args.limit]

    existing = {}
    if args.output.exists():
        existing = {r["ticker"]: r for r in json.loads(args.output.read_text()) if r.get("ticker")}

    print("=== yfinance statements fetch ===")
    print(f"  tickers in scope: {len(targets)}  workers: {args.workers}")
    print()

    results = dict(existing)
    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_fetch_one, t): t for t in targets}
        for fut in as_completed(futures):
            ticker, row, err = fut.result()
            completed += 1
            if err:
                print(f"  [{completed}/{len(targets)}] {ticker}: error {err}")
                continue
            if row is None:
                print(f"  [{completed}/{len(targets)}] {ticker}: yfinance returned no data")
                continue
            results[ticker] = row
            n_ann_rev = len(row["annual"].get("revenue", {}) or {})
            n_q_rev = len(row["quarterly"].get("revenue", {}) or {})
            print(f"  [{completed}/{len(targets)}] {ticker}: annual_rev_years={n_ann_rev}  quarterly_rev_periods={n_q_rev}")

            if completed % CHECKPOINT_EVERY == 0:
                atomic_write_json(args.output, list(results.values()))

    atomic_write_json(args.output, list(results.values()))
    print()
    print(f"Wrote {len(results)} rows → {args.output}")


if __name__ == "__main__":
    main()
