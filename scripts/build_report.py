"""Generate a Value-Line-style HTML equity research memo for a single ticker.

Usage:
    ./venv/bin/python -m scripts.build_report --ticker QDEL
    ./venv/bin/python -m scripts.build_report --ticker QDEL --out /tmp/qdel.html

Reads from data/companies_analyzed.json (Stage 4 output). The output HTML is
self-contained (inline CSS, base64-embedded chart PNGs) and renders correctly
in Gmail/Outlook/Apple Mail or any browser.

The render path is also importable as `render_one(ticker, ...)` so the
daily-digest orchestrator can drive it without subprocessing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.tools.json_io import load_latest_by_ticker
from app.tools.paths import COMPANIES_ANALYZED, COMPANIES_VALIDATION, DATA_DIR
from app.tools.report import pick_next_ticker, render_company_report


def _load_validation_by_ticker() -> dict:
    """Map ticker → validation row. Empty when no validation file exists yet."""
    if not COMPANIES_VALIDATION.exists():
        return {}
    return {r["ticker"]: r for r in json.loads(COMPANIES_VALIDATION.read_text()) if r.get("ticker")}


def render_one(
    ticker: str,
    *,
    analyzed_by_ticker: dict | None = None,
    validation_by_ticker: dict | None = None,
    out_path: Path | None = None,
    strict: bool = False,
) -> Path | None:
    """Render one ticker's HTML report and write it to disk.

    Args:
        ticker: stock symbol (case-insensitive).
        analyzed_by_ticker: ticker→row dict (latest per ticker). If omitted,
            loaded from `companies_analyzed.json`. Pass it explicitly when
            rendering many tickers in a loop — avoids re-reading the JSON
            once per call.
        validation_by_ticker: ticker→validation-row dict. Same hint.
        out_path: where to write. Defaults to `data/reports/<TICKER>.html`.
        strict: if True and validation status is "error", return None
            without writing (caller decides how to surface the skip).

    Returns the written `Path`, or None when skipped (strict-mode error or
    ticker missing from `analyzed_by_ticker`).
    """
    ticker = ticker.upper()
    if analyzed_by_ticker is None:
        analyzed_by_ticker = load_latest_by_ticker(COMPANIES_ANALYZED)
    if validation_by_ticker is None:
        validation_by_ticker = _load_validation_by_ticker()

    row = analyzed_by_ticker.get(ticker)
    if not row:
        return None

    validation = validation_by_ticker.get(ticker)
    if strict and validation and validation.get("status") == "error":
        return None

    if out_path is None:
        out_path = DATA_DIR / "reports" / f"{ticker}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    nxt = pick_next_ticker(analyzed_by_ticker, ticker)
    out_path.write_text(
        render_company_report(row, validation=validation, next_ticker=nxt),
        encoding="utf-8",
    )
    return out_path


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
    analyzed = load_latest_by_ticker(Path(args.source))
    if ticker not in analyzed:
        raise SystemExit(f"ticker {ticker} not found in {args.source}")

    validation_by_ticker = _load_validation_by_ticker()
    validation = validation_by_ticker.get(ticker)
    if args.strict and validation and validation.get("status") == "error":
        for iss in validation.get("issues") or []:
            print(f"  [{iss['severity']}] {iss['rule']}: {iss['detail']}")
        raise SystemExit(
            f"{ticker}: validation status=error; refusing to render "
            f"(use without --strict to render anyway)"
        )

    out_path = Path(args.out) if args.out else (DATA_DIR / "reports" / f"{ticker}.html")
    written = render_one(
        ticker,
        analyzed_by_ticker=analyzed,
        validation_by_ticker=validation_by_ticker,
        out_path=out_path,
        strict=args.strict,
    )
    if written is None:
        raise SystemExit(f"{ticker}: skipped (no analyzed row or strict-mode error)")

    size_kb = written.stat().st_size / 1024
    status_tag = f"  [validation: {validation['status']}]" if validation else ""
    print(f"wrote {written}  ({size_kb:.1f} KB){status_tag}")


if __name__ == "__main__":
    main()
