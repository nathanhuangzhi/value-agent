"""Stage 4.5: pull SEC EDGAR XBRL annual (and quarterly) statements for each
analyzed ticker. Writes one row per ticker to `data/sec/<TICKER>.json`
(see app.tools.sec_store). The report-rendering layer prefers SEC data over yfinance for the
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

from app.tools.json_io import read_jsonl
from app.tools.paths import COMPANIES_ANALYZED, COMPANIES_JSONL, COMPANIES_SEC_DIR
from app.tools.sec_store import SecStore
from app.tools.sec_xbrl_tools import build_sec_row, fetch_companyfacts, load_raw_companyfacts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", help="One ticker to fetch (else: all in companies_analyzed.json).")
    ap.add_argument("--limit", type=int, help="Process only the first N tickers.")
    ap.add_argument("--out-dir", type=Path, default=COMPANIES_SEC_DIR, help="per-ticker row directory (data/sec/)")
    ap.add_argument("--refresh", action="store_true",
                    help="Re-fetch tickers already in the cache (e.g. after adding "
                         "XBRL concepts to sec_xbrl_tools). Default: skip cached.")
    ap.add_argument("--reparse", action="store_true",
                    help="Rebuild every row from the raw companyfacts cache (data/sec_raw/) "
                         "without touching the network — after adding concepts or fixing the "
                         "extractor. Tickers with no raw file are downloaded.")
    ap.add_argument("--max-age-days", type=int, default=None,
                    help="Also re-fetch cached tickers whose fetched_at is older than this "
                         "many days (the daily run uses 7 → the whole pool is refreshed on a "
                         "rolling weekly basis, ~1/7 of it per day).")
    args = ap.parse_args()

    # Pick target tickers from the analyzed roster; look up CIKs from
    # companies.jsonl (Stage 1 already populates these).
    analyzed = json.loads(COMPANIES_ANALYZED.read_text())
    targets = {r["ticker"] for r in analyzed if r.get("ticker")}
    if args.ticker:
        targets = {args.ticker.upper()}

    universe = {r["ticker"]: r for r in read_jsonl(COMPANIES_JSONL) if r.get("ticker")}

    store = SecStore(args.out_dir)
    existing = set(store.tickers())

    todo = sorted(targets)
    if args.limit:
        todo = todo[: args.limit]

    print("=== SEC EDGAR fetch ===")
    print(f"  tickers in scope: {len(todo)}")
    print(f"  already fetched:  {sum(1 for t in todo if t in existing)}")
    print()

    n_written = 0
    stale_before = None
    if args.max_age_days is not None:
        from datetime import datetime, timedelta, timezone
        stale_before = (datetime.now(timezone.utc) - timedelta(days=args.max_age_days)).isoformat()
    n_stale = n_reparsed = 0
    for i, ticker in enumerate(todo, 1):
        u = universe.get(ticker)
        if not u or not u.get("cik"):
            print(f"  [{i}/{len(todo)}] {ticker}: no CIK; skip")
            continue
        use_raw = not args.refresh          # raw cache is the default source when present
        if ticker in existing and not args.ticker and not args.refresh:
            fetched_at = (store.get(ticker) or {}).get("fetched_at") or ""
            stale = bool(stale_before and fetched_at < stale_before)
            if not stale and not args.reparse:
                continue
            if stale:
                n_stale += 1
                use_raw = False         # stale → re-download (refreshes the raw file too)
        cached = load_raw_companyfacts(u["cik"]) if use_raw else None
        raw_fetched_at = None
        facts: dict | None
        if cached is not None:
            facts, raw_fetched_at = cached
            n_reparsed += 1
        else:
            try:
                facts = fetch_companyfacts(u["cik"])
            except Exception as e:
                print(f"  [{i}/{len(todo)}] {ticker}: error {type(e).__name__}: {e}")
                continue
            if facts is None:
                print(f"  [{i}/{len(todo)}] {ticker} (CIK {u['cik']}): 404 — no XBRL data")
                continue
        try:
            row = build_sec_row(ticker, u["cik"], facts, fetched_at=raw_fetched_at)
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {ticker}: extract error {type(e).__name__}: {e}")
            continue
        store.put(row)                      # one file per ticker — every row is its own checkpoint
        n_written += 1
        n_years = len(row["annual"].get("revenue", {}))
        flagged = row.get("mna_flagged_years") or []
        flag_str = f"  ⚠ M&A flag {flagged}" if flagged else ""
        print(f"  [{i}/{len(todo)}] {ticker} ({row['entity_name'][:30]:<30}): {n_years} FY years{flag_str}")

    print()
    if stale_before:
        print(f"  refreshed {n_stale} cached ticker(s) older than {args.max_age_days} days")
    if n_reparsed:
        print(f"  re-parsed {n_reparsed} ticker(s) from the raw cache (no download)")
    print(f"Wrote {n_written} row(s) → {args.out_dir} ({len(store.tickers())} tickers on disk)")


if __name__ == "__main__":
    main()
