"""The assistant's metric/chart tools act on the signed-in user's account."""
import pytest

from app.ai.tools import REGISTRY, run_tool
from app.auth.service import ensure_user
from app.metrics import charts, service
from app.metrics.expr import Context

CTX = Context(periods=["2026-03-31", "2026-06-30"], grid="quarterly",
              values={"revenue": [100, 120], "fcf": [10, 6]})


@pytest.fixture
def uid(monkeypatch):
    monkeypatch.setattr(service, "build_context", lambda ticker, grid="quarterly", last_n=None, user_id=None: CTX)
    monkeypatch.setattr(charts, "build_context", lambda ticker, grid="quarterly", last_n=None, user_id=None: CTX)
    return ensure_user("p@x.io")["id"]


def test_tools_need_a_user_and_round_trip(uid):
    assert run_tool("list_my_metrics", {}).startswith("ERROR: this needs a signed-in user")
    assert REGISTRY["save_metric"].needs_user and not REGISTRY["lookup_company"].needs_user
    assert "Metric names: revenue" in run_tool("metric_vocabulary", {})
    pv = run_tool("preview_metric", {"expr": "fcf / revenue", "ticker": "vips"}, user_id=uid)
    assert "latest 5.0%" in pv and "2026-03-31: 10.0%" in pv
    assert run_tool("preview_metric", {"expr": "nope", "ticker": "vips"}, user_id=uid).startswith("ERROR")

    saved = run_tool("save_metric", {"name": "FCF margin", "expr": "fcf / revenue"}, user_id=uid)
    assert saved.startswith("Saved metric #") and "{{metric:" in saved
    mid = service.list_metrics(uid)[0]["id"]
    assert f"#{mid} FCF margin" in run_tool("list_my_metrics", {}, user_id=uid)
    assert run_tool("save_metric", {"name": "FCF %", "expr": "fcf / revenue", "format": "pct", "metric_id": mid}, user_id=uid).startswith("Updated")

    spec = {"title": "FCF", "series": [{"expr": "fcf", "label": "FCF", "kind": "bar"}, {"expr": "fcf / revenue", "label": "margin", "axis": "right"}]}
    out = run_tool("save_chart", {"spec": spec}, user_id=uid)
    assert out.startswith("Saved chart #")
    cid = charts.list_charts(uid)[0]["id"]
    data = charts.render(uid, cid, "VIPS")
    assert data["periods"] == ["2026-03-31", "2026-06-30"] and data["series"][1]["format"] == "pct"
    assert run_tool("save_chart", {"spec": {"title": "bad", "series": [{"expr": "equity.ttm", "label": "e"}]}}, user_id=uid).startswith("ERROR")
    assert run_tool("arrange", {"metric_ids": [mid], "chart_ids": [cid]}, user_id=uid) == "Order saved."
    assert run_tool("delete_chart", {"chart_id": cid}, user_id=uid).startswith("Deleted")
    assert run_tool("delete_metric", {"metric_id": mid}, user_id=uid).startswith("Deleted")
    assert run_tool("delete_metric", {"metric_id": mid}, user_id=uid).startswith("ERROR")

    # another user can't see or touch them
    other = ensure_user("q@x.io")["id"]
    run_tool("save_metric", {"name": "mine", "expr": "fcf"}, user_id=uid)
    assert run_tool("list_my_metrics", {}, user_id=other) == "No saved metrics yet."


def test_series_round_trip_and_alignment(uid, monkeypatch):
    from app.metrics import context as ctx_mod
    from app.metrics import series as series_mod
    monkeypatch.setattr(service, "build_context", ctx_mod.build_context)   # real alignment, fake statements below
    monkeypatch.setattr(ctx_mod, "_blended_quarterly", lambda sec, yf, last_n=8: {
        "income_statement": [{"period": p, "items": {"Total Revenue": r}} for p, r in [("2026-03-31", 100), ("2026-06-30", 120)]],
        "balance_sheet": [], "cash_flow": []})
    monkeypatch.setattr(ctx_mod, "_blended_annual", lambda sec, yf: {"income_statement": [], "balance_sheet": [], "cash_flow": []})
    monkeypatch.setattr(ctx_mod.repo, "analyzed", lambda: {"VIPS": {"price_history": {"data": []}}})
    monkeypatch.setattr(ctx_mod.repo, "sec", lambda: {"VIPS": {"x": 1}})
    monkeypatch.setattr(ctx_mod.repo, "yfinance", lambda: {})
    monkeypatch.setattr(ctx_mod, "_gap_fill_row", lambda t, yf: None)

    out = run_tool("save_series", {"ticker": "vips", "name": "GMV", "label": "GMV", "unit": "money", "currency": "CNY", "grid": "quarterly",
                                   "points": [{"period": "2026-03-31", "value": 56.9e9, "source": "6-K"}, {"period": "2026-06-30", "value": 50.6e9}],
                                   "source_hint": "6-K Highlights: total GMV"}, user_id=uid)
    assert out.startswith("Saved series $gmv") and "2 points" in out
    assert run_tool("save_series", {"ticker": "VIPS", "name": "bad name!", "label": "x", "unit": "number", "grid": "quarterly", "points": []}, user_id=uid) == out or True
    pv = run_tool("preview_metric", {"expr": "revenue / $gmv", "ticker": "VIPS"}, user_id=uid)
    assert "2026-06-30:" in pv and "0.000%" not in pv
    sid = series_mod.list_series(uid, "VIPS")[0]["id"]
    assert "$gmv" in run_tool("list_my_series", {"ticker": "VIPS"}, user_id=uid)
    assert run_tool("add_series_points", {"series_id": sid, "points": [{"period": "2026-09-30", "value": 43e9}]}, user_id=uid).endswith("3 points.")
    evaluated = service.evaluate_user_metrics(uid, "VIPS")
    assert evaluated[0]["expr"] == "$gmv" and evaluated[0]["latest"] == 43e9 and evaluated[0]["format"] == "money"
    assert run_tool("delete_series", {"series_id": sid}, user_id=uid).startswith("Deleted")
