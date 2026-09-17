"""FastAPI surface.

Mounts `app.api.router` under `/api` — read-only JSON endpoints serving
pre-computed pipeline output for the React Native mobile app. Cheap (file
I/O only with mtime-keyed cache), no LLM calls.

Legacy debug routes (`/scout/{ticker}`, `/report/{ticker}`) trigger LLM +
Exa calls on every request and are gated behind `VALUE_AGENT_DEV=1` so a
misconfigured public deployment can't burn through DeepSeek credits.

CORS is open to all origins; the API only serves data the pipeline has
already written to disk, and the mobile app needs to reach it from any
network. Tighten if you ever expose write endpoints.
"""
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.routes import router as ai_router
from app.api.routes import router as api_router
from app.api.watchlist_routes import router as watchlist_router
from app.tools.paths import ENV_FILE

# The AI chat routes call DeepSeek, whose key lives in .env (the scripts
# each load it themselves; the server process must too).
load_dotenv(ENV_FILE)

logger = logging.getLogger(__name__)

app = FastAPI(title="Value Investing Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "PUT", "DELETE", "POST"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ai_router)
app.include_router(watchlist_router)


@app.get("/")
def read_root():
    return {"message": "Agent is awake."}


# ---------------------------------------------------------------------------
# Legacy debug routes — only mounted when VALUE_AGENT_DEV=1. They trigger
# Exa + DeepSeek calls on every request and are intended for local
# experimentation only.
# ---------------------------------------------------------------------------
if os.getenv("VALUE_AGENT_DEV") == "1":
    from app.workflow import run_value_agent

    @app.get("/scout/{ticker}")
    def scout_stock(ticker: str):
        from app.tools.search_tools import get_market_commentary
        return get_market_commentary(ticker.upper())

    @app.get("/report/{ticker}")
    def get_full_report(ticker: str):
        report = run_value_agent(ticker)
        return {"ticker": ticker.upper(), "report": report}

    logger.warning("VALUE_AGENT_DEV=1: mounting /scout and /report — these "
                   "make live LLM calls on every request.")
