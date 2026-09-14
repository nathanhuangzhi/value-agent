"""In-app AI chat: DeepSeek-backed conversations grounded in the pipeline's
company data.

- `context.py`  — company detection in a message + compact per-company data
                  block + the tool definitions the model can call
- `store.py`    — conversation persistence (one JSON file per chat)
- `chat.py`     — the streaming completion loop (tool calls → SSE events)
- `routes.py`   — FastAPI router mounted at /ai
"""
