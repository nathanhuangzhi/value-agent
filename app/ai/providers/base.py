"""What the chat loop needs from a model vendor — nothing more.

Messages are exchanged in one neutral shape (the OpenAI-style dicts the loop
builds: role system / user / assistant / tool, `tool_calls` on assistant
turns, `tool_call_id` on tool turns). A provider translates that shape to
its own API on the way out and yields text deltas as they arrive, ending
each request with one `Turn` that says how it stopped.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Turn:
    """The outcome of one model request."""
    text: str
    finish: str                                # "stop" | "tool_calls" | "length"
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # The assistant message to append to the history before tool results —
    # provider-native where the vendor needs its own blocks replayed
    # (Anthropic keeps thinking + tool_use blocks); neutral otherwise.
    assistant_message: dict[str, Any] = field(default_factory=dict)


class ChatProvider(Protocol):
    name: str

    def stream(self, *, model: str, messages: list[dict], tools: list[dict],
               allow_tools: bool) -> Iterator[str | Turn]:
        """Yield text deltas (str) as they arrive, then exactly one Turn."""
        ...

    def tool_result_messages(self, results: list[tuple[ToolCall, str]]) -> list[dict]:
        """Neutral messages carrying the tool outputs back to the model."""
        ...
