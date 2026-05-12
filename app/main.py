from fastapi import FastAPI

from app.workflow import run_value_agent

app = FastAPI(title="Value Investing Agent")


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

