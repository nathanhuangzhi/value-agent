"""One logger setup for the service and the scripts.

    from app.log import get_logger
    log = get_logger(__name__)
    log.warning("6-K index unreadable for %s", ticker, exc_info=True)

Format is `time level module: message`; level from LOG_LEVEL (default INFO).
uvicorn keeps its own access log; this covers app/ and scripts/. Configured
once on first import, so scripts get it without any boilerplate.
"""
from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("app")
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                                               datefmt="%Y-%m-%dT%H:%M:%S"))
        root.addHandler(handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(name if name.startswith("app") else f"app.{name}")
