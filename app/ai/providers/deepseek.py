"""DeepSeek through the OpenAI-compatible SDK (streaming + tool_calls)."""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from app.ai.providers.base import ToolCall, Turn
from app.tools.llm_router import build_deepseek_client


class DeepSeekProvider:
    name = "deepseek"

    def __init__(self, *, read_timeout_s: int = 180):
        self._read_timeout_s = read_timeout_s
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = build_deepseek_client(read_timeout_s=self._read_timeout_s, max_retries=1)
        return self._client

    def stream(self, *, model: str, messages: list[dict], tools: list[dict], allow_tools: bool) -> Iterator[str | Turn]:
        resp = self.client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto" if allow_tools else "none",
            temperature=0.3,
            stream=True,
            stream_options={"include_usage": True},
        )
        parts: list[str] = []
        calls: dict[int, dict] = {}
        finish = None
        prompt_tokens = completion_tokens = 0
        for chunk in resp:
            if chunk.usage:
                prompt_tokens += chunk.usage.prompt_tokens or 0
                completion_tokens += chunk.usage.completion_tokens or 0
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta and delta.content:
                parts.append(delta.content)
                yield delta.content
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments
            if choice.finish_reason:
                finish = choice.finish_reason

        text = "".join(parts)
        tool_calls = []
        for _, tc in sorted(calls.items()):
            try:
                args = json.loads(tc["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(tc["id"], tc["name"], args))
        assistant: dict[str, Any] = {"role": "assistant", "content": text or None}
        if tool_calls:
            assistant["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in tool_calls
            ]
        yield Turn(
            text=text,
            finish="tool_calls" if (finish == "tool_calls" and tool_calls) else ("length" if finish == "length" else "stop"),
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            assistant_message=assistant,
        )

    def tool_result_messages(self, results: list[tuple[ToolCall, str]]) -> list[dict]:
        return [{"role": "tool", "tool_call_id": tc.id, "content": out} for tc, out in results]
