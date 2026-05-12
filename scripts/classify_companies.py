"""
Stage 2: Run the structured classifier (DeepSeek) against every row in
data/companies.jsonl and write structured output to data/companies_classified.json
(single JSON array). Probes go to data/classify_probes.json.

Resume-safe: re-runs skip tickers already classified. Periodic atomic checkpoints
guard against partial writes on crash. Each call is JSON-mode + Pydantic-validated;
validation failures are recorded in data/companies_classify_failures.json.

Run:
    python -m scripts.classify_companies --probe POOL          # 1-ticker dry test
    python -m scripts.classify_companies --limit 50            # smoke test on first 50
    python -m scripts.classify_companies                       # full run
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from app.core.prompt_manager import load_prompt
from app.tools.json_io import atomic_write_json, read_json_array, read_jsonl
from app.tools.paths import (
    COMPANIES_JSONL,
    COMPANIES_CLASSIFIED,
    ENV_FILE,
    CLASSIFY_FAILURES,
    CLASSIFY_PROBES,
)
from app.tools.classification_tools import classify_company

load_dotenv(ENV_FILE)

CHECKPOINT_EVERY = 100  # successful results between full-file rewrites


def _classify_one(row: dict, model: str, temperature: float):
    """Render the prompt for this company, call DeepSeek, return (ticker, status, payload, err)."""
    _, prompt = load_prompt(
        "classify",
        ticker=row["ticker"],
        name=row.get("name"),
        sector=row.get("sector"),
        industry=row.get("industry"),
        market_cap=row.get("market_cap"),
        business_overview=row.get("business_overview", ""),
    )
    status, payload, err = classify_company(prompt, model=model, temperature=temperature)
    return row["ticker"], status, payload, err


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", type=str, default=None,
                    help="Run a single ticker (e.g. POOL) and append/update its row in classify_probes.json.")
    ap.add_argument("--limit", type=int, default=None, help="Process only the first N new tickers.")
    ap.add_argument("--workers", type=int, default=4, help="Concurrent DeepSeek workers (default 4).")
    ap.add_argument("--input", type=Path, default=COMPANIES_JSONL)
    ap.add_argument("--output", type=Path, default=COMPANIES_CLASSIFIED)
    ap.add_argument("--failures", type=Path, default=CLASSIFY_FAILURES)
    ap.add_argument("--probes", type=Path, default=CLASSIFY_PROBES)
    args = ap.parse_args()

    config, _ = load_prompt("classify")
    model = config["model"]
    temperature = config.get("temperature", 0.1)
    print(f"Provider: {config.get('provider', 'deepseek')} | Model: {model} | Temperature: {temperature}")

    companies = read_jsonl(args.input)
    by_ticker = {row["ticker"]: row for row in companies if row.get("ticker")}
    print(f"Loaded {len(companies)} companies from {args.input.name}")

    if args.probe:
        if args.probe not in by_ticker:
            print(f"!! ticker {args.probe!r} not found in {args.input.name}")
            sys.exit(1)
        row = by_ticker[args.probe]
        print(f"\n--- PROBE: {args.probe} ({row.get('name')}) ---")
        ticker, status, payload, err = _classify_one(row, model, temperature)
        probe_record = {
            "ticker": ticker,
            "model": model,
            "status": status,
            "payload": payload,
            "error": err,
        }
        existing = [r for r in read_json_array(args.probes) if r.get("ticker") != ticker]
        existing.append(probe_record)
        atomic_write_json(args.probes, existing)
        print(f"status: {status}")
        if payload:
            print(json.dumps(payload, indent=2))
        if err:
            print(f"error: {err}")
        print(f"\nsaved -> {args.probes} ({len(existing)} probes total)")
        return

    results = read_json_array(args.output)
    failures = read_json_array(args.failures)
    done = {r["ticker"] for r in results if r.get("ticker")}

    todo = [row for row in companies if row["ticker"] not in done]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"  -> {len(done)} already classified, {len(todo)} to process")
    if not todo:
        print("Nothing to do.")
        return

    ok = invalid = rate_limited = errored = 0
    started = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_classify_one, row, model, temperature): row for row in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            ticker, status, payload, err = fut.result()
            if status == "ok":
                results.append(payload)
                ok += 1
            else:
                failures.append({"ticker": ticker, "status": status, "error": err})
                if status == "validation_failed":
                    invalid += 1
                elif status == "rate_limited":
                    rate_limited += 1
                else:
                    errored += 1

            # Checkpoint every CHECKPOINT_EVERY completions (any status), so a
            # crash never loses more than that many rows of work.
            if i % CHECKPOINT_EVERY == 0:
                atomic_write_json(args.output, results)
                atomic_write_json(args.failures, failures)

            if i % 50 == 0 or i == len(todo):
                rate = i / (time.time() - started)
                eta = (len(todo) - i) / rate if rate else 0
                print(
                    f"  [{i}/{len(todo)}] ok={ok} invalid={invalid} "
                    f"rate_limited={rate_limited} err={errored} "
                    f"rate={rate:.1f}/s eta={eta/60:.1f}min"
                )

    atomic_write_json(args.output, results)
    atomic_write_json(args.failures, failures)

    print(f"Done. ok={ok} invalid={invalid} rate_limited={rate_limited} err={errored}")
    print(f"  -> {args.output} ({len(results)} total) | failures: {args.failures} ({len(failures)} total)")


if __name__ == "__main__":
    main()
