"""Generate the archive's HTML index pages:

  - `index.html` — top-level: one row per industry that's been analyzed,
    with ticker count and last-analyzed date. Clicking an industry opens
    that industry's ticker table.
  - `<industry-slug>.html` — one per industry: the sortable + searchable
    table of every ticker analyzed in that industry, identical in shape to
    the previous single-page index.

Reads metadata from companies_analyzed.json + companies_validation.json
and looks at which `<TICKER>.html` files are physically present.

Run:
    ./venv/bin/python -m scripts.build_index
    ./venv/bin/python -m scripts.build_index --out-dir /tmp/reports
"""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.tools.json_io import load_latest_by_ticker
from app.tools.paths import (
    COMPANIES_ANALYZED,
    COMPANIES_SEC,
    COMPANIES_VALIDATION,
    COMPANIES_YFINANCE,
    DATA_DIR,
)

# Color palette + shared formatters: single source of truth.
from app.tools.report.format import (
    AMBER,
    CREAM,
    MUTED,
    NAVY,
    RULE,
    TEXT,
    format_money_compact,
    status_badge,
)
from app.tools.report.ratios import compute_snapshot_ratios
from app.tools.report.sec_adapter import (
    load_sec_by_ticker,
    sec_to_yfinance_quarterly,
)


def _slug(s: str) -> str:
    """Filesystem/URL-safe lowercased slug. 'Medical Devices' → 'medical-devices'."""
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "uncategorized"


def _collect_rows(reports_dir: Path) -> list[dict]:
    """One row per HTML report on disk. Merges analyzed + validation metadata
    and adds TTM ratios (P/E, P/OCF, P/S, P/B) computed from the blended
    SEC + yfinance quarterly statements + the latest monthly close.
    Skips files starting with `_` and the index pages themselves."""
    analyzed = load_latest_by_ticker(COMPANIES_ANALYZED)

    validation: dict = {}
    if COMPANIES_VALIDATION.exists():
        validation = {r["ticker"]: r for r in json.loads(COMPANIES_VALIDATION.read_text()) if r.get("ticker")}

    # Same blended SEC+yfinance pipeline the report renderer uses — keep
    # the index table consistent with each ticker's KPI grid.
    sec_by_ticker = load_sec_by_ticker(COMPANIES_SEC)
    yf_by_ticker = load_sec_by_ticker(COMPANIES_YFINANCE)

    rows = []
    for html_path in sorted(reports_dir.glob("*.html")):
        if html_path.name.startswith("_"):
            continue
        ticker = html_path.stem.upper()
        # Skip our own generated index pages — they shouldn't appear as
        # rows in the ticker table even if their stem happens to slugify
        # back to itself.
        if ticker == "INDEX":
            continue
        a = analyzed.get(ticker) or {}
        v = validation.get(ticker) or {}
        if not a:
            # File on disk without an analyzed row — skip; likely a stray
            # generated page from a previous build.
            continue

        # Blend SEC + yfinance the same way render.py does, then run the
        # shared TTM-ratio computation so the index agrees with each
        # report's snapshot KPI grid.
        sec_row = sec_by_ticker.get(ticker)
        yf_row = yf_by_ticker.get(ticker)
        ratios = {"market_cap": None, "ttm_pe": None, "ttm_pocf": None, "ps": None, "pb": None}
        if sec_row or yf_row:
            q = sec_to_yfinance_quarterly(sec_row or {}, last_n=8, yfinance_row=yf_row)
            ph = (a.get("price_history") or {}).get("data") or []
            ratios = compute_snapshot_ratios(
                q["income_statement"], q["balance_sheet"], q["cash_flow"], ph,
            )

        rows.append({
            "ticker": ticker,
            "filename": html_path.name,
            "name": a.get("name") or ticker,
            "sector": a.get("sector") or "",
            "industry": a.get("industry") or "Uncategorized",
            # Prefer the price-history-recomputed mcap (same as the report's
            # snapshot uses); fall back to the Stage-1 stored mcap when we
            # have no quarterly shares / price history.
            "market_cap": ratios["market_cap"] or a.get("market_cap"),
            "ttm_pe": ratios["ttm_pe"],
            "ttm_pocf": ratios["ttm_pocf"],
            "ps": ratios["ps"],
            "pb": ratios["pb"],
            "analyzed_date": a.get("analyzed_date") or "",
            "status": v.get("status") or "ok",
        })
    return rows


_BASE_CSS = f"""
body {{ margin:0; padding:24px 0; background:#ebe6da; font-family:Georgia,serif; color:{TEXT}; }}
.card {{ max-width:1024px; margin:0 auto; background:#ffffff; border:1px solid {RULE}; }}
.band {{ background:{NAVY}; color:#ffffff; padding:24px 28px; }}
.band h1 {{ margin:0; font-size:24px; font-weight:bold; line-height:1.1; font-family:Helvetica,Arial,sans-serif; }}
.band .sub {{ font-size:12px; opacity:0.85; margin-top:6px; font-family:Helvetica,Arial,sans-serif; }}
.band a.back {{ color:#ffffff; opacity:0.8; text-decoration:none; font-size:12px; font-family:Helvetica,Arial,sans-serif; }}
.band a.back:hover {{ opacity:1; text-decoration:underline; }}
.toolbar {{ padding:16px 28px; border-bottom:1px solid {RULE}; background:{CREAM};
  display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
.toolbar input {{ flex:1; min-width:200px; padding:8px 12px; font-size:14px;
  border:1px solid {RULE}; border-radius:3px; font-family:Helvetica,Arial,sans-serif; }}
.toolbar .count {{ font-size:12px; color:{MUTED}; font-family:Helvetica,Arial,sans-serif; }}
.scroll {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
table {{ width:100%; border-collapse:collapse; min-width:600px; }}
th, td {{ padding:8px 12px; border-bottom:1px solid {RULE}; text-align:left; font-size:13px; }}
th {{ background:#fafaf2; color:{NAVY}; font-size:11px; letter-spacing:1px;
  font-family:Helvetica,Arial,sans-serif; cursor:pointer; user-select:none; position:sticky; top:0; }}
th:hover {{ background:#f2eee0; }}
th.asc::after  {{ content:' ▲'; color:{AMBER}; }}
th.desc::after {{ content:' ▼'; color:{AMBER}; }}
tbody tr:hover {{ background:#fafaf2; }}
.foot {{ background:#f5f1e8; padding:14px 28px; font-size:11px; color:{MUTED};
  font-family:Helvetica,Arial,sans-serif; border-top:1px solid {RULE}; }}
@media (max-width: 599px) {{
  .band {{ padding:18px 16px; }}
  .band h1 {{ font-size:20px; }}
  .toolbar {{ padding:12px 16px; }}
  .foot {{ padding:12px 16px; }}
}}
"""

# Sort + filter JS used on both the industry-list page and per-industry pages.
_TABLE_JS = """
function sortBy(col, type) {
  var tbody = document.querySelector('table tbody');
  var rows = Array.from(tbody.querySelectorAll('tr'));
  var header = document.querySelectorAll('table th')[col];
  var asc = !header.classList.contains('asc');
  document.querySelectorAll('table th').forEach(function(h){h.classList.remove('asc','desc');});
  header.classList.add(asc ? 'asc' : 'desc');
  rows.sort(function(a, b) {
    var ca = a.children[col]; var cb = b.children[col];
    var va = ca.dataset.sort != null ? ca.dataset.sort : ca.textContent.trim();
    var vb = cb.dataset.sort != null ? cb.dataset.sort : cb.textContent.trim();
    if (type === 'num') { va = parseFloat(va) || 0; vb = parseFloat(vb) || 0; }
    if (va < vb) return asc ? -1 : 1;
    if (va > vb) return asc ? 1 : -1;
    return 0;
  });
  rows.forEach(function(r){tbody.appendChild(r);});
}
function filterRows() {
  var q = document.getElementById('q').value.toLowerCase();
  var rows = document.querySelectorAll('table tbody tr');
  var shown = 0;
  rows.forEach(function(r){
    var txt = r.textContent.toLowerCase();
    var match = q === '' || txt.indexOf(q) !== -1;
    r.style.display = match ? '' : 'none';
    if (match) shown++;
  });
  document.getElementById('count').textContent = shown + ' of ' + rows.length;
}
"""


def _render_industry_index(industries: list[dict], total_tickers: int, now: datetime) -> str:
    """Top-level landing page. `industries` is a list of summary dicts."""
    n = len(industries)
    last_updated = now.strftime("%Y-%m-%d %H:%M UTC")
    rows_html = []
    for ind in industries:
        slug = ind["slug"]
        rows_html.append(
            f"<tr>"
            f"<td><a href='{html.escape(slug)}.html' "
            f"style='color:{NAVY};text-decoration:none;font-weight:bold;'>"
            f"{html.escape(ind['name'])}</a></td>"
            f"<td data-sort='{ind['ticker_count']}' style='text-align:right;font-family:Menlo,Consolas,monospace;'>"
            f"{ind['ticker_count']}</td>"
            f"<td>{html.escape(ind['latest_date'])}</td>"
            f"</tr>"
        )
    tbody = "\n".join(rows_html)

    return f"""<!DOCTYPE html>
<html><head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Equity Research Archive</title>
<style>{_BASE_CSS}</style>
</head>
<body>
<div class='card'>
  <div class='band'>
    <h1>Equity Research Archive</h1>
    <div class='sub'>{n} industries &middot; {total_tickers} tickers &middot; last updated {html.escape(last_updated)}</div>
  </div>
  <div class='toolbar'>
    <input id='q' type='search' placeholder='Search industry...' oninput='filterRows()' autocomplete='off'>
    <span class='count' id='count'>{n} of {n}</span>
  </div>
  <div class='scroll'>
    <table>
      <thead><tr>
        <th onclick='sortBy(0,"str")'>Industry</th>
        <th onclick='sortBy(1,"num")' style='text-align:right;'>Tickers</th>
        <th onclick='sortBy(2,"str")'>Latest Analyzed</th>
      </tr></thead>
      <tbody>{tbody}</tbody>
    </table>
  </div>
  <div class='foot'>For research and educational purposes only. Not investment advice.</div>
</div>
<script>{_TABLE_JS}</script>
</body></html>"""


def _fmt_ratio(v) -> tuple[str, str]:
    """Format a ratio (TTM P/E, P/S, etc.) for both display and sort. Returns
    `(display, sort_key)`. Displays one decimal; "—" when missing or
    non-finite. Sort key uses the raw number so sorting works
    numerically regardless of formatted length."""
    if v is None or not isinstance(v, (int, float)):
        return "—", ""
    return f"{v:,.1f}x", f"{v:.4f}"


def _render_industry_page(industry_name: str, rows: list[dict], now: datetime) -> str:
    """Per-industry ticker table. Now includes the four headline
    valuation ratios (TTM P/E, TTM P/OCF, P/S, P/B) alongside market cap.
    Sortable + searchable."""
    n = len(rows)
    last_updated = now.strftime("%Y-%m-%d %H:%M UTC")

    tbody_lines = []
    for r in rows:
        mcap = r["market_cap"]
        mcap_display = html.escape(format_money_compact(mcap)) if mcap else ""
        mcap_sort = f"{mcap:.0f}" if isinstance(mcap, (int, float)) and mcap else ""
        pe_disp, pe_sort = _fmt_ratio(r.get("ttm_pe"))
        pocf_disp, pocf_sort = _fmt_ratio(r.get("ttm_pocf"))
        ps_disp, ps_sort = _fmt_ratio(r.get("ps"))
        pb_disp, pb_sort = _fmt_ratio(r.get("pb"))
        tbody_lines.append(
            f"<tr>"
            f"<td><a href='{html.escape(r['filename'])}' "
            f"style='color:{NAVY};text-decoration:none;font-weight:bold;'>{html.escape(r['ticker'])}</a></td>"
            f"<td>{html.escape(r['name'])}</td>"
            f"<td data-sort='{mcap_sort}' style='text-align:right;font-family:Menlo,Consolas,monospace;'>{mcap_display}</td>"
            f"<td data-sort='{pe_sort}' style='text-align:right;font-family:Menlo,Consolas,monospace;'>{pe_disp}</td>"
            f"<td data-sort='{pocf_sort}' style='text-align:right;font-family:Menlo,Consolas,monospace;'>{pocf_disp}</td>"
            f"<td data-sort='{ps_sort}' style='text-align:right;font-family:Menlo,Consolas,monospace;'>{ps_disp}</td>"
            f"<td data-sort='{pb_sort}' style='text-align:right;font-family:Menlo,Consolas,monospace;'>{pb_disp}</td>"
            f"<td>{html.escape(r['analyzed_date'])}</td>"
            f"<td>{status_badge(r['status'])}</td>"
            f"</tr>"
        )
    tbody = "\n".join(tbody_lines)

    return f"""<!DOCTYPE html>
<html><head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(industry_name)} — Equity Research Archive</title>
<style>{_BASE_CSS}</style>
</head>
<body>
<div class='card'>
  <div class='band'>
    <a class='back' href='index.html'>← All industries</a>
    <h1 style='margin-top:6px;'>{html.escape(industry_name)}</h1>
    <div class='sub'>{n} tickers &middot; last updated {html.escape(last_updated)}</div>
  </div>
  <div class='toolbar'>
    <input id='q' type='search' placeholder='Search ticker, company...' oninput='filterRows()' autocomplete='off'>
    <span class='count' id='count'>{n} of {n}</span>
  </div>
  <div class='scroll'>
    <table>
      <thead><tr>
        <th onclick='sortBy(0,"str")'>Ticker</th>
        <th onclick='sortBy(1,"str")'>Company</th>
        <th onclick='sortBy(2,"num")' style='text-align:right;'>Market Cap</th>
        <th onclick='sortBy(3,"num")' style='text-align:right;'>TTM P/E</th>
        <th onclick='sortBy(4,"num")' style='text-align:right;'>TTM P/OCF</th>
        <th onclick='sortBy(5,"num")' style='text-align:right;'>P/S</th>
        <th onclick='sortBy(6,"num")' style='text-align:right;'>P/B</th>
        <th onclick='sortBy(7,"str")'>Analyzed</th>
        <th onclick='sortBy(8,"str")'>Data Quality</th>
      </tr></thead>
      <tbody>{tbody}</tbody>
    </table>
  </div>
  <div class='foot'>For research and educational purposes only. Not investment advice.</div>
</div>
<script>{_TABLE_JS}</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reports-dir", type=Path, default=DATA_DIR / "reports",
                    help="directory containing per-ticker HTML reports (default: data/reports)")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="where to write index.html + <industry>.html "
                         "(default: same as --reports-dir)")
    args = ap.parse_args()

    if not args.reports_dir.exists():
        raise SystemExit(f"{args.reports_dir} does not exist")
    out_dir = args.out_dir or args.reports_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _collect_rows(args.reports_dir)
    if not rows:
        raise SystemExit(f"No per-ticker HTML reports found in {args.reports_dir}")

    # Group by industry
    by_industry: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_industry[r["industry"]].append(r)

    industries_summary = []
    for industry_name, ticker_rows in sorted(by_industry.items()):
        ticker_rows_sorted = sorted(ticker_rows, key=lambda r: r["ticker"])
        slug = _slug(industry_name)
        latest_date = max((r["analyzed_date"] for r in ticker_rows if r["analyzed_date"]), default="")
        industries_summary.append({
            "name": industry_name,
            "slug": slug,
            "ticker_count": len(ticker_rows_sorted),
            "latest_date": latest_date,
        })

    now = datetime.now(timezone.utc)

    # Sort industries: most-recently-analyzed first
    industries_summary.sort(key=lambda i: (i["latest_date"], i["name"]), reverse=True)

    # Write industry pages
    industry_files: list[Path] = []
    for ind in industries_summary:
        ticker_rows_sorted = sorted(by_industry[ind["name"]], key=lambda r: r["ticker"])
        page = _render_industry_page(ind["name"], ticker_rows_sorted, now)
        out_path = out_dir / f"{ind['slug']}.html"
        out_path.write_text(page, encoding="utf-8")
        industry_files.append(out_path)

    # Write top-level index
    index_html = _render_industry_index(industries_summary, total_tickers=len(rows), now=now)
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    print(f"wrote {index_path}  ({index_path.stat().st_size/1024:.1f} KB, "
          f"{len(industries_summary)} industries)")
    for ind, path in zip(industries_summary, industry_files, strict=True):
        print(f"  {ind['slug']}.html  ({path.stat().st_size/1024:.0f} KB, {ind['ticker_count']} tickers)")


if __name__ == "__main__":
    main()
