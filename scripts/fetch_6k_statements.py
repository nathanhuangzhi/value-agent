"""Stage 4b''': extract quarterly statements from 6-K earnings releases
(foreign private issuers — see app/tools/sec_6k.py).

Targets: the watchlist ∪ tickers that already have a 6-K store ∪ SEC rows
whose reporting currency isn't USD. For each, every 6-K not yet in the
store is inspected; results releases go through DeepSeek (JSON mode) and
land in data/sec_6k/<TICKER>.json. Idempotent: a filing is processed once.

Run:
    ./venv/bin/python -m scripts.fetch_6k_statements --dry-run          # list + cost estimate, no LLM
    ./venv/bin/python -m scripts.fetch_6k_statements                    # extract everything new
    ./venv/bin/python -m scripts.fetch_6k_statements --ticker PDD --since 2024-01-01
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from dotenv import load_dotenv

from app.tools.json_io import read_json_array, read_jsonl
from app.tools.paths import COMPANIES_JSONL, COMPANIES_SEC, ENV_FILE
from app.tools.sec_6k import (
    SIXK_DIR,
    extract_with_llm,
    fetch_document,
    filing_documents,
    html_to_text,
    list_filings,
    load_all_stores,
    load_store,
    looks_like_results_release,
    save_store,
)
from app.tools.watchlist import load_watchlist

load_dotenv(ENV_FILE)

_APPROX_CHARS_PER_TOKEN = 3.2      # EDGAR text with numbers/pipes is token-dense
_APPROX_OUTPUT_TOKENS = 1800
_FLASH_IN, _FLASH_OUT = 0.30, 1.20  # $/M tokens, approximation (llm_router)


def _targets(explicit: str | None) -> list[str]:
    if explicit:
        return [explicit.upper()]
    t = set(load_watchlist()) | set(load_all_stores())
    for r in read_json_array(COMPANIES_SEC):
        if (r.get("currency") or "USD").upper() != "USD":
            t.add(r["ticker"])
    return sorted(t)


def _exhibit_candidates(names: list[str], primary: str) -> list[str]:
    ex = [n for n in names if "ex99" in n.lower() or "ex-99" in n.lower()]
    return ex or [n for n in names if n != primary]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker")
    ap.add_argument("--since", default=(date.today() - timedelta(days=3 * 365)).isoformat(),
                    help="only 6-Ks filed on/after this date (default: 3 years back)")
    ap.add_argument("--max-per-ticker", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true", help="list filings + estimate cost; no LLM calls")
    ap.add_argument("--recheck-skipped", action="store_true",
                    help="re-inspect filings previously marked 'not a results release' "
                         "(after a detection-rule change)")
    args = ap.parse_args()

    universe = {r["ticker"]: r for r in read_jsonl(COMPANIES_JSONL) if r.get("ticker")}
    targets = _targets(args.ticker)
    print("=== 6-K statements ===")
    print(f"  targets: {len(targets)}  ({', '.join(targets) or '—'})   since {args.since}")
    SIXK_DIR.mkdir(parents=True, exist_ok=True)

    total_new = total_chars = 0
    total_cost = 0.0
    for t in targets:
        u = universe.get(t)
        if not u or not u.get("cik"):
            print(f"  {t}: no CIK — skip")
            continue
        store = load_store(t)
        # A filing whose extraction failed (timeout, schema) is dropped from
        # the store so it's retried this run; skips and successes are final.
        failed = {f["accession"] for f in store["filings"]
                  if (f.get("skipped") or "").startswith("extraction failed")
                  or (args.recheck_skipped and f.get("skipped") == "not a results release")}
        if failed:
            store["filings"] = [f for f in store["filings"] if f["accession"] not in failed]
        seen = {f["accession"] for f in store["filings"]}
        try:
            filings = [f for f in list_filings(u["cik"], since=args.since) if f["accession"] not in seen]
        except Exception as e:
            print(f"  {t}: submissions error {type(e).__name__}: {e}")
            continue
        filings = filings[: args.max_per_ticker]
        n_results = 0
        for f in filings:
            entry = {"accession": f["accession"], "filed": f["filed"], "document": None,
                     "extracted": None, "usage": None, "skipped": None}
            try:
                docs = filing_documents(u["cik"], f["accession"])
            except Exception as e:
                entry["skipped"] = f"index error: {e}"
                store["filings"].append(entry)
                continue
            text = None
            for name in _exhibit_candidates(docs, f["primary_document"]):
                try:
                    raw = fetch_document(u["cik"], f["accession"], name)
                except Exception as e:
                    print(f"  {t} {f['accession']} {name}: fetch failed ({e})")
                    continue
                candidate = html_to_text(raw)
                if looks_like_results_release(candidate):
                    text, entry["document"] = candidate, name
                    cache = SIXK_DIR / t / f"{f['accession']}_{name}"
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(raw)
                    break
            if text is None:
                entry["skipped"] = "not a results release"
                if not args.dry_run:
                    store["filings"].append(entry)
                continue
            n_results += 1
            total_new += 1
            total_chars += len(text)
            if args.dry_run:
                print(f"    {t} {f['filed']} {entry['document']}  ({len(text):,} chars)")
                continue
            ex, usage, err = extract_with_llm(text, ticker=t, company=u.get("name") or t,
                                              filed=f["filed"], accession=f["accession"])
            entry["usage"] = usage
            total_cost += (usage or {}).get("estimated_cost_usd") or 0
            if ex is None:
                entry["skipped"] = f"extraction failed: {err}"
                print(f"    {t} {f['filed']}: FAILED {err}")
            else:
                entry["extracted"] = ex.model_dump()
                n_items = sum(len(getattr(ex.statements, k)) for k in ("income_statement", "balance_sheet", "cash_flow"))
                print(f"    {t} {f['filed']}: {ex.fiscal_label or ex.period_end} {ex.period_type} "
                      f"{ex.currency} — {n_items} line items, rev={ex.standard.revenue}, "
                      f"${(usage or {}).get('estimated_cost_usd', 0):.4f}")
            store["filings"].append(entry)
            save_store(store)
        if not args.dry_run:
            save_store(store)
        print(f"  {t}: {len(filings)} new 6-K(s), {n_results} results release(s)")

    print()
    if args.dry_run:
        est_in = total_chars / _APPROX_CHARS_PER_TOKEN
        est_cost = (est_in * _FLASH_IN + total_new * _APPROX_OUTPUT_TOKENS * _FLASH_OUT) / 1e6
        print(f"DRY RUN: {total_new} results releases would be extracted "
              f"(~{est_in/1000:.0f}k input tokens) ≈ ${est_cost:.2f} on deepseek-v4-flash")
    else:
        print(f"Extracted {total_new} releases, est. cost ${total_cost:.3f} → {SIXK_DIR}/")


if __name__ == "__main__":
    main()
