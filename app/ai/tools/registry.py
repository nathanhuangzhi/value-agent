"""Tool registry for the AI chat.

A tool is a plain function decorated with `@tool(...)`: the decorator
records the OpenAI-style function schema, the status line the app shows
while it runs, and the callable — so adding a tool is one definition in
one place. `TOOLS` (the schema list sent to the model), `run_tool` and
`status_for` are derived from the registry; nothing else needs editing.

    @tool("get_thing", description="…", params={"ticker": {"type": "string"}},
          required=["ticker"], status="Reading {ticker}…")
    def get_thing(ticker: str, extra: int | None = None) -> str: ...

Parameter names must match the schema's property names — `run_tool`
passes the model's arguments by keyword, with missing required strings
coerced to "" so a sloppy call degrades to the tool's own error message.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

StatusSpec = str | Callable[[dict], str]


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, Any]
    required: list[str]
    status: StatusSpec
    fn: Callable[..., str]
    marks_company: bool = True     # a successful call counts its ticker among the reply's sources
    needs_user: bool = False       # receives user_id= (the signed-in account) — personal state

    @property
    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": {"type": "object", "properties": self.params,
                                            "required": self.required}}}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, *, description: str, params: dict[str, Any], required: list[str] | None = None,
         status: StatusSpec, marks_company: bool = True, needs_user: bool = False):
    def register(fn: Callable[..., str]) -> Callable[..., str]:
        REGISTRY[name] = Tool(name, description, params, list(required or []), status, fn, marks_company, needs_user)
        return fn
    return register


def _t(args: dict) -> str:
    return (args.get("ticker") or args.get("query") or "").upper()


def schemas() -> list[dict]:
    return [t.schema for t in REGISTRY.values()]


def status_for(name: str, args: dict) -> str:
    t = REGISTRY.get(name)
    if t is None:
        return f"Running {name}…"
    if callable(t.status):
        return t.status(args)
    safe = {k: (v if v is not None else "") for k, v in args.items()}
    safe["ticker"] = _t(args)
    return t.status.format_map(_Defaults(safe))


class _Defaults(dict):
    def __missing__(self, key):
        return ""


def run_tool(name: str, args: dict, *, user_id: int | None = None) -> str:
    """Execute a tool call; always returns a string for the tool message."""
    t = REGISTRY.get(name)
    if t is None:
        return f"ERROR: unknown tool {name}"
    kwargs = {}
    for k, spec in t.params.items():
        v = args.get(k)
        if v is None and k in t.required and spec.get("type") == "string":
            v = ""
        kwargs[k] = v
    if t.needs_user:
        if user_id is None:
            return "ERROR: this needs a signed-in user"
        kwargs["user_id"] = user_id
    return t.fn(**kwargs)


def marks_company(name: str) -> bool:
    t = REGISTRY.get(name)
    return bool(t and t.marks_company)
