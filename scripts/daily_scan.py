"""
Stage 4: daily company-by-company analysis.

Picks the top-by-count remaining industry from data/companies_filtered.json
(excluding industries used on any prior day of the current cycle). If that
industry has fewer than --target tickers, the next-largest industry is added,
and so on.

Cycles: once every industry has been used, the next run opens a new cycle
(`cycle` field on the daily-log entry) and starts over from the first batch,
re-running each ticker's price history + narrative so the archive is
refreshed in the same deterministic order. Refreshed rows replace the old
row in place (`analyzed_date` = today, `narrative_rerun_at` set).

Each chosen ticker gets:
  - yfinance price history (10y monthly closes for the valuation chart)
  - run_value_agent narrative (Exa market commentary + DeepSeek) — unless
    --no-llm, which still rotates batches + refreshes price history but
    makes no Exa/DeepSeek calls; an existing narrative on the row is kept.

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
    python -m scripts.daily_scan --no-llm         # rotate + price history, no narratives
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
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
from app.tools.daily_selector import (  # noqa: E402
    cycle_start_date,
    entry_cycle,
    is_done_in_cycle,
    plan_todays_pick,
)
from app.tools.financials_tools import fetch_price_history  # noqa: E402
from app.tools.json_io import atomic_write_json, latest_by_ticker, read_json_array  # noqa: E402
from app.workflow import run_value_agent  # noqa: E402


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


_NARRATIVE_FIELDS = ("narrative", "narrative_model", "narrative_provider",
                     "narrative_sources", "usage", "analysis_error", "narrative_rerun_at")


def _process_ticker(universe_row: dict, today: str, fallback_model: str,
                    *, use_llm: bool = True, previous: dict | None = None) -> dict:
    """Per-ticker work: yfinance price history + the analysis pipeline.

    Pure function modulo network I/O — safe to run concurrently. Returns the
    fully-populated analyzed row ready to append to the output array.
    Financial statements (annual + quarterly) come from SEC EDGAR via the
    separate Stage 4b script (`fetch_sec_annual`), not from yfinance.

    With `use_llm=False` no Exa/DeepSeek call is made; the narrative fields
    are carried over from `previous` (the ticker's existing row) so a
    refresh never discards a paid-for narrative.
    """
    ticker = universe_row["ticker"]
    prices = fetch_price_history(ticker)
    if use_llm:
        analysis = run_value_agent(ticker)
        return _build_analyzed_row(universe_row, today, prices, analysis, fallback_model)
    row = _build_analyzed_row(universe_row, today, prices, {}, fallback_model)
    row["narrative_model"] = None
    for k in _NARRATIVE_FIELDS:
        if previous and previous.get(k) is not None:
            row[k] = previous[k]
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", type=int, default=20, help="Minimum tickers per day (default 20).")
    ap.add_argument("--workers", type=int, default=2, help="Concurrent ticker workers (default 2).")
    ap.add_argument("--filtered", type=Path, default=COMPANIES_FILTERED)
    ap.add_argument("--log", type=Path, default=DAILY_LOG)
    ap.add_argument("--output", type=Path, default=COMPANIES_ANALYZED)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print today's industry choice + ticker list. No LLM calls, no file writes.")
    ap.add_argument("--no-llm", action="store_true",
                    help="Rotate batches + refresh price history but skip Exa/DeepSeek; "
                         "existing narratives are kept on the row.")
    args = ap.parse_args()

    today = date.today().isoformat()

    if not args.filtered.exists():
        raise SystemExit(f"!! {args.filtered} does not exist. Run Stage 3 (filter_companies.py) first.")

    rows = read_json_array(args.filtered)
    log = read_json_array(args.log)
    analyzed = read_json_array(args.output)
    latest = latest_by_ticker(analyzed)

    # Find today's entry in the log (if any). This is what makes same-day reruns
    # safe: if we already picked industries today, never re-pick — only resume.
    todays_idx = next((i for i, e in enumerate(log) if e.get("date") == today), None)
    is_resume = todays_idx is not None

    if not is_resume:
        cycle, industries, restarted = plan_todays_pick(rows, log, args.target)
        if not industries:
            print(f"{args.filtered} has no tickers. Nothing to do.")
            return
        if restarted:
            print(f"Cycle {cycle - 1} complete — every industry in {args.filtered.name} has been "
                  f"analyzed. Starting cycle {cycle} from the first batch (narratives refreshed).")
        todays_entry = {"date": today, "cycle": cycle, "industries": industries,
                        "tickers": [], "count": 0}
        if not args.dry_run:
            log.append(todays_entry)
            todays_idx = len(log) - 1
            atomic_write_json(args.log, log)
    else:
        # is_resume==True implies todays_idx is not None; assert for the type checker.
        assert todays_idx is not None
        todays_entry = log[todays_idx]
        industries = todays_entry["industries"]
        cycle = entry_cycle(todays_entry)

    # A ticker is "done" if its latest row was written in this cycle. On a
    # dry run of a brand-new cycle nothing has been logged yet, so treat
    # today as the cycle start.
    cycle_start = cycle_start_date(log, cycle) or today
    candidates = [r for r in rows if r.get("industry") in industries]
    todo = [r for r in candidates if not is_done_in_cycle(latest.get(r["ticker"]), cycle_start)]

    print(f"=== Daily scan {today} (cycle {cycle}) ===")
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

    if args.no_llm:
        narrative_model = "none"
        print(f"  narrative: skipped (--no-llm) | workers: {args.workers}")
    else:
        analysis_config, _ = load_prompt("analysis")
        narrative_model = analysis_config.get("model", "unknown")
        print(f"  narrative model: {narrative_model} | workers: {args.workers}")
    print()

    started = time.time()
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0
    cost_known = False

    # Refreshes (cycle >= 2) overwrite the ticker's existing row so the file
    # doesn't grow by ~20 KB/ticker/cycle; first-time tickers append.
    row_index = {r["ticker"]: i for i, r in enumerate(analyzed) if r.get("ticker")}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(_process_ticker, row, today, narrative_model,
                      use_llm=not args.no_llm, previous=latest.get(row["ticker"])): row
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

            ticker = analyzed_row["ticker"]
            if ticker in row_index:
                if not args.no_llm:
                    analyzed_row["narrative_rerun_at"] = datetime.now(timezone.utc).isoformat()
                analyzed[row_index[ticker]] = analyzed_row
            else:
                row_index[ticker] = len(analyzed)
                analyzed.append(analyzed_row)
            atomic_write_json(args.output, analyzed)

            # Carried-over usage on a --no-llm refresh is the *old* narrative's
            # cost — don't report it as this run's spend.
            usage = {} if args.no_llm else (analyzed_row.get("usage") or {})
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

    # Re-assert for the type checker — todays_idx was set above by either
    # the new-day or resume branch.
    assert todays_idx is not None
    existing_tickers: list = list(todays_entry.get("tickers") or [])
    todays_entry["tickers"] = sorted({*existing_tickers, *(r["ticker"] for r in todo)})
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
        print("  est. cost: unavailable (no pricing entry for the model)")


if __name__ == "__main__":
    main()
