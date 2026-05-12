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

from app.tools.json_io import atomic_write_json
from app.tools.paths import COMPANIES_ANALYZED, COMPANIES_SEC, COMPANIES_VALIDATION
from app.tools.validation import validate_ticker, worst_severity


def _load_latest_by_ticker(path: Path, date_key: str = "analyzed_date") -> dict:
    """Load a JSON array, dedup by ticker keeping the most-recent row."""
    if not path.exists():
        return {}
    out: dict = {}
    for row in json.loads(path.read_text()):
        t = row.get("ticker")
        if not t:
            continue
        prev = out.get(t)
        if not prev or row.get(date_key, "") > prev.get(date_key, ""):
            out[t] = row
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", help="validate only this ticker")
    ap.add_argument("--output", type=Path, default=COMPANIES_VALIDATION)
    ap.add_argument("--verbose", action="store_true",
                    help="print every warn/error issue to stdout")
    args = ap.parse_args()

    sec = _load_latest_by_ticker(COMPANIES_SEC, date_key="fetched_at")
    analyzed = _load_latest_by_ticker(COMPANIES_ANALYZED, date_key="analyzed_date")

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
    for t in targets:
        issues = validate_ticker(sec.get(t), analyzed.get(t), today=today)
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
