import os
from google import genai
from dotenv import load_dotenv

# Tool Imports
from app.tools.finance_tools import get_financial_snapshot
from app.tools.search_tools import get_company_headwinds
from app.tools.discovery_tools import search_for_tickers

# The Prompt Manager (The "Better Way")
from app.core.prompt_manager import load_prompt

load_dotenv()

# Client setup
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options={'api_version': 'v1beta'}  # <--- UPDATE THIS
)

def run_value_agent(ticker: str):
    """
    Performs a deep-dive analysis on a specific ticker.
    Uses 'analysis.prompt.md' for instructions.
    """
    ticker = ticker.upper()
    try:
        # 1. Gather Data
        print(f"--- ACCOUNTANT: Fetching {ticker} numbers ---")
        financials = get_financial_snapshot(ticker)
        
        # Check for the FMP paywall status we implemented
        is_gated = financials.get("history") == "PREMIUM_GATED"
        data_source = 'NEURAL_SCRAPE (Paywall Pivot)' if is_gated else 'FMP_API_STABLE'
        
        # 2. Pivot Search if Gated
        if is_gated:
            search_query = f"Latest annual revenue, operating profit, and ROE for {ticker} from SEC filings or investor relations."
        else:
            search_query = None

        print(f"--- SCOUT: Searching for {ticker} context ---")
        headwinds = get_company_headwinds(ticker, custom_query=search_query)

        # 3. Load Analysis Skill from Markdown
        # We pass the data into the template variables
        config, prompt = load_prompt(
            "analysis", 
            ticker=ticker,
            data_source=data_source,
            financial_context=financials,
            headwinds=headwinds
        )

        print(f"--- BRAIN: Processing {ticker} analysis via {config.get('model')} ---")
        
        # 4. Execute with dynamic config from the Markdown file
        response = client.models.generate_content(
            model=config.get("model", "gemini-2.5-flash"), 
            contents=prompt,
            config={'temperature': config.get("temperature", 0.1)}
        )
        
        return response.text

    except Exception as e:
        print(f"❌ Analysis Workflow Error: {str(e)}")
        return f"❌ Analysis failed: {str(e)}"


def run_discovery_workflow():
    """
    Scans for new companies based on hardcoded criteria.
    Uses 'discovery.prompt.md' for instructions.
    """
    try:
        # 1. Trigger the hardcoded criteria search from discovery_tools.py
        print("--- DISCOVERER: Scanning market for new leads ---")
        raw_leads = search_for_tickers()
        
        # 2. Load Discovery Skill from Markdown
        config, prompt = load_prompt("discovery", raw_leads=raw_leads)
        
        print(f"--- BRAIN: Selecting best lead via {config.get('model')} ---")
        
        # 3. Ask Gemini to pick the best candidate
        response = client.models.generate_content(
            model=config.get("model", "gemini-2.5-flash"), 
            contents=prompt,
            config={'temperature': config.get("temperature", 0.2)}
        )
        
        # Clean the ticker output
        selected_ticker = response.text.strip()
        ticker = "".join(filter(str.isalnum, selected_ticker)).upper()
        
        if not ticker or ticker == "NONE":
            return "🔍 Discovery completed, but no compelling candidates were identified."

        print(f"--- SELECTION MADE: {ticker} ---")
        
        # 4. Chain into the deep-dive agent
        return run_value_agent(ticker)
        
    except Exception as e:
        print(f"❌ Discovery Workflow Error: {str(e)}")
        return f"❌ Discovery failed: {str(e)}"