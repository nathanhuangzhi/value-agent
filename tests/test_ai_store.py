import pytest

from app.ai import store


@pytest.fixture(autouse=True)
def chats_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHATS_DIR", tmp_path)
    return tmp_path


def test_create_append_load_list_delete():
    c = store.create("deepseek-v4-flash")
    assert c["title"] == "New chat" and c["messages"] == []
    store.append(c, {"role": "user", "content": "  what   about QDEL's debt?  "})
    assert c["title"] == "what about QDEL's debt?"          # first user turn names the chat
    assert c["messages"][0]["ts"]
    store.append(c, {"role": "assistant", "content": "fine"})
    loaded = store.load(c["id"])
    assert loaded is not None and len(loaded["messages"]) == 2
    summary = store.list_all()
    assert summary[0]["id"] == c["id"] and summary[0]["message_count"] == 2
    assert store.delete(c["id"]) and store.load(c["id"]) is None and not store.delete(c["id"])


def test_list_is_newest_first_and_skips_garbage(chats_dir):
    a = store.create("m")
    b = store.create("m")
    b["updated_at"] = "2999-01-01T00:00:00+00:00"
    store.save(b)
    (chats_dir / "junk.json").write_text("{not json")
    ids = [c["id"] for c in store.list_all()]
    assert ids[0] == b["id"] and a["id"] in ids and len(ids) == 2


def test_title_truncates():
    t = store.title_from("x" * 100)
    assert len(t) <= store._TITLE_MAX and t.endswith("…")


def test_bad_id_never_touches_disk():
    with pytest.raises(ValueError):
        store.load("../../etc/passwd")
