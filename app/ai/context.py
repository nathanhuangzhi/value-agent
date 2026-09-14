"""Company grounding for the AI chat.

Two ways a company's data reaches the model:
  1. `detect_companies(text)` — tickers / names spotted in the user's message;
     the server attaches `company_block(ticker)` for each before the call.
  2. Tools — `lookup_company` / `search_companies`, which the model calls
     itself for follow-ups, comparisons, or names it must resolve.

`company_block` is deliberately compact (~2-4k tokens): key statement lines
as year/quarter tables, snapshot ratios, the classification, recent prices,
and the dated analyst memo. The raw API payload is ~10x larger.
"""
from __future__ import annotations

import re

from fastapi import HTTPException

from app.api.routes import _load_analyzed, _load_universe, ticker_detail

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# Upper-case tokens that are real tickers but far more often plain words in
# an English sentence. They're only matched via the `$TICK` cashtag form.
_AMBIGUOUS = {
    "A", "I", "IT", "ON", "ALL", "FOR", "ARE", "CAN", "SO", "BE", "GO", "OR",
    "AN", "AT", "BY", "DO", "IF", "IN", "IS", "ME", "MY", "NO", "OF", "UP",
    "US", "WE", "AM", "AS", "TO", "HE", "OK", "PM", "AI", "ADD", "ANY", "BIG",
    "CAR", "DAY", "EAT", "FAR", "FLY", "GET", "HAS", "HIM", "HOW", "JOB", "KEY",
    "LOW", "MAN", "MAX", "NEW", "NOW", "ONE", "OUT", "OWN", "PAY", "RUN", "SEE",
    "TOP", "TWO", "WAY", "WHO", "YES", "YOU", "BEST", "CASH", "COST", "DEBT",
    "FREE", "GOOD", "HIGH", "LIFE", "LONG", "LOVE", "MORE", "NEXT", "OPEN",
    "PLAY", "REAL", "SAFE", "SAVE", "TECH", "TRUE", "WELL", "WORK", "YEAR",
    "SEC", "PE", "PB", "PS", "EV", "FCF", "OCF", "NI", "EPS", "ROE", "ROA",
    "TTM", "USD", "CEO", "CFO", "IPO", "ETF", "GAAP", "Q", "FY", "YTD",
}

_SUFFIX_RE = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|holdings?|group|plc|ltd|"
    r"limited|llc|lp|sa|nv|ag|se|trust|bancorp|the)\b\.?",
    re.I,
)


def _normalize_name(name: str) -> str:
    s = _SUFFIX_RE.sub(" ", name or "")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s


_name_index: tuple[int, list[tuple[str, str]]] = (-1, [])


def _analyzed_name_index() -> list[tuple[str, str]]:
    """[(normalized_name, ticker)] for every analyzed company, rebuilt when
    the analyzed set changes size (cheap proxy for 'changed')."""
    global _name_index
    analyzed = _load_analyzed()
    if _name_index[0] != len(analyzed):
        pairs = []
        for t, row in analyzed.items():
            n = _normalize_name(row.get("name") or "")
            if len(n) >= 5:
                pairs.append((n, t))
        # Longest names first so "quidelortho" wins over a shorter prefix.
        pairs.sort(key=lambda p: -len(p[0]))
        _name_index = (len(analyzed), pairs)
    return _name_index[1]


def detect_companies(text: str, *, limit: int = 4) -> list[str]:
    """Tickers the user is talking about, in order of appearance.

    Matches: `$QDEL` cashtags; upper-case tokens that are analyzed tickers
    (skipping words that are usually just English); and company names
    (suffix-stripped, ≥5 chars) as substrings. Capped at `limit` so a list
    of ten tickers doesn't blow the context."""
    analyzed = _load_analyzed()
    found: list[str] = []

    def _add(t: str):
        if t in analyzed and t not in found:
            found.append(t)

    for m in re.finditer(r"\$([A-Za-z]{1,6}(?:\.[A-Za-z])?)", text):
        _add(m.group(1).upper())
    for tok in re.findall(r"\b[A-Z]{2,6}(?:\.[A-Z])?\b", text):
        if tok not in _AMBIGUOUS:
            _add(tok)

    lowered = re.sub(r"[^a-z0-9]+", " ", text.lower())
    padded = f" {lowered} "
    for norm, t in _analyzed_name_index():
        if f" {norm} " in padded:
            _add(t)

    return found[:limit]


# ---------------------------------------------------------------------------
# Compact company block
# ---------------------------------------------------------------------------

_ANNUAL_LINES = [
    ("income_statement", "Total Revenue", "Revenue"),
    ("income_statement", "Gross Profit", "Gross profit"),
    ("income_statement", "Operating Income", "Operating income"),
    ("income_statement", "Net Income", "Net income"),
    ("income_statement", "Diluted EPS", "Diluted EPS"),
    ("income_statement", "Diluted Average Shares", "Diluted shares"),
    ("cash_flow", "Cash Flow From Continuing Operating Activities", "Operating cash flow"),
    ("cash_flow", "Capital Expenditure", "Capex"),
    ("cash_flow", "Free Cash Flow", "Free cash flow"),
    ("balance_sheet", "Cash And Cash Equivalents", "Cash"),
    ("balance_sheet", "Total Assets", "Total assets"),
    ("balance_sheet", "Receivables", "Receivables (total)"),
    ("balance_sheet", "Inventory", "Inventory"),
    ("balance_sheet", "Net PPE", "PP&E (net)"),
    ("balance_sheet", "Goodwill", "Goodwill"),
    ("balance_sheet", "Other Intangible Assets", "Intangibles (incl. land-use rights)"),
    ("balance_sheet", "Long Term Investments", "Long-term investments"),
    ("balance_sheet", "Total Liabilities", "Total liabilities"),
    ("balance_sheet", "Accounts Payable", "Accounts payable"),
    ("balance_sheet", "Deferred Revenue", "Deferred revenue"),
    ("balance_sheet", "Lease Obligations", "Lease obligations"),
    ("balance_sheet", "Current Debt", "Current debt"),
    ("balance_sheet", "Long Term Debt", "Long-term debt"),
    ("balance_sheet", "Total Debt", "Total debt"),
    ("balance_sheet", "Common Stock Equity", "Equity"),
]

_RATIO_LABELS = [
    ("market_cap", "Market cap", "money"),
    ("ttm_pe", "P/E (TTM)", "x"),
    ("ttm_pocf", "P/OCF (TTM)", "x"),
    ("p_fcf", "P/FCF", "x"),
    ("ps", "P/S", "x"),
    ("pb", "P/B", "x"),
    ("ev_revenue", "EV/Revenue", "x"),
    ("gross_margin", "Gross margin", "pct"),
    ("op_margin", "Operating margin", "pct"),
    ("net_margin", "Net margin", "pct"),
    ("roe", "ROE", "pct"),
    ("roa", "ROA", "pct"),
    ("debt_asset", "Debt / assets", "pct"),
    ("dividend_rate", "Dividend rate", "pct"),
]


def _money(v) -> str:
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e9:
        s = f"{v / 1e9:.2f}B"
    elif a >= 1e6:
        s = f"{v / 1e6:.1f}M"
    elif a >= 1e3:
        s = f"{v / 1e3:.0f}K"
    else:
        s = f"{v:.2f}"
    return s


def _fmt(v, kind: str) -> str:
    if v is None:
        return "—"
    if kind == "money":
        return _money(v)
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "x":
        return f"{v:.1f}x"
    return str(v)


def _statement_table(stmts: dict, lines, *, max_periods: int, period_label) -> str:
    """Rows = metrics, columns = periods (oldest → newest). yfinance-sourced
    cells get a trailing `y`."""
    periods: list[str] = []
    for key in ("income_statement", "cash_flow", "balance_sheet"):
        for p in stmts.get(key) or []:
            if p.get("period") and p["period"] not in periods:
                periods.append(p["period"])
    periods = sorted(periods)[-max_periods:]
    if not periods:
        return "_(no statements on file)_"

    by_stmt = {
        key: {p["period"]: p for p in (stmts.get(key) or []) if p.get("period")}
        for key in ("income_statement", "cash_flow", "balance_sheet")
    }
    out = ["| Metric | " + " | ".join(period_label(p) for p in periods) + " |",
           "|---|" + "---|" * len(periods)]
    for stmt, item, label in lines:
        cells = []
        any_val = False
        for p in periods:
            row = by_stmt[stmt].get(p) or {}
            v = (row.get("items") or {}).get(item)
            src = (row.get("sources") or {}).get(item)
            if v is None:
                cells.append("—")
            else:
                any_val = True
                cells.append(_money(v) + ("y" if src == "yfinance" else ""))
        if any_val:
            out.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def _fy_label(period: str) -> str:
    # Non-calendar fiscal years ending in Jan-May belong to the prior FY.
    y, m = int(period[:4]), int(period[5:7])
    return f"FY{y - 1 if m <= 5 else y}"


def _price_lines(row: dict) -> str:
    ph = (row.get("price_history") or {}).get("data") or []
    if not ph:
        return "_(no price history)_"
    closes = [(p["date"][:7], p["close"]) for p in ph if p.get("close") is not None]
    if not closes:
        return "_(no price history)_"
    last12 = closes[-12:]
    hi = max(c for _, c in closes)
    lo = min(c for _, c in closes)
    recent = ", ".join(f"{d} {c:.2f}" for d, c in last12)
    return (f"Last 12 monthly closes: {recent}. "
            f"10y range: {lo:.2f} – {hi:.2f}. Latest close {closes[-1][1]:.2f} ({closes[-1][0]}).")


def company_block(ticker: str, *, max_chars: int = 14000) -> str:
    """Markdown data block for one analyzed company. Raises HTTPException
    404 (via ticker_detail) if the ticker was never analyzed."""
    d = ticker_detail(ticker)
    row = _load_analyzed().get(ticker.upper()) or {}
    cls = d.get("classification") or {}
    meta = d.get("classification_meta") or {}
    snap = d.get("snapshot") or {}

    parts = [f"## Company data: {d['ticker']} — {d['name']}",
             f"{d.get('exchange') or ''} · {d.get('sector') or ''} / {d.get('industry') or ''} · "
             f"{d.get('country') or ''} · last scanned {d.get('analyzed_date') or '?'}"]

    ccy = d.get("currency")
    if ccy:
        if ccy.get("per_usd"):
            parts.append(f"**Currency:** statements reported in {ccy['code']}; all figures below are "
                         f"converted to USD at {ccy['per_usd']:.4f} {ccy['code']}/USD (as of {ccy.get('as_of')}). "
                         f"Multiply by that rate to quote {ccy['code']}.")
        else:
            parts.append(f"**Currency:** statements are in {ccy['code']} (no USD rate on file) — "
                         f"market cap is USD, so valuation ratios may be off.")

    overview = (d.get("business_overview") or "").strip()
    if overview:
        parts.append("**Business:** " + (overview[:900] + "…" if len(overview) > 900 else overview))
    if meta.get("logic_summary"):
        parts.append(f"**What it does (classifier):** {meta['logic_summary']}")
    if cls:
        attrs = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in cls.items() if v)
        parts.append(f"**Business model:** {attrs}")

    ratios = "; ".join(f"{label} {_fmt(snap.get(k), kind)}" for k, label, kind in _RATIO_LABELS
                       if snap.get(k) is not None)
    if ratios:
        parts.append(f"**Snapshot (latest):** {ratios}")

    parts.append("**Annual (USD; `y` = yfinance-sourced):**\n" + _statement_table(
        d.get("annual") or {}, _ANNUAL_LINES, max_periods=10, period_label=_fy_label))
    parts.append("**Quarterly (last 8):**\n" + _statement_table(
        d.get("quarterly") or {}, _ANNUAL_LINES, max_periods=8, period_label=lambda p: p[:7]))
    parts.append("**Price:** " + _price_lines(row))

    val = d.get("validation") or {}
    issues = [i for i in (val.get("issues") or []) if i.get("severity") in ("warn", "error")]
    if issues:
        parts.append("**Data-quality flags:** " + "; ".join(i.get("detail", "") for i in issues[:4]))

    memo = (d.get("narrative") or {}).get("text") or ""
    if memo.strip():
        when = (d.get("narrative") or {}).get("rerun_at") or d.get("analyzed_date") or "?"
        parts.append(f"**Analyst memo (dated {str(when)[:10]}; background, may be stale):**\n{memo.strip()}")

    text = "\n\n".join(parts)
    return text if len(text) <= max_chars else text[:max_chars] + "\n…(truncated)"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_company",
            "description": "Fetch the app's collected data for one company by ticker: "
                           "financial statements (10y annual, 8 quarters), valuation snapshot, "
                           "business-model classification, prices, and the dated analyst memo. "
                           "Only works for the ~1,250 analyzed companies; otherwise returns an error "
                           "and you should say the company has not been analyzed yet.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "e.g. QDEL"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_companies",
            "description": "Find companies by name or ticker fragment across ~7,000 NYSE/Nasdaq "
                           "listings. Returns ticker, name, industry, market cap and whether the "
                           "company has been analyzed (i.e. lookup_company will work).",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


def run_tool(name: str, args: dict) -> str:
    """Execute a tool call; always returns a string for the tool message."""
    if name == "lookup_company":
        t = (args.get("ticker") or "").upper().strip()
        try:
            return company_block(t)
        except HTTPException:
            return (f"ERROR: {t} has not been analyzed by the pipeline — no statements or memo "
                    f"on file. Use search_companies to confirm the ticker, and tell the user "
                    f"the data is not available.")
    if name == "search_companies":
        return search_companies(args.get("query") or "")
    return f"ERROR: unknown tool {name}"


def search_companies(query: str, *, limit: int = 12) -> str:
    q = query.strip().lower()
    if not q:
        return "ERROR: empty query"
    analyzed = _load_analyzed()
    universe = _load_universe()
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
