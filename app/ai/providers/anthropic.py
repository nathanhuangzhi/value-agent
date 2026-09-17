"""Claude through the official Anthropic SDK (streaming + tool use).

Translation from the loop's neutral messages:
  - every `system` message → the top-level `system` text, in order (the
    prompt, the attached company data, the compaction memory, the
    "budget used up" nudge);
  - `assistant` turns produced by this provider are replayed with their
    native content blocks (text / thinking / tool_use) — Claude needs the
    thinking blocks back unchanged inside a tool loop;
  - consecutive `tool` messages → one `user` message of `tool_result` blocks.
Tool schemas are the OpenAI-style function definitions turned into
`{name, description, input_schema}`.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.ai.providers.base import ToolCall, Turn

MAX_OUTPUT_TOKENS = 16_000


def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        f = t.get("function", t)
        out.append({"name": f["name"], "description": f.get("description", ""),
                    "input_schema": f.get("parameters") or {"type": "object", "properties": {}}})
    return out


def _translate(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts: list[str] = []
    out: list[dict] = []
    pending_results: list[dict] = []

    def flush_results():
        if pending_results:
            out.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for m in messages:
        role = m["role"]
        if role == "system":
            system_parts.append(m["content"])
            continue
        if role == "tool":
            pending_results.append({"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]})
            continue
        flush_results()
        if role == "assistant":
            if m.get("_native"):
                out.append({"role": "assistant", "content": m["content"]})
            else:
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls") or []:
                    import json
                    blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                                   "input": json.loads(tc["function"]["arguments"] or "{}")})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            continue
        out.append({"role": "user", "content": m["content"]})
    flush_results()
    # The API wants alternating turns starting with user; merge adjacent same-role turns.
    merged: list[dict] = []
    for m in out:
        if merged and merged[-1]["role"] == m["role"]:
            prev, cur = merged[-1]["content"], m["content"]
            prev_blocks = prev if isinstance(prev, list) else [{"type": "text", "text": prev}]
            cur_blocks = cur if isinstance(cur, list) else [{"type": "text", "text": cur}]
            merged[-1] = {"role": m["role"], "content": prev_blocks + cur_blocks}
        else:
            merged.append(m)
    return "\n\n".join(system_parts), merged


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, *, api_key: str | None = None, read_timeout_s: int = 180, client: Any = None):
        self._client = client
        self._api_key = api_key
        self._timeout = read_timeout_s

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key or None, timeout=float(self._timeout), max_retries=1)
        return self._client

    def stream(self, *, model: str, messages: list[dict], tools: list[dict], allow_tools: bool) -> Iterator[str | Turn]:
        system, msgs = _translate(messages)
        kwargs: dict[str, Any] = dict(model=model, max_tokens=MAX_OUTPUT_TOKENS, messages=msgs,
                                      thinking={"type": "adaptive"}, output_config={"effort": "medium"})
        if system:
            kwargs["system"] = system
        if allow_tools and tools:
            kwargs["tools"] = _to_anthropic_tools(tools)
        elif tools:
            kwargs["tools"] = _to_anthropic_tools(tools)
            kwargs["tool_choice"] = {"type": "none"}
        parts: list[str] = []
        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                if getattr(event, "type", None) == "text":
                    parts.append(event.text)
                    yield event.text
            final = stream.get_final_message()
        tool_calls = [ToolCall(b.id, b.name, dict(b.input) if isinstance(b.input, dict) else {})
                      for b in final.content if getattr(b, "type", None) == "tool_use"]
        if final.stop_reason == "max_tokens":
            finish = "length"
        elif tool_calls and final.stop_reason == "tool_use":
            finish = "tool_calls"
        else:
            finish = "stop"
        native = [b.model_dump() if hasattr(b, "model_dump") else b for b in final.content]
        yield Turn(
            text="".join(parts),
            finish=finish,
            tool_calls=tool_calls,
            prompt_tokens=getattr(final.usage, "input_tokens", 0) or 0,
            completion_tokens=getattr(final.usage, "output_tokens", 0) or 0,
            assistant_message={"role": "assistant", "content": native, "_native": True},
        )

    def tool_result_messages(self, results: list[tuple[ToolCall, str]]) -> list[dict]:
        return [{"role": "tool", "tool_call_id": tc.id, "content": out} for tc, out in results]
