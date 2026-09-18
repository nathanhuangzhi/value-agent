"""The user-data database: one SQLite file (data/app.db, WAL mode) holding
accounts, sessions, per-user watchlists and — later — custom metrics and
charts. Financial data stays in files; this is only what belongs to a
person. Schema is created on first use and migrated forward with simple
`ALTER`s guarded by version rows.

    from app.db import connect
    with connect() as cx:
        cx.execute(...)          # commits on success, rolls back on error
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.tools.paths import APP_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL,
    last_seen   TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS login_codes (
    email       TEXT PRIMARY KEY,
    code        TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    sent_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watchlist (             -- legacy single list; migrated into watchlists on first use
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    added_at    TEXT NOT NULL,
    PRIMARY KEY (user_id, ticker)
);
CREATE TABLE IF NOT EXISTS watchlists (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    UNIQUE (user_id, name)
);
CREATE TABLE IF NOT EXISTS watchlist_items (
    watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    added_at    TEXT NOT NULL,
    PRIMARY KEY (watchlist_id, ticker)
);
CREATE TABLE IF NOT EXISTS metrics (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    expr        TEXT NOT NULL,
    format      TEXT NOT NULL DEFAULT 'number',
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS metrics_user ON metrics(user_id, position);
CREATE TABLE IF NOT EXISTS charts (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    spec        TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS charts_user ON charts(user_id, position);
CREATE TABLE IF NOT EXISTS series (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    name        TEXT NOT NULL,              -- referenced in expressions as $name (lower-case, [a-z0-9_])
    label       TEXT NOT NULL,
    unit        TEXT NOT NULL DEFAULT 'number',   -- number | money | pct | ratio   (money = reporting currency)
    currency    TEXT,                        -- for money units: CNY, USD, …
    grid        TEXT NOT NULL DEFAULT 'quarterly',
    points      TEXT NOT NULL DEFAULT '[]',  -- [{period, value, source}]
    source_hint TEXT,                        -- where the assistant found it / how to find the next one
    last_source TEXT,                        -- newest filing date already folded in
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (user_id, ticker, name)
);
CREATE TABLE IF NOT EXISTS prefs (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    row_metric_id INTEGER
);
"""

_path: Path = APP_DB
_lock = threading.Lock()
_initialised: set[Path] = set()


def use_path(path: Path) -> None:
    """Point the module at another file (tests use a tmp path)."""
    global _path
    _path = Path(path)


def _init(cx: sqlite3.Connection) -> None:
    cx.executescript(SCHEMA)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A connection with rows as sqlite3.Row, foreign keys on, WAL mode;
    commits when the block exits cleanly, rolls back on an exception."""
    _path.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(_path, timeout=10, isolation_level=None)
    try:
        cx.row_factory = sqlite3.Row
        cx.execute("PRAGMA foreign_keys = ON")
        cx.execute("PRAGMA journal_mode = WAL")
        with _lock:
            if _path not in _initialised:
                _init(cx)
                _initialised.add(_path)
        cx.execute("BEGIN")
        try:
            yield cx
            cx.execute("COMMIT")
        except BaseException:
            cx.execute("ROLLBACK")
            raise
    finally:
        cx.close()
