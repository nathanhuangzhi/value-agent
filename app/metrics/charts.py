"""User charts: a title plus 1–4 expression series and how to draw them.

    {"title": "FCF and FCF margin", "period": "quarterly", "last_n": 12,
     "series": [{"expr": "fcf", "label": "FCF", "kind": "bar", "axis": "left", "format": "money"},
                {"expr": "fcf / revenue", "label": "FCF margin", "kind": "line", "axis": "right", "format": "pct"}]}

Specs are validated on write (expressions must parse) and rendered on
demand for a company: `render(user_id, chart_id, ticker)` → periods +
per-series values, ready for the app's SeriesChart.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.db import connect
from app.metrics.context import build_context
from app.metrics.expr import ExprError, evaluate, guess_format, validate

MAX_CHARTS = 30


class SeriesSpec(BaseModel):
    expr: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=40)
    kind: Literal["line", "bar"] = "line"
    axis: Literal["left", "right"] = "left"
    format: Literal["number", "ratio", "pct", "money", "bool"] | None = None

    @field_validator("expr")
    @classmethod
    def _parses(cls, v: str) -> str:
        validate(v)          # raises ExprError → pydantic wraps it as a ValueError
        return v.strip()


class ChartSpec(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    period: Literal["quarterly", "annual"] = "quarterly"
    last_n: int = Field(default=12, ge=2, le=40)
    series: list[SeriesSpec] = Field(min_length=1, max_length=4)


class ChartError(ValueError):
    pass


def parse_spec(spec: dict) -> ChartSpec:
    try:
        return ChartSpec.model_validate(spec)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", ()))
        msg = first.get("msg", "invalid chart")
        raise ChartError(f"{loc}: {msg}" if loc else msg) from e


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r) -> dict:
    return {"id": r["id"], "title": r["title"], "spec": json.loads(r["spec"]), "position": r["position"],
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def list_charts(user_id: int) -> list[dict]:
    with connect() as cx:
        return [_row(r) for r in cx.execute("SELECT * FROM charts WHERE user_id = ? ORDER BY position, id", (user_id,))]


def get_chart(user_id: int, chart_id: int) -> dict | None:
    with connect() as cx:
        r = cx.execute("SELECT * FROM charts WHERE user_id = ? AND id = ?", (user_id, chart_id)).fetchone()
    return _row(r) if r else None


def create_chart(user_id: int, spec: dict) -> dict:
    parsed = parse_spec(spec)
    with connect() as cx:
        n = cx.execute("SELECT COUNT(*) FROM charts WHERE user_id = ?", (user_id,)).fetchone()[0]
        if n >= MAX_CHARTS:
            raise ChartError(f"at most {MAX_CHARTS} charts")
        now = _now()
        cur = cx.execute("INSERT INTO charts (user_id, title, spec, position, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                         (user_id, parsed.title, parsed.model_dump_json(), n, now, now))
        r = cx.execute("SELECT * FROM charts WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row(r)


def update_chart(user_id: int, chart_id: int, spec: dict | None = None, position: int | None = None) -> dict | None:
    sets: list[str] = []
    args: list[object] = []
    if spec is not None:
        parsed = parse_spec(spec)
        sets += ["title = ?", "spec = ?"]
        args += [parsed.title, parsed.model_dump_json()]
    if position is not None:
        sets.append("position = ?")
        args.append(position)
    if not sets:
        return get_chart(user_id, chart_id)
    sets.append("updated_at = ?")
    args += [_now(), user_id, chart_id]
    with connect() as cx:
        cx.execute(f"UPDATE charts SET {', '.join(sets)} WHERE user_id = ? AND id = ?", args)  # noqa: S608
    return get_chart(user_id, chart_id)


def delete_chart(user_id: int, chart_id: int) -> bool:
    with connect() as cx:
        return cx.execute("DELETE FROM charts WHERE user_id = ? AND id = ?", (user_id, chart_id)).rowcount > 0


def render_spec(spec: ChartSpec, ticker: str, user_id: int | None = None) -> dict:
    """{title, period, periods, series:[{label, kind, axis, format, values}]} or {error}."""
    ctx = build_context(ticker, grid=spec.period, last_n=spec.last_n, user_id=user_id)
    if ctx is None:
        return {"title": spec.title, "error": f"no statements on file for {ticker.upper()}"}
    out = []
    for s in spec.series:
        try:
            node = validate(s.expr)
            values = evaluate(node, ctx)
        except ExprError as e:
            return {"title": spec.title, "error": f"{s.label}: {e}"}
        out.append({"label": s.label, "kind": s.kind, "axis": s.axis, "format": s.format or guess_format(node), "values": values})
    return {"title": spec.title, "period": spec.period, "periods": ctx.periods, "series": out}


def render(user_id: int, chart_id: int, ticker: str) -> dict | None:
    chart = get_chart(user_id, chart_id)
    if not chart:
        return None
    return {"id": chart_id, **render_spec(ChartSpec.model_validate(chart["spec"]), ticker, user_id)}


def render_all(user_id: int, ticker: str) -> list[dict]:
    return [{"id": ch["id"], "position": ch["position"], **render_spec(ChartSpec.model_validate(ch["spec"]), ticker, user_id)}
            for ch in list_charts(user_id)]


__all__ = ["ChartError", "ChartSpec", "SeriesSpec", "parse_spec", "list_charts", "get_chart", "create_chart",
           "update_chart", "delete_chart", "render", "render_all", "render_spec"]
