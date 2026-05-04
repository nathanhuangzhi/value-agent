from fastapi import FastAPI
# --- THIS IS THE MISSING BRIDGE ---
from app.workflow import run_value_agent

from app.workflow import run_discovery_workflow

app = FastAPI(title="Value Investing Agent")

@app.get("/")
def read_root():
    return {"message": "Agent is awake."}

@app.get("/scan")
def run_custom_scanner():
    # This runs your hardcoded discovery and the deep-dive analysis
    report = run_discovery_workflow()
    return {"status": "Discovery Scan Complete", "report": report}

@app.get("/analyze/{ticker}")
def analyze_stock(ticker: str):
    from app.tools.finance_tools import get_financial_snapshot
    return get_financial_snapshot(ticker.upper())

@app.get("/scout/{ticker}")
def scout_stock(ticker: str):
    from app.tools.search_tools import get_company_headwinds
    return get_company_headwinds(ticker.upper())

# THE "REPORT" ROUTE
@app.get("/report/{ticker}")
def get_full_report(ticker: str):
    # Now that the import is at the top, this will work!
    report = run_value_agent(ticker)
    return {"ticker": ticker.upper(), "report": report}

@app.get("/check-symbol/{ticker}")
def check_fmp_stable_status(ticker: str):
    import requests, os
    api_key = os.getenv("FMP_API_KEY")
    # This endpoint returns the entire list of symbols 'validated' for the stable route
    url = f"https://financialmodelingprep.com/stable/financial-statement-symbol-list?apikey={api_key}"
    response = requests.get(url).json()
    
    # We search the list for your ticker
    found = any(item['symbol'] == ticker.upper() for item in response)
    return {"ticker": ticker.upper(), "available_on_stable": found}

