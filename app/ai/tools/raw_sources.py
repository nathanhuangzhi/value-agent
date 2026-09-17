"""Raw upstream sources: SEC XBRL companyfacts and Yahoo's raw statement rows."""
from __future__ import annotations

from app.ai.tools.filings import _fmt_num
from app.ai.tools.registry import tool
from app.data import repo
from app.log import get_logger

log = get_logger(__name__)


@tool(
    "search_xbrl_concepts",
    marks_company=False,
    description="Search a company's raw SEC XBRL companyfacts (10-K/10-Q/20-F) for us-gaap concept names matching a keyword (e.g. 'Lease', 'Restricted', 'Goodwill'). Returns concept names with units, record counts and latest value — then call get_xbrl_concept.",
    params={"ticker": {"type": "string"}, "keyword": {"type": "string"}},
    required=["ticker", "keyword"],
    status="Searching {ticker}'s XBRL for “{keyword}”…",
)
def search_xbrl_concepts(ticker: str, keyword: str) -> str:
    from app.tools.sec_xbrl_tools import load_raw_companyfacts
    cik = repo.cik_for(ticker)
    raw = load_raw_companyfacts(cik) if cik else None
    if not raw:
        return f"ERROR: no SEC companyfacts cached for {ticker.upper()}"
    g = (raw[0].get("facts") or raw[0]).get("us-gaap", {})
    kw = (keyword or "").lower()
    hits = []
    for name, node in g.items():
        if kw not in name.lower():
            continue
        for unit, recs in (node.get("units") or {}).items():
            if not recs:
                continue
            latest = max(recs, key=lambda r: (r.get("end", ""), r.get("filed", "")))
            hits.append((name, unit, len(recs), latest.get("end"), latest.get("val")))
    if not hits:
        return f"No us-gaap concepts containing {keyword!r} for {ticker.upper()}."
    hits.sort(key=lambda h: (-h[2], h[0]))
    return "\n".join(f"- {n} [{u}] {c} records, latest {e}: {_fmt_num(v) if u != 'shares' else v}" for n, u, c, e, v in hits[:40])


@tool(
    "get_xbrl_concept",
    description="Raw SEC XBRL records for one us-gaap concept of a company: every (start, end, value, form, filed) fact in the reporting currency, newest first. Ground truth straight from EDGAR — use it to check any annual/quarterly number.",
    params={"ticker": {"type": "string"}, "concept": {"type": "string", "description": "exact us-gaap name, e.g. OperatingLeaseLiability"}, "limit": {"type": "integer", "description": "max records, default 24"}},
    required=["ticker", "concept"],
    status="Pulling {ticker} · {concept} from EDGAR…",
)
def get_xbrl_concept(ticker: str, concept: str, limit: int | None) -> str:
    from app.tools.sec_xbrl_tools import load_raw_companyfacts
    cik = repo.cik_for(ticker)
    raw = load_raw_companyfacts(cik) if cik else None
    if not raw:
        return f"ERROR: no SEC companyfacts cached for {ticker.upper()}"
    g = (raw[0].get("facts") or raw[0]).get("us-gaap", {})
    node = g.get(concept)
    if not node:
        return f"ERROR: {ticker.upper()} has no us-gaap concept {concept!r}; try search_xbrl_concepts"
    out = [f"## {ticker.upper()} · us-gaap:{concept} — {node.get('description') or ''}"]
    n = max(1, min(int(limit or 24), 200))
    for unit, recs in (node.get("units") or {}).items():
        rows = sorted(recs, key=lambda r: (r.get("end", ""), r.get("filed", "")), reverse=True)[:n]
        out.append(f"\n[{unit}] (start → end | value | form | filed)")
        out += [f"- {r.get('start') or 'instant'} → {r.get('end')} | {_fmt_num(r.get('val')) if unit != 'shares' else r.get('val')} | {r.get('form')} | {r.get('filed')}" for r in rows]
    return "\n".join(out)


@tool(
    "get_yfinance_raw",
    description="Yahoo Finance's raw statement rows for a company — every label Yahoo publishes (not just the app's mapped subset), by period. statement: annual_income, annual_balance, annual_cashflow, quarterly_income, quarterly_balance, quarterly_cashflow.",
    params={"ticker": {"type": "string"}, "statement": {"type": "string"}, "period_end": {"type": "string", "description": "YYYY-MM-DD; omit for all periods (compact)"}},
    required=["ticker", "statement"],
    status="Reading {ticker}'s Yahoo {statement}…",
)
def get_yfinance_raw(ticker: str, statement: str, period_end: str | None) -> str:
    from app.tools.yfinance_statements import load_yf_raw
    raw = load_yf_raw(ticker.upper())
    if not raw:
        return f"ERROR: no yfinance raw statements cached for {ticker.upper()}"
    frame = (raw.get("frames") or {}).get(statement)
    if frame is None:
        return "ERROR: statement must be one of annual_income, annual_balance, annual_cashflow, quarterly_income, quarterly_balance, quarterly_cashflow"
    out = [f"## {ticker.upper()} yfinance raw · {statement} · currency {raw.get('financial_currency')} · fetched {str(raw.get('fetched_at'))[:10]}"]
    if period_end:
        for label, series in frame.items():
            if period_end in series:
                out.append(f"- {label}: {_fmt_num(series[period_end])}")
        if len(out) == 1:
            return f"ERROR: no {statement} data at {period_end}; periods: {sorted({p for s in frame.values() for p in s})}"
    else:
        periods = sorted({p for s in frame.values() for p in s})[-6:]
        out.append("label | " + " | ".join(periods))
        for label, series in frame.items():
            out.append(f"{label} | " + " | ".join(_fmt_num(series.get(p)) for p in periods))
    return "\n".join(out)
