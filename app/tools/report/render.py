"""Top-level report assembly: bands, section wrappers, snapshot, business
bullets, narrative rendering, footer, and the `render_company_report`
entry point that stitches everything together."""

from __future__ import annotations

import html
import re

from markdown_it import MarkdownIt

from app.tools.paths import COMPANIES_SEC, COMPANIES_YFINANCE
from app.tools.report.charts import _chart_valuation_monthly
from app.tools.report.format import (
    AMBER,
    MUTED,
    NAVY,
    RULE,
    TEXT,
    _div,
    _fmt_dividend,
    _fmt_num,
    _fmt_pct,
    _format_money,
    _img_flush,
    inline_styles,
)
from app.tools.report.ratios import (
    _compute_valuation_history_monthly,
    _latest_value,
    _recomputed_mcap,
    _strict_ttm_sum,
    _ttm_dividend_per_share,
)
from app.tools.report.sec_adapter import (
    load_sec_by_ticker,
    sec_to_yfinance_annual,
    sec_to_yfinance_quarterly,
)
from app.tools.report.tables import _render_combined_data_table

_SEC_DATA: dict | None = None
_YF_DATA: dict | None = None


def _get_sec_data() -> dict:
    """Lazy-load companies_sec.json once per process."""
    global _SEC_DATA
    if _SEC_DATA is None:
        _SEC_DATA = load_sec_by_ticker(COMPANIES_SEC)
    return _SEC_DATA


def _get_yfinance_data() -> dict:
    """Lazy-load companies_yfinance.json once per process. Same shape as
    companies_sec.json — `load_sec_by_ticker` works for both."""
    global _YF_DATA
    if _YF_DATA is None:
        _YF_DATA = load_sec_by_ticker(COMPANIES_YFINANCE)
    return _YF_DATA


_MD = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable("table")


def render_company_report(row: dict, validation: dict | None = None,
                          next_ticker: dict | None = None) -> str:
    """Render one ticker's research memo as a standalone HTML document.

    `next_ticker`: optional `{ticker, href}` used to render a "Next →"
    navigation control. When None, no nav is shown. Callers typically pick
    the alphabetically-next ticker within the same industry so the reader
    can flip through a sector in one sitting (see `pick_next_ticker`)."""
    statements = _extract_blended_statements(row)
    body = _assemble_report_body(row, statements, validation, next_ticker)
    title = f"{row.get('ticker', '?')} — {html.escape(row.get('name') or row.get('ticker', '?'))} — Equity Research Memo"
    return _wrap_document(body, title)


def _extract_blended_statements(row: dict) -> dict:
    """Return a `{inc_annual, bs_annual, cf_annual, inc_quarterly,
    bs_quarterly, cf_quarterly, price_history}` dict, blending SEC primary
    + yfinance gap-fill. Falls back to the row's embedded
    `financial_statements` for tickers without sidecar data."""
    ticker = row.get("ticker", "?")
    fs = row.get("financial_statements") or {}
    inc_annual = (fs.get("income_statement") or {}).get("annual") or []
    bs_annual = (fs.get("balance_sheet") or {}).get("annual") or []
    cf_annual = (fs.get("cash_flow") or {}).get("annual") or []
    inc_quarterly = (fs.get("income_statement") or {}).get("quarterly") or []
    bs_quarterly = (fs.get("balance_sheet") or {}).get("quarterly") or []
    cf_quarterly = (fs.get("cash_flow") or {}).get("quarterly") or []

    sec_row = _get_sec_data().get(ticker)
    yf_row = _get_yfinance_data().get(ticker)
    if sec_row or yf_row:
        blended_annual = sec_to_yfinance_annual(sec_row or {}, yfinance_row=yf_row)
        inc_annual = blended_annual["income_statement"] or inc_annual
        bs_annual = blended_annual["balance_sheet"] or bs_annual
        cf_annual = blended_annual["cash_flow"] or cf_annual
        blended_q = sec_to_yfinance_quarterly(sec_row or {}, last_n=8, yfinance_row=yf_row)
        inc_quarterly = blended_q["income_statement"] or inc_quarterly
        bs_quarterly = blended_q["balance_sheet"] or bs_quarterly
        cf_quarterly = blended_q["cash_flow"] or cf_quarterly

    return {
        "inc_annual": inc_annual, "bs_annual": bs_annual, "cf_annual": cf_annual,
        "inc_quarterly": inc_quarterly, "bs_quarterly": bs_quarterly, "cf_quarterly": cf_quarterly,
        "price_history": (row.get("price_history") or {}).get("data") or [],
    }


def _assemble_report_body(row: dict, stmts: dict, validation: dict | None,
                          next_ticker: dict | None) -> str:
    """Compose the report's `<table>` content from its sections in order:
    band header, validation banner, snapshot+business-overview, valuation
    chart, historical-data table, investment narrative, next-ticker nav,
    footer. Each section returns either an HTML string or "" so we can
    blindly join."""
    ticker = row.get("ticker", "?")
    val_history = _compute_valuation_history_monthly(
        stmts["inc_quarterly"], stmts["bs_quarterly"],
        stmts["inc_annual"], stmts["bs_annual"], stmts["price_history"],
    )
    valuation_chart = _chart_valuation_monthly(val_history, price_history=stmts["price_history"])

    parts = [
        _band_header(
            ticker, row.get("name") or ticker,
            row.get("exchange") or "", row.get("sector") or "",
            row.get("industry") or "", row.get("market_cap"),
            row.get("analyzed_date") or "", row.get("country") or "",
        ),
    ]
    banner = _validation_banner(validation)
    if banner:
        parts.append(banner)
    parts.append(_render_top_two_col(
        snapshot_html=_render_snapshot(
            stmts["inc_quarterly"], stmts["bs_quarterly"],
            stmts["cf_quarterly"], stmts["price_history"], stmts["inc_annual"],
        ),
        overview_html=_render_business_bullets(
            row.get("classification") or {}, row.get("classification_meta") or {},
        ),
    ))
    if valuation_chart:
        parts.append(_section(
            "Stock Price & Valuation Multiples (monthly: Stock Price, Static P/E, Static P/S, P/B)",
            _img_flush(valuation_chart, "Price and valuation chart"),
        ))
    combined_table = _render_combined_data_table(
        stmts["inc_annual"], stmts["bs_annual"], stmts["cf_annual"],
        stmts["inc_quarterly"], stmts["bs_quarterly"], stmts["cf_quarterly"],
        price_history=stmts["price_history"],
    )
    if combined_table:
        parts.append(_section(
            "Historical Data (annual + quarterly)",
            f"<div class='scroll-wrap'>{combined_table}</div>",
        ))
    latest_source_date = _latest_source_date(row.get("narrative_sources") or [])
    parts.append(_section(
        "Investment Narrative",
        _render_narrative(row.get("narrative") or "", latest_source_date=latest_source_date),
    ))
    if next_ticker and next_ticker.get("ticker") and next_ticker.get("href"):
        parts.append(_next_ticker_nav(next_ticker))
    parts.append(_band_footer())
    return "".join(parts)


# Mobile-first responsive overrides. Lives in <style> at the top of the doc
# so it applies before any inline styles paint. Targets the class names we
# attach to per-section table cells (band-pad / sec-pad / foot-pad etc.).
_RESPONSIVE_STYLE = f"""@media (max-width:599px){{
  .band-pad{{padding:18px 16px !important;}}
  .sec-pad{{padding:18px 14px 4px !important;}}
  .foot-pad{{padding:14px 16px !important;}}
  .hdr-name{{font-size:22px !important;}}
  .hdr-mcap{{font-size:18px !important;}}
  .hdr-mcap-cell{{width:auto !important;}}
  .stack-col{{display:block !important;width:100% !important;padding:0 0 16px 0 !important;border-left:none !important;}}
  .stack-col + .stack-col{{padding:16px 0 0 0 !important;border-top:1px solid {RULE} !important;}}
  .kpi-cell{{width:50% !important;}}
  .img-flush{{margin:0 -14px !important;}}
}}
.scroll-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;}}"""


def _wrap_document(body: str, title: str) -> str:
    """Wrap an assembled body in `<html>...<body><table>...</table></body>`.
    The `<table>` is the responsive 720px-max-width card; the responsive
    CSS lives in the document-level `<style>` block."""
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title>"
        f"<style>{_RESPONSIVE_STYLE}</style>"
        f"</head>"
        f"<body style='margin:0;padding:24px 0;background:#ebe6da;font-family:Georgia,serif;color:{TEXT};'>"
        f"<table role='presentation' cellpadding='0' cellspacing='0' border='0' width='100%' "
        f"style='margin:0 auto;background:#ffffff;border:1px solid {RULE};max-width:720px;'>"
        f"{body}"
        f"</table></body></html>"
    )


def _validation_banner(validation):
    """Yellow banner for `warn`, red for `error`. Returns "" when validation
    is None / status ok / status info (the latter is too noisy to surface)."""
    if not validation:
        return ""
    status = validation.get("status")
    if status not in ("warn", "error"):
        return ""
    is_error = status == "error"
    bg = "#f8d7da" if is_error else "#fff3cd"
    border = "#dc3545" if is_error else "#e0a800"
    icon = "✗" if is_error else "⚠"
    label = "DATA QUALITY ERROR" if is_error else "DATA QUALITY WARNING"
    lines = []
    for iss in validation.get("issues") or []:
        if iss.get("severity") == "info":
            continue
        lines.append(
            f"<li style='margin-bottom:2px;'><b>{html.escape(iss.get('rule',''))}</b>: "
            f"{html.escape(iss.get('detail',''))}</li>"
        )
    body = (f"<ul style='margin:6px 0 0;padding-left:20px;font-size:11px;line-height:1.5;'>"
            f"{''.join(lines)}</ul>") if lines else ""
    return (
        f"<tr><td class='band-pad' style='background:{bg};border-left:4px solid {border};"
        f"padding:12px 28px;color:#444;font-family:Helvetica,Arial,sans-serif;'>"
        f"<div style='font-size:11px;letter-spacing:2px;font-weight:bold;color:#444;'>"
        f"{icon} {label}</div>"
        f"{body}"
        f"</td></tr>"
    )


def _band_header(ticker, name, exchange, sector, industry, mcap, analyzed_date, country):
    chips = " &middot; ".join(filter(None, [html.escape(exchange), f"{html.escape(sector)} / {html.escape(industry)}", html.escape(country)]))
    return (
        f"<tr><td class='band-pad' style='background:{NAVY};color:#ffffff;padding:24px 28px;'>"
        f"<table width='100%' role='presentation' cellpadding='0' cellspacing='0'><tr>"
        f"<td valign='top'>"
        f"<div style='font-size:11px;letter-spacing:2px;opacity:0.7;font-family:Helvetica,Arial,sans-serif;'>EQUITY RESEARCH MEMO</div>"
        f"<div class='hdr-name' style='font-size:30px;font-weight:bold;line-height:1.1;margin-top:6px;'>{html.escape(name)}</div>"
        f"<div style='font-size:13px;opacity:0.85;margin-top:6px;'><b>{ticker}</b> &middot; {chips}</div>"
        f"</td>"
        f"<td class='hdr-mcap-cell' valign='top' align='right' width='180'>"
        f"<div class='hdr-mcap' style='font-size:24px;font-weight:bold;'>{_format_money(mcap)}</div>"
        f"<div style='font-size:12px;opacity:0.85;font-family:Helvetica,Arial,sans-serif;'>Market Cap &middot; {analyzed_date}</div>"
        f"</td></tr></table></td></tr>"
    )


def _section(title, body):
    return (
        f"<tr><td class='sec-pad' style='padding:24px 28px 4px;'>"
        f"<div style='font-size:11px;letter-spacing:2px;color:{AMBER};font-family:Helvetica,Arial,sans-serif;"
        f"border-bottom:2px solid {AMBER};padding-bottom:6px;margin-bottom:14px;'>{title.upper()}</div>"
        f"{body}"
        f"</td></tr>"
    )


def _mini_section_header(title):
    """A smaller section heading for use inside `_render_top_two_col` —
    matches the visual style of `_section` but without the outer `<tr>`
    padding so it can sit inside a 2-column layout."""
    return (
        f"<div style='font-size:11px;letter-spacing:2px;color:{AMBER};font-family:Helvetica,Arial,sans-serif;"
        f"border-bottom:2px solid {AMBER};padding-bottom:6px;margin-bottom:12px;'>{title.upper()}</div>"
    )


def _render_top_two_col(snapshot_html, overview_html):
    """Two-column row holding the Snapshot KPI grid (left) and Business
    Overview bullets (right). More compact than two stacked sections.
    Email-safe nested-table layout. On mobile (<600px), the `.stack-col`
    CSS class stacks the columns vertically and swaps the divider from a
    left-border to a top-border."""
    return (
        f"<tr><td class='sec-pad' style='padding:24px 28px 4px;'>"
        f"<table role='presentation' cellpadding='0' cellspacing='0' width='100%' "
        f"style='border-collapse:collapse;'>"
        f"<tr>"
        f"<td class='stack-col' valign='top' width='62%' style='padding-right:16px;'>"
        f"{_mini_section_header('Snapshot')}"
        f"{snapshot_html}"
        f"</td>"
        f"<td class='stack-col' valign='top' width='38%' style='padding-left:16px;border-left:1px solid {RULE};'>"
        f"{_mini_section_header('Business Overview')}"
        f"{overview_html}"
        f"</td>"
        f"</tr>"
        f"</table>"
        f"</td></tr>"
    )


def _band_footer():
    return (
        f"<tr><td class='foot-pad' style='background:#f5f1e8;padding:16px 28px;font-size:11px;color:{MUTED};"
        f"font-family:Helvetica,Arial,sans-serif;border-top:1px solid {RULE};'>"
        f"For research and educational purposes only. Not investment advice."
        f"</td></tr>"
    )


def _render_snapshot(inc_quarterly, bs_quarterly, cf_quarterly, price_history, inc_annual):
    """Every metric here is derived from the quarterly statements, monthly
    price history, and (for Static P/E) the most recent annual income
    statement. No fields from yfinance's `info` dict, so the snapshot is
    internally consistent and matches the monthly valuation chart."""
    mcap = _recomputed_mcap(price_history, inc_quarterly)

    ttm_rev = _strict_ttm_sum(inc_quarterly, ["Total Revenue", "Operating Revenue"])
    ttm_gp = _strict_ttm_sum(inc_quarterly, ["Gross Profit"])
    ttm_op = _strict_ttm_sum(inc_quarterly, ["Operating Income", "Total Operating Income As Reported"])
    ttm_ni = _strict_ttm_sum(inc_quarterly, ["Net Income", "Net Income Common Stockholders"])
    ttm_ebitda = _strict_ttm_sum(inc_quarterly, ["EBITDA", "Normalized EBITDA"])
    ttm_ocf = _strict_ttm_sum(cf_quarterly, ["Cash Flow From Continuing Operating Activities", "Operating Cash Flow"])
    ttm_fcf = _strict_ttm_sum(cf_quarterly, ["Free Cash Flow"])

    latest_annual_ni = _latest_value(inc_annual, ["Net Income", "Net Income Common Stockholders"])
    latest_bv = _latest_value(bs_quarterly, ["Common Stock Equity", "Stockholders Equity", "Total Equity Gross Minority Interest"])
    latest_cash = _latest_value(bs_quarterly, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"])
    latest_debt = _latest_value(bs_quarterly, ["Total Debt", "Long Term Debt"])
    latest_assets = _latest_value(bs_quarterly, ["Total Assets"])
    latest_shares = _latest_value(inc_quarterly, ["Diluted Average Shares", "Basic Average Shares"])

    dividend_rate_per_share = _ttm_dividend_per_share(cf_quarterly, latest_shares)

    ev = (mcap + latest_debt - (latest_cash or 0)) if (mcap is not None and latest_debt is not None) else None

    pairs = [
        ("Market Cap", _format_money(mcap, decimals=1)),
        ("TTM P/E", _fmt_num(_div(mcap, ttm_ni), decimals=1)),
        ("Static P/E", _fmt_num(_div(mcap, latest_annual_ni), decimals=1)),
        ("EV/EBITDA", _fmt_num(_div(ev, ttm_ebitda), decimals=1)),
        ("EV/Revenue", _fmt_num(_div(ev, ttm_rev), decimals=1)),
        ("Price/Book", _fmt_num(_div(mcap, latest_bv), decimals=1)),
        ("Price/Sales", _fmt_num(_div(mcap, ttm_rev), decimals=1)),
        ("P/FCF", _fmt_num(_div(mcap, ttm_fcf), decimals=1)),
        ("P/OCF", _fmt_num(_div(mcap, ttm_ocf), decimals=1)),
        ("Debt/Asset", _fmt_pct(_div(latest_debt, latest_assets), decimals=1)),
        ("Gross Margin", _fmt_pct(_div(ttm_gp, ttm_rev), decimals=1)),
        ("Operating Margin", _fmt_pct(_div(ttm_op, ttm_rev), decimals=1)),
        ("Profit Margin", _fmt_pct(_div(ttm_ni, ttm_rev), decimals=1)),
        ("Return on Equity", _fmt_pct(_div(ttm_ni, latest_bv), decimals=1)),
        ("Return on Assets", _fmt_pct(_div(ttm_ni, latest_assets), decimals=1)),
        ("Dividend Rate", _fmt_dividend(dividend_rate_per_share, decimals=1)),
    ]
    cells = []
    for label, value in pairs:
        cells.append(
            f"<td class='kpi-cell' style='border:1px solid {RULE};padding:5px 7px;width:25%;vertical-align:top;'>"
            f"<div style='font-size:9px;letter-spacing:1px;color:{MUTED};font-family:Helvetica,Arial,sans-serif;'>{label.upper()}</div>"
            f"<div style='font-size:13px;color:{TEXT};margin-top:2px;font-family:Helvetica,Arial,sans-serif;'>{value}</div>"
            f"</td>"
        )
    rows = []
    per_row = 4
    for i in range(0, len(cells), per_row):
        chunk = cells[i:i + per_row]
        while len(chunk) < per_row:
            chunk.append(f"<td class='kpi-cell' style='border:1px solid {RULE};width:25%;'></td>")
        rows.append("<tr>" + "".join(chunk) + "</tr>")
    return (
        f"<table cellpadding='0' cellspacing='0' width='100%' "
        f"style='border-collapse:collapse;'>{''.join(rows)}</table>"
    )


def _render_business_bullets(classification, classification_meta):
    """Compact bullet list of structured business attributes from the
    Stage 2 classifier (10 categorical fields + the one-line logic_summary)."""
    summary = (classification_meta.get("logic_summary") or "").strip()
    fields = [
        ("Sector", classification.get("sector")),
        ("Industry", classification.get("industry")),
        ("Revenue model", classification.get("revenue_model")),
        ("Customers", classification.get("customer_type")),
        ("Asset intensity", classification.get("asset_intensity")),
        ("Value chain", classification.get("value_chain_position")),
        ("Geographic exposure", classification.get("geographic_exposure")),
        ("Inventory strategy", classification.get("inventory_strategy")),
        ("Global presence", classification.get("global_presence")),
    ]
    items = []
    if summary:
        items.append(
            f"<li style='margin-bottom:4px;'><b style='color:{NAVY};'>What it does:</b> "
            f"{html.escape(summary)}</li>"
        )
    for label, value in fields:
        if not value:
            continue
        items.append(
            f"<li style='margin-bottom:1px;'><b style='color:{NAVY};'>{label}:</b> "
            f"{html.escape(str(value))}</li>"
        )
    if not items:
        return f"<p style='color:{MUTED};margin:0;'>(no structured business profile available)</p>"
    return (
        f"<ul style='margin:0;padding-left:18px;font-size:12px;line-height:1.4;color:{TEXT};'>"
        f"{''.join(items)}</ul>"
    )


_NARRATIVE_TITLE_RE = re.compile(
    r"^\s*(?:#+\s*|\*\*)\s*Investment\s+Narrative\s*(?:\*\*)?\s*\n+",
    re.IGNORECASE,
)

# Matches dates anywhere in a URL or snippet. Listed longest-first so the
# more-specific pattern wins when both match the same string.
_DATE_PATTERNS = (
    # ISO 8601 with hyphens: "2026-05-12" or "2026-05-12T18:30:00Z"
    re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b"),
    # URL path variants with slashes: "/2026/05/12/" or "2026/5/12"
    re.compile(r"\b(20\d{2})/(\d{1,2})/(\d{1,2})\b"),
)


def _latest_source_date(sources):
    """Best-effort: return the most recent publication date among
    `narrative_sources`, as `YYYY-MM-DD`, or None if no date can be
    extracted.

    Resolution order per source:
      1. `published_date` field (populated for runs against the updated
         `search_tools.get_market_commentary`)
      2. Regex match against the URL (catches `/2026/05/12/` and
         `2026-5-12-` style paths)
      3. Regex match against the snippet text (catches ISO-like dates
         embedded in the article preview)

    Returns the LATEST date across all sources, so re-running the search
    months later doesn't silently surface a stale article."""
    from datetime import date as _date

    best: _date | None = None
    for s in sources or []:
        candidate = _parse_source_date(s)
        if candidate and (best is None or candidate > best):
            best = candidate
    return best.isoformat() if best else None


def _parse_source_date(source):
    """Return a `datetime.date` if any of the source's fields contains a
    plausible date, else None. Encapsulates the per-source resolution so
    the test suite can exercise each fallback path independently."""
    from datetime import date as _date

    pub = (source or {}).get("published_date")
    if isinstance(pub, str) and pub:
        # Tolerate ISO datetimes by slicing the date part.
        try:
            return _date.fromisoformat(pub[:10])
        except ValueError:
            pass

    for field in ("url", "snippet"):
        text = (source or {}).get(field) or ""
        for pat in _DATE_PATTERNS:
            m = pat.search(text)
            if not m:
                continue
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    return _date(y, mo, d)
            except (ValueError, TypeError):
                continue
    return None


def _render_narrative(md_text, *, latest_source_date: str | None = None):
    if not md_text:
        return f"<p style='color:{MUTED};margin:0;'>(no narrative available)</p>"
    # The model is asked to title its memo "Investment Narrative", but the HTML
    # section header already labels the block — strip the redundant inline
    # heading whether it appears as `# Investment Narrative` or `**Investment
    # Narrative**`.
    md_text = _NARRATIVE_TITLE_RE.sub("", md_text, count=1)
    rendered = _MD.render(md_text)
    rendered = inline_styles(rendered)
    date_line = ""
    if latest_source_date:
        date_line = (
            f"<div style='font-size:11px;color:{MUTED};font-family:Helvetica,Arial,sans-serif;"
            f"letter-spacing:1px;margin-bottom:12px;'>"
            f"Most recent source: {html.escape(latest_source_date)}</div>"
        )
    return (
        f"<div style='font-size:14px;line-height:1.65;color:{TEXT};font-family:Georgia,serif;'>"
        f"{date_line}{rendered}</div>"
    )


def _next_ticker_nav(next_ticker: dict) -> str:
    """Bottom-right navigation pill linking to the next ticker in the same
    industry. Email-safe styling (no flexbox / grid) — uses a right-aligned
    table cell so it renders consistently in Gmail / Outlook / browsers."""
    ticker = html.escape(next_ticker.get("ticker", ""))
    name = next_ticker.get("name") or ""
    label = ticker
    if name:
        # Trim long names so the pill stays compact.
        short = name if len(name) <= 28 else name[:25].rstrip() + "…"
        label = f"{ticker} &middot; {html.escape(short)}"
    href = html.escape(next_ticker.get("href", ""))
    return (
        f"<tr><td class='sec-pad' style='padding:8px 28px 18px;' align='right'>"
        f"<a href='{href}' "
        f"style='display:inline-block;padding:8px 16px;background:{NAVY};color:#ffffff;"
        f"text-decoration:none;font-family:Helvetica,Arial,sans-serif;font-size:13px;"
        f"font-weight:bold;letter-spacing:0.5px;border-radius:3px;'>"
        f"Next: {label} →</a>"
        f"</td></tr>"
    )


