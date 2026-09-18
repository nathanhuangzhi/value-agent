from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import service
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mailbox(monkeypatch):
    sent = {}
    monkeypatch.setattr(service, "_send_code", lambda email, code: sent.__setitem__(email, code))
    return sent


def sign_in(client, mailbox, email="Nathan@Example.com"):
    assert client.post("/auth/code", json={"email": email}).status_code == 200
    code = mailbox[email.lower()]
    r = client.post("/auth/verify", json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_code_flow_creates_user_and_session(client, mailbox):
    token = sign_in(client, mailbox)
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["email"] == "nathan@example.com"
    # the code is single-use
    assert client.post("/auth/verify", json={"email": "nathan@example.com", "code": mailbox["nathan@example.com"]}).status_code == 400
    client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/me").status_code == 401


def test_bad_email_wrong_code_rate_limit(client, mailbox, monkeypatch):
    assert client.post("/auth/code", json={"email": "nope"}).status_code == 422
    client.post("/auth/code", json={"email": "a@b.co"})
    assert client.post("/auth/code", json={"email": "a@b.co"}).status_code == 429     # resend within a minute
    for _ in range(service.MAX_ATTEMPTS):
        assert client.post("/auth/verify", json={"email": "a@b.co", "code": "000000"}).status_code in (400, 429)
    assert client.post("/auth/verify", json={"email": "a@b.co", "code": mailbox["a@b.co"]}).status_code == 429
    # expiry
    monkeypatch.setattr(service, "CODE_RESEND_AFTER", timedelta(0))
    client.post("/auth/code", json={"email": "c@d.co"})
    monkeypatch.setattr(service, "_now", lambda: service.datetime.now(service.timezone.utc) + timedelta(minutes=11))
    assert client.post("/auth/verify", json={"email": "c@d.co", "code": mailbox["c@d.co"]}).status_code == 400


def test_watchlist_is_per_user_and_union_feeds_the_pipeline(client, mailbox, tmp_path, monkeypatch):
    from app.tools import watchlist as wl
    monkeypatch.setattr(wl, "WATCHLIST", tmp_path / "watchlist.json")
    monkeypatch.setattr(wl, "watchlist_rows", lambda t=None: ([], []))
    a = sign_in(client, mailbox, "a@x.io")
    b = sign_in(client, mailbox, "b@x.io")
    ha, hb = {"Authorization": f"Bearer {a}"}, {"Authorization": f"Bearer {b}"}
    assert client.put("/watchlist", json={"tickers": ["vips", "PDD"]}, headers=ha).json()["tickers"] == ["PDD", "VIPS"]
    assert client.put("/watchlist", json={"tickers": ["QDEL"]}, headers=hb).json()["tickers"] == ["QDEL"]
    assert client.get("/watchlist", headers=ha).json()["tickers"] == ["PDD", "VIPS"]
    assert wl.load_watchlist() == ["PDD", "QDEL", "VIPS"]                  # the union the pipeline reads
    client.delete("/watchlist/VIPS", headers=ha)
    assert wl.load_watchlist() == ["PDD", "QDEL"]
    assert client.get("/watchlist").status_code == 401
