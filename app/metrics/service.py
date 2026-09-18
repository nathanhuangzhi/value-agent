"""User metrics: CRUD in app.db + evaluation against a company."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import connect
from app.metrics.context import build_context
from app.metrics.expr import ExprError, evaluate, guess_format, validate

FORMATS = ("number", "ratio", "pct", "money", "bool")
MAX_METRICS = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r) -> dict:
    return {"id": r["id"], "name": r["name"], "expr": r["expr"], "format": r["format"], "position": r["position"],
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def list_metrics(user_id: int) -> list[dict]:
    with connect() as cx:
        return [_row(r) for r in cx.execute("SELECT * FROM metrics WHERE user_id = ? ORDER BY position, id", (user_id,))]


def get_metric(user_id: int, metric_id: int) -> dict | None:
    with connect() as cx:
        r = cx.execute("SELECT * FROM metrics WHERE user_id = ? AND id = ?", (user_id, metric_id)).fetchone()
    return _row(r) if r else None


def create_metric(user_id: int, name: str, expr: str, fmt: str | None) -> dict:
    node = validate(expr)
    fmt = fmt if fmt in FORMATS else guess_format(node)
    with connect() as cx:
        n = cx.execute("SELECT COUNT(*) FROM metrics WHERE user_id = ?", (user_id,)).fetchone()[0]
        if n >= MAX_METRICS:
            raise ExprError(f"at most {MAX_METRICS} metrics")
        now = _now()
        cur = cx.execute("INSERT INTO metrics (user_id, name, expr, format, position, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                         (user_id, name.strip()[:60], expr.strip(), fmt, n, now, now))
        r = cx.execute("SELECT * FROM metrics WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row(r)


def update_metric(user_id: int, metric_id: int, *, name: str | None = None, expr: str | None = None,
                  fmt: str | None = None, position: int | None = None) -> dict | None:
    if expr is not None:
        validate(expr)
    sets, args = [], []
    for col, val in (("name", name.strip()[:60] if name else None), ("expr", expr.strip() if expr else None),
                     ("format", fmt if fmt in FORMATS else None), ("position", position)):
        if val is not None:
            sets.append(f"{col} = ?")
            args.append(val)
    if not sets:
        return get_metric(user_id, metric_id)
    sets.append("updated_at = ?")
    args += [_now(), user_id, metric_id]
    with connect() as cx:
        cx.execute(f"UPDATE metrics SET {', '.join(sets)} WHERE user_id = ? AND id = ?", args)  # noqa: S608 (columns are constants)
    return get_metric(user_id, metric_id)


def delete_metric(user_id: int, metric_id: int) -> bool:
    with connect() as cx:
        cur = cx.execute("DELETE FROM metrics WHERE user_id = ? AND id = ?", (user_id, metric_id))
        return cur.rowcount > 0


# ---- evaluation ----------------------------------------------------------------

def evaluate_expr(expr: str, ticker: str, *, grid: str = "quarterly", last_n: int = 8) -> dict:
    """{series:[{period, value}], latest, format} or {error}."""
    try:
        node = validate(expr)
    except ExprError as e:
        return {"error": str(e)}
    ctx = build_context(ticker, grid=grid)
    if ctx is None:
        return {"error": f"no statements on file for {ticker.upper()}"}
    try:
        values = evaluate(node, ctx)
    except ExprError as e:
        return {"error": str(e)}
    series = [{"period": p, "value": v} for p, v in zip(ctx.periods, values, strict=True)][-last_n:]
    latest = next((s["value"] for s in reversed(series) if s["value"] is not None), None)
    return {"series": series, "latest": latest, "format": guess_format(node)}


def evaluate_user_metrics(user_id: int, ticker: str, *, last_n: int = 8) -> list[dict]:
    """Every metric of the user against one company (one context build, N evaluations)."""
    metrics = list_metrics(user_id)
    if not metrics:
        return []
    ctx = build_context(ticker)
    out = []
    for m in metrics:
        entry = {**m, "series": [], "latest": None, "error": None}
        if ctx is None:
            entry["error"] = "no statements on file"
        else:
            try:
                values = evaluate(validate(m["expr"]), ctx)
                entry["series"] = [{"period": p, "value": v} for p, v in zip(ctx.periods, values, strict=True)][-last_n:]
                entry["latest"] = next((s["value"] for s in reversed(entry["series"]) if s["value"] is not None), None)
            except ExprError as e:
                entry["error"] = str(e)
        out.append(entry)
    return out


def latest_for_tickers(user_id: int, metric_id: int, tickers: list[str]) -> dict[str, float | None]:
    """One metric's latest value for many companies (industry-row column)."""
    m = get_metric(user_id, metric_id)
    if not m:
        return {}
    node = validate(m["expr"])
    out: dict[str, float | None] = {}
    for t in tickers:
        ctx = build_context(t)
        if ctx is None:
            out[t] = None
            continue
        values = evaluate(node, ctx)
        out[t] = next((v for v in reversed(values) if v is not None), None)
    return out


__all__ = ["FORMATS", "list_metrics", "get_metric", "create_metric", "update_metric", "delete_metric",
           "evaluate_expr", "evaluate_user_metrics", "latest_for_tickers", "json"]
