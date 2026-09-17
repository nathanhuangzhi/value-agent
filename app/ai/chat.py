"""The chat completion loop: build messages → stream from DeepSeek → run
tool calls the model asks for → repeat → final answer.

`stream_reply` is a generator of SSE-ready event dicts:
    {"type": "companies", "tickers": [...]}          data attached up front
    {"type": "status",  "text": "Looking up INGN…"}   a tool call in flight
    {"type": "delta",   "text": "..."}                answer tokens
    {"type": "done",    "message": {...}}             the persisted assistant turn
    {"type": "error",   "text": "..."}
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date

from app.ai import store
from app.ai.context import TOOLS, company_block, detect_companies, run_tool
from app.core.prompt_manager import load_prompt
from app.tools.llm_router import _PRICING_USD_PER_M_TOKENS, build_deepseek_client, run_prompt

MODELS = {"flash": "deepseek-v4-flash", "pro": "deepseek-v4-pro"}
_HISTORY_TURNS = 20      # prior user+assistant messages sent to the model …
_HISTORY_CHARS = 60_000  # … capped by size, newest first (long replies pile up fast)
_COMPACT_AT = 40_000     # un-summarised history above this many chars is folded into the memory …
_COMPACT_KEEP = 6        # … except the most recent turns, which stay verbatim
_MAX_TOOL_ROUNDS = 8     # tool-calling rounds before the model is told to answer
_MAX_CONTINUES = 2       # automatic "continue" when a reply hits the output limit


def resolve_model(name: str | None, fallback: str) -> str:
    if not name:
        return fallback
    return MODELS.get(name, name)


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
        client = build_deepseek_client(read_timeout_s=180, max_retries=1)
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
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="none" if forced_answer else "auto",
                temperature=0.3,
                stream=True,
                stream_options={"include_usage": True},
            )
            tool_calls: dict[int, dict] = {}
            round_parts: list[str] = []
            finish = None
            for chunk in stream:
                if chunk.usage:
                    total_prompt += chunk.usage.prompt_tokens or 0
                    total_completion += chunk.usage.completion_tokens or 0
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta and delta.content:
                    round_parts.append(delta.content)
                    answer_parts.append(delta.content)
                    yield {"type": "delta", "text": delta.content}
                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        slot = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                slot["name"] = tc.function.name
                            if tc.function.arguments:
                                slot["arguments"] += tc.function.arguments
                if choice.finish_reason:
                    finish = choice.finish_reason

            if finish == "length" and continues < _MAX_CONTINUES:
                # Output limit hit mid-answer: ask for the rest, seamlessly.
                continues += 1
                messages.append({"role": "assistant", "content": "".join(round_parts)})
                messages.append({"role": "user", "content": "Continue exactly where you stopped — no recap, no repetition."})
                yield {"type": "status", "text": "Continuing…"}
                continue

            if finish != "tool_calls" or not tool_calls or forced_answer:
                break

            # Model wants data: run each call, feed results back, loop.
            tool_rounds += 1
            if round_parts and not "".join(round_parts).endswith("\n"):
                answer_parts.append("\n\n")          # keep its "let me check…" apart from the answer
                yield {"type": "delta", "text": "\n\n"}
            assistant_msg = {
                "role": "assistant",
                "content": "".join(round_parts) or None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"}}
                    for _, tc in sorted(tool_calls.items())
                ],
            }
            messages.append(assistant_msg)
            for _, tc in sorted(tool_calls.items()):
                try:
                    args = json.loads(tc["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                label = (args.get("ticker") or args.get("query") or "").upper()
                status = {
                    "lookup_company": f"Looking up {label}…",
                    "search_companies": f"Searching companies for “{args.get('query', '')}”…",
                    "list_filings": f"Listing filings for {label}…",
                    "get_6k_statement": f"Reading {label}'s 6-K statements{(' ' + args['period_end']) if args.get('period_end') else ''}…",
                    "get_press_release": f"Reading {label}'s press release…",
                    "list_annual_reports": f"Listing {label}'s annual reports…",
                    "get_annual_report_section": f"Reading {label}'s annual report · {args.get('section', '')}…",
                    "search_annual_report": f"Searching {label}'s annual report for “{args.get('keyword', '')}”…",
                    "list_earnings_calls": f"Listing {label}'s earnings calls…",
                    "get_earnings_call": f"Reading {label}'s {args.get('quarter') or 'latest'} earnings call ({args.get('part') or 'remarks'})…",
                    "search_earnings_calls": f"Searching {label}'s earnings calls for “{args.get('keyword', '')}”…",
                    "search_xbrl_concepts": f"Searching {label}'s XBRL for “{args.get('keyword', '')}”…",
                    "get_xbrl_concept": f"Pulling {label} · {args.get('concept', '')} from EDGAR…",
                    "get_yfinance_raw": f"Reading {label}'s Yahoo {args.get('statement', '')}…",
                }.get(tc["name"], f"Running {tc['name']}…")
                yield {"type": "status", "text": status}
                result = run_tool(tc["name"], args)
                if tc["name"] in ("lookup_company", "get_6k_statement", "get_press_release",
                                  "get_xbrl_concept", "get_yfinance_raw", "get_annual_report_section",
                                  "search_annual_report", "get_earnings_call", "search_earnings_calls") and not result.startswith("ERROR"):
                    t = (args.get("ticker") or "").upper()
                    if t and t not in companies_used:
                        companies_used.append(t)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
    except Exception as e:  # DeepSeek / network failure: surface, keep the user turn
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
        pass
