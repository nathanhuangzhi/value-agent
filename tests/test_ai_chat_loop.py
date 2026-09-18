"""The reply loop against a scripted fake of the OpenAI-style streaming client."""
from types import SimpleNamespace as NS

import pytest

from app.ai import chat


def _chunk(text=None, tool_calls=None, finish=None, usage=None):
    delta = NS(content=text, tool_calls=tool_calls)
    choice = NS(delta=delta, finish_reason=finish)
    return NS(choices=[choice] if (text is not None or tool_calls or finish) else [],
              usage=NS(prompt_tokens=usage[0], completion_tokens=usage[1]) if usage else None)


def _tc(index, id_, name, arguments):
    return NS(index=index, id=id_, function=NS(name=name, arguments=arguments))


class FakeClient:
    """Each call to create() pops the next scripted turn; records the kwargs."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls: list[dict] = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.turns:
            raise AssertionError("more calls than scripted turns")
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return iter(turn)


@pytest.fixture
def conv(monkeypatch, tmp_path):
    monkeypatch.setattr(chat.store, "CHATS_DIR", tmp_path)
    monkeypatch.setattr(chat, "detect_companies", lambda text: [])
    monkeypatch.setattr(chat, "load_prompt", lambda name, **v: ({}, "SYSTEM"))
    monkeypatch.setattr(chat, "compact", lambda c: False)
    return chat.store.create("m")


def _run(monkeypatch, conv, turns, text="hi"):
    """Drive the real DeepSeek provider (OpenAI-shape translation) over a scripted client."""
    from app.ai.providers.deepseek import DeepSeekProvider
    client = FakeClient(turns)
    provider = DeepSeekProvider()
    provider._client = client
    monkeypatch.setattr(chat, "provider_for", lambda model: provider)
    events = list(chat.stream_reply(conv, text, "m"))
    return client, events


def test_plain_answer_is_streamed_and_stored(monkeypatch, conv):
    client, ev = _run(monkeypatch, conv, [[_chunk("Hel"), _chunk("lo", finish="stop", usage=(10, 2))]])
    assert [e["text"] for e in ev if e["type"] == "delta"] == ["Hel", "lo"]
    done = ev[-1]
    assert done["type"] == "done" and done["message"]["content"] == "Hello"
    assert done["message"]["usage"]["prompt_tokens"] == 10
    stored = chat.store.load(conv["id"])["messages"]
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert client.calls[0]["tool_choice"] == "auto" and client.calls[0]["messages"][0]["content"] == "SYSTEM"


def test_tool_round_runs_tool_and_feeds_result_back(monkeypatch, conv):
    monkeypatch.setattr(chat, "run_tool", lambda name, args, user_id=None: f"RESULT({name}:{args['ticker']})")
    turns = [
        [_chunk("Let me look. ", tool_calls=[_tc(0, "c1", "lookup_company", '{"ticker": "qdel"}')]),
         _chunk(finish="tool_calls")],
        [_chunk("QDEL is fine.", finish="stop")],
    ]
    client, ev = _run(monkeypatch, conv, turns)
    kinds = [e["type"] for e in ev]
    assert "status" in kinds and kinds[-1] == "done"
    assert ev[-1]["message"]["content"] == "Let me look. \n\nQDEL is fine."
    assert ev[-1]["message"]["companies"] == ["QDEL"]
    second = client.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"][0]["function"]["name"] == "lookup_company"
    assert second[-2]["content"] == "Let me look. "          # this round's text only, not accumulated
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "content": "RESULT(lookup_company:qdel)"}


def test_tool_budget_forces_a_final_answer(monkeypatch, conv):
    monkeypatch.setattr(chat, "_MAX_TOOL_ROUNDS", 2)
    monkeypatch.setattr(chat, "run_tool", lambda name, args, user_id=None: "x")
    wants_tool = [_chunk(tool_calls=[_tc(0, "c", "list_filings", '{"ticker":"A"}')]), _chunk(finish="tool_calls")]
    turns = [wants_tool, wants_tool, [_chunk("Best I can say.", finish="stop")]]
    client, ev = _run(monkeypatch, conv, turns)
    assert ev[-1]["type"] == "done" and ev[-1]["message"]["content"].endswith("Best I can say.")
    assert len(client.calls) == 3
    assert client.calls[2]["tool_choice"] == "none"
    assert client.calls[2]["messages"][-1]["role"] == "system" and "budget" in client.calls[2]["messages"][-1]["content"]


def test_length_stop_continues_seamlessly(monkeypatch, conv):
    turns = [[_chunk("first half ", finish="length")], [_chunk("second half.", finish="stop")]]
    client, ev = _run(monkeypatch, conv, turns)
    assert ev[-1]["message"]["content"] == "first half second half."
    cont = client.calls[1]["messages"]
    assert cont[-2] == {"role": "assistant", "content": "first half "}
    assert cont[-1]["role"] == "user" and "Continue" in cont[-1]["content"]
    assert any(e["type"] == "status" and "Continuing" in e["text"] for e in ev)


def test_provider_failure_surfaces_and_keeps_user_turn(monkeypatch, conv):
    _, ev = _run(monkeypatch, conv, [RuntimeError("boom")])
    assert ev[-1] == {"type": "error", "text": "RuntimeError: boom"}
    assert [m["role"] for m in chat.store.load(conv["id"])["messages"]] == ["user"]


def test_history_is_capped_by_size_and_memory_is_injected(monkeypatch):
    monkeypatch.setattr(chat, "load_prompt", lambda name, **v: ({}, "SYSTEM"))
    monkeypatch.setattr(chat, "_HISTORY_CHARS", 50)
    conv = {"messages": [{"role": "user", "content": "a" * 40}, {"role": "assistant", "content": "b" * 40},
                         {"role": "user", "content": "c" * 10}, {"role": "assistant", "content": "d" * 10}],
            "summary": "MEMORY", "summary_upto": 0}
    msgs = chat._build_messages(conv, "next", {"QDEL": "DATA"})
    assert msgs[0]["role"] == "system" and msgs[1]["content"].endswith("MEMORY")
    assert not any(m["content"] == "a" * 40 for m in msgs)       # oldest dropped by the size cap
    assert any(m["content"] == "c" * 10 for m in msgs)
    assert msgs[-2]["role"] == "system" and "DATA" in msgs[-2]["content"]
    assert msgs[-1] == {"role": "user", "content": "next"}
