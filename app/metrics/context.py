"""Build the base series a user expression evaluates against — from the
same USD-converted, three-source-blended statements the company page
shows, so custom numbers always agree with the app's tables."""
from __future__ import annotations

from app.api.routes import _blended_annual, _blended_quarterly, _gap_fill_row
from app.data import repo
from app.metrics.expr import ALIASES, Context
from app.tools.report.ratios import _close_at_or_before

_STATEMENT_OF = {"flow": None, "stock": "balance_sheet", "per_share": "income_statement", "market": None}


def _series(stmts: dict, item: str, periods: list[str]) -> list[float | None]:
    by_period: dict[str, float | None] = {}
    for stmt in ("income_statement", "balance_sheet", "cash_flow"):
        for p in stmts.get(stmt) or []:
            v = (p.get("items") or {}).get(item)
            if v is not None and p.get("period") not in by_period:
                by_period[p["period"]] = v
    return [by_period.get(p) for p in periods]


def _periods(stmts: dict) -> list[str]:
    out: set[str] = set()
    for stmt in ("income_statement", "balance_sheet", "cash_flow"):
        out |= {p["period"] for p in stmts.get(stmt) or [] if p.get("period")}
    return sorted(out)


def _fill_values(stmts: dict, periods: list[str], price_history: list[dict]) -> dict[str, list[float | None]]:
    values: dict[str, list[float | None]] = {}
    for alias, (item, kind) in ALIASES.items():
        if kind == "market":
            continue
        values[alias] = _series(stmts, item, periods)
    price = [_close_at_or_before(price_history, p if len(p) > 4 else f"{p}-12-31") for p in periods]
    shares = values.get("shares") or [None] * len(periods)
    values["price"] = price
    values["mcap"] = [None if (pr is None or not sh) else pr * sh for pr, sh in zip(price, shares, strict=True)]
    return values


def build_context(ticker: str, *, grid: str = "quarterly", last_n: int | None = None) -> Context | None:
    """None when the company has no statements on file."""
    t = ticker.upper()
    analyzed = repo.analyzed().get(t)
    if not analyzed:
        return None
    sec_row = repo.sec().get(t)
    yf_row = _gap_fill_row(t, repo.yfinance().get(t))
    if not (sec_row or yf_row):
        return None
    ph = (analyzed.get("price_history") or {}).get("data") or []
    q = _blended_quarterly(sec_row, yf_row)
    a = _blended_annual(sec_row, yf_row)
    q_periods, a_periods = _periods(q), _periods(a)
    if grid == "annual":
        periods = a_periods[-last_n:] if last_n else a_periods
        return Context(periods=periods, grid="annual", values=_fill_values(a, periods, ph),
                       annual_periods=periods, annual_values=_fill_values(a, periods, ph))
    periods = q_periods[-last_n:] if last_n else q_periods
    return Context(periods=periods, grid="quarterly", values=_fill_values(q, periods, ph),
                   annual_periods=a_periods, annual_values=_fill_values(a, a_periods, ph))
