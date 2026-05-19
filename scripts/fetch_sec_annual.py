"""Stage 4.5: pull SEC EDGAR XBRL annual (and quarterly) statements for each
analyzed ticker. Writes a sidecar file `data/companies_sec.json` keyed by
ticker. The report-rendering layer prefers SEC data over yfinance for the
historical table when SEC has it (deeper history — 10+ years typical vs
yfinance's 3-5).

Free, no API key. Polite rate-limit (~8 req/sec) built into the fetcher.

Extraction logic (metric concept fallbacks, share-count rescaler, etc.)
lives in `app.tools.sec_xbrl_tools`; this script is just the resume-safe
CLI wrapper over `build_sec_row(...)`.

Run:
    python -m scripts.fetch_sec_annual                  # full run
    python -m scripts.fetch_sec_annual --ticker QDEL    # one ticker
    python -m scripts.fetch_sec_annual --limit 5        # smoke test
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.tools.json_io import atomic_write_json, read_jsonl
from app.tools.paths import COMPANIES_ANALYZED, COMPANIES_JSONL, COMPANIES_SEC
from app.tools.sec_xbrl_tools import build_sec_row, fetch_companyfacts

CHECKPOINT_EVERY = 20  # rows between full-file rewrites


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", help="One ticker to fetch (else: all in companies_analyzed.json).")
    ap.add_argument("--limit", type=int, help="Process only the first N tickers.")
    ap.add_argument("--output", type=Path, default=COMPANIES_SEC)
    args = ap.parse_args()

    # Pick target tickers from the analyzed roster; look up CIKs from
    # companies.jsonl (Stage 1 already populates these).
    analyzed = json.loads(COMPANIES_ANALYZED.read_text())
    targets = {r["ticker"] for r in analyzed if r.get("ticker")}
    if args.ticker:
        targets = {args.ticker.upper()}

    universe = {r["ticker"]: r for r in read_jsonl(COMPANIES_JSONL) if r.get("ticker")}

    existing = {}
    if args.output.exists():
        existing = {r["ticker"]: r for r in json.loads(args.output.read_text()) if r.get("ticker")}

    todo = sorted(targets)
    if args.limit:
        todo = todo[: args.limit]

    print("=== SEC EDGAR fetch ===")
    print(f"  tickers in scope: {len(todo)}")
    print(f"  already fetched:  {sum(1 for t in todo if t in existing)}")
    print()

    results = dict(existing)
    for i, ticker in enumerate(todo, 1):
        if ticker in results and not args.ticker:
            continue
        u = universe.get(ticker)
        if not u or not u.get("cik"):
            print(f"  [{i}/{len(todo)}] {ticker}: no CIK; skip")
            continue
        try:
            facts = fetch_companyfacts(u["cik"])
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {ticker}: error {type(e).__name__}: {e}")
            continue
        if facts is None:
            print(f"  [{i}/{len(todo)}] {ticker} (CIK {u['cik']}): 404 — no XBRL data")
            continue
        try:
            row = build_sec_row(ticker, u["cik"], facts)
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {ticker}: extract error {type(e).__name__}: {e}")
            continue
        results[ticker] = row
        n_years = len(row["annual"].get("revenue", {}))
        flagged = row.get("mna_flagged_years") or []
        flag_str = f"  ⚠ M&A flag {flagged}" if flagged else ""
        print(f"  [{i}/{len(todo)}] {ticker} ({row['entity_name'][:30]:<30}): {n_years} FY years{flag_str}")

        if i % CHECKPOINT_EVERY == 0:
            atomic_write_json(args.output, list(results.values()))

    atomic_write_json(args.output, list(results.values()))
    print()
    print(f"Wrote {len(results)} rows → {args.output}")


if __name__ == "__main__":
    main()
