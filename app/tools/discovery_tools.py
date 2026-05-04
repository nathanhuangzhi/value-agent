import os
from exa_py import Exa
from dotenv import load_dotenv

load_dotenv()
exa = Exa(api_key=os.getenv("EXA_API_KEY"))

def search_for_tickers():
    # 🎯 EDIT YOUR CRITERIA HERE
    # Be as specific as possible. Exa works best with descriptive, natural language.
    query = (
        "Identify publicly traded US companies with a market cap under $2B, "
        "positive free cash flow, and a dominant niche position in the "
        "semiconductor supply chain or specialized logistics. Please list tickers."
    )
    
    print(f"--- DISCOVERER: Scanning for criteria: {query[:50]}... ---")
    
    # Using 'neural' search and 'financial report' category to filter for professional data
    search_response = exa.search(
        query,
        num_results=10, # Increased to give Gemini more options to pick from
        type="neural",
        category="financial report"
    )
    
    context = ""
    for res in search_response.results:
        context += f"\nSource: {res.title}\n{res.text[:1200]}\n"
    return context