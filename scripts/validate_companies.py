"""Stage 4c: data-quality validation.

Runs the rule set in `app.tools.validation` against every (sec_row,
analyzed_row) pair and writes per-ticker issue lists to
`data/companies_validation.json`. The build_report step reads this file and
renders a banner when severity ≥ warn.

Run:
    ./venv/bin/python -m scripts.validate_companies              # full run
    ./venv/bin/python -m scripts.validate_companies --ticker QDEL
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from app.tools.json_io import atomic_write_json, load_latest_by_ticker
from app.tools.paths import COMPANIES_ANALYZED, COMPANIES_SEC, COMPANIES_VALIDATION, COMPANIES_YFINANCE_DIR
from app.tools.report.sec_adapter import _ads_normalized, load_sharded_by_ticker
from app.tools.sec_6k import load_all_stores, sixk_as_source_row
from app.tools.validation import validate_ticker, worst_severity


def _with_sixk(sec_row: dict | None, sixk_row: dict | None) -> dict | None:
    """SEC row with 6-K quarterly entries filling periods XBRL lacks
    (same reporting currency only)."""
    if not sixk_row:
        return sec_row
    if not sec_row:
        return {"ticker": sixk_row["ticker"], "currency": sixk_row["financial_currency"],
                "annual": {}, "quarterly": sixk_row["quarterly"]}
    if (sec_row.get("currency") or "USD") != sixk_row["financial_currency"]:
        return sec_row
    import copy
    out = copy.deepcopy(sec_row)
    q = out.setdefault("quarterly", {})
    for metric, periods in sixk_row["quarterly"].items():
        d = q.setdefault(metric, {})
        for pk, entry in periods.items():
            d.setdefault(pk, entry)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", help="validate only this ticker")
    ap.add_argument("--output", type=Path, default=COMPANIES_VALIDATION)
    ap.add_argument("--verbose", action="store_true",
                    help="print every warn/error issue to stdout")
    args = ap.parse_args()

    sec = load_latest_by_ticker(COMPANIES_SEC, date_key="fetched_at")
    analyzed = load_latest_by_ticker(COMPANIES_ANALYZED, date_key="analyzed_date")

    targets = sorted(set(sec) | set(analyzed))
    if args.ticker:
        targets = [args.ticker.upper()]

    # When validating a subset (--ticker), merge into any existing
    # validation file so we don't clobber other tickers' entries.
    existing = {}
    if args.output.exists():
        existing = {r["ticker"]: r for r in json.loads(args.output.read_text()) if r.get("ticker")}

    today = date.today()
    counts = {"ok": 0, "info": 0, "warn": 0, "error": 0}
    flagged_rows = []
    # ADS filers: SEC shares/EPS are per ordinary share; bring them onto the
    # ADS basis (what the price refers to) before the price×shares checks.
    yf = load_sharded_by_ticker(COMPANIES_YFINANCE_DIR)
    sixk = load_all_stores()
    for t in targets:
        sec_row = _ads_normalized(sec.get(t), yf.get(t)) if sec.get(t) else None
        # Foreign filers have no quarterly XBRL; their 6-K extractions ARE the
        # SEC quarterly record, so fold them in before the quarterly rules run.
        sec_row = _with_sixk(sec_row, sixk_as_source_row(sixk.get(t)))
        issues = validate_ticker(sec_row, analyzed.get(t), today=today)
        status = worst_severity(issues)
        counts[status] += 1
        row = {
            "ticker": t,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "issues": issues,
        }
        existing[t] = row
        if status in ("warn", "error"):
            flagged_rows.append(row)

    out = sorted(existing.values(), key=lambda r: r["ticker"])
    atomic_write_json(args.output, out)

    print("=== validation summary ===")
    for k in ("ok", "info", "warn", "error"):
        print(f"  {k:6s}: {counts[k]}")
    print(f"\nwrote {len(out)} rows → {args.output}")

    if args.verbose or args.ticker:
        for row in flagged_rows:
            print(f"\n{row['ticker']} [{row['status']}]")
            for iss in row["issues"]:
                print(f"  [{iss['severity']}] {iss['rule']}: {iss['detail']}")


if __name__ == "__main__":
    main()
