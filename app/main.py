"""FastAPI surface.

Mounts `app.api.router` under `/api` — read-only JSON endpoints serving
pre-computed pipeline output for the React Native mobile app. Cheap (file
I/O only with mtime-keyed cache), no LLM calls.

CORS is open to all origins; the API only serves data the pipeline has
already written to disk, and the mobile app needs to reach it from any
network. Tighten if you ever expose write endpoints.
"""
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.routes import router as ai_router
from app.api.routes import router as api_router
from app.api.watchlist_routes import router as watchlist_router
from app.auth.routes import router as auth_router
from app.tools.paths import ENV_FILE

# The AI chat routes call DeepSeek, whose key lives in .env (the scripts
# each load it themselves; the server process must too).
load_dotenv(ENV_FILE)

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
app.include_router(auth_router)


@app.get("/")
def read_root():
    return {"message": "Agent is awake."}
