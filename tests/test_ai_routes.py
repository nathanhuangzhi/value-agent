"""HTTP surface of the AI chat: conversations CRUD, the streamed reply, resume."""
import time

import pytest
from fastapi.testclient import TestClient

from app.ai import jobs, routes, store
from app.main import app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHATS_DIR", tmp_path)
    jobs._jobs.clear()


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose requests carry a signed-in user's bearer token."""
    from app.auth import service
    sent = {}
    monkeypatch.setattr(service, "_send_code", lambda email, code: sent.__setitem__(email, code))
    c = TestClient(app)
    c.post("/auth/code", json={"email": "t@x.io"})
    token = c.post("/auth/verify", json={"email": "t@x.io", "code": sent["t@x.io"]}).json()["token"]
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def _events(body: str) -> list[dict]:
    import json
    return [json.loads(f.split("data: ", 1)[1]) for f in body.split("\n\n") if f.startswith("id:")]


def test_conversation_crud(client):
    r = client.post("/ai/conversations", json={"model": "pro"})
    conv = r.json()
    assert r.status_code == 200 and conv["model"] == "deepseek-v4-pro"
    assert client.get(f"/ai/conversations/{conv['id']}").json()["pending"] is False
    assert client.get("/ai/conversations").json()["conversations"][0]["id"] == conv["id"]
    assert client.delete(f"/ai/conversations/{conv['id']}").json() == {"deleted": conv["id"]}
    assert client.get(f"/ai/conversations/{conv['id']}").status_code == 404
    assert client.get("/ai/conversations/nope").status_code == 404


def test_message_streams_events_and_resume_replays(client, monkeypatch):
    def fake_stream_reply(conv, text, model):
        for i in range(3):
            time.sleep(0.02)
            yield {"type": "delta", "text": str(i)}
        yield {"type": "done", "message": {"content": "012"}, "conversation": {"id": conv["id"]}}

    monkeypatch.setattr(jobs, "stream_reply", fake_stream_reply)
    conv = client.post("/ai/conversations", json={}).json()
    r = client.post(f"/ai/conversations/{conv['id']}/messages", json={"content": "hi"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = _events(r.text)
    assert [e["type"] for e in ev] == ["delta", "delta", "delta", "done"]
    # the finished job stays buffered: a resume from index 2 replays the tail
    r2 = client.get(f"/ai/conversations/{conv['id']}/stream", params={"from": 2})
    assert [e["type"] for e in _events(r2.text)] == ["delta", "done"]
    assert client.get("/ai/conversations/unknown/stream").status_code == 404


def test_second_message_while_busy_is_409(client, monkeypatch):
    def slow(conv, text, model):
        time.sleep(0.3)
        yield {"type": "done", "message": {}, "conversation": {}}

    monkeypatch.setattr(jobs, "stream_reply", slow)
    conv = client.post("/ai/conversations", json={}).json()
    jobs.start(store.load(conv["id"]), "first", "m")
    r = client.post(f"/ai/conversations/{conv['id']}/messages", json={"content": "second"})
    assert r.status_code == 409
    assert client.get(f"/ai/conversations/{conv['id']}").json()["pending"] is True


def test_validation(client):
    conv = client.post("/ai/conversations", json={}).json()
    assert client.post(f"/ai/conversations/{conv['id']}/messages", json={"content": ""}).status_code == 422
    assert client.post("/ai/conversations/nope/messages", json={"content": "x"}).status_code == 404
    assert routes.models()["models"][0]["key"] == "flash"


def test_app_token_gate(client, monkeypatch):
    from app.settings import settings
    monkeypatch.setattr(settings, "app_token", "s3cret")
    assert client.get("/ai/models").status_code == 401
    assert client.get("/ai/models", headers={"X-App-Token": "wrong"}).status_code == 401
    assert client.get("/ai/models", headers={"X-App-Token": "s3cret"}).status_code == 200
    assert client.get("/api/industries.json").status_code != 401     # read-only data stays open


def test_conversations_are_private(client):
    conv = client.post("/ai/conversations", json={}).json()
    other = TestClient(app)          # not signed in
    assert other.get(f"/ai/conversations/{conv['id']}").status_code == 401
    assert other.get("/ai/conversations").status_code == 401
    assert client.get("/ai/conversations").json()["conversations"][0]["id"] == conv["id"]
