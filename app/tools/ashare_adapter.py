"""Map Tushare rows onto the pipeline's metric vocabulary.

The output is a **source row** in exactly the shape
`app.tools.yfinance_statements.build_yfinance_row` produces —
`{ticker, source, financial_currency, annual, quarterly}` with
`{metric: {period_key: {val, end, concept, source}}}` inside — so it can be
laid over the yfinance shard by `sec_adapter.overlay_source_row` and blended
by the ordinary machinery. Nothing downstream needs to know about A-shares:
precedence becomes Tushare > 东方财富 > yfinance, per cell, with tags.

Two quirks of Chinese filings are handled here:

* **Restatements.** `report_type=1` returns several rows for one
  `end_date` (the original and each adjustment), and a first-published row
  can carry nulls a later one fills (`ebit` on 600066's 2025Q1). Dedupe is
  therefore per *cell*: rows are applied oldest-announced first and the last
  non-null value wins.
* **Dividends.** Chinese cash-flow statements bundle dividends with interest
  (`c_pay_dist_dpcp_int_exp`), so the payout comes from the 分红 records
  instead: each 实施 row's per-share amount × the share count, booked to the
  quarter its `pay_date` falls in — i.e. cash actually paid in the period,
  the same basis as a US filer's "Cash Dividends Paid" line.
* **YTD cumulation.** Income and cash flow are cumulative within the fiscal
  year (Q1 / 中报 / 三季报 / 年报). Tushare's `report_type=2` gives true
  single quarters; where it's missing, `ytd_to_quarter` differences
  consecutive periods of the same year (the same trick
  `sec_xbrl_tools.extract_quarterly_cash_flow` does for 10-Qs).
"""
from __future__ import annotations

from datetime import datetime, timezone

# metric key -> Tushare field candidates, first non-null wins
INCOME_FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("total_revenue", "revenue"),
    "cost_of_revenue": ("oper_cost",),
    "operating_income": ("operate_profit",),
    "net_income": ("n_income_attr_p", "n_income"),
    "diluted_eps": ("diluted_eps", "basic_eps"),
    "rd_expense": ("rd_exp",),
    "pretax_income": ("total_profit",),
    "income_tax": ("income_tax",),
    "ebitda": ("ebitda",),
    "interest_expense": ("fin_exp_int_exp",),
    "selling_marketing_expense": ("sell_exp",),
    "general_admin_expense": ("admin_exp",),
}

BALANCE_FIELDS: dict[str, tuple[str, ...]] = {
    "cash": ("money_cap",),
    "short_term_investments": ("trad_asset",),
    "total_assets": ("total_assets",),
    "stockholders_equity": ("total_hldr_eqy_exc_min_int",),
    "goodwill": ("goodwill",),
    "ppe_net": ("fix_assets", "fix_assets_total"),
    "inventory": ("inventories",),
    "receivables": ("accounts_receiv",),
    "intangibles": ("intan_assets",),
    "long_term_investments": ("lt_eqt_invest",),
    "total_liabilities": ("total_liab",),
    "long_term_debt": ("lt_borr",),
    "short_term_debt": ("st_borr",),
    "accounts_payable": ("acct_payable", "accounts_pay"),
    "deferred_revenue": ("contract_liab", "adv_receipts"),
    "current_assets": ("total_cur_assets",),
    "current_liabilities": ("total_cur_liab",),
    "retained_earnings": ("undistr_porfit",),
    "minority_interest": ("minority_int",),
    # 期末总股本 — the app needs a share count for EPS checks and market cap.
    "diluted_shares": ("total_share",),
}

CASHFLOW_FIELDS: dict[str, tuple[str, ...]] = {
    "operating_cf": ("n_cashflow_act",),
    # 购建固定资产、无形资产和其他长期资产支付的现金 — reported positive;
    # the pipeline's convention is capex negative (see sec_adapter).
    "capex": ("c_pay_acq_const_fiolta",),
}

# 毛利 = 营业收入 − 营业成本. Computed here rather than left to the blend's
# `derived_gross_profit` because yfinance publishes a Gross Profit for A-shares
# built on a different cost base (¥1.49B vs the filing's ¥10.00B for 600066
# FY2025 — the latter matches 主营业务构成 exactly), and a present-but-wrong
# yfinance cell would never be replaced by the derivation.
_DERIVED = {"gross_profit": ("revenue", "cost_of_revenue")}

_NEGATE = {"capex"}
# Balance-sheet items are point-in-time; only flows are YTD-cumulative.
_FLOW_MAPS = (INCOME_FIELDS, CASHFLOW_FIELDS)


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _announced(row: dict) -> tuple[str, str, str]:
    """Sort key: oldest announcement first, original before its adjustments."""
    return (str(row.get("ann_date") or ""), str(row.get("f_ann_date") or ""),
            str(row.get("update_flag") or ""))


def _end(row: dict) -> str:
    """`20251231` → `2025-12-31`."""
    d = str(row.get("end_date") or "")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d


def dedupe(rows: list[dict]) -> dict[str, dict]:
    """{ISO end date: merged row}. Later announcements overwrite earlier ones
    cell by cell, so a restatement wins but never blanks a field it omits."""
    out: dict[str, dict] = {}
    for row in sorted(rows or [], key=_announced):
        end = _end(row)
        if not end:
            continue
        dst = out.setdefault(end, {})
        for k, v in row.items():
            if v not in (None, ""):
                dst[k] = v
    return out


# A-share reporting periods, in order: 一季报 / 中报 / 三季报 / 年报.
_QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")


def ytd_to_quarter(by_end: dict[str, dict], fields: dict[str, tuple[str, ...]]) -> dict[str, dict]:
    """Difference YTD-cumulative rows into single quarters, per fiscal year.

    Q1 is already a single quarter; every later period is `value − the period
    immediately before it`. The predecessor has to be the *adjacent* quarter,
    not merely the previous one on file: differencing 三季报 against 一季报
    when 中报 is missing would silently label a six-month figure as one
    quarter, so that cell is dropped instead."""
    out: dict[str, dict] = {}
    for end in sorted(by_end):
        cur = by_end[end]
        row = {k: v for k, v in cur.items() if not isinstance(v, (int, float))}
        try:
            idx = _QUARTER_ENDS.index(end[5:])
        except ValueError:                       # not a calendar quarter end
            idx = -1
        prev = None if idx <= 0 else by_end.get(f"{end[:4]}-{_QUARTER_ENDS[idx - 1]}")
        for candidates in fields.values():
            for f in candidates:
                v = _num(cur.get(f))
                if v is None:
                    continue
                if idx == 0:                     # 一季报 is already a quarter
                    row[f] = v
                else:
                    pv = _num((prev or {}).get(f))
                    if pv is None:
                        continue
                    row[f] = v - pv
                break
        out[end] = row
    return out


def dividend_cash(raw: dict | None, shares_by_end: dict[str, float]) -> dict[str, float]:
    """{quarter-end ISO: cash dividend paid that quarter, negative}.

    Only 实施 (executed) records count — 预案 and 股东大会通过 are proposals.
    The amount is per share (`cash_div_tax`, pre-tax, which is what a payout
    ratio and a yield are quoted on), multiplied by the share count reported
    at or before the payment."""
    out: dict[str, float] = {}
    if not raw:
        return out
    shares_sorted = sorted(shares_by_end.items())
    for row in raw.get("dividend") or []:
        if row.get("div_proc") != "实施":
            continue
        per_share = _num(row.get("cash_div_tax")) or _num(row.get("cash_div"))
        pay = str(row.get("pay_date") or row.get("ex_date") or "")
        if not per_share or len(pay) != 8:
            continue
        paid_iso = f"{pay[:4]}-{pay[4:6]}-{pay[6:8]}"
        idx = min((int(pay[4:6]) - 1) // 3, 3)
        quarter = f"{pay[:4]}-{_QUARTER_ENDS[idx]}"
        shares = next((v for end, v in reversed(shares_sorted) if end <= paid_iso), None)
        if not shares:
            continue
        out[quarter] = out.get(quarter, 0.0) - per_share * shares
    return out


def _entries(by_end: dict[str, dict], fields: dict[str, tuple[str, ...]],
             *, period_key, only_year_end: bool = False,
             source: str = "ashare") -> dict[str, dict]:
    """{metric: {period_key: entry}} for one statement. `source` is the cell
    tag the blend and the FX conversion key off (东方财富 reuses this with
    "eastmoney" — see app/tools/eastmoney_tools.py)."""
    out: dict[str, dict] = {}
    for end, row in by_end.items():
        if only_year_end and not end.endswith("-12-31"):
            continue
        pk = period_key(end)
        for metric, candidates in fields.items():
            for f in candidates:
                v = _num(row.get(f))
                if v is None:
                    continue
                out.setdefault(metric, {})[pk] = {
                    "val": -v if metric in _NEGATE else v,
                    "end": end,
                    "concept": f,
                    "source": source,
                }
                break
    return out


def _derive(entries: dict[str, dict]) -> dict[str, dict]:
    """Add the metrics we compute from others (see `_DERIVED`)."""
    for metric, (a, b) in _DERIVED.items():
        left, right = entries.get(a) or {}, entries.get(b) or {}
        for pk in left.keys() & right.keys():
            entries.setdefault(metric, {})[pk] = {
                "val": left[pk]["val"] - right[pk]["val"],
                "end": left[pk]["end"],
                "concept": f"{left[pk]['concept']} - {right[pk]['concept']}",
                "source": "ashare",
            }
    return entries


def _merge(*parts: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for part in parts:
        for metric, periods in part.items():
            out.setdefault(metric, {}).update(periods)
    return out


def ashare_source_row(raw: dict | None) -> dict | None:
    """Tushare payload (`ashare_tools.fetch`) → blendable source row.

    Annual figures come from the 年报 (`report_type=1` at Dec 31); quarterly
    from 单季合并 (`report_type=2`), falling back to differenced YTD for the
    periods Tushare's single-quarter series doesn't reach."""
    if not raw:
        return None
    inc_y = dedupe(raw.get("income") or [])
    bal_y = dedupe(raw.get("balancesheet") or [])
    cf_y = dedupe(raw.get("cashflow") or [])
    inc_q = dedupe(raw.get("income_q") or []) or ytd_to_quarter(inc_y, INCOME_FIELDS)
    cf_q = dedupe(raw.get("cashflow_q") or []) or ytd_to_quarter(cf_y, CASHFLOW_FIELDS)
    # Fill quarters the 单季 series lacks (it starts later than 合并报表 does).
    for have, ytd, fields in ((inc_q, inc_y, INCOME_FIELDS), (cf_q, cf_y, CASHFLOW_FIELDS)):
        for end, row in ytd_to_quarter(ytd, fields).items():
            have.setdefault(end, row)

    def fy(end: str) -> str:
        return end[:4]

    def qk(end: str) -> str:
        return end

    annual = _derive(_merge(
        _entries(inc_y, INCOME_FIELDS, period_key=fy, only_year_end=True),
        _entries(bal_y, BALANCE_FIELDS, period_key=fy, only_year_end=True),
        _entries(cf_y, CASHFLOW_FIELDS, period_key=fy, only_year_end=True),
    ))
    quarterly = _derive(_merge(
        _entries(inc_q, INCOME_FIELDS, period_key=qk),
        _entries(bal_y, BALANCE_FIELDS, period_key=qk),
        _entries(cf_q, CASHFLOW_FIELDS, period_key=qk),
    ))
    # Dividends: paid once or twice a year, booked to the quarter they hit.
    shares_by_end = {end: v for end, row in bal_y.items()
                     if (v := _num(row.get("total_share")))}
    div = dividend_cash(raw, shares_by_end)
    for quarter, amount in div.items():
        quarterly.setdefault("cash_dividends_paid", {})[quarter] = {
            "val": amount, "end": quarter, "concept": "cash_div_tax × total_share",
            "source": "ashare",
        }
    for year in {q[:4] for q in div}:
        annual.setdefault("cash_dividends_paid", {})[year] = {
            "val": sum(v for q, v in div.items() if q[:4] == year),
            "end": f"{year}-12-31", "concept": "cash_div_tax × total_share",
            "source": "ashare",
        }
    basic = (raw.get("stock_basic") or [{}])[0]
    return {
        "ticker": raw.get("ticker") or "",
        "ts_code": raw.get("ts_code") or "",
        "name": basic.get("name") or "",
        "fetched_at": raw.get("fetched_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "ashare",
        "financial_currency": "CNY",
        "annual": annual,
        "quarterly": quarterly,
    }


def latest_daily_basic(raw: dict | None) -> dict:
    """Most recent `daily_basic` row — close, 总市值 (万元), 总股本 (万股),
    pe/pe_ttm/pb. Tushare's own valuation numbers, which the cross-check
    reconciles our computed ones against."""
    rows = sorted((raw or {}).get("daily_basic") or [], key=lambda r: str(r.get("trade_date") or ""))
    return rows[-1] if rows else {}


def market_cap(raw: dict | None) -> float | None:
    """Market cap in yuan (Tushare reports 总市值 in 万元)."""
    mv = _num(latest_daily_basic(raw).get("total_mv"))
    return mv * 10_000 if mv is not None else None


def main_business(raw: dict | None, period: str | None = None) -> list[dict]:
    """主营业务构成 rows, newest period first, aggregates dropped.

    Tushare returns 分地区 (`bz_code` D) and 分行业/产品 (I / P) plus roll-up
    rows that restate the total ("地区", "行业", "合计特别调整") — those are
    noise next to the real segments, so they're filtered out."""
    skip = {"地区", "行业", "产品", "合计特别调整", "合计"}
    rows = []
    for r in (raw or {}).get("fina_mainbz") or []:
        item = (r.get("bz_item") or "").strip()
        if item in skip:
            continue
        end = _end({"end_date": r.get("end_date")})
        if period and not end.startswith(period[:4]):
            continue
        rows.append({
            "period": end,
            "item": item,
            "kind": {"D": "region", "I": "industry", "P": "product"}.get(r.get("bz_code") or "", "other"),
            "revenue": _num(r.get("bz_sales")),
            "cost": _num(r.get("bz_cost")),
            "profit": _num(r.get("bz_profit")),
            "currency": r.get("curr_type") or "CNY",
        })
    return sorted(rows, key=lambda r: (r["period"], r["kind"], r["item"]), reverse=True)
