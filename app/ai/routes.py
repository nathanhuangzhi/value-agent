"""FastAPI router for the AI chat tab, mounted at /ai.

    GET    /ai/conversations                 → [{id, title, model, updated_at, message_count}]
    POST   /ai/conversations {model?}        → the new conversation
    GET    /ai/conversations/{id}            → full conversation incl. messages
    DELETE /ai/conversations/{id}
    POST   /ai/conversations/{id}/messages {content, model?}
           → text/event-stream of `data: {json}` events (see app.ai.chat)
    GET    /ai/models                        → the flash / pro choices

The static archive can't run this; it's served by uvicorn on the pipeline
box behind `tailscale serve --set-path /ai http://127.0.0.1:8000/ai`
(deploy/serve_ai.sh). Tailnet membership is the auth.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.ai import store
from app.ai.chat import MODELS, resolve_model, stream_reply

router = APIRouter(prefix="/ai", tags=["ai-chat"])


class NewConversation(BaseModel):
    model: str | None = None


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    model: str | None = None


@router.get("/models")
def models():
    return {"models": [
        {"key": "flash", "id": MODELS["flash"], "label": "Flash", "hint": "fast · cheap"},
        {"key": "pro", "id": MODELS["pro"], "label": "Pro", "hint": "deeper · ~5x cost"},
    ]}


@router.get("/conversations")
def list_conversations():
    return {"conversations": store.list_all()}


@router.post("/conversations")
def create_conversation(body: NewConversation):
    return store.create(resolve_model(body.model, MODELS["flash"]))


@router.get("/conversations/{conv_id}")
def get_conversation(conv_id: str):
    conv = store.load(conv_id)
    if not conv:
        raise HTTPException(404, detail="conversation not found")
    return conv


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str):
    if not store.delete(conv_id):
        raise HTTPException(404, detail="conversation not found")
    return {"deleted": conv_id}


@router.post("/conversations/{conv_id}/messages")
def post_message(conv_id: str, body: NewMessage):
    conv = store.load(conv_id)
    if not conv:
        raise HTTPException(404, detail="conversation not found")
    model = resolve_model(body.model, conv.get("model") or MODELS["flash"])

    def events():
        for ev in stream_reply(conv, body.content.strip(), model):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
