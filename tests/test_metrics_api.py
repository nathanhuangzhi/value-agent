import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.metrics import service
from app.metrics.expr import Context

CTX = Context(periods=["2026-03-31", "2026-06-30"], grid="quarterly",
              values={"revenue": [100, 120], "fcf": [10, 6], "mcap": [1000, 1200], "net_income": [8, 9]})


@pytest.fixture
def client(monkeypatch):
    from app.auth import service as auth
    sent = {}
    monkeypatch.setattr(auth, "_send_code", lambda email, code: sent.__setitem__(email, code))
    monkeypatch.setattr(service, "build_context", lambda ticker, grid="quarterly", last_n=None: CTX if ticker.upper() == "VIPS" else None)
    c = TestClient(app)
    c.post("/auth/code", json={"email": "m@x.io"})
    token = c.post("/auth/verify", json={"email": "m@x.io", "code": sent["m@x.io"]}).json()["token"]
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def test_metric_crud_and_evaluation(client):
    r = client.post("/me/metrics", json={"name": "FCF margin", "expr": "fcf / revenue"})
    assert r.status_code == 200 and r.json()["format"] == "ratio"
    mid = r.json()["id"]
    assert client.post("/me/metrics", json={"name": "bad", "expr": "equity.ttm"}).status_code == 422
    assert [m["name"] for m in client.get("/me/metrics").json()["metrics"]] == ["FCF margin"]
    assert client.put(f"/me/metrics/{mid}", json={"format": "pct", "name": "FCF %"}).json()["format"] == "pct"

    custom = client.get("/me/tickers/vips/custom.json").json()
    m = custom["metrics"][0]
    assert m["name"] == "FCF %" and m["latest"] == pytest.approx(0.05) and m["series"][0]["value"] == pytest.approx(0.1)
    none = client.get("/me/tickers/qdel/custom.json").json()["metrics"][0]
    assert none["error"] == "no statements on file"

    pv = client.post("/me/metrics/preview", json={"expr": "pe", "ticker": "VIPS"}).json()
    assert pv["series"][-1]["value"] is None            # ttm needs four quarters
    assert "error" in client.post("/me/metrics/preview", json={"expr": "foo", "ticker": "VIPS"}).json()

    latest = client.get(f"/me/metrics/{mid}/latest", params={"tickers": "VIPS,QDEL"}).json()["values"]
    assert latest == {"VIPS": pytest.approx(0.05), "QDEL": None}

    assert client.delete(f"/me/metrics/{mid}").json() == {"deleted": mid}
    assert client.delete(f"/me/metrics/{mid}").status_code == 404
    assert client.get("/me/metrics/aliases").json()["derived"]["pe"] == "mcap / net_income.ttm"


def test_metrics_are_private(client):
    client.post("/me/metrics", json={"name": "x", "expr": "fcf"})
    assert TestClient(app).get("/me/metrics").status_code == 401
