"""Data-quality rules over `companies_sec.json` + `companies_analyzed.json`.

Each rule is a pure function `(sec_row, analyzed_row, today) -> list[Issue]`.
The driver `validate_ticker` runs every rule and returns the combined list.

An Issue is a plain dict with severity ∈ {error, warn, info}:
- error: missing data that breaks a headline metric in the report.
- warn:  anomaly that should be investigated; report renders with a banner.
- info:  soft cross-source drift; report renders without banner.

The pipeline placement is:
    fetch_sec_annual → validate_companies → build_report

build_report reads the per-ticker validation entry and renders a banner if
severity ≥ warn. Rules deliberately do NOT touch the underlying data — they
flag, they don't fix.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

Issue = dict


def _issue(severity: str, rule: str, detail: str) -> Issue:
    return {"severity": severity, "rule": rule, "detail": detail}


def _annual(sec_row):
    return (sec_row or {}).get("annual") or {}


def _quarterly(sec_row):
    return (sec_row or {}).get("quarterly") or {}


def _val(entry):
    """Pull `val` from an XBRL entry dict, or return raw scalar."""
    if isinstance(entry, dict):
        return entry.get("val")
    return entry


def _latest(by_key: dict):
    if not by_key:
        return None, None
    k = max(by_key.keys())
    return k, _val(by_key[k])


# =============== TIER 1: presence ===============

def rule_annual_revenue_present(sec, analyzed, today):
    """An *absent* revenue concept is an error — every operating company
    files some revenue line. A *reported* value of 0 is legitimate for
    pre-revenue dev-stage filers (biotechs, SPACs, shell companies), so
    that's downgraded to info — it doesn't mean the data is broken, it
    means the company hasn't sold anything yet."""
    rev = _annual(sec).get("revenue") or {}
    if not rev:
        return [_issue("error", "missing_annual_revenue", "no annual Revenue concept in SEC data")]
    y, v = _latest(rev)
    if v is None:
        return [_issue("error", "missing_annual_revenue", f"FY{y} revenue is missing")]
    if v < 0:
        return [_issue("warn", "negative_annual_revenue",
            f"FY{y} reported revenue is {v} — returns/refunds dominating sales?")]
    if v == 0:
        return [_issue("info", "zero_annual_revenue",
            f"FY{y} reported revenue is 0 — pre-revenue stage")]
    return []


def rule_net_income_present(sec, analyzed, today):
    issues = []
    if not (_annual(sec).get("net_income") or {}):
        issues.append(_issue("error", "missing_annual_net_income", "no annual Net Income concept"))
    if not (_quarterly(sec).get("net_income") or {}):
        issues.append(_issue("warn", "missing_quarterly_net_income",
            "no quarterly Net Income — TTM metrics will be n/a"))
    return issues


def rule_operating_income_present(sec, analyzed, today):
    if not (_annual(sec).get("operating_income") or {}):
        return [_issue("error", "missing_operating_income",
            "no annual Operating Income — margins won't compute")]
    return []


def rule_diluted_shares_present(sec, analyzed, today):
    if not (_annual(sec).get("diluted_shares") or {}):
        return [_issue("error", "missing_diluted_shares",
            "no diluted-shares concept — P/E + EPS won't compute")]
    return []


def rule_balance_sheet_present(sec, analyzed, today):
    annual = _annual(sec)
    issues = []
    if not (annual.get("total_assets") or {}):
        issues.append(_issue("error", "missing_total_assets", "no Total Assets concept"))
    if not (annual.get("stockholders_equity") or {}):
        issues.append(_issue("error", "missing_stockholders_equity",
            "no Stockholders Equity — P/B and ROE won't compute"))
    return issues


def rule_gross_profit_derivable(sec, analyzed, today):
    annual = _annual(sec)
    if (annual.get("gross_profit") or {}) or (annual.get("cost_of_revenue") or {}):
        return []
    return [_issue("warn", "no_gross_profit_source",
        "neither Gross Profit nor Cost of Revenue fetched — Gross Margin will show n/a")]


def rule_price_history_present(sec, analyzed, today):
    ph = ((analyzed or {}).get("price_history") or {}).get("data") or []
    if not ph:
        return [_issue("error", "no_price_history", "no price_history in analyzed row")]
    latest = max((p.get("date") for p in ph if p.get("date")), default=None)
    if not latest:
        return [_issue("error", "no_price_history", "no dated price points")]
    try:
        latest_d = date.fromisoformat(latest[:10])
    except ValueError:
        return [_issue("error", "no_price_history", f"unparseable date {latest!r}")]
    days = (today - latest_d).days
    if days > 60:
        return [_issue("warn", "stale_price", f"latest close {latest} is {days} days old")]
    return []


# =============== TIER 2: sanity ranges ===============

def _gp_for_year(annual, year):
    """Return Gross Profit for a year, derived from Revenue − COGS if not
    directly reported."""
    gp = _val((annual.get("gross_profit") or {}).get(year))
    if gp is not None:
        return gp
    rev = _val((annual.get("revenue") or {}).get(year))
    cor = _val((annual.get("cost_of_revenue") or {}).get(year))
    if rev is not None and cor is not None:
        return rev - cor
    return None


_GM_MIN_REVENUE = 1_000_000

def rule_gross_margin_in_range(sec, analyzed, today):
    """Gross margin outside [-5%, 105%] suggests a unit mismatch between
    Revenue and COGS. Skipped when revenue < $1M — for dev-stage filers,
    a single line of fixed COGS can drive gross margin to -200% legitimately
    (a $50K product cost against $20K of sample revenue, etc.)."""
    annual = _annual(sec)
    rev = annual.get("revenue") or {}
    issues = []
    for year in rev:
        rev_val = _val(rev[year])
        if not rev_val:
            continue
        if abs(rev_val) < _GM_MIN_REVENUE:
            continue
        gp = _gp_for_year(annual, year)
        if gp is None:
            continue
        gm = gp / rev_val
        if gm < -0.05 or gm > 1.05:
            issues.append(_issue("warn", "gross_margin_out_of_range",
                f"FY{year} Gross Margin {gm:.0%} outside expected [0, 100%]"))
    return issues


_NI_VS_REV_MIN_REVENUE = 10_000_000

def rule_ni_magnitude_vs_revenue(sec, analyzed, today):
    """|NI| > 1.5× Revenue suggests one of them is in the wrong units. The
    heuristic only works when revenue is large enough that the comparison
    is meaningful — for dev-stage filers with <$10M revenue, losing 5×
    revenue annually is the norm, not a unit mismatch."""
    annual = _annual(sec)
    rev = annual.get("revenue") or {}
    ni = annual.get("net_income") or {}
    issues = []
    for year in rev:
        rev_v = _val(rev[year])
        ni_v = _val(ni.get(year))
        if not rev_v or ni_v is None:
            continue
        if abs(rev_v) < _NI_VS_REV_MIN_REVENUE:
            continue
        if abs(ni_v) > 1.5 * abs(rev_v):
            issues.append(_issue("warn", "ni_exceeds_revenue",
                f"FY{year} |Net Income| {ni_v/1e6:,.0f}M > 1.5× Revenue {rev_v/1e6:,.0f}M — heavy cash burn"))
    return issues


def rule_shares_in_range(sec, analyzed, today):
    annual = _annual(sec).get("diluted_shares") or {}
    issues = []
    for year, e in annual.items():
        s = _val(e)
        if s is None:
            continue
        if s <= 0 or s > 100e9:
            issues.append(_issue("warn", "shares_out_of_range",
                f"FY{year} diluted shares {s:,.0f} outside (0, 100B]"))
    return issues


# =============== TIER 3: cross-period ===============

def rule_latest_filing_fresh(sec, analyzed, today):
    q_rev = _quarterly(sec).get("revenue") or {}
    if not q_rev:
        return []
    latest_d_str = max(q_rev.keys())
    try:
        latest_d = date.fromisoformat(latest_d_str)
    except ValueError:
        return []
    days = (today - latest_d).days
    if days > 180:
        return [_issue("warn", "stale_filings",
            f"latest quarterly period {latest_d_str} is {days} days old (>180)")]
    return []


_YOY_MIN_REVENUE = 1_000_000

def rule_yoy_revenue_plausible(sec, analyzed, today):
    """Annual revenue ratio outside [0.33×, 3×] without an M&A flag → warn.
    Skips year-pairs where either side is below $1M revenue — ratios are
    meaningless when the denominator is in the noise (e.g., $50K → $500K
    is 10× but tells you nothing about business trajectory)."""
    rev = _annual(sec).get("revenue") or {}
    mna = {int(y) for y in (sec or {}).get("mna_flagged_years") or []}
    keys = []
    for k in rev:
        try:
            keys.append((int(k), k))
        except (TypeError, ValueError):
            continue
    keys.sort()
    issues = []
    for i in range(1, len(keys)):
        (y, ky), (py, pky) = keys[i], keys[i - 1]
        v = _val(rev[ky])
        pv = _val(rev[pky])
        if not v or not pv:
            continue
        if abs(v) < _YOY_MIN_REVENUE or abs(pv) < _YOY_MIN_REVENUE:
            continue
        if y in mna or py in mna:
            continue
        ratio = v / pv
        if ratio > 3.0 or ratio < (1 / 3.0):
            issues.append(_issue("warn", "yoy_revenue_jump",
                f"FY{py}→FY{y} revenue {pv/1e6:,.0f}M → {v/1e6:,.0f}M ({ratio:.1f}×, not M&A-flagged)"))
    return issues


def rule_q_sum_vs_annual(sec, analyzed, today):
    """Sum of the 4 quarters within a fiscal year should match annual revenue
    within ±5%. Uses the XBRL start/end span to assign quarters to fiscal
    years correctly (works for non-calendar year-ends)."""
    annual = _annual(sec).get("revenue") or {}
    quarterly = _quarterly(sec).get("revenue") or {}
    if not annual or not quarterly:
        return []
    issues = []
    for year_key, ann_entry in annual.items():
        if not isinstance(ann_entry, dict):
            continue
        ann_val = ann_entry.get("val")
        if not ann_val:
            continue
        ann_start = (ann_entry.get("start") or "")[:10]
        ann_end = (ann_entry.get("end") or "")[:10]
        if not ann_start or not ann_end:
            continue
        q_vals = []
        for _, q_entry in quarterly.items():
            if not isinstance(q_entry, dict):
                continue
            q_start = (q_entry.get("start") or "")[:10]
            q_end = (q_entry.get("end") or "")[:10]
            if not q_start or not q_end:
                continue
            if q_start >= ann_start and q_end <= ann_end and q_entry.get("val") is not None:
                q_vals.append(q_entry["val"])
        if len(q_vals) != 4:
            continue
        q_sum = sum(q_vals)
        diff = (q_sum - ann_val) / ann_val
        if abs(diff) > 0.05:
            issues.append(_issue("warn", "q_sum_vs_annual",
                f"FY{year_key} annual rev {ann_val/1e6:,.0f}M vs Σ4-quarters {q_sum/1e6:,.0f}M ({diff:+.0%})"))
    return issues


def rule_eps_consistent(sec, analyzed, today):
    """Reported diluted EPS should approximately equal NI / Diluted Shares."""
    annual = _annual(sec)
    ni = annual.get("net_income") or {}
    ds = annual.get("diluted_shares") or {}
    eps = annual.get("diluted_eps") or {}
    issues = []
    for year in eps:
        ni_v = _val(ni.get(year))
        ds_v = _val(ds.get(year))
        eps_v = _val(eps[year])
        if ni_v is None or not ds_v or eps_v is None:
            continue
        if abs(eps_v) < 0.05:
            continue
        computed = ni_v / ds_v
        diff = (computed - eps_v) / abs(eps_v)
        if abs(diff) > 0.05:
            issues.append(_issue("info", "eps_mismatch",
                f"FY{year} reported EPS {eps_v:.2f} vs NI/shares {computed:.2f} ({diff:+.0%})"))
    return issues


# =============== TIER 4: cross-source ===============

def rule_mcap_reconcile(sec, analyzed, today):
    """Stage 1 stored market_cap vs price×shares from SEC+price_history."""
    stage1 = (analyzed or {}).get("market_cap")
    if not stage1:
        return []
    ph = ((analyzed or {}).get("price_history") or {}).get("data") or []
    latest_close = None
    for p in reversed(ph):
        if p.get("close") is not None:
            latest_close = p["close"]
            break
    shares = _annual(sec).get("diluted_shares") or {}
    if not shares or latest_close is None:
        return []
    _, latest_shares = _latest(shares)
    if not latest_shares:
        return []
    recomputed = latest_close * latest_shares
    diff = (recomputed - stage1) / stage1
    if abs(diff) > 0.30:
        return [_issue("info", "mcap_reconciliation",
            f"Stage-1 mcap {stage1/1e9:.2f}B vs price×shares {recomputed/1e9:.2f}B ({diff:+.0%})")]
    return []


# =============== driver ===============

ALL_RULES: tuple[Callable, ...] = (
    rule_annual_revenue_present,
    rule_net_income_present,
    rule_operating_income_present,
    rule_diluted_shares_present,
    rule_balance_sheet_present,
    rule_gross_profit_derivable,
    rule_price_history_present,
    rule_gross_margin_in_range,
    rule_ni_magnitude_vs_revenue,
    rule_shares_in_range,
    rule_latest_filing_fresh,
    rule_yoy_revenue_plausible,
    rule_q_sum_vs_annual,
    rule_eps_consistent,
    rule_mcap_reconcile,
)


_SEVERITY_ORDER = {"info": 0, "warn": 1, "error": 2}


def worst_severity(issues: list[Issue]) -> str:
    if not issues:
        return "ok"
    return max(issues, key=lambda i: _SEVERITY_ORDER.get(i["severity"], 0))["severity"]


def validate_ticker(sec_row, analyzed_row=None, today=None):
    """Run every rule against one ticker; collect issues. A rule that raises
    is captured as its own error issue so one broken rule never crashes the
    whole pipeline."""
    today = today or date.today()
    issues = []
    for rule_fn in ALL_RULES:
        try:
            issues.extend(rule_fn(sec_row, analyzed_row, today))
        except Exception as e:
            issues.append(_issue("error", f"rule_exception:{rule_fn.__name__}",
                f"{type(e).__name__}: {e}"))
    return issues
