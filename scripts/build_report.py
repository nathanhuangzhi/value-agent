"""Generate a Value-Line-style HTML equity research memo for a single ticker.

Usage:
    ./venv/bin/python -m scripts.build_report --ticker QDEL
    ./venv/bin/python -m scripts.build_report --ticker QDEL --out /tmp/qdel.html

Reads from data/companies_analyzed.json (Stage 4 output). The output HTML is
self-contained (inline CSS, base64-embedded chart PNGs) and renders correctly
in Gmail/Outlook/Apple Mail or any browser.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.tools.paths import COMPANIES_ANALYZED, COMPANIES_VALIDATION, DATA_DIR
from app.tools.report import latest_by_ticker, pick_next_ticker, render_company_report


def _load_validation(ticker: str) -> dict | None:
    if not COMPANIES_VALIDATION.exists():
        return None
    for row in json.loads(COMPANIES_VALIDATION.read_text()):
        if row.get("ticker") == ticker:
            return row
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True, help="ticker symbol (e.g. QDEL)")
    parser.add_argument(
        "--source",
        default=str(COMPANIES_ANALYZED),
        help=f"analyzed companies JSON (default: {COMPANIES_ANALYZED})",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="output HTML path (default: data/reports/<TICKER>.html)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero (and don't write) if validation status is error",
    )
    args = parser.parse_args()

    ticker = args.ticker.upper()
    rows = json.loads(Path(args.source).read_text())
    matching = [r for r in rows if r.get("ticker") == ticker]
    if not matching:
        raise SystemExit(f"ticker {ticker} not found in {args.source}")
    row = sorted(matching, key=lambda r: r.get("analyzed_date", ""))[-1]

    validation = _load_validation(ticker)
    if args.strict and validation and validation.get("status") == "error":
        for iss in validation.get("issues") or []:
            print(f"  [{iss['severity']}] {iss['rule']}: {iss['detail']}")
        raise SystemExit(f"{ticker}: validation status=error; refusing to render (use without --strict to render anyway)")

    out_path = Path(args.out) if args.out else (DATA_DIR / "reports" / f"{ticker}.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    next_ticker = pick_next_ticker(latest_by_ticker(rows), ticker)
    out_path.write_text(
        render_company_report(row, validation=validation, next_ticker=next_ticker),
        encoding="utf-8",
    )
    size_kb = out_path.stat().st_size / 1024
    status_tag = f"  [validation: {validation['status']}]" if validation else ""
    print(f"wrote {out_path}  ({size_kb:.1f} KB){status_tag}")


if __name__ == "__main__":
    main()
