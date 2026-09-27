"""Stage 4b'': pull A-share statements from Tushare for every A-share row in
`companies_analyzed.json`, writing `data/ashare/<TICKER>.json` — one source
row per company, shaped exactly like a yfinance row so the ordinary blend
handles it (precedence SEC XBRL > Tushare > 6-K > yfinance, per cell).

A-shares are the companies added by `scripts.add_company` (`source: "ashare"`);
they have no SEC filings, so this is their primary statement source. The raw
Tushare responses are kept under `data/ashare_raw/` (gitignored), so a change
to the field map is a `--reparse` away rather than a re-download.

Run:
    ./venv/bin/python -m scripts.fetch_ashare_statements                        # every A-share
    ./venv/bin/python -m scripts.fetch_ashare_statements --ticker 600066.SS     # one
    ./venv/bin/python -m scripts.fetch_ashare_statements --reparse              # re-map cached raw
"""
from __future__ import annotations

import argparse

from app.log import get_logger
from app.tools.ashare_adapter import ashare_source_row
from app.tools.ashare_tools import TushareError, fetch, is_ashare
from app.tools.json_io import atomic_write_json, read_json_array
from app.tools.paths import ASHARE_DIR, COMPANIES_ANALYZED

log = get_logger(__name__)


def ashare_tickers() -> list[str]:
    """A-share tickers on file, newest analyzed row per ticker wins."""
    out = {}
    for row in read_json_array(COMPANIES_ANALYZED):
        t = (row.get("ticker") or "").upper()
        if t and (row.get("source") == "ashare" or is_ashare(t)):
            out[t] = True
    return sorted(out)


def fetch_one(ticker: str, *, reparse: bool = False) -> dict | None:
    """Fetch (or re-map) one company and write its source row."""
    row = ashare_source_row(fetch(ticker, reparse=reparse))
    if not row:
        return None
    ASHARE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(ASHARE_DIR / f"{ticker.upper()}.json", row)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch A-share statements from Tushare")
    ap.add_argument("--ticker", help="one ticker (default: every A-share in companies_analyzed.json)")
    ap.add_argument("--reparse", action="store_true", help="re-map the cached raw payload, no network")
    args = ap.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else ashare_tickers()
    if not tickers:
        print("No A-share tickers on file — add one with scripts.add_company")
        return

    for t in tickers:
        try:
            row = fetch_one(t, reparse=args.reparse)
        except TushareError as e:
            log.error("%s: %s", t, e)
            print(f"  {t}: FAILED ({e})")
            continue
        if not row:
            print(f"  {t}: no data")
            continue
        years = sorted(row["annual"].get("revenue") or {})
        quarters = sorted(row["quarterly"].get("revenue") or {})
        print(f"  {t} {row.get('name', '')}: {len(years)} annual ({years[0] if years else '-'}"
              f"..{years[-1] if years else '-'}), {len(quarters)} quarterly "
              f"(..{quarters[-1] if quarters else '-'}), {row['financial_currency']}")


if __name__ == "__main__":
    main()
