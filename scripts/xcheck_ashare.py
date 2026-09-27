"""Cross-check an A-share's figures across Tushare, 东方财富 and yfinance.

All three repackage the same exchange filings, so they should agree to
rounding; where they don't, the number the app shows deserves a second look.
This writes `data/ashare_xcheck/<T>.json` (read by `validate_companies` and
by the AI chat's `compare_sources` tool) and prints a per-period table.

It also reconciles the ratios we compute against the ones Tushare publishes
(`pe_ttm` / `pe` / `pb` / 总市值) — an end-to-end check that catches a
share-count or FX error the per-cell comparison can't see.

Run:
    ./venv/bin/python -m scripts.xcheck_ashare                       # every A-share
    ./venv/bin/python -m scripts.xcheck_ashare --ticker 600066.SS
    ./venv/bin/python -m scripts.xcheck_ashare --ticker 600066.SS --grid quarterly -v
"""
from __future__ import annotations

import argparse

from app.data import repo
from app.log import get_logger
from app.tools import eastmoney_tools as em
from app.tools.ashare_adapter import latest_daily_basic
from app.tools.ashare_tools import load_raw
from app.tools.ashare_xcheck import build_report
from app.tools.json_io import atomic_write_json
from app.tools.paths import ASHARE_XCHECK_DIR
from scripts.fetch_ashare_statements import ashare_tickers

log = get_logger(__name__)

_MARK = {"ok": "  ", "info": " ·", "warn": " !", "error": " ✗"}


def sources_for(ticker: str, *, reparse: bool = False) -> dict[str, dict | None]:
    """The three source rows for one ticker, by name."""
    return {
        "ashare": repo.ashare().get(ticker.upper()),
        "eastmoney": em.eastmoney_source_row(em.fetch(ticker, reparse=reparse)),
        "yfinance": repo.yfinance().get(ticker.upper()),
    }


def report_for(ticker: str, *, reparse: bool = False) -> dict:
    from app.api.routes import _snapshot_ratios_for  # local: avoids a circular import at module load

    ticker = ticker.upper()
    row = repo.analyzed().get(ticker) or {}
    snapshot = _snapshot_ratios_for(ticker, row, repo.sec(), repo.yfinance()) if row else None
    per_usd = (repo.fx().get((row.get("quote_currency") or "CNY").upper()) or {}).get("per_usd")
    return build_report(
        ticker, sources_for(ticker, reparse=reparse),
        snapshot=snapshot,
        daily_basic=latest_daily_basic(load_raw(ticker)),
        per_usd=per_usd,
    )


def print_report(report: dict, *, grid: str, verbose: bool) -> None:
    names = report["sources"]
    print(f"{report['ticker']}  sources: {', '.join(names)}  worst: {report['worst']}")
    rows = [c for c in report["cells"] if c["grid"] == grid]
    if rows:
        width = max(len(c["metric"]) for c in rows)
        header = f"  {'period':<11} {'metric':<{width}} " + " ".join(f"{n:>18}" for n in names)
        print(header)
        for c in rows:
            if not verbose and c["severity"] == "ok":
                continue
            vals = " ".join(f"{c['values'].get(n, float('nan')):>18,.0f}" if n in c["values"]
                            else f"{'-':>18}" for n in names)
            spread = "" if c["spread_pct"] is None else f"  Δ{c['spread_pct'] * 100:.3f}%"
            print(f"  {c['period']:<11} {c['metric']:<{width}} {vals}{spread}{_MARK[c['severity']]}")
        agreed = sum(1 for c in rows if c["severity"] == "ok")
        print(f"  {agreed}/{len(rows)} {grid} cells agree within {0.1}%")
    for v in report["valuation"]:
        print(f"  valuation {v['metric']:<11} ours {v['ours']:>16,.4f}  tushare {v['tushare']:>16,.4f}"
              f"  Δ{(v['spread_pct'] or 0) * 100:.3f}%{_MARK[v['severity']]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Cross-check A-share figures across sources")
    ap.add_argument("--ticker")
    ap.add_argument("--grid", choices=("annual", "quarterly"), default="annual")
    ap.add_argument("--reparse", action="store_true", help="use the cached 东方财富 payload")
    ap.add_argument("-v", "--verbose", action="store_true", help="print agreeing cells too")
    args = ap.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else ashare_tickers()
    if not tickers:
        print("No A-share tickers on file — add one with scripts.add_company")
        return
    ASHARE_XCHECK_DIR.mkdir(parents=True, exist_ok=True)
    for t in tickers:
        report = report_for(t, reparse=args.reparse)
        atomic_write_json(ASHARE_XCHECK_DIR / f"{t}.json", report)
        print_report(report, grid=args.grid, verbose=args.verbose)


if __name__ == "__main__":
    main()
