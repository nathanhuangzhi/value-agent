import os
from exa_py import Exa
from dotenv import load_dotenv

load_dotenv()
exa = Exa(api_key=os.getenv("EXA_API_KEY"))

def get_company_headwinds(ticker: str, custom_query: str = None):
    # If FMP is gated, we use a specific financial extraction query
    query = custom_query or f"What are the specific valuation narrative headwinds or negative market sentiments affecting {ticker} stock recently?"
    
    print(f"--- EXA SCOUTING: {query} ---")
    
    # We removed 'use_autoprompt' to fix the crash
    # 'category' helps Exa filter for professional financial data
    search_response = exa.search(
        query,
        num_results=5,
        type="neural",
        category="financial report" 
    )
    
    results = []
    for res in search_response.results:
        results.append({
            "title": res.title,
            "url": res.url,
            "snippet": res.text[:1000] if hasattr(res, 'text') else "No snippet."
        })
    return results