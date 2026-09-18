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
    monkeypatch.setattr(service, "build_context", lambda ticker, grid="quarterly", last_n=None: CTX)
    monkeypatch.setattr(charts, "build_context", lambda ticker, grid="quarterly", last_n=None: CTX)
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
