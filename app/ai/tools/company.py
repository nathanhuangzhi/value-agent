"""The app's own company data: the summarised block and the universe search."""
from __future__ import annotations

from fastapi import HTTPException

from app.ai.context import _money, company_block
from app.ai.tools.registry import tool
from app.data import repo
from app.log import get_logger
from app.tools.paths import ASHARE_XCHECK_DIR

log = get_logger(__name__)


@tool(
    "search_companies",
    marks_company=False,
    description="Find companies by name or ticker fragment across ~7,000 NYSE/Nasdaq listings. Returns ticker, name, industry, market cap and whether the company has been analyzed (i.e. lookup_company will work).",
    params={"query": {"type": "string"}},
    required=["query"],
    status="Searching companies for “{query}”…",
)
def search_companies(query: str, *, limit: int = 12) -> str:
    q = query.strip().lower()
    if not q:
        return "ERROR: empty query"
    analyzed = repo.analyzed()
    universe = repo.universe()
    hits = []
    for t in sorted(set(universe) | set(analyzed)):
        src = analyzed.get(t) or universe[t]
        name = src.get("name") or t
        if t.lower().startswith(q) or q in name.lower():
            hits.append((0 if t.lower().startswith(q) else 1, t, name,
                         src.get("industry") or "", src.get("market_cap"), t in analyzed))
        if len(hits) >= limit * 3:
            break
    hits.sort(key=lambda h: (h[0], -(h[4] or 0)))
    if not hits:
        return f"No companies match {query!r}."
    lines = [f"- {t}: {name} · {ind} · mcap {_money(cap)} · "
             f"{'analyzed' if an else 'NOT analyzed (identity only)'}"
             for _, t, name, ind, cap, an in hits[:limit]]
    return "\n".join(lines)


@tool(
    "lookup_company",
    description="Fetch the app's collected data for one company by ticker: financial statements (10y annual, 8 quarters), valuation snapshot, business-model classification and prices. Only works for the ~1,250 analyzed companies; otherwise returns an error and you should say the company has not been analyzed yet.",
    params={"ticker": {"type": "string", "description": "e.g. QDEL"}},
    required=["ticker"],
    status="Looking up {ticker}…",
)
def lookup_company(ticker: str) -> str:
    t = (ticker or "").upper().strip()
    try:
        return company_block(t)
    except HTTPException:
        return (f"ERROR: {t} has not been analyzed by the pipeline — no statements "
                f"on file. Use search_companies to confirm the ticker, and tell the user "
                f"the data is not available.")


# ---- A-shares (沪深) ---------------------------------------------------------
# These companies have no SEC filings, so the filing / 6-K / earnings-call
# tools have nothing to serve for them. What they do have is a deeper
# statement history than yfinance, a structured segment breakdown and three
# independent sources to compare — the two tools below.

@tool(
    "main_business",
    description=(
        "主营业务构成 for an A-share (沪深) company: revenue, cost and profit split by "
        "region (国内/海外) and by product/industry, per fiscal year, straight from the filing. "
        "Use it for segment questions instead of guessing from the income statement."
    ),
    params={"ticker": {"type": "string", "description": "e.g. 600066.SS"},
            "period": {"type": "string", "description": "fiscal year, e.g. 2025 (default: the latest two)"}},
    required=["ticker"],
    status="Reading 主营业务构成 for {ticker}…",
)
def main_business(ticker: str, period: str | None = None) -> str:
    from app.tools.ashare_adapter import main_business as mb
    from app.tools.ashare_tools import load_raw

    t = (ticker or "").upper().strip()
    rows = mb(load_raw(t) or {}, period)
    if not rows:
        return (f"ERROR: no 主营业务构成 on file for {t} — it is only collected for A-shares "
                f"(600066.SS-style tickers).")
    periods = sorted({r["period"] for r in rows}, reverse=True)[:1 if period else 2]
    out = []
    for p in periods:
        out.append(f"{p}:")
        for r in [r for r in rows if r["period"] == p]:
            margin = "" if not r["revenue"] or r["profit"] is None else f" · 毛利率 {r['profit'] / r['revenue']:.1%}"
            out.append(f"  - {r['item']} ({r['kind']}): revenue {_money(r['revenue'])} "
                       f"{r['currency']}{margin}")
    return "\n".join(out)


@tool(
    "compare_sources",
    description=(
        "For an A-share, compare the same figures across every source on file (Tushare, 东方财富, "
        "yfinance) and against the valuation ratios Tushare publishes. Use it when the user asks "
        "whether a number is trustworthy, or when two numbers seem to disagree."
    ),
    params={"ticker": {"type": "string", "description": "e.g. 600066.SS"},
            "grid": {"type": "string", "enum": ["annual", "quarterly"]}},
    required=["ticker"],
    status="Cross-checking {ticker} across sources…",
)
def compare_sources(ticker: str, grid: str | None = "annual") -> str:
    t = (ticker or "").upper().strip()
    grid = grid or "annual"          # the registry passes None for an omitted param
    report = repo.read_json(ASHARE_XCHECK_DIR / f"{t}.json", {})
    if not report:
        return (f"ERROR: no cross-check on file for {t} — it is produced for A-shares by "
                f"scripts.xcheck_ashare.")
    cells = [c for c in report.get("cells") or [] if c["grid"] == grid]
    agreed = [c for c in cells if c["severity"] == "ok"]
    out = [f"{t} cross-check as of {report.get('as_of')} — sources: {', '.join(report.get('sources') or [])}",
           f"{len(agreed)}/{len(cells)} {grid} cells agree to within 0.1%."]
    for c in [c for c in cells if c["severity"] != "ok"]:
        vals = ", ".join(f"{k} {_money(v)}" for k, v in c["values"].items())
        out.append(f"  ! {c['metric']} {c['period']}: {vals} (spread {(c['spread_pct'] or 0):.2%})")
    for v in report.get("valuation") or []:
        out.append(f"  our {v['metric']} {v['ours']:,.4g} vs Tushare's {v['tushare']:,.4g} "
                   f"(spread {(v['spread_pct'] or 0):.2%})")
    return "\n".join(out)
