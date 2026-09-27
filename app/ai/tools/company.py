"""The app's own company data: the summarised block and the universe search."""
from __future__ import annotations

from fastapi import HTTPException

from app.ai.context import _money, company_block
from app.ai.tools.registry import tool
from app.data import repo
from app.log import get_logger
from app.tools.paths import ASHARE_XCHECK_DIR

log = get_logger(__name__)


@tool(
    "search_companies",
    marks_company=False,
    description="Find companies by name or ticker fragment across ~7,000 NYSE/Nasdaq listings. Returns ticker, name, industry, market cap and whether the company has been analyzed (i.e. lookup_company will work).",
    params={"query": {"type": "string"}},
    required=["query"],
    status="Searching companies for “{query}”…",
)
def search_companies(query: str, *, limit: int = 12) -> str:
    q = query.strip().lower()
    if not q:
        return "ERROR: empty query"
    analyzed = repo.analyzed()
    universe = repo.universe()
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


@tool(
    "lookup_company",
    description="Fetch the app's collected data for one company by ticker: financial statements (10y annual, 8 quarters), valuation snapshot, business-model classification and prices. Only works for the ~1,250 analyzed companies; otherwise returns an error and you should say the company has not been analyzed yet.",
    params={"ticker": {"type": "string", "description": "e.g. QDEL"}},
    required=["ticker"],
    status="Looking up {ticker}…",
)
def lookup_company(ticker: str) -> str:
    t = (ticker or "").upper().strip()
    try:
        return company_block(t)
    except HTTPException:
        return (f"ERROR: {t} has not been analyzed by the pipeline — no statements "
                f"on file. Use search_companies to confirm the ticker, and tell the user "
                f"the data is not available.")


# ---- A-shares (沪深) ---------------------------------------------------------
# These companies have no SEC filings, so the filing / 6-K / earnings-call
# tools have nothing to serve for them. What they do have is a deeper
# statement history than yfinance, a structured segment breakdown and three
# independent sources to compare — the two tools below.

@tool(
    "main_business",
    description=(
        "主营业务构成 for an A-share (沪深) company: revenue, cost and profit split by "
        "region (国内/海外) and by product/industry, per fiscal year, straight from the filing. "
        "Use it for segment questions instead of guessing from the income statement."
    ),
    params={"ticker": {"type": "string", "description": "e.g. 600066.SS"},
            "period": {"type": "string", "description": "fiscal year, e.g. 2025 (default: the latest two)"}},
    required=["ticker"],
    status="Reading 主营业务构成 for {ticker}…",
)
def main_business(ticker: str, period: str | None = None) -> str:
    from app.tools.ashare_adapter import main_business as mb
    from app.tools.ashare_tools import load_raw

    t = (ticker or "").upper().strip()
    rows = mb(load_raw(t) or {}, period)
    if not rows:
        return (f"ERROR: no 主营业务构成 on file for {t} — it is only collected for A-shares "
                f"(600066.SS-style tickers).")
    periods = sorted({r["period"] for r in rows}, reverse=True)[:1 if period else 2]
    out = []
    for p in periods:
        out.append(f"{p}:")
        for r in [r for r in rows if r["period"] == p]:
            margin = "" if not r["revenue"] or r["profit"] is None else f" · 毛利率 {r['profit'] / r['revenue']:.1%}"
            out.append(f"  - {r['item']} ({r['kind']}): revenue {_money(r['revenue'])} "
                       f"{r['currency']}{margin}")
    return "\n".join(out)


@tool(
    "compare_sources",
    description=(
        "For an A-share, compare the same figures across every source on file (Tushare, 东方财富, "
        "yfinance) and against the valuation ratios Tushare publishes. Use it when the user asks "
        "whether a number is trustworthy, or when two numbers seem to disagree."
    ),
    params={"ticker": {"type": "string", "description": "e.g. 600066.SS"},
            "grid": {"type": "string", "enum": ["annual", "quarterly"]}},
    required=["ticker"],
    status="Cross-checking {ticker} across sources…",
)
def compare_sources(ticker: str, grid: str | None = "annual") -> str:
    t = (ticker or "").upper().strip()
    grid = grid or "annual"          # the registry passes None for an omitted param
    report = repo.read_json(ASHARE_XCHECK_DIR / f"{t}.json", {})
    if not report:
        return (f"ERROR: no cross-check on file for {t} — it is produced for A-shares by "
                f"scripts.xcheck_ashare.")
    cells = [c for c in report.get("cells") or [] if c["grid"] == grid]
    agreed = [c for c in cells if c["severity"] == "ok"]
    out = [f"{t} cross-check as of {report.get('as_of')} — sources: {', '.join(report.get('sources') or [])}",
           f"{len(agreed)}/{len(cells)} {grid} cells agree to within 0.1%."]
    for c in [c for c in cells if c["severity"] != "ok"]:
        vals = ", ".join(f"{k} {_money(v)}" for k, v in c["values"].items())
        out.append(f"  ! {c['metric']} {c['period']}: {vals} (spread {(c['spread_pct'] or 0):.2%})")
    for v in report.get("valuation") or []:
        out.append(f"  our {v['metric']} {v['ours']:,.4g} vs Tushare's {v['tushare']:,.4g} "
                   f"(spread {(v['spread_pct'] or 0):.2%})")
    return "\n".join(out)


# Curated slice of Tushare's 108-field 财务指标 — the ones that answer a
# question the statements alone don't. Everything else stays on disk in
# data/ashare_raw/<T>.json and can be surfaced by extending this map.
_INDICATORS: tuple[tuple[str, str], ...] = (
    ("eps", "EPS 每股收益"), ("bps", "BPS 每股净资产"), ("ocfps", "每股经营现金流"),
    ("grossprofit_margin", "毛利率 %"), ("netprofit_margin", "净利率 %"),
    ("roe", "ROE %"), ("roe_waa", "ROE 加权 %"), ("roa", "ROA %"), ("roic", "ROIC %"),
    ("debt_to_assets", "资产负债率 %"), ("current_ratio", "流动比率"),
    ("quick_ratio", "速动比率"), ("cash_ratio", "现金比率"),
    ("inv_turn", "存货周转率"), ("ar_turn", "应收周转率"), ("assets_turn", "总资产周转率"),
    ("ocf_to_or", "经营现金流/营业收入"), ("fcff", "企业自由现金流"),
    ("or_yoy", "营收同比 %"), ("netprofit_yoy", "净利润同比 %"),
    ("dt_netprofit_yoy", "扣非净利润同比 %"), ("ebitda", "EBITDA"),
    ("interestdebt", "带息债务"), ("netdebt", "净债务"),
    # Per-share and capital structure
    ("revenue_ps", "每股营业收入"), ("cfps", "每股现金流"), ("fcff_ps", "每股企业自由现金流"),
    ("assets_to_eqt", "权益乘数"), ("debt_to_eqt", "产权比率"),
    ("currentdebt_to_debt", "流动负债/总负债 %"), ("longdeb_to_debt", "非流动负债/总负债 %"),
    # Turnover and efficiency
    ("ca_turn", "流动资产周转率"), ("fa_turn", "固定资产周转率"),
    ("turn_days", "营业周期 (天)"), ("inv_turn_days", "存货周转天数"),
    ("arturn_days", "应收周转天数"),
    # Expense structure, as a share of revenue
    ("cogs_of_sales", "营业成本/营收 %"), ("expense_of_sales", "销售成本率 %"),
    ("adminexp_of_gr", "管理费用/营收 %"), ("finaexp_of_gr", "财务费用/营收 %"),
    ("gc_of_gr", "营业总成本/营收 %"), ("ebit_of_gr", "EBIT/营收 %"),
    # Growth
    ("assets_yoy", "总资产同比 %"), ("eqt_yoy", "净资产同比 %"),
    ("bps_yoy", "每股净资产同比 %"), ("ocf_yoy", "经营现金流同比 %"),
    ("q_sales_yoy", "单季营收同比 %"), ("q_profit_yoy", "单季净利同比 %"),
    # Quality of earnings
    ("profit_to_gr", "净利润/营业总收入 %"), ("op_of_gr", "营业利润/营收 %"),
    ("extra_item", "非经常性损益"), ("profit_dedt", "扣非净利润"),
)


@tool(
    "ashare_indicators",
    description=(
        "Tushare's ready-made 财务指标 for an A-share: margins, ROE/ROA/ROIC, turnover, "
        "liquidity, YoY growth, EBITDA, net debt — plus the company's 分红 history. Use it "
        "instead of deriving these from the statements, and for dividend questions."
    ),
    params={"ticker": {"type": "string", "description": "e.g. 600066.SS"},
            "period": {"type": "string", "description": "period end YYYYMMDD or YYYY; omit for the latest"}},
    required=["ticker"],
    status="Reading {ticker}'s 财务指标…",
)
def ashare_indicators(ticker: str, period: str | None = None) -> str:
    from app.tools.ashare_tools import load_raw

    t = (ticker or "").upper().strip()
    raw = load_raw(t)
    if not raw:
        return (f"ERROR: nothing on file for {t} — Tushare data is collected for A-shares "
                f"(600066.SS-style tickers).")
    rows = sorted(raw.get("fina_indicator") or [], key=lambda r: str(r.get("end_date") or ""))
    if period:
        want = period.replace("-", "")
        rows = [r for r in rows if str(r.get("end_date") or "").startswith(want)]
    if not rows:
        return f"ERROR: no 财务指标 for {t} at period {period!r}"
    row = rows[-1]
    out = [f"{t} 财务指标 · period {row.get('end_date')} (announced {row.get('ann_date')})"]
    for field, label in _INDICATORS:
        v = row.get(field)
        if v in (None, ""):
            continue
        out.append(f"  {label}: {v:,.4g}" if isinstance(v, (int, float)) else f"  {label}: {v}")

    paid = [d for d in raw.get("dividend") or [] if d.get("div_proc") == "实施" and d.get("cash_div_tax")]
    paid.sort(key=lambda d: str(d.get("end_date") or ""), reverse=True)
    if paid:
        out.append("分红 (实施):")
        for d in paid[:6]:
            out.append(f"  FY{str(d.get('end_date'))[:4]} 每股 {d['cash_div_tax']} 元 (税前)"
                       f" · 除权 {d.get('ex_date')} · 派发 {d.get('pay_date')}")
    return "\n".join(out)


@tool(
    "ashare_shareholders",
    description=(
        "Who owns an A-share: the ten largest holders with their stakes and the change since "
        "last period, plus how the total number of shareholders has moved (a crowding signal)."
    ),
    params={"ticker": {"type": "string"}, "period": {"type": "string", "description": "YYYYMMDD; omit for the latest"}},
    required=["ticker"],
    status="Reading {ticker}'s 股东情况…",
)
def ashare_shareholders(ticker: str, period: str | None = None) -> str:
    from app.tools.ashare_tools import load_raw

    t = (ticker or "").upper().strip()
    raw = load_raw(t)
    if not raw:
        return f"ERROR: nothing on file for {t} — A-shares only."
    holders = raw.get("top10_holders") or []
    periods = sorted({str(h.get("end_date")) for h in holders if h.get("end_date")})
    want = (period.replace("-", "") if period else (periods[-1] if periods else None))
    rows = [h for h in holders if str(h.get("end_date")) == want]
    out = [f"{t} 十大股东 · period {want}"]
    for h in sorted(rows, key=lambda r: -(r.get("hold_ratio") or 0)):
        chg = h.get("hold_change")
        chg_s = "" if chg in (None, 0) else f" ({'+' if chg > 0 else ''}{chg:,.0f} shares)"
        out.append(f"  {h.get('hold_ratio', 0):5.2f}%  {h.get('holder_name')}"
                   f" · {h.get('holder_type') or '?'}{chg_s}")
    nums = sorted(raw.get("stk_holdernumber") or [], key=lambda r: str(r.get("end_date") or ""))
    if nums:
        out.append("股东户数:")
        for r in nums[-5:]:
            out.append(f"  {r.get('end_date')}: {r.get('holder_num'):,}")
    return "\n".join(out)


@tool(
    "ashare_guidance",
    description=(
        "业绩预告 / 业绩快报 for an A-share — the profit range or preliminary figures a company "
        "published before the full filing. Use it for 'what did they guide' and for the most "
        "recent quarter when the statements aren't out yet."
    ),
    params={"ticker": {"type": "string"}},
    required=["ticker"],
    status="Reading {ticker}'s 业绩预告/快报…",
)
def ashare_guidance(ticker: str) -> str:
    from app.tools.ashare_tools import load_raw

    t = (ticker or "").upper().strip()
    raw = load_raw(t)
    if not raw:
        return f"ERROR: nothing on file for {t} — A-shares only."
    out = [f"{t} 业绩预告 / 快报"]
    fc = sorted(raw.get("forecast") or [], key=lambda r: str(r.get("end_date") or ""), reverse=True)
    for r in fc[:6]:
        rng = ""
        if r.get("p_change_min") is not None:
            rng = f" 净利同比 {r['p_change_min']}%~{r.get('p_change_max')}%"
        net = ""
        if r.get("net_profit_min") is not None:      # Tushare reports these in 万元
            net = f" · 净利 {r['net_profit_min'] / 10_000:.2f}~{(r.get('net_profit_max') or 0) / 10_000:.2f} 亿元"
        out.append(f"  预告 {r.get('end_date')} [{r.get('type')}]{rng}{net} (公告 {r.get('ann_date')})")
    ex = sorted(raw.get("express") or [], key=lambda r: str(r.get("end_date") or ""), reverse=True)
    for r in ex[:4]:
        out.append(f"  快报 {r.get('end_date')}: 营收 {(r.get('revenue') or 0) / 1e8:.2f} 亿元 · "
                   f"净利 {(r.get('n_income') or 0) / 1e8:.2f} 亿元 (公告 {r.get('ann_date')})")
    return "\n".join(out) if len(out) > 1 else f"No 业绩预告/快报 on file for {t}."
