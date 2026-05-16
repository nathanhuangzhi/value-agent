"""FastAPI surface.

Two parts:

  - Legacy ad-hoc routes at the root (`/`, `/scout/{t}`, `/report/{t}`)
    used by local debugging. These call the LLM and trigger network I/O
    on every request; not intended for production traffic.
  - Mounted `app.api.router` under `/api` — read-only JSON endpoints
    serving pre-computed pipeline output for the React Native mobile
    app. Cheap (file I/O only), no LLM calls.

CORS is open to all origins; the API only serves data the pipeline has
already written to disk, and the mobile app needs to reach it from any
network. Tighten if you ever expose write endpoints.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.workflow import run_value_agent

app = FastAPI(title="Value Investing Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def read_root():
    return {"message": "Agent is awake."}


@app.get("/scout/{ticker}")
def scout_stock(ticker: str):
    from app.tools.search_tools import get_market_commentary
    return get_market_commentary(ticker.upper())


@app.get("/report/{ticker}")
def get_full_report(ticker: str):
    report = run_value_agent(ticker)
    return {"ticker": ticker.upper(), "report": report}
