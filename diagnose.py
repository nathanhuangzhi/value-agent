import requests
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("FMP_API_KEY")
ticker = "POOL"
headers = {'User-Agent': 'Mozilla/5.0'}

endpoints = {
    "STABLE": f"https://financialmodelingprep.com/stable/key-metrics?symbol={ticker}&apikey={api_key}",
    "V3": f"https://financialmodelingprep.com/api/v3/key-metrics?symbol={ticker}&apikey={api_key}"
}

print(f"--- Investigating {ticker} ---")
for name, url in endpoints.items():
    try:
        r = requests.get(url, headers=headers)
        print(f"{name} Results:")
        print(f"  - Status: {r.status_code}")
        print(f"  - Length: {len(r.text)} characters")
        
        if len(r.text) > 0:
            print(f"  - Snippet: {r.text[:100]}...")
        else:
            print("  - Snippet: [EMPTY RESPONSE]")
        print("-" * 30)
    except Exception as e:
        print(f"  - Error calling {name}: {e}")