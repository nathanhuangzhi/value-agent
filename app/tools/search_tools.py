"""Exa-based market commentary search.

Used by `app.workflow.run_value_agent` to feed recent narrative context to
the analysis prompt. The Exa client is constructed lazily on first call so
this module is safe to import without `.env` loaded — entry-point scripts
own `load_dotenv(ENV_FILE)` and the tests that don't need network never
touch this code path.
"""
import logging
import os

from exa_py import Exa

logger = logging.getLogger(__name__)


_exa_client: Exa | None = None


def _client() -> Exa:
    global _exa_client
    if _exa_client is None:
        key = os.getenv("EXA_API_KEY")
        if not key:
            raise RuntimeError("EXA_API_KEY not set in environment.")
        _exa_client = Exa(api_key=key)
    return _exa_client


def get_market_commentary(ticker: str, custom_query: str | None = None):
    """Exa-based search for the recent investment narrative around a ticker.

    Returns a list of {title, url, snippet, published_date} dicts for the top
    results (news / analyst notes / sentiment). Direction-agnostic by default —
    the query asks for the current narrative whether it's bullish, bearish,
    or mixed.

    `category="financial report"` is deliberately NOT set; that filter biases
    Exa toward SEC EDGAR + IR pages, which return structured earnings data
    rather than commentary.
    """
    query = custom_query or (
        f"What is the recent investment narrative, business momentum, and "
        f"market commentary about {ticker} stock?"
    )

    logger.info("exa search: %s", query)

    search_response = _client().search(
        query,
        num_results=5,
        type="neural",
    )

    results = []
    for res in search_response.results:
        text = getattr(res, "text", None) or ""
        results.append({
            "title": res.title,
            "url": res.url,
            "snippet": text[:1000] if text else "No snippet.",
            # Exa returns `published_date` (ISO-8601) when it can extract one
            # from the source; otherwise None. Keeping it on the row lets the
            # report show "Most recent source: YYYY-MM-DD" deterministically.
            "published_date": getattr(res, "published_date", None),
        })
    return results
