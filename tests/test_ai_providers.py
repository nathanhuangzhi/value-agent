"""Provider translation layer: neutral messages ↔ vendor shapes, without the network."""
from contextlib import contextmanager
from types import SimpleNamespace as NS

from app.ai.providers import MODELS, available, provider_for, resolve_model, spec_for
from app.ai.providers.anthropic import AnthropicProvider, _to_anthropic_tools, _translate
from app.ai.providers.base import ToolCall, Turn


def test_catalogue_and_resolution(monkeypatch):
    assert resolve_model("flash", "x") == MODELS["flash"] == "deepseek-v4-flash"
    assert resolve_model(None, "fallback") == "fallback"
    assert resolve_model("claude-opus-5", "x") == "claude-opus-5"
    assert spec_for("claude-opus-5").provider == "anthropic"
    from app.ai import providers as P
    monkeypatch.setattr(P.settings, "anthropic_api_key", "")
    assert [m.key for m in available()] == ["flash", "pro"]
    assert provider_for("deepseek-v4-flash").name == "deepseek"


def test_translate_neutral_messages_to_anthropic_shape():
    msgs = [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "system", "content": "Company data attached"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "checking", "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "lookup_company", "arguments": '{"ticker": "QDEL"}'}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "DATA"},
        {"role": "system", "content": "budget used up"},
    ]
    system, out = _translate(msgs)
    assert system == "SYSTEM\n\nCompany data attached\n\nbudget used up"
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant", "user"]
    assert out[3]["content"][1] == {"type": "tool_use", "id": "t1", "name": "lookup_company", "input": {"ticker": "QDEL"}}
    assert out[4]["content"] == [{"type": "tool_result", "tool_use_id": "t1", "content": "DATA"}]
    # a native assistant turn is replayed verbatim (thinking + tool_use blocks)
    native = [{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "text", "text": "hi"}]
    _, out2 = _translate([{"role": "user", "content": "q"}, {"role": "assistant", "content": native, "_native": True}])
    assert out2[1]["content"] is native


def test_tool_schema_conversion():
    t = _to_anthropic_tools([{"type": "function", "function": {"name": "x", "description": "d",
                                                              "parameters": {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}}}])
    assert t == [{"name": "x", "description": "d", "input_schema": {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}}]


class FakeStream:
    def __init__(self, events, final):
        self._events, self._final = events, final

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._final


def test_anthropic_provider_streams_text_and_reports_tool_use():
    captured = {}

    @contextmanager
    def fake_stream(**kwargs):
        captured.update(kwargs)
        final = NS(stop_reason="tool_use",
                   content=[NS(type="text", text="Let me check", model_dump=lambda: {"type": "text", "text": "Let me check"}),
                            NS(type="tool_use", id="tu1", name="lookup_company", input={"ticker": "QDEL"},
                               model_dump=lambda: {"type": "tool_use", "id": "tu1", "name": "lookup_company", "input": {"ticker": "QDEL"}})],
                   usage=NS(input_tokens=100, output_tokens=20))
        yield FakeStream([NS(type="text", text="Let me "), NS(type="text", text="check")], final)

    client = NS(messages=NS(stream=fake_stream))
    p = AnthropicProvider(client=client)
    items = list(p.stream(model="claude-opus-5", messages=[{"role": "system", "content": "S"}, {"role": "user", "content": "q"}],
                          tools=[{"type": "function", "function": {"name": "lookup_company", "parameters": {"type": "object", "properties": {}}}}],
                          allow_tools=True))
    assert items[:2] == ["Let me ", "check"]
    turn = items[-1]
    assert isinstance(turn, Turn) and turn.finish == "tool_calls" and turn.tool_calls == [ToolCall("tu1", "lookup_company", {"ticker": "QDEL"})]
    assert turn.prompt_tokens == 100 and turn.assistant_message["_native"] is True
    assert captured["system"] == "S" and captured["thinking"] == {"type": "adaptive"} and captured["tools"][0]["name"] == "lookup_company"
    assert "tool_choice" not in captured
    # forced answer: tools stay declared (history references them) but are switched off
    list(p.stream(model="claude-opus-5", messages=[{"role": "user", "content": "q"}], tools=captured["tools"] and [{"function": {"name": "x"}}], allow_tools=False))
    assert captured["tool_choice"] == {"type": "none"}
    assert p.tool_result_messages([(turn.tool_calls[0], "OUT")]) == [{"role": "tool", "tool_call_id": "tu1", "content": "OUT"}]
