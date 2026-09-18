"""Conversation persistence for the AI chat: one JSON file per conversation
under data/ai_chats/ (gitignored — personal chat history, not pipeline
state).

    {
      "id": "20260914-0a1b2c",
      "user_id": 1,                           # owner (app.db users.id)
      "title": "QDEL vs Inogen",
      "model": "deepseek-v4-flash",          # last model used
      "created_at": "...", "updated_at": "...",
      "messages": [
        {"role": "user", "content": "...", "ts": "..."},
        {"role": "assistant", "content": "...", "ts": "...",
         "model": "deepseek-v4-pro", "companies": ["QDEL"],
         "usage": {"prompt_tokens": 1, "completion_tokens": 2, "estimated_cost_usd": 0.0}}
      ]
    }

Only user/assistant turns are stored; tool round-trips are transient.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

from app.log import get_logger
from app.tools.json_io import atomic_write_json, read_json_array
from app.tools.paths import DATA_DIR

log = get_logger(__name__)

CHATS_DIR = DATA_DIR / "ai_chats"
_TITLE_MAX = 48


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(conv_id: str) -> Path:
    if not conv_id.replace("-", "").isalnum():
        raise ValueError(f"bad conversation id {conv_id!r}")
    return CHATS_DIR / f"{conv_id}.json"


def new_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def create(model: str, user_id: int | None = None) -> dict:
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    conv: dict = {"id": new_id(), "user_id": user_id, "title": "New chat", "model": model,
            "created_at": _now(), "updated_at": _now(), "messages": []}
    save(conv)
    return conv


def load(conv_id: str) -> dict | None:
    p = _path(conv_id)
    if not p.exists():
        return None
    import json
    return json.loads(p.read_text())


def save(conv: dict) -> None:
    conv["updated_at"] = _now()
    atomic_write_json(_path(conv["id"]), conv)


def delete(conv_id: str) -> bool:
    p = _path(conv_id)
    if not p.exists():
        return False
    p.unlink()
    return True


def list_all(user_id: int | None = None) -> list[dict]:
    """Newest first; summary fields only. With `user_id`, only that user's."""
    if not CHATS_DIR.exists():
        return []
    import json
    out = []
    for p in CHATS_DIR.glob("*.json"):
        try:
            c = json.loads(p.read_text())
        except Exception:
            log.warning("skipping unreadable conversation file %s", p, exc_info=True)
            continue
        if user_id is not None and c.get("user_id") != user_id:
            continue
        out.append({
            "id": c.get("id") or p.stem,
            "title": c.get("title") or "New chat",
            "model": c.get("model"),
            "updated_at": c.get("updated_at") or "",
            "message_count": len(c.get("messages") or []),
        })
    out.sort(key=lambda c: c["updated_at"], reverse=True)
    return out


def title_from(text: str) -> str:
    t = " ".join(text.split())
    return t if len(t) <= _TITLE_MAX else t[:_TITLE_MAX - 1].rstrip() + "…"


def append(conv: dict, message: dict) -> None:
    message.setdefault("ts", _now())
    conv["messages"].append(message)
    if message["role"] == "user" and conv.get("title") in (None, "", "New chat"):
        conv["title"] = title_from(message["content"])
    save(conv)


__all__ = ["CHATS_DIR", "create", "load", "save", "delete", "list_all", "append",
           "title_from", "read_json_array"]
