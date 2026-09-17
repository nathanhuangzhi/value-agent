from app.ai import chat


def test_compact_folds_old_turns_and_keeps_recent(monkeypatch, tmp_path):
    monkeypatch.setattr(chat.store, "CHATS_DIR", tmp_path)
    monkeypatch.setattr(chat, "_COMPACT_AT", 100)
    monkeypatch.setattr(chat, "_COMPACT_KEEP", 2)
    seen = {}

    class R:
        text = "MEMORY: VIPS 2026Q2 revenue RMB 20.3B (6-K)"

    def fake_run_prompt(name, **vars):
        seen.update(vars)
        return R()

    monkeypatch.setattr(chat, "run_prompt", fake_run_prompt)
    conv = {"id": "c1", "title": "t", "model": "m", "created_at": "", "updated_at": "",
            "messages": [{"role": "user", "content": "q1" * 40}, {"role": "assistant", "content": "a1" * 40},
                         {"role": "user", "content": "q2" * 40}, {"role": "assistant", "content": "a2" * 40}]}
    assert chat.compact(conv)
    assert conv["summary"].startswith("MEMORY")
    assert conv["summary_upto"] == 2                 # the last two stay verbatim
    assert "q1q1" in seen["turns"] and "q2q2" not in seen["turns"]
    # building the prompt uses the memory + only the turns after it
    msgs = chat._build_messages(conv, "next", {})
    assert any("memory" in m["content"].lower() and "MEMORY" in m["content"] for m in msgs if m["role"] == "system")
    assert not any("q1q1" in m["content"] for m in msgs)
    assert any("q2q2" in m["content"] for m in msgs)
    # nothing new to fold → no second call
    assert not chat.compact(conv)
