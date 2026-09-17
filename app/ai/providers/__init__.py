"""Model catalogue + provider lookup for the chat.

`MODELS` maps the app's short keys to (provider, model id, label, hint).
Claude entries are offered only when ANTHROPIC_API_KEY is set. The
conversation stores the model *id*; `provider_for(model_id)` finds the
vendor that serves it.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.ai.providers.base import ChatProvider
from app.settings import settings


@dataclass(frozen=True)
class ModelSpec:
    key: str
    provider: str
    model_id: str
    label: str
    hint: str


CATALOGUE: list[ModelSpec] = [
    ModelSpec("flash", "deepseek", "deepseek-v4-flash", "Flash", "fast · cheap"),
    ModelSpec("pro", "deepseek", "deepseek-v4-pro", "Pro", "deeper · ~5x cost"),
    ModelSpec("claude", "anthropic", "claude-opus-5", "Claude", "Opus 5 · strongest on long filings"),
]

MODELS: dict[str, str] = {m.key: m.model_id for m in CATALOGUE}      # key → model id


def available() -> list[ModelSpec]:
    return [m for m in CATALOGUE if m.provider != "anthropic" or settings.anthropic_api_key]


def spec_for(model_id: str) -> ModelSpec | None:
    return next((m for m in CATALOGUE if m.model_id == model_id), None)


def resolve_model(name: str | None, fallback: str) -> str:
    """A short key ('flash') or a model id → model id."""
    if not name:
        return fallback
    return MODELS.get(name, name)


_providers: dict[str, ChatProvider] = {}


def provider_for(model_id: str) -> ChatProvider:
    spec = spec_for(model_id)
    vendor = spec.provider if spec else "deepseek"
    if vendor not in _providers:
        if vendor == "anthropic":
            from app.ai.providers.anthropic import AnthropicProvider
            _providers[vendor] = AnthropicProvider(api_key=settings.anthropic_api_key,
                                                   read_timeout_s=settings.chat.read_timeout_s)
        else:
            from app.ai.providers.deepseek import DeepSeekProvider
            _providers[vendor] = DeepSeekProvider(read_timeout_s=settings.chat.read_timeout_s)
    return _providers[vendor]


__all__ = ["CATALOGUE", "MODELS", "ModelSpec", "available", "provider_for", "resolve_model", "spec_for"]
