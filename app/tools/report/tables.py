"""HTML rendering for the combined annual + quarterly historical-data
table, plus the column-extraction helper."""

from __future__ import annotations

from app.tools.report.format import (
    NAVY, RULE, TEXT, MUTED, AMBER,
    _pick_first, _div, _fmt_pct, _fy_label, _quarter_label,
)
from app.tools.report.ratios import (
    _latest_value_at_or_before,
    _other_opex_amount,
    _prior_year_label,
    _top_asset_keys,
    _yoy_cell_style,
)


def _pick_first_with_source(items: dict, sources: dict, labels):
    """Like `_pick_first` but also returns the source tag for the chosen
    label ("sec" / "yfinance" / "derived"). Returns (value, source) where
    source is None when no label resolved."""
    for k in labels:
        v = items.get(k)
        if v is not None:
            return v, (sources or {}).get(k)
    return None, None


def _collect_table_columns(inc_periods, bs_periods, cf_periods, label_fn,
                           price_history=None, fallback_inc=None, fallback_bs=None,
                           static_annual_inc=None, extra_bs_keys=None):
    """Build a list of column dicts for the historical-data table, one per
    period that has at least one populated metric. When `price_history` is
    supplied, also computes Static P/E, Static P/S, and P/B per period using
    end-of-period monthly close × diluted shares as the market cap.

    Each column also carries a parallel `sources` map for the row keys that
    map directly to an items entry (raw $-value rows). The renderer uses
    this to mark cells whose value originated in yfinance rather than SEC.

    `static_annual_inc`: when supplied, Static P/E and Static P/S use the
    most recent ANNUAL NI / Revenue as the denominator (period_end ≤ this
    column's period). This keeps the metric semantically "static" (annual
    base) regardless of whether the column itself is annual or quarterly —
    quarterly columns just get a different point-in-time market cap.

    `fallback_inc` / `fallback_bs` (typically the quarterly statements)
    supply diluted shares / book value when a given period doesn't have
    those fields directly populated."""
    cf_by = {p.get("period"): (p.get("items") or {}) for p in (cf_periods or [])}
    bs_by = {p.get("period"): (p.get("items") or {}) for p in (bs_periods or [])}
    cf_src_by = {p.get("period"): (p.get("sources") or {}) for p in (cf_periods or [])}
    bs_src_by = {p.get("period"): (p.get("sources") or {}) for p in (bs_periods or [])}
    price_by_month = {}
    for p in (price_history or []):
        d = p.get("date")
        c = p.get("close")
        if d and c is not None:
            price_by_month[d[:7]] = c
    fallback_inc_sorted = sorted(
        [q for q in (fallback_inc or []) if q.get("period")], key=lambda q: q["period"]
    )
    fallback_bs_sorted = sorted(
        [q for q in (fallback_bs or []) if q.get("period")], key=lambda q: q["period"]
    )
    static_annual_sorted = sorted(
        [q for q in (static_annual_inc or []) if q.get("period")], key=lambda q: q["period"]
    )
    cols = []
    for q in (inc_periods or []):
        period = q.get("period")
        if not period:
            continue
        items = q.get("items") or {}
        item_src = q.get("sources") or {}
        cf_items = cf_by.get(period, {})
        bs_items = bs_by.get(period, {})
        cf_src = cf_src_by.get(period, {})
        bs_src = bs_src_by.get(period, {})
        rev, rev_src = _pick_first_with_source(items, item_src, ["Total Revenue", "Operating Revenue"])
        gp, gp_src = _pick_first_with_source(items, item_src, ["Gross Profit"])
        op, op_src = _pick_first_with_source(items, item_src, ["Operating Income", "Total Operating Income As Reported"])
        ni, ni_src = _pick_first_with_source(items, item_src, ["Net Income", "Net Income Common Stockholders"])
        eps, eps_src = _pick_first_with_source(items, item_src, ["Diluted EPS", "Basic EPS"])
        shares, shares_src = _pick_first_with_source(items, item_src, ["Diluted Average Shares", "Basic Average Shares"])
        ocf, ocf_src = _pick_first_with_source(cf_items, cf_src, ["Cash Flow From Continuing Operating Activities", "Operating Cash Flow"])
        fcf, fcf_src = _pick_first_with_source(cf_items, cf_src, ["Free Cash Flow"])
        capex_raw, capex_src = _pick_first_with_source(cf_items, cf_src, ["Capital Expenditure"])
        capex = abs(capex_raw) if capex_raw is not None else None
        cash, cash_src = _pick_first_with_source(bs_items, bs_src, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"])
        debt, debt_src = _pick_first_with_source(bs_items, bs_src, ["Total Debt", "Long Term Debt"])
        assets, assets_src = _pick_first_with_source(bs_items, bs_src, ["Total Assets"])
        rd = _pick_first(items, ["Research And Development"])
        sm = _pick_first(items, ["Selling And Marketing Expense"])
        ga = _pick_first(items, ["General And Administrative Expense"])
        sga = _pick_first(items, ["Selling General And Administration"])
        other = _other_opex_amount(gp, op, rd, sm, ga, sga)
        if all(v is None for v in (rev, gp, op, ni, eps, shares, ocf, fcf, capex, cash, debt, assets)):
            continue

        shares_for_mcap = shares
        if shares_for_mcap is None and fallback_inc_sorted:
            shares_for_mcap = _latest_value_at_or_before(
                fallback_inc_sorted, period[:7],
                ["Diluted Average Shares", "Basic Average Shares"],
            )
        bv = _pick_first(bs_items, ["Common Stock Equity", "Stockholders Equity", "Total Equity Gross Minority Interest"])
        if bv is None and fallback_bs_sorted:
            bv = _latest_value_at_or_before(
                fallback_bs_sorted, period[:7],
                ["Common Stock Equity", "Stockholders Equity", "Total Equity Gross Minority Interest"],
            )
        price = price_by_month.get(period[:7])
        mcap = (shares_for_mcap * price) if (shares_for_mcap is not None and price is not None) else None

        if static_annual_sorted:
            static_ni = _latest_value_at_or_before(
                static_annual_sorted, period[:7],
                ["Net Income", "Net Income Common Stockholders"],
            )
            static_rev = _latest_value_at_or_before(
                static_annual_sorted, period[:7],
                ["Total Revenue", "Operating Revenue"],
            )
        else:
            static_ni, static_rev = ni, rev

        col = {
            "label": label_fn(q),
            "rev": rev, "gp": gp, "op": op, "ni": ni, "eps": eps, "shares": shares,
            "sps": _div(rev, shares_for_mcap),
            "bvps": _div(bv, shares_for_mcap),
            "ocf": ocf, "fcf": fcf, "capex": capex,
            "cash": cash, "debt": debt, "assets": assets,
            "gm": _div(gp, rev), "om": _div(op, rev), "nm": _div(ni, rev),
            "rd_r": _div(rd, rev), "sm_r": _div(sm, rev), "ga_r": _div(ga, rev), "sga_r": _div(sga, rev),
            "other_r": _div(other, rev),
            "static_pe": _div(mcap, static_ni),
            "static_ps": _div(mcap, static_rev),
            "pb": _div(mcap, bv),
            # Per-cell source tags for the raw $-value rows. The renderer
            # consults this to mark yfinance-sourced cells. Derived ratios
            # (margins, ratios) are not source-tagged — the user can infer
            # provenance from the raw rows that feed them.
            "sources": {
                "rev": rev_src, "gp": gp_src, "op": op_src, "ni": ni_src,
                "eps": eps_src, "shares": shares_src,
                "ocf": ocf_src, "fcf": fcf_src, "capex": capex_src,
                "cash": cash_src, "debt": debt_src, "assets": assets_src,
            },
        }
        for key in (extra_bs_keys or []):
            col[key] = bs_items.get(key)
            col["sources"][key] = bs_src.get(key)
        cols.append(col)
    return cols


_TABLE_ANNUAL_COLS = 10
_TABLE_QUARTERLY_COLS = 5


def _empty_col(extra_keys):
    """Placeholder column used to pad the table to a fixed width. All
    metric keys are present but None so the row formatter renders an
    empty dash for each cell."""
    metric_keys = (
        "rev", "gp", "op", "ni", "eps", "shares", "sps", "bvps",
        "ocf", "fcf", "capex", "cash", "debt", "assets",
        "gm", "om", "nm",
        "rd_r", "sm_r", "ga_r", "sga_r", "other_r",
        "static_pe", "static_ps", "pb",
    )
    col = {"label": "", "sources": {}}
    for k in metric_keys:
        col[k] = None
    for k in (extra_keys or []):
        col[k] = None
    return col


def _slice_and_pad(cols, target, extra_keys):
    """Cap to the most-recent `target` columns; left-pad with empty
    placeholders when fewer are available."""
    cols = cols[-target:]
    pad = target - len(cols)
    if pad > 0:
        cols = [_empty_col(extra_keys) for _ in range(pad)] + cols
    return cols


def _render_combined_data_table(inc_annual, bs_annual, cf_annual,
                                inc_quarterly, bs_quarterly, cf_quarterly,
                                price_history=None):
    """One table with annual columns first (FY22, FY23, ...), a vertical
    divider, then quarterly columns (2025 Q1, ...). Same metric rows down
    the side. A group header row labels the two column blocks.

    Annual is always exactly 10 columns and quarterly always exactly 5;
    missing periods on the left render as empty unlabeled cells. The
    valuation chart upstream still sees the full history — this fixed
    width is a table-presentation concern only."""
    top_asset_keys = _top_asset_keys(bs_annual, bs_quarterly, top_n=2)
    annual_cols = _collect_table_columns(
        inc_annual, bs_annual, cf_annual, _fy_label,
        price_history=price_history,
        fallback_inc=inc_quarterly,
        fallback_bs=bs_quarterly,
        static_annual_inc=inc_annual,
        extra_bs_keys=top_asset_keys,
    )
    quarterly_cols = _collect_table_columns(
        inc_quarterly, bs_quarterly, cf_quarterly, _quarter_label,
        price_history=price_history,
        static_annual_inc=inc_annual,
        extra_bs_keys=top_asset_keys,
    )
    annual_cols = _slice_and_pad(annual_cols, _TABLE_ANNUAL_COLS, top_asset_keys)
    quarterly_cols = _slice_and_pad(quarterly_cols, _TABLE_QUARTERLY_COLS, top_asset_keys)
    cols = annual_cols + quarterly_cols
    if not cols or all(c["label"] == "" for c in cols):
        return ""
    n_a = len(annual_cols)
    n_q = len(quarterly_cols)
    n_cols = len(cols)
    divider_idx = n_a  # quarterly section starts at this column index

    sm_count = sum(1 for c in cols if c.get("sm_r") is not None)
    ga_count = sum(1 for c in cols if c.get("ga_r") is not None)
    opex_breakout = sm_count >= 2 and ga_count >= 2

    # Conditional decimals: any displayed value with magnitude < 10 gets one
    # decimal place; anything ≥ 10 stays integer. Applied AFTER the unit
    # scaling (M, %, x) so the threshold compares the on-screen number, not
    # the raw underlying value.
    def _fmt(scaled, suffix="", prefix=""):
        if scaled is None:
            return "—"
        decs = 1 if abs(scaled) < 10 else 0
        return f"{prefix}{scaled:,.{decs}f}{suffix}"

    money_m = lambda v: _fmt(v / 1e6) if v is not None else "—"
    per_share = lambda v: _fmt(v, prefix="$") if v is not None else "—"
    shares_m = lambda v: _fmt(v / 1e6) if v is not None else "—"
    pct_str = lambda v: _fmt(v * 100, suffix="%") if v is not None else "—"
    ratio_str = lambda v: _fmt(v, suffix="x") if v is not None else "—"

    rows = [
        ("group", "Income Statement ($M)"),
        ("Revenue", "rev", money_m),
        ("Gross Profit", "gp", money_m),
        ("Operating Income", "op", money_m),
        ("Net Income", "ni", money_m),
        ("group", "Profitability Margins"),
        ("Gross Margin", "gm", pct_str),
        ("Operating Margin", "om", pct_str),
        ("Net Margin", "nm", pct_str),
        ("group", "Operating Expense Ratios (% of revenue)"),
        *(
            [
                ("Selling & Marketing / Revenue", "sm_r", pct_str),
                ("Administrative / Revenue", "ga_r", pct_str),
            ]
            if opex_breakout
            else [("SG&A / Revenue", "sga_r", pct_str)]
        ),
        ("R&D / Revenue", "rd_r", pct_str),
        ("Other Opex / Revenue", "other_r", pct_str),
        ("group", "Balance Sheet ($M)"),
        ("Total Assets", "assets", money_m),
        ("Cash & Equivalents", "cash", money_m),
        *[(key, key, money_m) for key in top_asset_keys],
        ("Total Debt", "debt", money_m),
        ("group", "Cash Flow ($M)"),
        ("Operating CF", "ocf", money_m),
        ("Capex", "capex", money_m),
        ("Free CF", "fcf", money_m),
        ("group", "Per-Share Metrics"),
        ("Diluted Shares (M)", "shares", shares_m),
        ("Diluted EPS", "eps", per_share),
        ("Sales Per Share", "sps", per_share),
        ("Book Value Per Share", "bvps", per_share),
        ("group", "Valuation Multiples"),
        ("Static P/E", "static_pe", ratio_str),
        ("Static P/S", "static_ps", ratio_str),
        ("P/B", "pb", ratio_str),
    ]

    # Header row 1: ANNUAL (colspan=n_a) | QUARTERLY (colspan=n_q)
    superheader = f"<tr><td style='border-bottom:1px solid {RULE};'></td>"
    if n_a > 0:
        superheader += (
            f"<th colspan='{n_a}' align='center' "
            f"style='padding:7px 6px;font-size:11px;color:{NAVY};letter-spacing:2px;"
            f"font-family:Helvetica,Arial,sans-serif;background:#f4ede0;border-bottom:1px solid {RULE};'>"
            f"ANNUAL</th>"
        )
    if n_q > 0:
        bl = f"border-left:2px solid {RULE};" if n_a > 0 else ""
        superheader += (
            f"<th colspan='{n_q}' align='center' "
            f"style='padding:7px 6px;font-size:11px;color:{NAVY};letter-spacing:2px;"
            f"font-family:Helvetica,Arial,sans-serif;background:#eef2f7;border-bottom:1px solid {RULE};{bl}'>"
            f"QUARTERLY</th>"
        )
    superheader += "</tr>"

    # Header row 2: METRIC | period labels
    head = (
        f"<tr><th align='left' style='padding:7px 10px;font-size:11px;color:{MUTED};letter-spacing:1px;"
        f"border-bottom:2px solid {RULE};font-family:Helvetica,Arial,sans-serif;'>METRIC</th>"
    )
    for i, c in enumerate(cols):
        bl = f"border-left:2px solid {RULE};" if i == divider_idx else ""
        head += (
            f"<th align='right' style='padding:7px 8px;font-size:11px;color:{MUTED};letter-spacing:1px;"
            f"border-bottom:2px solid {RULE};font-family:Helvetica,Arial,sans-serif;{bl}'>{c['label']}</th>"
        )
    head += "</tr>"

    col_by_label = {c["label"]: c for c in cols}

    # Track whether any cell came from yfinance so we know whether to
    # render the legend below the table.
    any_yfinance_cell = False
    yf_marker_html = (
        f"<sup style='color:{AMBER};font-size:9px;font-weight:bold;"
        f"margin-left:2px;font-family:Helvetica,Arial,sans-serif;'>y</sup>"
    )

    body = []
    for row in rows:
        if row[0] == "group":
            body.append(
                f"<tr><td colspan='{n_cols + 1}' style='padding:9px 10px 4px;"
                f"font-size:11px;color:{NAVY};font-family:Helvetica,Arial,sans-serif;"
                f"font-weight:bold;letter-spacing:1px;border-bottom:1px solid {RULE};"
                f"background:#fafaf2;'>{row[1].upper()}</td></tr>"
            )
            continue
        label, key, fmt = row
        cells = [
            f"<td style='padding:6px 10px;font-size:13px;color:{TEXT};border-bottom:1px solid {RULE};'>{label}</td>"
        ]
        for i, c in enumerate(cols):
            bl = f"border-left:2px solid {RULE};" if i == divider_idx else ""
            prev = col_by_label.get(_prior_year_label(c["label"]))
            yoy = _yoy_cell_style(c[key], prev[key] if prev else None)
            src = (c.get("sources") or {}).get(key)
            value_str = fmt(c[key])
            marker = ""
            if c[key] is not None and src == "yfinance":
                marker = yf_marker_html
                any_yfinance_cell = True
            cells.append(
                f"<td align='right' style='padding:6px 8px;font-size:13px;color:{TEXT};"
                f"border-bottom:1px solid {RULE};font-family:Menlo,Consolas,monospace;{bl}{yoy}'>{value_str}{marker}</td>"
            )
        body.append("<tr>" + "".join(cells) + "</tr>")

    legend_html = ""
    if any_yfinance_cell:
        legend_html = (
            f"<tr><td colspan='{n_cols + 1}' style='padding:8px 10px 2px;"
            f"font-size:11px;color:{MUTED};font-family:Helvetica,Arial,sans-serif;'>"
            f"<sup style='color:{AMBER};font-weight:bold;'>y</sup> = value sourced from "
            f"yfinance (SEC EDGAR did not report this cell). SEC EDGAR is the "
            f"authoritative source where available."
            f"</td></tr>"
        )

    # Reserve ~50px per column (label + each period). When the parent has
    # overflow-x:auto on a narrow screen, this forces horizontal scrolling
    # rather than crushing the columns into illegibility.
    min_width = max(660, 130 + n_cols * 50)
    return (
        f"<table cellpadding='0' cellspacing='0' width='100%' "
        f"style='border-collapse:collapse;min-width:{min_width}px;'>"
        f"{superheader}{head}{''.join(body)}{legend_html}</table>"
    )
