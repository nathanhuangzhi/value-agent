import os
import requests
from dotenv import load_dotenv

load_dotenv()

def fetch_from_fmp(ticker: str):
    api_key = os.getenv("FMP_API_KEY")
    # Only use 'stable' since v3 is deprecated as of May 2026
    BASE_URL = "https://financialmodelingprep.com/stable"
    
    cleaned_history = []

    def safe_api_call(endpoint):
        url = f"{BASE_URL}/{endpoint}?symbol={ticker}&period=annual&limit=3&apikey={api_key}"
        response = requests.get(url, headers={'User-Agent': 'ValueAgent/1.0'})
        
        if response.status_code == 402:
            return "ERROR_PREMIUM_ONLY"
        if response.status_code != 200:
            return "ERROR_API_ISSUE"
        
        data = response.json()
        return data if isinstance(data, list) and len(data) > 0 else "ERROR_NO_DATA"

    metrics_data = safe_api_call("key-metrics")
    income_data = safe_api_call("income-statement")

    # If we hit a paywall, return a specific flag
    if metrics_data == "ERROR_PREMIUM_ONLY":
        print(f"💰 {ticker} is a premium-only ticker on your FMP plan.")
        return "PREMIUM_GATED"

    if isinstance(metrics_data, list) and isinstance(income_data, list):
        for i in range(min(len(metrics_data), len(income_data))):
            m, inc = metrics_data[i], income_data[i]
            ey = m.get("earningsYield") or 0
            fy = m.get("freeCashFlowYield") or 0
            
            cleaned_history.append({
                "year": m.get("date", "0000")[:4],
                "pe": round(1/ey, 2) if ey != 0 else 0,
                "pfcf": round(1/fy, 2) if fy != 0 else 0,
                "revenue": inc.get("revenue", 0),
                "op_profit": inc.get("operatingIncome", 0),
                "roe": round(float(m.get("returnOnEquity", 0)) * 100, 2)
            })
    
    return cleaned_history

def get_financial_snapshot(ticker: str):
    data = fetch_from_fmp(ticker)
    return {
        "ticker": ticker,
        "source": "FMP-Stable-V3", # Update version to track change
        "history": data
    }