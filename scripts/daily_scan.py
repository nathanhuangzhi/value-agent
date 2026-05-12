"""
Stage 4: daily company-by-company analysis.

Picks the top-by-count remaining industry from data/companies_filtered.json
(excluding industries used on any prior day). If that industry has fewer than
--target tickers, the next-largest industry is added, and so on.

Each chosen ticker gets:
  - yfinance price history (10y monthly closes for the valuation chart)
  - run_value_agent narrative (Exa market commentary + DeepSeek)

Financial statements (annual + quarterly) come from SEC EDGAR via the
separate Stage 4b script (`scripts.fetch_sec_annual`), not from yfinance.

Results are appended to a single JSON array at data/companies_analyzed.json.
The day's industry choice is logged to data/daily_industry_log.json.

Resume-safe: a re-run on the same day skips tickers already analyzed. Per-row
atomic checkpoint so analysis calls are never lost on crash.

Run:
    python -m scripts.daily_scan
    python -m scripts.daily_scan --target 30 --workers 4
    python -m scripts.daily_scan --dry-run        # plan only, no LLM calls
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from app.tools.paths import (
    COMPANIES_ANALYZED,
    COMPANIES_FILTERED,
    DAILY_LOG,
    ENV_FILE,
)

load_dotenv(ENV_FILE)

# Imports below depend on the .env being loaded (LLM keys, etc.).
from app.core.prompt_manager import load_prompt  # noqa: E402
from app.tools.daily_selector import pick_todays_industries  # noqa: E402
from app.tools.financials_tools import fetch_price_history  # noqa: E402
from app.tools.json_io import atomic_write_json, read_json_array  # noqa: E402
from app.workflow import run_value_agent  # noqa: E402


def _used_industries(log: list[dict]) -> set[str]:
    used: set[str] = set()
    for entry in log:
        used.update(entry.get("industries", []))
    return used


def _build_analyzed_row(
    universe_row: dict,
    today: str,
    prices: dict | None,
    analysis: dict,
    fallback_model: str,
) -> dict:
    """Compose one row of data/companies_analyzed.json from its inputs.
    Financial statements (annual + quarterly) come from SEC EDGAR (Stage 4b
    sidecar at data/companies_sec.json), not from this row."""
    usage = analysis.get("usage") or {}
    return {
        "ticker": universe_row["ticker"],
        "analyzed_date": today,
        "name": universe_row.get("name"),
        "sector": universe_row.get("sector"),
        "industry": universe_row.get("industry"),
        "market_cap": universe_row.get("market_cap"),
        "country": universe_row.get("country"),
        "exchange": universe_row.get("exchange"),
        "business_overview": universe_row.get("business_overview"),
        "classification": universe_row.get("classification"),
        "classification_meta": universe_row.get("classification_meta"),
        "price_history": prices,
        "narrative_sources": analysis.get("narrative_sources"),
        "narrative": analysis.get("narrative"),
        "narrative_model": analysis.get("narrative_model") or fallback_model,
        "narrative_provider": analysis.get("narrative_provider"),
        "usage": usage or None,
        "analysis_error": analysis.get("error"),
    }


def _process_ticker(universe_row: dict, today: str, fallback_model: str) -> dict:
    """Per-ticker work: yfinance price history + the analysis pipeline.

    Pure function modulo network I/O — safe to run concurrently. Returns the
    fully-populated analyzed row ready to append to the output array.
    Financial statements (annual + quarterly) come from SEC EDGAR via the
    separate Stage 4b script (`fetch_sec_annual`), not from yfinance.
    """
    ticker = universe_row["ticker"]
    prices = fetch_price_history(ticker)
    analysis = run_value_agent(ticker)
    return _build_analyzed_row(universe_row, today, prices, analysis, fallback_model)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", type=int, default=20, help="Minimum tickers per day (default 20).")
    ap.add_argument("--workers", type=int, default=2, help="Concurrent ticker workers (default 2).")
    ap.add_argument("--filtered", type=Path, default=COMPANIES_FILTERED)
    ap.add_argument("--log", type=Path, default=DAILY_LOG)
    ap.add_argument("--output", type=Path, default=COMPANIES_ANALYZED)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print today's industry choice + ticker list. No LLM calls, no file writes.")
    args = ap.parse_args()

    today = date.today().isoformat()

    if not args.filtered.exists():
        raise SystemExit(f"!! {args.filtered} does not exist. Run Stage 3 (filter_companies.py) first.")

    rows = read_json_array(args.filtered)
    log = read_json_array(args.log)
    analyzed = read_json_array(args.output)
    seen_tickers = {r["ticker"] for r in analyzed if r.get("ticker")}

    # Find today's entry in the log (if any). This is what makes same-day reruns
    # safe: if we already picked industries today, never re-pick — only resume.
    todays_idx = next((i for i, e in enumerate(log) if e.get("date") == today), None)
    is_resume = todays_idx is not None

    if not is_resume:
        industries, _ = pick_todays_industries(rows, _used_industries(log), args.target)
        if not industries:
            print("All industries in companies_filtered.json have been analyzed in prior runs. Nothing to do.")
            return
        todays_entry = {"date": today, "industries": industries, "tickers": [], "count": 0}
        if not args.dry_run:
            log.append(todays_entry)
            todays_idx = len(log) - 1
            atomic_write_json(args.log, log)
    else:
        todays_entry = log[todays_idx]
        industries = todays_entry["industries"]

    candidates = [r for r in rows if r.get("industry") in industries]
    todo = [r for r in candidates if r["ticker"] not in seen_tickers]

    print(f"=== Daily scan {today} ===")
    print(f"  industries: {industries}{'  (resumed)' if is_resume and not args.dry_run else ''}")
    print(f"  tickers in scope: {len(candidates)}")
    print(f"  already analyzed: {len(candidates) - len(todo)}")
    print(f"  to analyze now: {len(todo)}")
    print()

    if args.dry_run:
        for r in todo:
            cap = r.get("market_cap") or 0
            print(f"  {r['ticker']:6s}  ${cap/1e6:>8,.0f}M  {r.get('industry'):35s}  {r.get('name')}")
        print("\n(dry run — no LLM calls, no file writes)")
        return

    if not todo:
        print(f"{today}: all {len(candidates)} tickers already analyzed. Nothing to do.")
        return

    analysis_config, _ = load_prompt("analysis")
    narrative_model = analysis_config.get("model", "unknown")
    print(f"  narrative model: {narrative_model} | workers: {args.workers}")
    print()

    started = time.time()
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0
    cost_known = False

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(_process_ticker, row, today, narrative_model): row
            for row in todo
        }
        for i, fut in enumerate(as_completed(futures), 1):
            row = futures[fut]
            try:
                analyzed_row = fut.result()
            except Exception as e:
                # _process_ticker shouldn't raise (run_value_agent catches), but
                # handle it anyway so one bad ticker doesn't kill the run.
                print(f"[{i}/{len(todo)}] !! {row['ticker']}: {type(e).__name__}: {e}")
                continue

            analyzed.append(analyzed_row)
            atomic_write_json(args.output, analyzed)

            usage = analyzed_row.get("usage") or {}
            if usage.get("prompt_tokens"):
                total_prompt_tokens += usage["prompt_tokens"]
            if usage.get("completion_tokens"):
                total_completion_tokens += usage["completion_tokens"]
            if usage.get("estimated_cost_usd") is not None:
                total_cost += usage["estimated_cost_usd"]
                cost_known = True

            cost_str = f", est ${usage.get('estimated_cost_usd'):.4f}" if usage.get("estimated_cost_usd") is not None else ""
            tok_str = f", {usage.get('total_tokens')} tokens" if usage.get("total_tokens") else ""
            print(f"[{i}/{len(todo)}] {analyzed_row['ticker']} {analyzed_row.get('name')}{tok_str}{cost_str}")

    todays_entry["tickers"] = sorted({*todays_entry.get("tickers", []), *(r["ticker"] for r in todo)})
    todays_entry["count"] = len(todays_entry["tickers"])
    log[todays_idx] = todays_entry
    atomic_write_json(args.log, log)

    elapsed = time.time() - started
    print(f"\nDone. analyzed {len(todo)} tickers in {elapsed/60:.1f} min")
    print(f"  -> {args.output} (total rows on disk: {len(analyzed)})")
    print(f"  -> {args.log}")
    print(f"  tokens: {total_prompt_tokens:,} prompt + {total_completion_tokens:,} completion "
          f"= {total_prompt_tokens + total_completion_tokens:,} total")
    if cost_known:
        print(f"  est. cost: ${total_cost:.4f} (using approximate rates in app/tools/llm_router.py)")
    else:
        print(f"  est. cost: unavailable (no pricing entry for the model)")


if __name__ == "__main__":
    main()
