"""Adapter: convert SEC EDGAR XBRL data into the yfinance-shape that the
existing report renderer expects, plus blend yfinance data as a gap-filler.

Two source files feed in:
- SEC EDGAR (`companies_sec.json`) — authoritative, deeper history.
- yfinance (`companies_yfinance.json`) — fills gaps where SEC has nothing.

Per-cell merge policy:
- If SEC has a value for that (metric, period), SEC wins.
- If SEC has no value but yfinance does, yfinance fills the cell.
- Every emitted period dict carries a parallel `sources` map:
  `{yfinance_label: "sec" | "yfinance" | "derived"}`. The renderer uses
  this to mark yfinance-sourced cells visibly.

Output shape (per statement, annual or quarterly):
    [
        {
            "period": "2024-12-31",
            "items":   {"Total Revenue": 12345.0, ...},
            "sources": {"Total Revenue": "sec",    ...},
        },
        ...
    ]
"""

from __future__ import annotations

# Map SEC metric keys → yfinance item labels. The label is what the
# renderer's _pick_first() looks up.
SEC_TO_YFINANCE_INCOME = {
    "revenue": "Total Revenue",
    "gross_profit": "Gross Profit",
    "cost_of_revenue": "Cost Of Revenue",
    "operating_income": "Operating Income",
    "net_income": "Net Income",
    "diluted_eps": "Diluted EPS",
    "diluted_shares": "Diluted Average Shares",
    "rd_expense": "Research And Development",
    "sga_expense": "Selling General And Administration",
    "selling_marketing_expense": "Selling And Marketing Expense",
    "general_admin_expense": "General And Administrative Expense",
}

SEC_TO_YFINANCE_CASHFLOW = {
    "operating_cf": "Cash Flow From Continuing Operating Activities",
    "capex": "Capital Expenditure",
}

SEC_TO_YFINANCE_BALANCE = {
    "cash": "Cash And Cash Equivalents",
    "total_assets": "Total Assets",
    "stockholders_equity": "Common Stock Equity",
    "goodwill": "Goodwill",
    "ppe_net": "Net PPE",
    "inventory": "Inventory",
    "receivables": "Accounts Receivable",
}


def _merge_period_dicts(sec_section: dict, yf_section: dict) -> tuple[dict, dict]:
    """Merge SEC and yfinance section dicts. Both are shaped like
    `{metric_key: {period_key: entry}}`. Returns a tuple
    `(merged_entries, source_map)` where:
    - merged_entries[metric_key][period_key] = the winning entry (SEC if
      both have a value; yfinance only when SEC has nothing for that cell)
    - source_map[metric_key][period_key] = "sec" or "yfinance"

    Keys present in either source carry through; the value chosen depends
    on the rule above. Used for both annual (year-key int) and quarterly
    (date-string key) sections — both share the same shape."""
    merged: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    metric_keys = set(sec_section or {}) | set(yf_section or {})
    for metric in metric_keys:
        sec_d = (sec_section or {}).get(metric, {}) or {}
        yf_d = (yf_section or {}).get(metric, {}) or {}
        period_keys = set(sec_d) | set(yf_d)
        m_entries = {}
        m_sources = {}
        for pk in period_keys:
            if pk in sec_d:
                m_entries[pk] = sec_d[pk]
                m_sources[pk] = "sec"
            else:
                m_entries[pk] = yf_d[pk]
                m_sources[pk] = "yfinance"
        if m_entries:
            merged[metric] = m_entries
            sources[metric] = m_sources
    return merged, sources


def _resolve_total_debt(by_key: dict, period_key, sources_by_key: dict | None = None):
    """Combine the LT noncurrent + ST current debt buckets without
    double-counting the legacy "ambiguous total" concept. Returns
    `(val, entry, source)`:
    - `val`: the computed Total Debt (0 if balance sheet was filed with no
      debt concept; None if no balance sheet at all)
    - `entry`: one of the underlying records (used for period_str fallback)
    - `source`: "sec" | "yfinance" | "derived" — propagated from
      `sources_by_key` if provided; otherwise "sec" by default."""
    sources_by_key = sources_by_key or {}
    lt = by_key.get("long_term_debt", {}).get(period_key)
    st = by_key.get("short_term_debt", {}).get(period_key)
    legacy = by_key.get("debt_total_legacy", {}).get(period_key)

    def _src(metric):
        return sources_by_key.get(metric, {}).get(period_key, "sec")

    if lt is not None or st is not None:
        val = (lt["val"] if lt else 0) + (st["val"] if st else 0)
        # If either side is yfinance, the combined value is from yfinance
        # (or "derived" since we summed). Mark as yfinance if any non-SEC
        # input.
        sources_used = [
            _src("long_term_debt") if lt is not None else None,
            _src("short_term_debt") if st is not None else None,
        ]
        src = "yfinance" if any(s == "yfinance" for s in sources_used) else "sec"
        return val, (lt or st), src
    if legacy is not None:
        return legacy["val"], legacy, _src("debt_total_legacy")
    assets = by_key.get("total_assets", {}).get(period_key)
    if assets is not None:
        # Defaulted-to-zero is "derived" — neither SEC nor yfinance
        # reported a debt value; we inferred zero because a balance sheet
        # was filed. Propagate the assets source (whichever filing said
        # this period had a balance sheet).
        return 0, assets, _src("total_assets")
    return None, None, None


def _build_period(period_key: str, mapping: dict, merged: dict, source_map: dict,
                  *, derived_total_debt: bool, derived_gross_profit: bool,
                  derived_fcf: bool, derived_zero_revenue: bool):
    """Build one period dict ({period, items, sources}) for a given
    period_key. Returns (period_dict, last_entry_with_end) or
    (None, None) if no items were populated."""
    items: dict = {}
    sources: dict = {}
    last_entry_with_end: dict | None = None
    for sec_key, yf_label in mapping.items():
        entry = merged.get(sec_key, {}).get(period_key)
        if entry is not None:
            items[yf_label] = entry["val"]
            sources[yf_label] = source_map.get(sec_key, {}).get(period_key, "sec")
            if entry.get("end"):
                last_entry_with_end = entry

    if derived_total_debt:
        val, entry, src = _resolve_total_debt(merged, period_key, source_map)
        if val is not None:
            items["Total Debt"] = val
            sources["Total Debt"] = src or "sec"
        if last_entry_with_end is None and isinstance(entry, dict) and entry.get("end"):
            last_entry_with_end = entry

    if derived_zero_revenue and items.get("Total Revenue") is None:
        oi = items.get("Operating Income")
        ni = items.get("Net Income")
        if oi is not None and ni is not None:
            items["Total Revenue"] = 0
            sources["Total Revenue"] = "derived"

    if derived_gross_profit and items.get("Gross Profit") is None:
        rev = items.get("Total Revenue")
        cor = items.get("Cost Of Revenue")
        if rev is not None and cor is not None:
            items["Gross Profit"] = rev - cor
            # Derived from rev & cor — mark as the lower-rank source of
            # the two inputs so the user sees the "weakest link".
            rev_src = sources.get("Total Revenue", "sec")
            cor_src = sources.get("Cost Of Revenue", "sec")
            sources["Gross Profit"] = "yfinance" if "yfinance" in (rev_src, cor_src) else "sec"

    if derived_fcf:
        ocf = items.get("Cash Flow From Continuing Operating Activities")
        ocf_src = sources.get("Cash Flow From Continuing Operating Activities", "sec")
        if items.get("Capital Expenditure") is None and ocf is not None:
            items["Capital Expenditure"] = 0
            sources["Capital Expenditure"] = "derived"
        if items.get("Free Cash Flow") is None:
            capex = items.get("Capital Expenditure")
            if ocf is not None and capex is not None:
                items["Free Cash Flow"] = ocf - abs(capex)
                capex_src = sources.get("Capital Expenditure", "sec")
                sources["Free Cash Flow"] = "yfinance" if "yfinance" in (ocf_src, capex_src) else "sec"

    if not items:
        return None, None
    return {"period": period_key, "items": items, "sources": sources}, last_entry_with_end


def _to_period_list(merged: dict, source_map: dict, mapping: dict,
                    *, period_keys=None, period_format=None, derived_total_debt=False,
                    derived_gross_profit=False, derived_fcf=False,
                    derived_zero_revenue=False):
    """Walk every period key present anywhere in `merged` (or restricted
    to `period_keys`) and build one period dict per key. `period_format`
    callable converts the dict key into the output `period` string; if
    None, the key is used as-is (after str())."""
    if period_keys is None:
        keys: set = set()
        for metric in (mapping):
            keys.update((merged.get(metric) or {}).keys())
        if derived_total_debt:
            for k in ("long_term_debt", "short_term_debt", "debt_total_legacy", "total_assets"):
                keys.update((merged.get(k) or {}).keys())
        period_keys = keys

    out = []
    for pk in sorted(period_keys):
        period_dict, last_entry = _build_period(
            pk, mapping, merged, source_map,
            derived_total_debt=derived_total_debt,
            derived_gross_profit=derived_gross_profit,
            derived_fcf=derived_fcf,
            derived_zero_revenue=derived_zero_revenue,
        )
        if period_dict is None:
            continue
        # Override period string with format-callable's result if given,
        # else fall back to entry-end-date or pk string.
        if period_format is not None:
            period_dict["period"] = period_format(pk, last_entry)
        elif last_entry and last_entry.get("end"):
            period_dict["period"] = last_entry["end"]
        else:
            period_dict["period"] = str(pk)
        out.append(period_dict)
    return out


def _format_annual_period(pk, last_entry):
    """Annual periods key by year (str/int). Prefer the actual filing
    end-date when present (lets `_fy_label` show the company's true fiscal
    year-end month, important for non-calendar filers like AEMD's March
    year-ends)."""
    if last_entry and last_entry.get("end"):
        return last_entry["end"]
    return f"{pk}-12-31"


def _normalize_annual_keys(d: dict) -> dict:
    """SEC keys annual years as int, yfinance as str. Normalize to str for
    consistent set-union behavior in `_merge_period_dicts`."""
    out: dict = {}
    for metric, periods in (d or {}).items():
        out[metric] = {str(k): v for k, v in (periods or {}).items()}
    return out


def sec_to_yfinance_annual(sec_row: dict, yfinance_row: dict | None = None) -> dict:
    """Take one row from companies_sec.json (and optionally one from
    companies_yfinance.json) and return three period-lists shaped like
    yfinance's `financial_statements.{income_statement, balance_sheet,
    cash_flow}.annual`. Each period dict carries a parallel `sources` map
    indicating per-cell origin."""
    sec_annual = _normalize_annual_keys((sec_row or {}).get("annual"))
    yf_annual = _normalize_annual_keys((yfinance_row or {}).get("annual"))
    merged, sources = _merge_period_dicts(sec_annual, yf_annual)
    return {
        "income_statement": _to_period_list(
            merged, sources, SEC_TO_YFINANCE_INCOME,
            period_format=_format_annual_period,
            derived_gross_profit=True,
            derived_zero_revenue=True,
        ),
        "cash_flow": _to_period_list(
            merged, sources, SEC_TO_YFINANCE_CASHFLOW,
            period_format=_format_annual_period,
            derived_fcf=True,
        ),
        "balance_sheet": _to_period_list(
            merged, sources, SEC_TO_YFINANCE_BALANCE,
            period_format=_format_annual_period,
            derived_total_debt=True,
        ),
    }


def sec_to_yfinance_quarterly(sec_row: dict, *, last_n: int = 8,
                               yfinance_row: dict | None = None) -> dict:
    """Quarterly variant. Period keys are ISO date strings (already aligned
    between SEC and yfinance). Capped to the last `last_n` periods to keep
    the report's table width reasonable."""
    sec_q = (sec_row or {}).get("quarterly") or {}
    yf_q = (yfinance_row or {}).get("quarterly") or {}
    merged, sources = _merge_period_dicts(sec_q, yf_q)
    full = {
        "income_statement": _to_period_list(
            merged, sources, SEC_TO_YFINANCE_INCOME,
            derived_gross_profit=True,
            derived_zero_revenue=True,
        ),
        "cash_flow": _to_period_list(
            merged, sources, SEC_TO_YFINANCE_CASHFLOW,
            derived_fcf=True,
        ),
        "balance_sheet": _to_period_list(
            merged, sources, SEC_TO_YFINANCE_BALANCE,
            derived_total_debt=True,
        ),
    }
    return {k: v[-last_n:] for k, v in full.items()}


def load_sec_by_ticker(path) -> dict:
    """Load companies_sec.json (or any same-shaped sidecar like
    companies_yfinance.json) into a dict keyed by ticker."""
    import json
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return {}
    return {r["ticker"]: r for r in json.loads(p.read_text()) if r.get("ticker")}


def load_sharded_by_ticker(dir_path) -> dict:
    """Load a directory of same-shaped shard files (e.g. data/yfinance/<industry
    -slug>.json) into one dict keyed by ticker — same return shape as
    `load_sec_by_ticker`, so callers stay agnostic to monolith vs. shards.

    On a duplicate ticker (e.g. one reclassified into a new industry while a
    stale row lingers in its old shard), the row with the latest `fetched_at`
    wins. A missing directory yields an empty dict."""
    import json
    from pathlib import Path
    d = Path(dir_path)
    if not d.is_dir():
        return {}
    out: dict = {}
    for f in sorted(d.glob("*.json")):
        for r in json.loads(f.read_text()):
            t = r.get("ticker")
            if not t:
                continue
            prev = out.get(t)
            if prev is None or (r.get("fetched_at") or "") >= (prev.get("fetched_at") or ""):
                out[t] = r
    return out
