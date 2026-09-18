"""The signed-in user's own metrics and charts — the assistant designs
them in conversation, saves them, and they keep evaluating against fresh
data on every company page."""
from __future__ import annotations

import json

from app.ai.tools.registry import tool
from app.metrics import charts, service
from app.metrics.expr import ALIASES, DERIVED, ExprError

VOCAB = ("Metric names: " + ", ".join(ALIASES) + ". Shorthands: " + ", ".join(f"{k} = {v}" for k, v in DERIVED.items())
         + ". Suffixes: .q (single quarter, default) .ttm (trailing four quarters, flows only) .fy (latest fiscal year) "
           ".yoy (change vs a year ago) .abs. Functions: abs(x) max(a,b) min(a,b) avg(x,n) sum(x,n) lag(x,n). "
           "Operators + - * / ( ) < <= > >= == != and or not. Blank when an input is missing or ÷0.")


def _fmt(v, fmt: str) -> str:
    if v is None:
        return "—"
    if fmt == "bool":
        return "yes" if v else "no"
    if fmt == "pct":
        return f"{v * 100:.1f}%"
    if fmt == "ratio":
        return f"{v:.2f}x"
    if fmt == "money":
        a = abs(v)
        s = f"{a / 1e9:.2f}B" if a >= 1e9 else f"{a / 1e6:.1f}M" if a >= 1e6 else f"{a:,.0f}"
        return ("-" if v < 0 else "") + "$" + s
    return f"{v:,.3f}"


@tool(
    "metric_vocabulary",
    description="The vocabulary of the metric expression language (names, suffixes, functions) — read it before "
                "writing an expression for the user.",
    params={}, required=[], status="Reading the metric vocabulary…", marks_company=False,
)
def metric_vocabulary() -> str:
    return VOCAB


@tool(
    "preview_metric",
    description="Evaluate an expression for one company before saving it: returns the last eight quarters and the "
                "latest value, or the parse error. Use it to check a formula and show the user real numbers.",
    params={"expr": {"type": "string"}, "ticker": {"type": "string"},
            "grid": {"type": "string", "enum": ["quarterly", "annual"]}},
    required=["expr", "ticker"], status="Evaluating {expr} on {ticker}…", marks_company=False, needs_user=True,
)
def preview_metric(expr: str, ticker: str, grid: str | None, user_id: int) -> str:
    r = service.evaluate_expr(expr, ticker, grid="annual" if grid == "annual" else "quarterly")
    if "error" in r:
        return f"ERROR: {r['error']}"
    fmt = r["format"]
    rows = ", ".join(f"{s['period']}: {_fmt(s['value'], fmt)}" for s in r["series"])
    return f"{expr} on {ticker.upper()} (format {fmt}) — latest {_fmt(r['latest'], fmt)}\n{rows}"


@tool(
    "list_my_metrics",
    description="The user's saved custom metrics (id, name, expression, format).",
    params={}, required=[], status="Listing your metrics…", marks_company=False, needs_user=True,
)
def list_my_metrics(user_id: int) -> str:
    ms = service.list_metrics(user_id)
    if not ms:
        return "No saved metrics yet."
    return "\n".join(f"#{m['id']} {m['name']}: {m['expr']} [{m['format']}]" for m in ms)


@tool(
    "save_metric",
    description="Create a custom metric for the user (or update one when metric_id is given). It is then shown "
                "on every company page and re-evaluated whenever data updates. format: number | ratio | pct | "
                "money | bool (omit to auto-detect). Confirm the formula with a preview first.",
    params={"name": {"type": "string"}, "expr": {"type": "string"}, "format": {"type": "string"},
            "metric_id": {"type": "integer"}},
    required=["name", "expr"], status="Saving metric “{name}”…", marks_company=False, needs_user=True,
)
def save_metric(name: str, expr: str, format: str | None, metric_id: int | None, user_id: int) -> str:
    try:
        if metric_id:
            m = service.update_metric(user_id, metric_id, name=name, expr=expr, fmt=format)
            if not m:
                return f"ERROR: metric #{metric_id} not found"
            return f"Updated metric #{m['id']} {m['name']}: {m['expr']} [{m['format']}]"
        m = service.create_metric(user_id, name, expr, format)
        return f"Saved metric #{m['id']} {m['name']}: {m['expr']} [{m['format']}]. Show it inline with {{{{metric:{m['id']}:TICKER}}}}."
    except ExprError as e:
        return f"ERROR: {e}"


@tool(
    "delete_metric",
    description="Delete one of the user's custom metrics by id.",
    params={"metric_id": {"type": "integer"}}, required=["metric_id"],
    status="Deleting metric…", marks_company=False, needs_user=True,
)
def delete_metric(metric_id: int, user_id: int) -> str:
    return f"Deleted metric #{metric_id}" if service.delete_metric(user_id, metric_id) else f"ERROR: metric #{metric_id} not found"


@tool(
    "list_my_charts",
    description="The user's saved charts (id, title, spec).",
    params={}, required=[], status="Listing your charts…", marks_company=False, needs_user=True,
)
def list_my_charts(user_id: int) -> str:
    cs = charts.list_charts(user_id)
    if not cs:
        return "No saved charts yet."
    return "\n".join(f"#{c['id']} {c['title']}: {json.dumps(c['spec'], ensure_ascii=False)}" for c in cs)


@tool(
    "save_chart",
    description="Create a chart for the user (or update one when chart_id is given). A chart is a title plus 1–4 "
                "series drawn for whichever company page it is viewed on. spec: {title, period: quarterly|annual, "
                "last_n: 2–40, series: [{expr, label, kind: line|bar, axis: left|right, format?}]}. Put two "
                "differently-scaled series on different axes (e.g. money on left, a margin on right). After saving, "
                "show it in your reply with the token {{chart:ID:TICKER}} on its own line.",
    params={"spec": {"type": "object"}, "chart_id": {"type": "integer"}},
    required=["spec"], status="Saving chart…", marks_company=False, needs_user=True,
)
def save_chart(spec: dict | None, chart_id: int | None, user_id: int) -> str:
    if not isinstance(spec, dict):
        return "ERROR: spec must be an object"
    try:
        if chart_id:
            c = charts.update_chart(user_id, chart_id, spec=spec)
            if not c:
                return f"ERROR: chart #{chart_id} not found"
            return f"Updated chart #{c['id']} “{c['title']}”. Show it with {{{{chart:{c['id']}:TICKER}}}}."
        c = charts.create_chart(user_id, spec)
        return f"Saved chart #{c['id']} “{c['title']}”. Show it with {{{{chart:{c['id']}:TICKER}}}}."
    except charts.ChartError as e:
        return f"ERROR: {e}"


@tool(
    "delete_chart",
    description="Delete one of the user's charts by id.",
    params={"chart_id": {"type": "integer"}}, required=["chart_id"],
    status="Deleting chart…", marks_company=False, needs_user=True,
)
def delete_chart(chart_id: int, user_id: int) -> str:
    return f"Deleted chart #{chart_id}" if charts.delete_chart(user_id, chart_id) else f"ERROR: chart #{chart_id} not found"


@tool(
    "arrange",
    description="Set the display order of the user's metrics and charts on company pages: pass the ids in the "
                "order they should appear.",
    params={"metric_ids": {"type": "array", "items": {"type": "integer"}},
            "chart_ids": {"type": "array", "items": {"type": "integer"}}},
    required=[], status="Arranging your page…", marks_company=False, needs_user=True,
)
def arrange(metric_ids: list[int] | None, chart_ids: list[int] | None, user_id: int) -> str:
    for i, mid in enumerate(metric_ids or []):
        service.update_metric(user_id, mid, position=i)
    for i, cid in enumerate(chart_ids or []):
        charts.update_chart(user_id, cid, position=i)
    return "Order saved."
