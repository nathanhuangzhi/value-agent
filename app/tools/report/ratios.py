"""Pure math helpers — TTM sums, period lookups, valuation-history
reconstruction. No I/O, no matplotlib, no HTML. Drop-in unit-testable."""

from __future__ import annotations

from app.tools.report.format import _pick_first


def _strict_ttm_sum(quarterly, value_keys):
    """Sum the last 4 quarters' values. Returns None unless ALL 4 have a
    non-None value (strict — no scaling, no partial sums)."""
    if not quarterly or len(quarterly) < 4:
        return None
    total = 0.0
    for q in quarterly[-4:]:
        v = _pick_first(q.get("items") or {}, value_keys)
        if v is None:
            return None
        total += v
    return total


def _latest_value(quarterly, value_keys):
    """Most recent quarter where any of the keys has a non-None value."""
    for q in reversed(quarterly or []):
        v = _pick_first(q.get("items") or {}, value_keys)
        if v is not None:
            return v
    return None


def _latest_close(price_history):
    for p in reversed(price_history or []):
        c = p.get("close")
        if c is not None:
            return c
    return None


def _recomputed_mcap(price_history, inc_quarterly):
    """Most recent monthly close × most recently reported diluted shares.
    Matches the market cap derivation used by the monthly valuation chart."""
    price = _latest_close(price_history)
    shares = _latest_value(inc_quarterly, ["Diluted Average Shares", "Basic Average Shares"])
    if price is None or shares is None:
        return None
    return price * shares


_ASSET_CANDIDATE_KEYS = [
    "Goodwill",
    "Other Intangible Assets",
    "Goodwill And Other Intangible Assets",
    "Net PPE",
    "Property Plant And Equipment Net",
    "Property Plant And Equipment Gross",
    "Gross PPE",
    "Inventory",
    "Receivables",
    "Accounts Receivable",
    "Other Short Term Investments",
    "Available For Sale Securities",
    "Long Term Investments",
    "Other Investments",
    "Investments And Advances",
    "Other Non Current Assets",
    "Other Assets",
]


_ASSET_KEY_CATEGORY = {
    "Goodwill": "goodwill",
    "Other Intangible Assets": "intangibles",
    "Goodwill And Other Intangible Assets": "intangibles",
    "Net PPE": "ppe",
    "Property Plant And Equipment Net": "ppe",
    "Property Plant And Equipment Gross": "ppe",
    "Gross PPE": "ppe",
    "Inventory": "inventory",
    "Receivables": "receivables",
    "Accounts Receivable": "receivables",
    "Other Short Term Investments": "investments",
    "Available For Sale Securities": "investments",
    "Long Term Investments": "investments",
    "Other Investments": "investments",
    "Investments And Advances": "investments",
    "Other Non Current Assets": "other_assets",
    "Other Assets": "other_assets",
}


def _top_asset_keys(bs_annual, bs_quarterly, top_n=2):
    """Find the top-N largest non-cash asset line items by value from the most
    recently reported balance sheet (quarterly preferred over annual). Returns
    a list of yfinance line-item names sorted by value descending.

    Near-aliases (e.g. "Net PPE" and "Property Plant And Equipment Net", or
    "Goodwill" and "Goodwill And Other Intangible Assets") are deduplicated
    by mapping each candidate to a category and keeping only the
    first-encountered key per category."""
    sorted_q = sorted([p for p in (bs_quarterly or []) if p.get("period")], key=lambda p: p["period"], reverse=True)
    sorted_a = sorted([p for p in (bs_annual or []) if p.get("period")], key=lambda p: p["period"], reverse=True)
    latest_items = {}
    for p in sorted_q + sorted_a:
        items = p.get("items") or {}
        if any(items.get(k) is not None for k in _ASSET_CANDIDATE_KEYS):
            latest_items = items
            break
    if not latest_items:
        return []
    scored = []
    seen_categories = set()
    for key in _ASSET_CANDIDATE_KEYS:
        v = latest_items.get(key)
        if v is None or v <= 0:
            continue
        category = _ASSET_KEY_CATEGORY.get(key, key)
        if category in seen_categories:
            continue
        scored.append((key, v))
        seen_categories.add(category)
    scored.sort(key=lambda x: x[1], reverse=True)
    return [k for k, _ in scored[:top_n]]


def _prior_year_label(label):
    """For YoY comparison: 'FY2025' → 'FY2024'; '2026 Q1' → '2025 Q1'."""
    if label.startswith("FY"):
        try:
            return f"FY{int(label[2:6]) - 1}"
        except ValueError:
            return None
    parts = label.split(" ", 1)
    if len(parts) == 2 and parts[0].isdigit():
        return f"{int(parts[0]) - 1} {parts[1]}"
    return None


def _yoy_cell_style(new_v, old_v):
    """Inline style fragment for YoY highlighting. Green tint when relative
    change ≥ +20%, red tint when ≤ −20%, empty otherwise. Uses (new-old)/|old|
    so it works regardless of sign."""
    if new_v is None or old_v is None or old_v == 0:
        return ""
    change = (new_v - old_v) / abs(old_v)
    if change >= 0.20:
        return "background:#e0efe0;"
    if change <= -0.20:
        return "background:#f6e0d8;"
    return ""


def _other_opex_amount(gp, op_inc, rd, sm, ga, sga):
    """Other operating expense $ amount = (Gross Profit − Operating Income) −
    R&D − SG&A. Uses combined SG&A when populated, otherwise sums the S&M +
    G&A breakout. R&D is treated as 0 if not reported. Returns None when GP
    or Operating Income isn't available, or when neither SG&A combined nor
    the S&M+G&A breakout is populated."""
    if gp is None or op_inc is None:
        return None
    total_opex = gp - op_inc
    rd_v = rd if rd is not None else 0
    if sga is not None:
        ssga = sga
    elif sm is not None and ga is not None:
        ssga = sm + ga
    else:
        return None
    return total_opex - rd_v - ssga


def _ttm_dividend_per_share(cf_quarterly, latest_shares):
    """Annual dividend rate per share from the cash-flow statement: sum of the
    last 4 quarters' "Cash Dividends Paid" (or equivalent), divided by the
    most recently reported diluted share count. Returns 0.0 for non-payers
    (no dividend lines in cash flow), or None if shares aren't available."""
    if latest_shares is None or latest_shares == 0:
        return None
    keys = ["Cash Dividends Paid", "Common Stock Dividend Paid", "Cash Dividends Paid Common"]
    if not cf_quarterly:
        return 0.0
    total = 0.0
    found_any = False
    for q in cf_quarterly[-4:]:
        v = _pick_first(q.get("items") or {}, keys)
        if v is not None:
            total += abs(v)
            found_any = True
    if not found_any:
        return 0.0
    return total / latest_shares


def _compute_valuation_history_monthly(inc_q, bs_q, inc_annual, bs_annual, price_history):
    """For each monthly price point, compute Static P/E, Static P/S, and P/B.
    Static ratios use the most recently reported annual income statement
    (period_end ≤ current month). P/B uses the most recently reported book
    value (quarterly preferred, annual fallback). Market cap = monthly close
    × most recently reported diluted shares (quarterly preferred, annual
    fallback). Returns list of {date, static_pe, static_ps, pb} dicts."""
    if not price_history:
        return []

    inc_q_sorted = sorted([q for q in (inc_q or []) if q.get("period")], key=lambda q: q["period"])
    bs_q_sorted = sorted([q for q in (bs_q or []) if q.get("period")], key=lambda q: q["period"])
    inc_a_sorted = sorted([q for q in (inc_annual or []) if q.get("period")], key=lambda q: q["period"])
    bs_a_sorted = sorted([q for q in (bs_annual or []) if q.get("period")], key=lambda q: q["period"])

    sorted_prices = sorted(
        [p for p in price_history if p.get("date") and p.get("close") is not None],
        key=lambda p: p["date"],
    )

    out = []
    for pt in sorted_prices:
        date = pt["date"]
        price = pt["close"]
        month = date[:7]

        annual_ni = _latest_value_at_or_before(inc_a_sorted, month, ["Net Income", "Net Income Common Stockholders"])
        annual_rev = _latest_value_at_or_before(inc_a_sorted, month, ["Total Revenue", "Operating Revenue"])

        shares = (
            _latest_value_at_or_before(inc_q_sorted, month, ["Diluted Average Shares", "Basic Average Shares"])
            or _latest_value_at_or_before(inc_a_sorted, month, ["Diluted Average Shares", "Basic Average Shares"])
        )
        if shares is None:
            continue
        mcap_m = shares * price

        bv = (
            _latest_value_at_or_before(bs_q_sorted, month, ["Common Stock Equity", "Stockholders Equity", "Total Equity Gross Minority Interest"])
            or _latest_value_at_or_before(bs_a_sorted, month, ["Common Stock Equity", "Stockholders Equity", "Total Equity Gross Minority Interest"])
        )

        static_pe = (mcap_m / annual_ni) if (annual_ni is not None and annual_ni != 0) else None
        static_ps = (mcap_m / annual_rev) if (annual_rev is not None and annual_rev != 0) else None
        pb = (mcap_m / bv) if (bv is not None and bv != 0) else None

        if static_pe is None and static_ps is None and pb is None:
            continue

        out.append({"date": date, "static_pe": static_pe, "static_ps": static_ps, "pb": pb})

    return out


def compute_snapshot_ratios(inc_quarterly, bs_quarterly, cf_quarterly, price_history,
                             inc_annual=None):
    """Compute the headline KPIs used by the per-ticker snapshot grid AND
    the industry-index table. Returns a dict with 15 fields — any field
    is None when inputs are missing or the denominator would be zero.

    Both the report snapshot and the industry table should call this so
    the two views never disagree on TTM math. The input shape is the
    same blended-periods list that `sec_to_yfinance_annual/quarterly`
    produces.

    `inc_annual` is optional — when supplied, also computes Static P/E
    (mcap / latest annual NI). When omitted, Static P/E is None.
    """
    # --- TTM rolling sums (strict: require all 4 quarters to have data) ---
    mcap = _recomputed_mcap(price_history, inc_quarterly)
    ttm_rev = _strict_ttm_sum(inc_quarterly, ["Total Revenue", "Operating Revenue"])
    ttm_gp = _strict_ttm_sum(inc_quarterly, ["Gross Profit"])
    ttm_op = _strict_ttm_sum(inc_quarterly, ["Operating Income",
                                              "Total Operating Income As Reported"])
    ttm_ni = _strict_ttm_sum(inc_quarterly, ["Net Income",
                                              "Net Income Common Stockholders"])
    ttm_ocf = _strict_ttm_sum(cf_quarterly, ["Cash Flow From Continuing Operating Activities",
                                              "Operating Cash Flow"])
    ttm_fcf = _strict_ttm_sum(cf_quarterly, ["Free Cash Flow"])

    # --- Point-in-time balance sheet items ---
    latest_bv = _latest_value(bs_quarterly, ["Common Stock Equity", "Stockholders Equity",
                                              "Total Equity Gross Minority Interest"])
    latest_cash = _latest_value(bs_quarterly, ["Cash And Cash Equivalents",
                                                "Cash Cash Equivalents And Short Term Investments"])
    latest_debt = _latest_value(bs_quarterly, ["Total Debt", "Long Term Debt"])
    latest_assets = _latest_value(bs_quarterly, ["Total Assets"])
    latest_shares = _latest_value(inc_quarterly, ["Diluted Average Shares",
                                                   "Basic Average Shares"])
    latest_annual_ni = _latest_value(inc_annual or [], ["Net Income",
                                                         "Net Income Common Stockholders"])

    dividend_rate = _ttm_dividend_per_share(cf_quarterly, latest_shares)

    # Enterprise Value: mcap + debt − cash. Cash defaults to 0 when missing
    # so we still get an EV for debt-only filers; debt is required because
    # without a debt number EV ≈ mcap (which we already have as a separate KPI).
    ev = (mcap + latest_debt - (latest_cash or 0)) if (mcap is not None and latest_debt is not None) else None

    def _div_safe(num, den):
        if num is None or den is None or den == 0:
            return None
        return num / den

    return {
        # mcap + 7 valuation multiples
        "market_cap":   mcap,
        "ttm_pe":       _div_safe(mcap, ttm_ni),
        "static_pe":    _div_safe(mcap, latest_annual_ni),
        "ev_revenue":   _div_safe(ev, ttm_rev),
        "pb":           _div_safe(mcap, latest_bv),
        "ps":           _div_safe(mcap, ttm_rev),
        "p_fcf":        _div_safe(mcap, ttm_fcf),
        "ttm_pocf":     _div_safe(mcap, ttm_ocf),
        # 6 health / profitability ratios (returned as decimals, not %)
        "debt_asset":   _div_safe(latest_debt, latest_assets),
        "gross_margin": _div_safe(ttm_gp, ttm_rev),
        "op_margin":    _div_safe(ttm_op, ttm_rev),
        "net_margin":   _div_safe(ttm_ni, ttm_rev),
        "roe":          _div_safe(ttm_ni, latest_bv),
        "roa":          _div_safe(ttm_ni, latest_assets),
        # income to shareholders
        "dividend_rate": dividend_rate,
    }


def _latest_value_at_or_before(sorted_periods, month_yyyy_mm, value_keys):
    """Most recent period in `sorted_periods` (already sorted ascending by
    period) whose period_end YYYY-MM is at or before `month_yyyy_mm` and that
    has a non-None value for one of the keys."""
    for p in reversed(sorted_periods):
        per = p.get("period") or ""
        if per[:7] > month_yyyy_mm:
            continue
        v = _pick_first(p.get("items") or {}, value_keys)
        if v is not None:
            return v
    return None
