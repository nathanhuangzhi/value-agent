"""Re-run the analysis prompt for tickers already in companies_analyzed.json.

Use this after editing `app/prompts/analysis.prompt.md` to refresh the
narrative for the existing roster without re-fetching financials or
re-running the classifier.

Per-ticker, this calls `run_value_agent(ticker)` which:
  1. Hits Exa for fresh market commentary,
  2. Calls DeepSeek with the current analysis prompt,
  3. Replaces these five fields on the row in place:
     `narrative`, `narrative_model`, `narrative_provider`,
     `narrative_sources`, `usage`.

Everything else (financials, classification, business_overview, etc.) is
preserved. Atomic checkpoint per ticker, so an interrupted run resumes
cleanly.

Run:
    ./venv/bin/python -m scripts.rerun_narratives --tickers AEMD,APYX,INGN  # smoke test
    ./venv/bin/python -m scripts.rerun_narratives --exclude QDEL            # everyone except QDEL
    ./venv/bin/python -m scripts.rerun_narratives --limit 5                 # first 5 only
    ./venv/bin/python -m scripts.rerun_narratives --workers 2               # tune concurrency
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from dotenv import load_dotenv

from app.tools.json_io import atomic_write_json, load_latest_by_ticker
from app.tools.paths import COMPANIES_ANALYZED, COMPANIES_VALIDATION, DATA_DIR, ENV_FILE
from app.workflow import run_value_agent
from scripts.build_report import render_one


def main():
    load_dotenv(ENV_FILE)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", help="comma-separated explicit ticker list (overrides --exclude)")
    ap.add_argument("--exclude", help="comma-separated tickers to skip (default: nothing)")
    ap.add_argument("--limit", type=int, help="process only the first N targets")
    ap.add_argument("--workers", type=int, default=2,
                    help="parallel narrative calls (default 2, matches daily_scan)")
    ap.add_argument("--no-rebuild", action="store_true",
                    help="skip rebuilding the HTML report for each re-narrated ticker")
    args = ap.parse_args()

    rows = json.loads(COMPANIES_ANALYZED.read_text())
    # We mutate `rows` in place and checkpoint after each completion.
    by_ticker_indexes: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        t = r.get("ticker")
        if t:
            by_ticker_indexes.setdefault(t, []).append(i)

    # Determine target ticker list
    if args.tickers:
        targets = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        excluded = {t.strip().upper() for t in (args.exclude or "").split(",") if t.strip()}
        targets = sorted(t for t in by_ticker_indexes if t not in excluded)

    if args.limit:
        targets = targets[: args.limit]

    # Sanity check: every target exists in the file
    missing = [t for t in targets if t not in by_ticker_indexes]
    if missing:
        sys.exit(f"Not in {COMPANIES_ANALYZED.name}: {missing}")

    print("=== rerun_narratives ===")
    print(f"  targets:  {len(targets)}  ({', '.join(targets[:5])}{', ...' if len(targets) > 5 else ''})")
    print(f"  workers:  {args.workers}")
    print()

    total_cost = 0.0
    errors: list[str] = []
    completed = 0

    def _rerun_one(ticker: str) -> tuple[str, dict]:
        return ticker, run_value_agent(ticker)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_rerun_one, t): t for t in targets}
        for fut in as_completed(futures):
            ticker, result = fut.result()
            completed += 1
            err = result.get("error")
            if err:
                errors.append(f"{ticker}: {err}")
                print(f"  [{completed}/{len(targets)}] {ticker}  ERROR  {err}")
                continue

            # Update every row for this ticker (there may be older duplicates;
            # keeping them all consistent avoids stale narratives showing up
            # if someone picks a non-latest row later).
            for idx in by_ticker_indexes[ticker]:
                row = rows[idx]
                row["narrative"] = result["narrative"]
                row["narrative_model"] = result["narrative_model"]
                row["narrative_provider"] = result["narrative_provider"]
                row["narrative_sources"] = result["narrative_sources"]
                row["usage"] = result["usage"]
                row["narrative_rerun_at"] = datetime.now(timezone.utc).isoformat()
                row["analysis_error"] = None

            cost = (result.get("usage") or {}).get("estimated_cost_usd") or 0
            total_cost += cost
            atomic_write_json(COMPANIES_ANALYZED, rows)
            print(f"  [{completed}/{len(targets)}] {ticker}  ${cost:.4f}  "
                  f"({(result.get('usage') or {}).get('total_tokens', '?')} tok)")

    print()
    print("=== narratives done ===")
    print(f"  succeeded: {completed - len(errors)}/{len(targets)}")
    print(f"  total cost: ${total_cost:.4f}")
    if errors:
        print(f"\n  errors ({len(errors)}):")
        for e in errors:
            print(f"    {e}")

    if args.no_rebuild:
        print("\n  --no-rebuild set: HTML reports were NOT regenerated.")
        return

    # Rebuild HTML so the rendered reports reflect the new narratives.
    print("\n=== rebuild HTML ===")
    fresh_latest = load_latest_by_ticker(COMPANIES_ANALYZED)
    validation: dict = {}
    if COMPANIES_VALIDATION.exists():
        validation = {r["ticker"]: r for r in json.loads(COMPANIES_VALIDATION.read_text()) if r.get("ticker")}
    reports_dir = DATA_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    error_tickers = {e.split(":", 1)[0] for e in errors}
    for ticker in targets:
        if ticker in error_tickers:
            continue
        render_one(
            ticker,
            analyzed_by_ticker=fresh_latest,
            validation_by_ticker=validation,
        )
    print(f"  rebuilt {len(targets) - len(error_tickers)} HTML reports → {reports_dir}/")


if __name__ == "__main__":
    main()
