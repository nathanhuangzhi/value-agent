"""A-share 年报 / 半年报 from 巨潮资讯网 (cninfo), converted to Markdown.

The SEC path (`fetch_annual_reports.py`) downloads an HTML 10-K/20-F and
flattens it to text. Chinese issuers file a PDF instead, so this stage
downloads the PDF as filed and converts it with PyMuPDF — headings stay
headings and 合并利润表 comes out as a Markdown table, which is what the AI
chat's `list_annual_reports` / `get_annual_report_section` /
`search_annual_report` tools read.

Idempotent: a filing already converted is skipped, so a daily run only picks
up a new 年报 or 半年报 (each ~40s, 200k characters).

Run:
    ./venv/bin/python -m scripts.fetch_ashare_reports                        # every A-share on file
    ./venv/bin/python -m scripts.fetch_ashare_reports --ticker 600066.SS
    ./venv/bin/python -m scripts.fetch_ashare_reports --keep 1 --no-interim  # newest 年报 only
    ./venv/bin/python -m scripts.fetch_ashare_reports --reparse              # rebuild the TOC, no network
"""
from __future__ import annotations

import argparse

from app.log import get_logger
from app.tools.ashare_reports import DEFAULT_KEEP, reparse_ticker, sync_ticker
from scripts.fetch_ashare_statements import ashare_tickers

log = get_logger(__name__)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch A-share 定期报告 from cninfo")
    ap.add_argument("--ticker")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="reports per category (default 3)")
    ap.add_argument("--no-interim", action="store_true", help="年报 only, skip 半年报")
    ap.add_argument("--reparse", action="store_true", help="rebuild the TOC from converted files")
    args = ap.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else ashare_tickers()
    if not tickers:
        print("No A-share companies on file — add one with scripts.add_company")
        return
    for t in tickers:
        print(f"=== {t} ===")
        if args.reparse:
            reparse_ticker(t)
            continue
        try:
            idx = sync_ticker(t, keep=args.keep, interim=not args.no_interim)
        except Exception as e:                      # cninfo boundary — keep going
            log.error("%s: %s", t, e)
            print(f"  FAILED ({type(e).__name__}: {e})")
            continue
        print(f"  {len(idx['filings'])} report(s) on file: "
              + ", ".join(f"{f['form']} FY{f['fiscal_year']}" for f in idx["filings"]))


if __name__ == "__main__":
    main()
