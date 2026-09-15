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

    Matches: `$QDEL` / `#QDEL` tags; upper-case tokens that are analyzed tickers
    (skipping words that are usually just English); and company names
    (suffix-stripped, ≥5 chars) as substrings. Capped at `limit` so a list
    of ten tickers doesn't blow the context."""
    analyzed = _load_analyzed()
    found: list[str] = []

    def _add(t: str):
        if t in analyzed and t not in found:
            found.append(t)

    # `$QDEL` cashtags and `#QDEL` hashtags (the app's company-page chat
    # pre-fills "#TICKER ") — case-insensitive, any word length.
    for m in re.finditer(r"[$#]([A-Za-z]{1,6}(?:\.[A-Za-z])?)\b", text):
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
    ("balance_sheet", "Cash And Cash Equivalents", "Cash & equivalents"),
    ("balance_sheet", "Short Term Investments", "Short-term investments"),
    ("balance_sheet", "Restricted Cash", "Restricted cash"),
    ("balance_sheet", "Cash Cash Equivalents And Short Term Investments", "Cash + STI + restricted"),
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


TOOLS += [
    {
        "type": "function",
        "function": {
            "name": "list_filings",
            "description": "What raw source documents exist for a company: the quarterly 6-K results "
                           "releases on file (period_end, fiscal label, currency) and whether SEC XBRL "
                           "companyfacts and yfinance raw statements are cached. Call before get_6k_statement "
                           "/ get_press_release to know which periods are available.",
            "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_6k_statement",
            "description": "EVERY line item of one quarterly results release (6-K) as filed — income "
                           "statement, balance sheet and cash-flow statement, each line with the current and "
                           "prior-year values in the reporting currency. This is the raw filing, not the app's "
                           "summarised metrics: use it to verify a figure, find a line the summary lacks "
                           "(e.g. 'amounts due from related parties', 'restricted cash'), or trace a total.",
            "parameters": {"type": "object",
                           "properties": {"ticker": {"type": "string"},
                                          "period_end": {"type": "string", "description": "YYYY-MM-DD; omit for the latest"}},
                           "required": ["ticker"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_press_release",
            "description": "Full text of a quarterly results press release (6-K exhibit): management "
                           "commentary, segment/KPI disclosures, guidance, non-GAAP reconciliations, share "
                           "repurchases. Long (~20k chars) — call it when the question is about narrative, "
                           "guidance or a KPI rather than a statement line.",
            "parameters": {"type": "object",
                           "properties": {"ticker": {"type": "string"},
                                          "period_end": {"type": "string", "description": "YYYY-MM-DD; omit for the latest"},
                                          "max_chars": {"type": "integer", "description": "default 20000"}},
                           "required": ["ticker"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_xbrl_concepts",
            "description": "Search a company's raw SEC XBRL companyfacts (10-K/10-Q/20-F) for us-gaap concept "
                           "names matching a keyword (e.g. 'Lease', 'Restricted', 'Goodwill'). Returns concept "
                           "names with units, record counts and latest value — then call get_xbrl_concept.",
            "parameters": {"type": "object",
                           "properties": {"ticker": {"type": "string"}, "keyword": {"type": "string"}},
                           "required": ["ticker", "keyword"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_xbrl_concept",
            "description": "Raw SEC XBRL records for one us-gaap concept of a company: every (start, end, "
                           "value, form, filed) fact in the reporting currency, newest first. Ground truth "
                           "straight from EDGAR — use it to check any annual/quarterly number.",
            "parameters": {"type": "object",
                           "properties": {"ticker": {"type": "string"},
                                          "concept": {"type": "string", "description": "exact us-gaap name, e.g. OperatingLeaseLiability"},
                                          "limit": {"type": "integer", "description": "max records, default 24"}},
                           "required": ["ticker", "concept"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_yfinance_raw",
            "description": "Yahoo Finance's raw statement rows for a company — every label Yahoo publishes "
                           "(not just the app's mapped subset), by period. statement: annual_income, "
                           "annual_balance, annual_cashflow, quarterly_income, quarterly_balance, quarterly_cashflow.",
            "parameters": {"type": "object",
                           "properties": {"ticker": {"type": "string"},
                                          "statement": {"type": "string"},
                                          "period_end": {"type": "string", "description": "YYYY-MM-DD; omit for all periods (compact)"}},
                           "required": ["ticker", "statement"]},
        },
    },
]


def _fmt_num(v) -> str:
    if v is None:
        return "—"
    a = abs(v)
    return f"{v/1e9:.3f}B" if a >= 1e8 else f"{v/1e6:.2f}M" if a >= 1e5 else f"{v:,.2f}"


def _cik_for(ticker: str):
    from app.api.routes import _load_universe
    return (_load_universe().get(ticker.upper()) or {}).get("cik")


def _sixk_filing(ticker: str, period_end: str | None):
    from app.tools.sec_6k import load_store
    store = load_store(ticker.upper())
    filings = [f for f in store.get("filings") or [] if f.get("extracted") and f["extracted"].get("period_end")]
    if not filings:
        return None, "no 6-K releases on file for this ticker (it may be a domestic 10-Q filer)"
    if period_end:
        f = next((x for x in filings if x["extracted"]["period_end"] == period_end), None)
        if not f:
            return None, f"no 6-K for {period_end}; available: {', '.join(sorted(x['extracted']['period_end'] for x in filings))}"
        return f, None
    return max(filings, key=lambda x: x["extracted"]["period_end"]), None


def tool_list_filings(ticker: str) -> str:
    from app.tools.sec_6k import load_store
    from app.tools.sec_xbrl_tools import load_raw_companyfacts
    from app.tools.yfinance_statements import load_yf_raw
    t = ticker.upper()
    out = [f"## Raw sources for {t}"]
    store = load_store(t)
    rel = sorted((f["extracted"] for f in store.get("filings") or [] if f.get("extracted") and f["extracted"].get("period_end")),
                 key=lambda e: e["period_end"], reverse=True)
    if rel:
        out.append("6-K results releases (period_end · label · currency):")
        out += [f"- {e['period_end']} · {e.get('fiscal_label')} · {e.get('currency')}" for e in rel]
    else:
        out.append("6-K results releases: none (domestic filer, or not a watchlist/ADR ticker)")
    cik = _cik_for(t)
    raw = load_raw_companyfacts(cik) if cik else None
    if raw:
        n_concepts = len((raw[0].get("facts") or raw[0]).get("us-gaap", {}))
        out.append(f"SEC XBRL companyfacts: cached ({n_concepts} us-gaap concepts)")
    else:
        out.append("SEC XBRL companyfacts: not cached")
    yr = load_yf_raw(t)
    out.append(f"yfinance raw statements: {'cached, fetched ' + str(yr.get('fetched_at'))[:10] + ', currency ' + str(yr.get('financial_currency')) if yr else 'not cached'}")
    return "\n".join(out)


def tool_get_6k_statement(ticker: str, period_end: str | None) -> str:
    f, err = _sixk_filing(ticker, period_end)
    if err:
        return "ERROR: " + err
    ex = f["extracted"]
    out = [f"## {ticker.upper()} 6-K results release — period ending {ex['period_end']} ({ex.get('fiscal_label')}), "
           f"{ex.get('currency')} full units, filed {f.get('filed')}, accession {f.get('accession')}",
           f"cash-flow column: {ex.get('cash_flow_period_type')}; convenience USD rate: {ex.get('convenience_usd_rate')}"]
    for key, title in (("income_statement", "Income statement"), ("balance_sheet", "Balance sheet"), ("cash_flow", "Cash-flow statement")):
        rows = (ex.get("statements") or {}).get(key) or []
        out.append(f"\n### {title} (line | current | prior year)")
        out += [f"- {r.get('label')} | {_fmt_num(r.get('value'))} | {_fmt_num(r.get('prior_year_value'))}" for r in rows] or ["(none)"]
    return "\n".join(out)


def tool_get_press_release(ticker: str, period_end: str | None, max_chars: int | None) -> str:
    from app.tools.sec_6k import SIXK_DIR, html_to_text
    f, err = _sixk_filing(ticker, period_end)
    if err:
        return "ERROR: " + err
    path = SIXK_DIR / ticker.upper() / f"{f['accession']}_{f.get('document')}"
    if not path.exists():
        return f"ERROR: the exhibit HTML for {f['accession']} is not cached on this box"
    text = html_to_text(path.read_text(errors="replace"))
    limit = max(2000, min(int(max_chars or 20000), 60000))
    head = f"## {ticker.upper()} press release, period ending {f['extracted']['period_end']} (filed {f.get('filed')})\n\n"
    return head + (text if len(text) <= limit else text[:limit] + f"\n…(truncated at {limit} chars of {len(text)})")


def tool_search_xbrl_concepts(ticker: str, keyword: str) -> str:
    from app.tools.sec_xbrl_tools import load_raw_companyfacts
    cik = _cik_for(ticker)
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


def tool_get_xbrl_concept(ticker: str, concept: str, limit: int | None) -> str:
    from app.tools.sec_xbrl_tools import load_raw_companyfacts
    cik = _cik_for(ticker)
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


def tool_get_yfinance_raw(ticker: str, statement: str, period_end: str | None) -> str:
    from app.tools.yfinance_statements import load_yf_raw
    raw = load_yf_raw(ticker.upper())
    if not raw:
        return f"ERROR: no yfinance raw statements cached for {ticker.upper()}"
    frame = (raw.get("frames") or {}).get(statement)
    if frame is None:
        return f"ERROR: statement must be one of annual_income, annual_balance, annual_cashflow, quarterly_income, quarterly_balance, quarterly_cashflow"
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


def run_tool(name: str, args: dict) -> str:
    """Execute a tool call; always returns a string for the tool message."""
    if name == "list_filings":
        return tool_list_filings(args.get("ticker") or "")
    if name == "get_6k_statement":
        return tool_get_6k_statement(args.get("ticker") or "", args.get("period_end"))
    if name == "get_press_release":
        return tool_get_press_release(args.get("ticker") or "", args.get("period_end"), args.get("max_chars"))
    if name == "search_xbrl_concepts":
        return tool_search_xbrl_concepts(args.get("ticker") or "", args.get("keyword") or "")
    if name == "get_xbrl_concept":
        return tool_get_xbrl_concept(args.get("ticker") or "", args.get("concept") or "", args.get("limit"))
    if name == "get_yfinance_raw":
        return tool_get_yfinance_raw(args.get("ticker") or "", args.get("statement") or "", args.get("period_end"))
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
