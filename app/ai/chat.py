"""The chat completion loop: build messages → stream from the model's
provider → run tool calls the model asks for → repeat → final answer.

`stream_reply` is a generator of SSE-ready event dicts:
    {"type": "companies", "tickers": [...]}          data attached up front
    {"type": "status",  "text": "Looking up INGN…"}   a tool call in flight
    {"type": "delta",   "text": "..."}                answer tokens
    {"type": "done",    "message": {...}}             the persisted assistant turn
    {"type": "error",   "text": "..."}
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import date

from app.ai import store
from app.ai.context import company_block, detect_companies
from app.ai.providers import MODELS, provider_for, resolve_model
from app.ai.providers.base import Turn
from app.ai.tools import TOOLS, marks_company, run_tool, status_for
from app.core.prompt_manager import load_prompt
from app.log import get_logger
from app.settings import settings
from app.tools.llm_router import _PRICING_USD_PER_M_TOKENS, run_prompt

log = get_logger(__name__)

# Tunables (see app.settings; module-level so tests can override them).
_HISTORY_TURNS = settings.chat.history_turns
_HISTORY_CHARS = settings.chat.history_chars
_COMPACT_AT = settings.chat.compact_at
_COMPACT_KEEP = settings.chat.compact_keep
_MAX_TOOL_ROUNDS = settings.chat.max_tool_rounds
_MAX_CONTINUES = settings.chat.max_continues

__all__ = ["MODELS", "resolve_model", "stream_reply", "compact"]


def _cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    rates = _PRICING_USD_PER_M_TOKENS.get(model)
    if not rates:
        return None
    return round((prompt_tokens * rates["input"] + completion_tokens * rates["output"]) / 1e6, 6)


def _build_messages(conv: dict, user_text: str, attached: dict[str, str]) -> list[dict]:
    config, system = load_prompt("ai_chat", today=date.today().isoformat())
    msgs: list[dict] = [{"role": "system", "content": system}]
    # Older turns live in a rolling memory (see compact()); only what came after it is verbatim.
    if conv.get("summary"):
        msgs.append({"role": "system", "content": "Your memory of the earlier part of this conversation "
                                                  "(figures and sources already established):\n\n" + conv["summary"]})
    history = [m for m in conv["messages"][conv.get("summary_upto", 0):]
               if m["role"] in ("user", "assistant")][-_HISTORY_TURNS:]
    kept: list[dict] = []
    size = 0
    for m in reversed(history):
        size += len(m["content"])
        if size > _HISTORY_CHARS and len(kept) >= 2:
            break
        kept.append({"role": m["role"], "content": m["content"]})
    msgs.extend(reversed(kept))
    if attached:
        msgs.append({"role": "system",
                     "content": "Company data attached for this message:\n\n"
                                + "\n\n---\n\n".join(attached.values())})
    msgs.append({"role": "user", "content": user_text})
    return msgs


def compact(conv: dict) -> bool:
    """Fold older turns into conv["summary"] once the verbatim history is
    heavy — the assistant's equivalent of context compaction. Keeps the last
    `_COMPACT_KEEP` messages verbatim; safe to call after every reply."""
    upto = conv.get("summary_upto", 0)
    msgs = conv["messages"]
    pending = msgs[upto:]
    if sum(len(m["content"]) for m in pending) <= _COMPACT_AT or len(pending) <= _COMPACT_KEEP:
        return False
    fold = pending[:-_COMPACT_KEEP]
    turns = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in fold)
    result = run_prompt("compact_chat", summary=conv.get("summary") or "(empty)", turns=turns)
    if not result.text.strip():
        return False
    conv["summary"] = result.text.strip()
    conv["summary_upto"] = upto + len(fold)
    conv["compactions"] = conv.get("compactions", 0) + 1
    store.save(conv)
    return True


def stream_reply(conv: dict, user_text: str, model: str) -> Iterator[dict]:
    """Persist the user turn, stream the assistant turn, persist it."""
    store.append(conv, {"role": "user", "content": user_text})

    tickers = detect_companies(user_text)
    attached: dict[str, str] = {}
    for t in tickers:
        try:
            attached[t] = company_block(t)
        except Exception:
            continue
    if attached:
        yield {"type": "companies", "tickers": list(attached)}

    companies_used = list(attached)
    total_prompt = 0
    total_completion = 0
    answer_parts: list[str] = []

    try:
        messages = _build_messages(conv, user_text, attached)
        provider = provider_for(model)
        tool_rounds = 0
        continues = 0
        while True:
            # Out of tool rounds: one last call without tools so a reply always ends
            # in an answer instead of a dangling "let me check…".
            forced_answer = tool_rounds >= _MAX_TOOL_ROUNDS
            if forced_answer:
                messages.append({"role": "system",
                                 "content": "The tool budget for this reply is used up. Answer now from what "
                                            "you have gathered, and say plainly what you could not verify."})
            turn: Turn | None = None
            for item in provider.stream(model=model, messages=messages, tools=TOOLS, allow_tools=not forced_answer):
                if isinstance(item, Turn):
                    turn = item
                    break
                answer_parts.append(item)
                yield {"type": "delta", "text": item}
            assert turn is not None, "provider ended without a Turn"
            total_prompt += turn.prompt_tokens
            total_completion += turn.completion_tokens

            if turn.finish == "length" and continues < _MAX_CONTINUES:
                # Output limit hit mid-answer: ask for the rest, seamlessly.
                continues += 1
                messages.append({"role": "assistant", "content": turn.text})
                messages.append({"role": "user", "content": "Continue exactly where you stopped — no recap, no repetition."})
                yield {"type": "status", "text": "Continuing…"}
                continue

            if turn.finish != "tool_calls" or forced_answer:
                break

            # Model wants data: run each call, feed results back, loop.
            tool_rounds += 1
            if turn.text and not turn.text.endswith("\n"):
                answer_parts.append("\n\n")          # keep its "let me check…" apart from the answer
                yield {"type": "delta", "text": "\n\n"}
            messages.append(turn.assistant_message)
            results = []
            for tc in turn.tool_calls:
                yield {"type": "status", "text": status_for(tc.name, tc.arguments)}
                t0 = time.monotonic()
                result = run_tool(tc.name, tc.arguments)
                log.info("tool %s %s -> %s chars in %.1fs%s", tc.name, json.dumps(tc.arguments, ensure_ascii=False),
                         len(result), time.monotonic() - t0, " (ERROR)" if result.startswith("ERROR") else "")
                if marks_company(tc.name) and not result.startswith("ERROR"):
                    t = (tc.arguments.get("ticker") or "").upper()
                    if t and t not in companies_used:
                        companies_used.append(t)
                results.append((tc, result))
            messages.extend(provider.tool_result_messages(results))
    except Exception as e:  # provider / network failure: surface, keep the user turn
        log.warning("reply failed for conversation %s", conv["id"], exc_info=True)
        yield {"type": "error", "text": f"{type(e).__name__}: {e}"}
        return

    text = "".join(answer_parts).strip()
    usage = {
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "estimated_cost_usd": _cost(model, total_prompt, total_completion),
    }
    message = {"role": "assistant", "content": text, "model": model,
               "companies": companies_used, "usage": usage}
    store.append(conv, message)
    conv["model"] = model
    store.save(conv)
    yield {"type": "done", "message": message, "conversation": {
        "id": conv["id"], "title": conv["title"], "model": conv["model"],
        "updated_at": conv["updated_at"]}}
    try:
        compact(conv)                        # after `done`, so the reader never waits on it
    except Exception:
        log.warning("compaction failed for conversation %s", conv["id"], exc_info=True)
