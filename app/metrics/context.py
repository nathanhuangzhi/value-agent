"""Build the base series a user expression evaluates against — from the
same USD-converted, three-source-blended statements the company page
shows, so custom numbers always agree with the app's tables."""
from __future__ import annotations

from app.api.routes import _blended_annual, _blended_quarterly, _gap_fill_row
from app.data import repo
from app.metrics.expr import ALIASES, Context
from app.metrics.series import values_for
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


def _align(points: dict[str, float | None], periods: list[str], *, annual: bool) -> list[float | None]:
    """A user series onto grid periods: annual by fiscal-year label, quarterly by
    the quarter's year-month (a point dated 2026-06-30 matches the grid's 2026-06 quarter)."""
    if annual:
        by_year = {k[:4]: v for k, v in points.items()}          # grid labels are fiscal-year-end dates
        return [by_year.get(p[:4]) for p in periods]
    by_month = {k[:7]: v for k, v in points.items()}
    return [by_month.get(p[:7]) for p in periods]


def _to_usd(points: dict[str, float | None], currency: str | None) -> dict[str, float | None]:
    """Money series in a reporting currency are converted with the same daily
    rates as the statements, so $gmv and revenue share a unit."""
    if not currency or currency.upper() == "USD":
        return points
    rate = (repo.fx().get(currency.upper()) or {}).get("per_usd")
    if not rate:
        return points
    return {k: (None if v is None else v / rate) for k, v in points.items()}


def _user_series(user_id: int | None, ticker: str, q_periods: list[str], a_periods: list[str]) -> tuple[dict, dict]:
    if user_id is None:
        return {}, {}
    q_vals: dict[str, list[float | None]] = {}
    a_vals: dict[str, list[float | None]] = {}
    for name, s in values_for(user_id, ticker).items():
        if s["unit"] == "money":
            s = {**s, "points": _to_usd(s["points"], s.get("currency"))}
        if s["grid"] == "annual":
            a_vals[name] = _align(s["points"], a_periods, annual=True)
            q_vals[name] = [None] * len(q_periods)          # annual-only series: use $name.fy on a quarterly grid
        else:
            q_vals[name] = _align(s["points"], q_periods, annual=False)
            # annual view of a quarterly series: the four quarters of each fiscal year, when complete
            a_vals[name] = []
            for fy in a_periods:
                qs = [v for k, v in s["points"].items() if k[:4] == fy[:4]]
                a_vals[name].append(sum(qs) if len(qs) == 4 and all(v is not None for v in qs) else None)
    return q_vals, a_vals


def build_context(ticker: str, *, grid: str = "quarterly", last_n: int | None = None, user_id: int | None = None) -> Context | None:
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
    q = _blended_quarterly(sec_row, yf_row, last_n=40)     # charts may look back ten years; TTM needs history
    a = _blended_annual(sec_row, yf_row)
    q_periods, a_periods = _periods(q), _periods(a)
    uq, ua = _user_series(user_id, t, q_periods, a_periods)
    if grid == "annual":
        periods = a_periods[-last_n:] if last_n else a_periods
        cut = len(a_periods) - len(periods)
        return Context(periods=periods, grid="annual", values=_fill_values(a, periods, ph),
                       annual_periods=periods, annual_values=_fill_values(a, periods, ph),
                       user_values={k: v[cut:] for k, v in ua.items()}, user_annual={k: v[cut:] for k, v in ua.items()})
    periods = q_periods[-last_n:] if last_n else q_periods
    cut = len(q_periods) - len(periods)
    return Context(periods=periods, grid="quarterly", values=_fill_values(q, periods, ph),
                   annual_periods=a_periods, annual_values=_fill_values(a, a_periods, ph),
                   user_values={k: v[cut:] for k, v in uq.items()}, user_annual=ua)
