"""Filing inventory and the quarterly 6-K results releases (foreign filers)."""
from __future__ import annotations

from app.ai.tools.registry import _t, tool
from app.data import repo
from app.log import get_logger

log = get_logger(__name__)


def _fmt_num(v) -> str:
    if v is None:
        return "—"
    a = abs(v)
    return f"{v/1e9:.3f}B" if a >= 1e8 else f"{v/1e6:.2f}M" if a >= 1e5 else f"{v:,.2f}"


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


@tool(
    "list_filings",
    marks_company=False,
    description="What raw source documents exist for a company: the quarterly 6-K results releases on file (period_end, fiscal label, currency) and whether SEC XBRL companyfacts and yfinance raw statements are cached. Call before get_6k_statement / get_press_release to know which periods are available.",
    params={"ticker": {"type": "string"}},
    required=["ticker"],
    status="Listing filings for {ticker}…",
)
def list_filings(ticker: str) -> str:
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
    from app.tools.sec_annual_reports import load_index
    ar = load_index(t).get("filings") or []
    if ar:
        out.append("Annual reports as filed (list_annual_reports for the table of contents): "
                   + ", ".join(f"{f['form']} FY{f['fiscal_year']}" for f in ar))
    else:
        out.append("Annual reports as filed: none cached yet (list_annual_reports fetches the latest on demand)")
    from app.tools.earnings_calls import load_store as load_calls
    calls = load_calls(t).get("calls") or {}
    out.append("Earnings-call transcripts: " + (", ".join(sorted(calls, reverse=True)) if calls
               else "none cached (list_earnings_calls fetches the latest quarter on demand)"))
    cik = repo.cik_for(t)
    raw = load_raw_companyfacts(cik) if cik else None
    if raw:
        n_concepts = len((raw[0].get("facts") or raw[0]).get("us-gaap", {}))
        out.append(f"SEC XBRL companyfacts: cached ({n_concepts} us-gaap concepts)")
    else:
        out.append("SEC XBRL companyfacts: not cached")
    yr = load_yf_raw(t)
    out.append(f"yfinance raw statements: {'cached, fetched ' + str(yr.get('fetched_at'))[:10] + ', currency ' + str(yr.get('financial_currency')) if yr else 'not cached'}")
    return "\n".join(out)


@tool(
    "get_6k_statement",
    description="EVERY line item of one quarterly results release (6-K) as filed — income statement, balance sheet and cash-flow statement, each line with the current and prior-year values in the reporting currency. This is the raw filing, not the app's summarised metrics: use it to verify a figure, find a line the summary lacks (e.g. 'amounts due from related parties', 'restricted cash'), or trace a total.",
    params={"ticker": {"type": "string"}, "period_end": {"type": "string", "description": "YYYY-MM-DD; omit for the latest"}},
    required=["ticker"],
    status=lambda a: f"Reading {_t(a)}'s 6-K statements{(' ' + a['period_end']) if a.get('period_end') else ''}…",
)
def get_6k_statement(ticker: str, period_end: str | None) -> str:
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


@tool(
    "get_press_release",
    description="Full text of a quarterly results press release (6-K exhibit): management commentary, segment/KPI disclosures, guidance, non-GAAP reconciliations, share repurchases. Long (~20k chars) — call it when the question is about narrative, guidance or a KPI rather than a statement line.",
    params={"ticker": {"type": "string"}, "period_end": {"type": "string", "description": "YYYY-MM-DD; omit for the latest"}, "max_chars": {"type": "integer", "description": "default 20000"}},
    required=["ticker"],
    status="Reading {ticker}'s press release…",
)
def get_press_release(ticker: str, period_end: str | None, max_chars: int | None) -> str:
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
