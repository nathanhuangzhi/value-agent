"""Runtime configuration in one place: environment variables (.env) plus the
tunables that used to be scattered as module constants.

    from app.settings import settings
    settings.deepseek_api_key, settings.chat.max_tool_rounds, ...

Loaded once at import; tests monkeypatch attributes on the module-level
`settings` rather than the env (ChatSettings is frozen; Settings is not).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

from app.tools.paths import ENV_FILE

load_dotenv(ENV_FILE)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class ChatSettings:
    history_turns: int = 20       # prior user+assistant messages sent to the model …
    history_chars: int = 60_000   # … capped by size, newest first
    compact_at: int = 40_000      # un-summarised history above this is folded into the memory …
    compact_keep: int = 6         # … except the most recent turns, which stay verbatim
    max_tool_rounds: int = 8      # tool-calling rounds before the model is told to answer
    max_continues: int = 2        # automatic "continue" when a reply hits the output limit
    read_timeout_s: int = 180     # per-stream read timeout against the provider


@dataclass
class Settings:
    deepseek_api_key: str = ""
    anthropic_api_key: str = ""
    alphavantage_api_keys: tuple[str, ...] = ()
    sec_contact_email: str = ""
    app_token: str = ""             # when set, /ai and /watchlist require X-App-Token
    log_level: str = "INFO"
    chat: ChatSettings = field(default_factory=ChatSettings)

    @classmethod
    def load(cls) -> Settings:
        env = os.environ
        return cls(
            deepseek_api_key=env.get("DEEPSEEK_API_KEY", "").strip(),
            anthropic_api_key=env.get("ANTHROPIC_API_KEY", "").strip(),
            alphavantage_api_keys=tuple(k.strip() for k in env.get("ALPHAVANTAGE_API_KEY", "").split(",") if k.strip()),
            sec_contact_email=env.get("SEC_CONTACT_EMAIL", "").strip(),
            app_token=env.get("APP_TOKEN", "").strip(),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            chat=ChatSettings(
                history_turns=_int("CHAT_HISTORY_TURNS", 20),
                history_chars=_int("CHAT_HISTORY_CHARS", 60_000),
                compact_at=_int("CHAT_COMPACT_AT", 40_000),
                compact_keep=_int("CHAT_COMPACT_KEEP", 6),
                max_tool_rounds=_int("CHAT_MAX_TOOL_ROUNDS", 8),
                max_continues=_int("CHAT_MAX_CONTINUES", 2),
                read_timeout_s=_int("CHAT_READ_TIMEOUT_S", 180),
            ),
        )


settings = Settings.load()
