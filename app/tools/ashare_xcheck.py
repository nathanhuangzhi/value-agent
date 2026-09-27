"""Reconcile an A-share's numbers across every source we can reach.

Three independent packagings of the same filings are on disk — Tushare
(`ashare`), 东方财富 (`eastmoney`) and yfinance — and the blend only ever
shows one of them per cell. This module compares them so a silent
disagreement becomes visible: the report it produces is written to
`data/ashare_xcheck/<T>.json`, its worst finding is folded into
`companies_validation.json` by `app/tools/validation.py`, and the AI chat
reads it through `compare_sources`.

It also reconciles the ratios *we* compute against the ones Tushare
publishes (`daily_basic.pe_ttm` / `pe` / `pb` / `total_mv`). That single
check is the fastest way to catch a share-count or FX mistake, because it
compares an end-to-end result rather than an input.

Pure functions only — the caller does the I/O (`scripts/xcheck_ashare.py`).
"""
from __future__ import annotations

from datetime import date

# Headline items worth reconciling: every input to the ratios the app shows.
CHECK_METRICS: tuple[str, ...] = (
    "revenue", "gross_profit", "operating_income", "net_income",
    "total_assets", "stockholders_equity", "operating_cf", "capex",
)

# Relative spread → severity. Sources derive from one filing, so anything
# past rounding is a real discrepancy; 1% is where it starts to move a ratio.
AGREE_PCT = 0.001
INFO_PCT = 0.01
WARN_PCT = 0.05

_SEVERITY_ORDER = {"ok": 0, "info": 1, "warn": 2, "error": 3}

# Cells a source defines differently, so comparing them would flag a
# disagreement that isn't one. yfinance's A-share 成本 is not 营业成本 (for
# 600066 FY2025 it implies a ¥1.49B gross profit against the filing's
# ¥10.00B, which 主营业务构成 confirms), so its cost line and everything
# derived from it are excluded rather than compared.
INCOMPARABLE: dict[str, frozenset[str]] = {
    # yfinance's A-share 成本 is not 营业成本 (for 600066 FY2025 it implies a
    # ¥1.49B gross profit against the filing's ¥10.00B, which 主营业务构成
    # confirms), and its 营业利润 is built differently again — it diverges from
    # the filing by 0.6–30% across 2022-2025 while Tushare and 东方财富 agree
    # to the cent. The blend never shows these yfinance cells for an A-share,
    # so comparing them would only raise a permanent false alarm.
    "yfinance": frozenset({"gross_profit", "cost_of_revenue", "operating_income"}),
}


def severity_for(spread_pct: float | None, *, sign_flip: bool = False) -> str:
    if sign_flip:
        return "error"
    if spread_pct is None:
        return "ok"
    if spread_pct <= AGREE_PCT:
        return "ok"
    if spread_pct <= INFO_PCT:
        return "info"
    if spread_pct <= WARN_PCT:
        return "warn"
    return "error"


def _spread(values: list[float]) -> tuple[float | None, bool]:
    """(relative spread, sign disagreement) across ≥2 values."""
    if len(values) < 2:
        return None, False
    lo, hi = min(values), max(values)
    sign_flip = any(v > 0 for v in values) and any(v < 0 for v in values)
    scale = max(abs(v) for v in values)
    if scale == 0:
        return (0.0 if lo == hi else 1.0), sign_flip
    return (hi - lo) / scale, sign_flip


def _value(row: dict | None, grid: str, metric: str, period: str) -> float | None:
    entry = (((row or {}).get(grid) or {}).get(metric) or {}).get(period)
    return None if entry is None else entry.get("val")


def compare_rows(rows: dict[str, dict | None], *, grid: str = "annual",
                 metrics: tuple[str, ...] = CHECK_METRICS,
                 last_n: int | None = 8) -> list[dict]:
    """One entry per (period, metric) that at least two sources report.

    `rows` maps a source name to a source row (the shape
    `ashare_adapter.ashare_source_row` returns). Periods are whatever keys
    those rows use — fiscal years for `annual`, period ends for `quarterly`.
    """
    periods: set[str] = set()
    for row in rows.values():
        for metric in metrics:
            periods |= set((((row or {}).get(grid) or {}).get(metric) or {}).keys())
    ordered = sorted(periods)[-last_n:] if last_n else sorted(periods)

    out = []
    for period in ordered:
        for metric in metrics:
            values = {name: _value(row, grid, metric, period) for name, row in rows.items()
                      if metric not in INCOMPARABLE.get(name, frozenset())}
            present = {k: v for k, v in values.items() if v is not None}
            if len(present) < 2:
                continue
            spread, sign_flip = _spread(list(present.values()))
            out.append({
                "grid": grid,
                "period": period,
                "metric": metric,
                "values": present,
                "spread_pct": spread,
                "severity": severity_for(spread, sign_flip=sign_flip),
            })
    return out


def reconcile_valuation(snapshot: dict | None, daily_basic: dict | None,
                        *, per_usd: float | None = None) -> list[dict]:
    """Our computed valuation ratios vs Tushare's published ones.

    Tushare reports 总市值 in 万元 and its P/E and P/B on the same basis we
    do, so these should line up to rounding. Market cap needs `per_usd`
    because ours is in USD (statements are converted) while theirs is yuan.
    """
    snapshot, daily_basic = snapshot or {}, daily_basic or {}
    ours_mcap = _f(snapshot.get("market_cap"))
    if ours_mcap is not None and per_usd:
        ours_mcap = ours_mcap * per_usd
    theirs_mv = _f(daily_basic.get("total_mv"))
    pairs = [
        ("market_cap", ours_mcap, None if theirs_mv is None else theirs_mv * 10_000),
        ("ttm_pe", snapshot.get("ttm_pe"), _f(daily_basic.get("pe_ttm"))),
        ("static_pe", snapshot.get("static_pe"), _f(daily_basic.get("pe"))),
        ("pb", snapshot.get("pb"), _f(daily_basic.get("pb"))),
    ]
    out = []
    for name, ours, theirs in pairs:
        if ours is None or theirs is None:
            continue
        spread, sign_flip = _spread([float(ours), theirs])
        out.append({
            "metric": name,
            "ours": float(ours),
            "tushare": theirs,
            "spread_pct": spread,
            "severity": severity_for(spread, sign_flip=sign_flip),
            "as_of": daily_basic.get("trade_date"),
        })
    return out


def _f(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def worst_severity(report: dict | None) -> str:
    cells = list((report or {}).get("cells") or []) + list((report or {}).get("valuation") or [])
    if not cells:
        return "ok"
    return max((c.get("severity", "ok") for c in cells), key=lambda s: _SEVERITY_ORDER.get(s, 0))


# A disagreement about a period this old is almost always a restatement one
# source picked up and another didn't (长安汽车's 2020 total assets: ¥120.92B
# vs ¥118.27B). Worth recording, not worth a banner on today's page.
STALE_YEARS = 3


def as_issues(report: dict | None, *, today: str | None = None) -> list[dict]:
    """The report's findings as `app/tools/validation.py` issues, so a real
    disagreement surfaces through the banner the page already has.

    This lives here rather than as a validation rule because the rules are
    pure functions of (sec_row, analyzed_row) and this needs a third file;
    `scripts/validate_companies.py` merges the result in.
    """
    report = report or {}
    this_year = int((today or report.get("as_of") or date.today().isoformat())[:4])
    out = []
    for cell in sorted((report.get("disagreements") or []),
                       key=lambda c: -(c.get("spread_pct") or 0))[:5]:
        vals = ", ".join(f"{k}={v:,.0f}" for k, v in (cell.get("values") or {}).items())
        try:
            stale = this_year - int(str(cell["period"])[:4]) > STALE_YEARS
        except ValueError:
            stale = False
        out.append({
            "severity": "info" if stale else cell["severity"],
            "rule": "source_disagreement",
            "detail": f"{cell['metric']} {cell['period']} differs by "
                      f"{(cell.get('spread_pct') or 0) * 100:.2f}% across sources ({vals})",
        })
    for v in report.get("valuation") or []:
        if v.get("severity") in ("warn", "error"):
            out.append({
                "severity": v["severity"],
                "rule": "valuation_reconcile",
                "detail": f"our {v['metric']} {v['ours']:,.4g} vs Tushare {v['tushare']:,.4g} "
                          f"({(v.get('spread_pct') or 0) * 100:.2f}%)",
            })
    return out


def build_report(ticker: str, rows: dict[str, dict | None], *,
                 snapshot: dict | None = None, daily_basic: dict | None = None,
                 per_usd: float | None = None, today: str | None = None) -> dict:
    """The per-ticker reconciliation written to data/ashare_xcheck/<T>.json."""
    cells = (compare_rows(rows, grid="annual", last_n=6)
             + compare_rows(rows, grid="quarterly", last_n=8))
    report = {
        "ticker": ticker.upper(),
        "as_of": today or date.today().isoformat(),
        "sources": sorted(k for k, v in rows.items() if v),
        "cells": cells,
        "valuation": reconcile_valuation(snapshot, daily_basic, per_usd=per_usd),
    }
    report["worst"] = worst_severity(report)
    report["disagreements"] = [c for c in cells if c["severity"] != "ok"]
    return report
