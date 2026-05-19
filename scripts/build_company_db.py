"""
Stage 1 ETL: fetch business overviews for every NYSE + Nasdaq ticker
and write to data/companies.jsonl.

Resume-safe: re-running skips tickers already on disk. Append-only writes
flush after every row, so an interrupted run never loses progress.

Run:
    python -m scripts.build_company_db
    python -m scripts.build_company_db --limit 50      # smoke test
    python -m scripts.build_company_db --workers 4     # tune concurrency
"""

import argparse
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from yfinance.exceptions import YFRateLimitError

from app.tools.json_io import jsonl_field_set
from app.tools.paths import COMPANIES_JSONL
from app.tools.profile_tools import fetch_company_profile
from app.tools.universe_tools import fetch_us_listed_tickers

# Per-worker retry on YFRateLimitError. Exponential backoff with jitter.
_RETRY_DELAYS_S = [5, 15, 45, 120]


def fetch_with_backoff(ticker: str) -> tuple[str, dict | None]:
    """Returns (status, profile) where status is 'ok' / 'empty' / 'throttled'."""
    for delay in [0] + _RETRY_DELAYS_S:
        if delay:
            time.sleep(delay + random.uniform(0, delay * 0.25))
        try:
            profile = fetch_company_profile(ticker)
        except YFRateLimitError:
            continue
        return ("ok", profile) if profile else ("empty", None)
    return ("throttled", None)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="Process only the first N new tickers (smoke testing).")
    ap.add_argument("--workers", type=int, default=2, help="Concurrent yfinance workers (default 2).")
    ap.add_argument("--output", type=Path, default=COMPANIES_JSONL, help="Output JSONL path.")
    ap.add_argument("--abort-after-throttled", type=int, default=20,
                    help="Stop the run if this many tickers are throttled. Resume later. Default 20.")
    args = ap.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    print("Fetching ticker universe from SEC EDGAR...")
    universe = fetch_us_listed_tickers()
    print(f"  -> {len(universe)} tickers (NYSE + Nasdaq)")

    done = jsonl_field_set(args.output, "ticker")
    todo = [row for row in universe if row["ticker"] not in done]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"  -> {len(done)} already on disk, {len(todo)} to fetch")
    if not todo:
        print("Nothing to do.")
        return

    succeeded = empty = errored = throttled = 0
    started = time.time()

    with args.output.open("a") as out, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(fetch_with_backoff, row["ticker"]): row for row in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            row = futures[fut]
            ticker = row["ticker"]
            try:
                status, profile = fut.result()
            except Exception as e:
                errored += 1
                print(f"  !! {ticker}: {e!r}")
                continue

            if status == "ok" and profile is not None:
                profile.setdefault("name", row["name"])
                profile["cik"] = row["cik"]
                out.write(json.dumps(profile, ensure_ascii=False) + "\n")
                out.flush()
                succeeded += 1
            elif status == "throttled":
                throttled += 1
            else:
                empty += 1

            if i % 50 == 0 or i == len(todo):
                rate = i / (time.time() - started)
                remaining = (len(todo) - i) / rate if rate else 0
                print(
                    f"  [{i}/{len(todo)}] ok={succeeded} empty={empty} "
                    f"throttled={throttled} err={errored} "
                    f"rate={rate:.1f}/s eta={remaining/60:.1f}min"
                )

            if throttled >= args.abort_after_throttled:
                print(f"\n  !! Aborted: {throttled} tickers throttled. Wait 30+ min and rerun to resume.")
                for f in futures:
                    f.cancel()
                break

    print(f"Done. ok={succeeded} empty={empty} throttled={throttled} err={errored} -> {args.output}")


if __name__ == "__main__":
    main()
