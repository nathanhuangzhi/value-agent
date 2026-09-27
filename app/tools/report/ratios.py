"""Pure math helpers — TTM sums, period lookups, valuation-history
reconstruction. No I/O, no matplotlib, no HTML. Drop-in unit-testable."""

from __future__ import annotations

from typing import Any

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


SHARE_KEYS = ["Diluted Average Shares", "Basic Average Shares"]
_SHARE_WINDOW = 6        # quarters of share counts to judge against
_SHARE_TOLERANCE = 2.0   # a usable count sits within this factor of their median
_ANCHOR_TOLERANCE = 3.0  # …or of the count implied by yfinance's own market cap


def implied_shares(market_cap, price_history, price_fx: float = 1.0):
    """Share count implied by an independently sourced market cap — yfinance's
    own `marketCap`, stored on the analyzed row at scan time — against the
    latest close. It is the anchor `reliable_shares` checks filed counts
    against, and it is the right concept for market cap: shares outstanding
    now, not a weighted average over a past quarter."""
    price = _latest_close(price_history)
    if not market_cap or not price:
        return None
    return market_cap / (price / (price_fx or 1.0))


def reliable_shares(periods, *, expected: float | None = None,
                    window: int = _SHARE_WINDOW, tolerance: float = _SHARE_TOLERANCE):
    """Share count to value the company on.

    The newest quarter's `WeightedAverageNumberOfDilutedShares…` fact is often
    not usable: 279 of 1,251 companies file one that contradicts the quarters
    around it by more than 2x, and some series alternate between two scales
    entirely (NPK's SEC facts read 7,137 where yfinance has 7,137,000 for the
    same quarter). Taking the latest value on trust put market cap — and every
    P/E, P/B, P/S and P/FCF with it — out by orders of magnitude.

    `expected` is an independent anchor: the share count implied by yfinance's
    own market cap. When it is given, the newest filed count within 3x of it
    wins and the anchor itself is the fallback — i.e. where our filings-derived
    count disagrees with the market's by an order of magnitude, the market
    decides. Without an anchor, the newest count within `tolerance` of the
    recent median is used."""
    vals = [v for p in (periods or []) if (v := _pick_first(p.get("items") or {}, SHARE_KEYS))]
    if not vals and expected:
        return expected
    if not vals:
        return None
    recent = vals[-window:]
    if expected:
        near = [v for v in reversed(recent) if expected / _ANCHOR_TOLERANCE <= v <= expected * _ANCHOR_TOLERANCE]
        return near[0] if near else expected
    med = _median(recent)
    if not med:
        return next((v for v in reversed(recent) if v), None)
    for v in reversed(recent):
        if med / tolerance <= v <= med * tolerance:
            return v
    return med


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def to_usd_prices(price_history, price_fx: float = 1.0):
    """Price history with every close divided by `price_fx` (the quote
    currency's per-USD rate — see `app.tools.fx.quote_fx`).

    Blended statements are already USD by the time they reach this module,
    but `price_history` is in the currency the stock trades in. Every
    price-derived number here (market cap, the P/E family, the quarterly
    multiples, the valuation history) would be off by the FX factor for a
    CNY-quoted A-share, so callers convert the series ONCE at the boundary
    and pass the converted list to every function below. Returns the input
    object itself when there is nothing to convert."""
    if not price_history or not price_fx or price_fx == 1.0:
        return price_history
    return [
        {**p, "close": (None if p.get("close") is None else p["close"] / price_fx)}
        for p in price_history
    ]


def _latest_close(price_history):
    for p in reversed(price_history or []):
        c = p.get("close")
        if c is not None:
            return c
    return None


def _recomputed_mcap(price_history, inc_quarterly, expected_shares: float | None = None):
    """Most recent monthly close × most recently reported diluted shares.
    Matches the market cap derivation used by the monthly valuation chart."""
    price = _latest_close(price_history)
    shares = reliable_shares(inc_quarterly, expected=expected_shares)
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


def _top_asset_keys(bs_annual, bs_quarterly, top_n=None):
    """Find the largest non-cash asset line items by value (all of them when
    `top_n` is None — the balance-sheet section lists every asset class
    present, largest first) from the most
    recently reported balance sheet (quarterly preferred over annual). Returns
    a list of yfinance line-item names sorted by value descending.

    Near-aliases (e.g. "Net PPE" and "Property Plant And Equipment Net", or
    "Goodwill" and "Goodwill And Other Intangible Assets") are deduplicated
    by mapping each candidate to a category and keeping only the
    first-encountered key per category."""
    sorted_q = sorted([p for p in (bs_quarterly or []) if p.get("period")], key=lambda p: p["period"], reverse=True)
    sorted_a = sorted([p for p in (bs_annual or []) if p.get("period")], key=lambda p: p["period"], reverse=True)
    latest_items: dict[str, Any] = {}
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
    return [k for k, _ in (scored[:top_n] if top_n else scored)]


# Liability line items the balance-sheet section may surface, largest
# first. Labels are the adapter's item names (SEC_TO_YFINANCE_BALANCE).
_LIABILITY_CANDIDATE_KEYS = [
    "Long Term Debt",
    "Current Debt",
    "Accounts Payable",
    "Accrued Liabilities",
    "Deferred Revenue",
    "Lease Obligations",
]


def _top_liability_keys(bs_annual, bs_quarterly, top_n=3):
    """Top-N largest liability line items from the most recent balance
    sheet (quarterly preferred), by value descending. Counterpart of
    `_top_asset_keys`; no alias dedup needed since each candidate is one
    adapter item."""
    sorted_q = sorted([p for p in (bs_quarterly or []) if p.get("period")], key=lambda p: p["period"], reverse=True)
    sorted_a = sorted([p for p in (bs_annual or []) if p.get("period")], key=lambda p: p["period"], reverse=True)
    for p in sorted_q + sorted_a:
        items = p.get("items") or {}
        scored = [(k, items[k]) for k in _LIABILITY_CANDIDATE_KEYS
                  if items.get(k) is not None and items[k] > 0]
        if scored:
            scored.sort(key=lambda x: x[1], reverse=True)
            return [k for k, _ in scored[:top_n]]
    return []


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


def _compute_valuation_history_monthly(inc_q, bs_q, inc_annual, bs_annual, price_history,
                                       expected_shares: float | None = None):
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

    baseline_shares = (reliable_shares(inc_q_sorted, expected=expected_shares)
                       or reliable_shares(inc_a_sorted, expected=expected_shares))
    out = []
    for pt in sorted_prices:
        date = pt["date"]
        price = pt["close"]
        month = date[:7]

        annual_ni = _latest_value_at_or_before(inc_a_sorted, month, ["Net Income", "Net Income Common Stockholders"])
        annual_rev = _latest_value_at_or_before(inc_a_sorted, month, ["Total Revenue", "Operating Revenue"])

        shares = (
            _latest_value_at_or_before(inc_q_sorted, month, SHARE_KEYS)
            or _latest_value_at_or_before(inc_a_sorted, month, SHARE_KEYS)
        )
        # An outlier count would spike that month's multiples; fall back to the
        # count the rest of the series agrees on (see reliable_shares).
        if shares and baseline_shares and not (
                baseline_shares / _SHARE_TOLERANCE <= shares <= baseline_shares * _SHARE_TOLERANCE):
            shares = baseline_shares
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
                             inc_annual=None, expected_shares: float | None = None):
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
    mcap = _recomputed_mcap(price_history, inc_quarterly, expected_shares)
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
    # Cash for EV = cash & equivalents + short-term investments (the
    # combined item the adapter derives), falling back to cash alone.
    latest_cash = _latest_value(bs_quarterly, ["Cash Cash Equivalents And Short Term Investments",
                                                "Cash And Cash Equivalents"])
    latest_debt = _latest_value(bs_quarterly, ["Total Debt", "Long Term Debt"])
    latest_assets = _latest_value(bs_quarterly, ["Total Assets"])
    latest_shares = reliable_shares(inc_quarterly, expected=expected_shares)
    latest_annual_ni = _latest_value(inc_annual or [], ["Net Income",
                                                         "Net Income Common Stockholders"])

    dividend_rate = _ttm_dividend_per_share(cf_quarterly, latest_shares)

    # Enterprise Value: mcap + debt − (cash + ST investments). Cash defaults to 0 when missing
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


def _close_at_or_before(price_history, period_end: str):
    """Last monthly close on or before the quarter's end month."""
    month = (period_end or "")[:7]
    best = None
    for p in price_history or []:
        d = (p.get("date") or "")[:7]
        if d and d <= month and p.get("close") is not None:
            best = p["close"]
    return best


def _annualised(mcap, quarterly_den):
    if mcap is None or quarterly_den is None or quarterly_den == 0:
        return None
    return mcap / (quarterly_den * 4)


def quarterly_multiples(inc_quarterly, cf_quarterly, price_history, *, n: int = 4,
                        expected_shares: float | None = None) -> list[dict]:
    """Per-quarter valuation multiples for the last `n` quarters, ANNUALISED so
    they sit on the same scale as the TTM figures:

        pqe   = mcap at quarter end / (quarterly net income × 4)
        pqfcf = mcap at quarter end / (quarterly free cash flow × 4)

    mcap at quarter end = last monthly close on or before the quarter's end
    month × that quarter's diluted shares (latest known shares if the
    quarter lacks them). A negative quarter yields a negative multiple —
    the app draws it as a red bar. None when price, shares or the
    denominator is missing/zero."""
    ni_keys = ["Net Income", "Net Income Common Stockholders"]
    sh_keys = SHARE_KEYS
    baseline = reliable_shares(inc_quarterly, expected=expected_shares)
    cf_by_period = {p.get("period"): p for p in cf_quarterly or []}
    out = []
    for q in (inc_quarterly or [])[-n:]:
        period = q.get("period") or ""
        items = q.get("items") or {}
        own = _pick_first(items, sh_keys)
        # Ignore this quarter's own count when it contradicts the others.
        if own and baseline and not (baseline / _SHARE_TOLERANCE <= own <= baseline * _SHARE_TOLERANCE):
            own = None
        shares = own or baseline
        price = _close_at_or_before(price_history, period)
        mcap = price * shares if (price is not None and shares) else None
        ni = _pick_first(items, ni_keys)
        fcf = _pick_first((cf_by_period.get(period) or {}).get("items") or {}, ["Free Cash Flow"])

        out.append({"period": period, "pqe": _annualised(mcap, ni), "pqfcf": _annualised(mcap, fcf)})
    return out


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
