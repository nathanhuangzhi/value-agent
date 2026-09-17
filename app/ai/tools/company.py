"""The app's own company data: the summarised block and the universe search."""
from __future__ import annotations

from fastapi import HTTPException

from app.ai.context import _money, company_block
from app.ai.tools.registry import tool
from app.data import repo
from app.log import get_logger

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
