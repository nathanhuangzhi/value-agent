"""Stage 4b': pull yfinance annual + quarterly statements for each analyzed
ticker. Writes per-industry shard files `data/yfinance/<industry-slug>.json`
(each a list of ticker rows shaped like `companies_sec.json`) so the report
adapter can blend the two sources cell-by-cell. Sharding by industry keeps
every file small (well under GitHub's 100 MB push limit) and means a daily
run only rewrites the shard(s) for the industries it actually scanned.

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
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.tools.json_io import atomic_write_json
from app.tools.paths import COMPANIES_ANALYZED, COMPANIES_YFINANCE_DIR
from app.tools.report.sec_adapter import load_sharded_by_ticker
from app.tools.yfinance_statements import fetch_yfinance_statements

CHECKPOINT_EVERY = 20  # rows between shard rewrites


def _slug(s: str) -> str:
    """Industry → shard filename stem. Matches app.api.routes._slug so the
    filenames line up with the API's industry slugs."""
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "uncategorized"


def _fetch_one(ticker: str) -> tuple[str, dict | None, str | None]:
    """Wrapper that catches exceptions per-ticker so one bad fetch doesn't
    kill the run. Returns (ticker, row_or_None, error_str_or_None)."""
    try:
        return ticker, fetch_yfinance_statements(ticker), None
    except Exception as e:
        return ticker, None, f"{type(e).__name__}: {e}"


def _write_shards(out_dir: Path, results: dict, ticker_slug: dict, only: set[str]) -> None:
    """Rewrite the shard file(s) named in `only`. Each shard is the full list
    of rows whose ticker maps to that industry slug, sorted by ticker."""
    by_slug: dict[str, list] = defaultdict(list)
    for ticker, row in results.items():
        by_slug[ticker_slug.get(ticker, "uncategorized")].append(row)
    out_dir.mkdir(parents=True, exist_ok=True)
    for slug in only:
        rows = sorted(by_slug.get(slug, []), key=lambda r: r["ticker"])
        atomic_write_json(out_dir / f"{slug}.json", rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", help="One ticker to fetch (else: all in companies_analyzed.json).")
    ap.add_argument("--limit", type=int, help="Process only the first N tickers.")
    ap.add_argument("--workers", type=int, default=2,
                    help="Concurrent yfinance workers (default 2). Match build_company_db.")
    ap.add_argument("--output-dir", type=Path, default=COMPANIES_YFINANCE_DIR,
                    help="Directory of per-industry shard files (default data/yfinance/).")
    args = ap.parse_args()

    analyzed = json.loads(COMPANIES_ANALYZED.read_text())
    # ticker → industry slug, so each fetched row lands in the right shard.
    ticker_slug = {r["ticker"]: _slug(r.get("industry") or "")
                   for r in analyzed if r.get("ticker")}

    targets = sorted(ticker_slug)
    if args.ticker:
        targets = [args.ticker.upper()]
    if args.limit:
        targets = targets[: args.limit]

    # Seed from existing shards so we only re-fetch what's missing and only
    # rewrite the shards we actually touch.
    results = load_sharded_by_ticker(args.output_dir)

    print("=== yfinance statements fetch ===")
    print(f"  tickers in scope: {len(targets)}  workers: {args.workers}")
    print(f"  output: {args.output_dir}/<industry-slug>.json")
    print()

    touched: set[str] = set()
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
            touched.add(ticker_slug.get(ticker, "uncategorized"))
            n_ann_rev = len(row["annual"].get("revenue", {}) or {})
            n_q_rev = len(row["quarterly"].get("revenue", {}) or {})
            print(f"  [{completed}/{len(targets)}] {ticker}: annual_rev_years={n_ann_rev}  quarterly_rev_periods={n_q_rev}")

            if completed % CHECKPOINT_EVERY == 0 and touched:
                _write_shards(args.output_dir, results, ticker_slug, touched)

    if touched:
        _write_shards(args.output_dir, results, ticker_slug, touched)
    print()
    print(f"Wrote {len(results)} rows across {len(touched)} shard(s) → {args.output_dir}/")


if __name__ == "__main__":
    main()
