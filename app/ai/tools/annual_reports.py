"""Annual reports (20-F / 10-K) as filed, section by section."""
from __future__ import annotations

from app.ai.tools.registry import tool
from app.data import repo
from app.log import get_logger

log = get_logger(__name__)


def _annual_index(ticker: str, *, fetch: bool = True):
    """The cached annual-report index; fetch the latest report on demand when empty."""
    from app.tools.sec_annual_reports import load_index, sync_ticker
    t = ticker.upper()
    idx = load_index(t)
    if not idx.get("filings") and fetch:
        cik = repo.cik_for(t)
        if not cik:
            return None, f"no CIK on file for {t}"
        try:
            idx = sync_ticker(t, cik, keep=1, log=lambda *_: None)
        except Exception as e:
            return None, f"could not fetch {t}'s annual report from EDGAR: {type(e).__name__}: {e}"
    if not idx.get("filings"):
        return None, f"no annual report (20-F/10-K) found on EDGAR for {t}"
    return idx, None


def _annual_filing(ticker: str, fiscal_year: str | None):
    from app.tools.sec_annual_reports import pick_filing
    idx, err = _annual_index(ticker)
    if err:
        return None, "ERROR: " + err
    f = pick_filing(idx, fiscal_year)
    if not f:
        years = ", ".join(x["fiscal_year"] for x in idx["filings"])
        return None, f"ERROR: no annual report for FY{fiscal_year} cached; available: {years}"
    return f, None


@tool(
    "list_annual_reports",
    marks_company=False,
    description="The annual reports (20-F for foreign filers, 10-K otherwise) cached as filed, with each report's table of contents: Items (business, risk factors, operating and financial review / MD&A, ...) and the numbered notes to the financial statements. Call first, then get_annual_report_section or search_annual_report. If nothing is cached for a company, the latest report is fetched from EDGAR.",
    params={"ticker": {"type": "string"}},
    required=["ticker"],
    status="Listing {ticker}'s annual reports…",
)
def list_annual_reports(ticker: str) -> str:
    idx, err = _annual_index(ticker)
    if err:
        return "ERROR: " + err
    out = [f"## Annual reports on file for {ticker.upper()}"]
    for f in idx["filings"]:
        out.append(f"\n### {f['form']} for fiscal year {f['fiscal_year']} (period {f.get('report_date')}, filed {f['filed']}, {f['chars']:,} chars)")
        for h in f.get("toc") or []:
            out.append(f"- {h['key']}: {h['title']}  ({h['end'] - h['line']} lines)")
    out.append("\nRead one with get_annual_report_section(ticker, section=<key or title words>, fiscal_year=<YYYY>).")
    return "\n".join(out)


@tool(
    "get_annual_report_section",
    description="Read one section of an annual report as filed: an Item ('item 5'), a note to the financial statements ('note 9', or part of its title: 'equity method investees', 'segment information', 'income tax'), or 'line:N' from a search hit. Returns up to max_chars (default 12000) from `offset`; the result says how much remains — call again with the next offset for long sections. This is the audited annual detail the XBRL feed lacks: note breakdowns, segment tables, accounting policies, MD&A.",
    params={"ticker": {"type": "string"}, "section": {"type": "string"}, "fiscal_year": {"type": "string", "description": "YYYY of the report's period end; omit for the latest"}, "offset": {"type": "integer"}, "max_chars": {"type": "integer"}},
    required=["ticker", "section"],
    status="Reading {ticker}'s annual report · {section}…",
)
def get_annual_report_section(ticker: str, section: str, fiscal_year: str | None,
                                   offset: int | None, max_chars: int | None) -> str:
    from app.tools.sec_annual_reports import find_section, read_text, section_text
    f, err = _annual_filing(ticker, fiscal_year)
    if err:
        return err
    sec = find_section(f, section)
    if not sec:
        keys = ", ".join(h["key"] for h in f.get("toc") or [])
        return f"ERROR: no section matching {section!r} in the FY{f['fiscal_year']} {f['form']}; sections: {keys}"
    limit = max(2000, min(int(max_chars or 12000), 40000))
    if sec.get("end") is None:                       # 'line:N' — a window, not a section
        sec = {**sec, "end": sec["line"] + 400}
    chunk, total, nxt = section_text(read_text(ticker.upper(), f), sec, offset=int(offset or 0), max_chars=limit)
    head = (f"## {ticker.upper()} {f['form']} FY{f['fiscal_year']} — {sec['title']} "
            f"(chars {int(offset or 0):,}–{nxt:,} of {total:,})\n\n")
    tail = f"\n\n…({total - nxt:,} chars remain — call again with offset={nxt})" if nxt < total else ""
    return head + chunk + tail


@tool(
    "search_annual_report",
    description="Find where a keyword or phrase appears in an annual report (case-insensitive): returns up to 12 hits with line numbers and a line of context, so you can then read around one with get_annual_report_section(section='line:N').",
    params={"ticker": {"type": "string"}, "keyword": {"type": "string"}, "fiscal_year": {"type": "string", "description": "YYYY; omit for the latest"}},
    required=["ticker", "keyword"],
    status="Searching {ticker}'s annual report for “{keyword}”…",
)
def search_annual_report(ticker: str, keyword: str, fiscal_year: str | None) -> str:
    from app.tools.sec_annual_reports import read_text, search_text
    f, err = _annual_filing(ticker, fiscal_year)
    if err:
        return err
    if not (keyword or "").strip():
        return "ERROR: keyword is required"
    hits = search_text(read_text(ticker.upper(), f), keyword.strip())
    if not hits:
        return f"No hits for {keyword!r} in {ticker.upper()}'s FY{f['fiscal_year']} {f['form']}."
    out = [f"## {ticker.upper()} {f['form']} FY{f['fiscal_year']}: {len(hits)} hits for {keyword!r} (read around one with section='line:N')"]
    for h in hits:
        out.append(f"\n[line {h['line']}]\n{h['snippet']}")
    return "\n".join(out)
