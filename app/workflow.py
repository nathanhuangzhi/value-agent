from dotenv import load_dotenv

from app.tools.llm_router import run_prompt
from app.tools.search_tools import get_market_commentary

load_dotenv()


def run_value_agent(ticker: str) -> dict:
    """
    Performs a deep-dive analysis on a specific ticker. Fetches recent
    market commentary from Exa and asks DeepSeek-V4-Pro to summarize the
    investment narrative. Structured financial data comes from yfinance
    (gathered by daily_scan, not here) and SEC EDGAR (Stage 4b sidecar).

    Schema:
        {
            "narrative": str,                # the model's Markdown response
            "narrative_model": str,          # e.g. "deepseek-v4-pro"
            "narrative_provider": str,       # e.g. "deepseek"
            "usage": {                       # from llm_router.PromptResult
                "prompt_tokens": int | None,
                "completion_tokens": int | None,
                "total_tokens": int | None,
                "estimated_cost_usd": float | None,
            },
            "narrative_sources": list,       # Exa search results fed to the prompt
            "error": str | None,             # set if anything in the pipeline failed
        }

    """
    ticker = ticker.upper()
    try:
        print(f"--- SCOUT: Searching for {ticker} context ---")
        narrative_sources = get_market_commentary(ticker)

        print(f"--- BRAIN: Processing {ticker} analysis ---")
        result = run_prompt(
            "analysis",
            ticker=ticker,
            narrative_sources=narrative_sources,
        )

        return {
            "narrative": result.text,
            "narrative_model": result.model,
            "narrative_provider": result.provider,
            "usage": {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
                "estimated_cost_usd": result.estimated_cost_usd,
            },
            "narrative_sources": narrative_sources,
            "error": None,
        }

    except Exception as e:
        print(f"❌ Analysis Workflow Error: {str(e)}")
        return {
            "narrative": None,
            "narrative_model": None,
            "narrative_provider": None,
            "usage": None,
            "narrative_sources": None,
            "error": f"{type(e).__name__}: {e}",
        }
