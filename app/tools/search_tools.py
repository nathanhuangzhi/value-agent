import os
from exa_py import Exa
from dotenv import load_dotenv

load_dotenv()
exa = Exa(api_key=os.getenv("EXA_API_KEY"))


def get_market_commentary(ticker: str, custom_query: str | None = None):
    """Exa-based search for the recent investment narrative around a ticker.

    Returns a list of {title, url, snippet} dicts for the top results
    (news / analyst notes / sentiment). Direction-agnostic by default —
    the query asks for the current narrative whether it's bullish,
    bearish, or mixed.

    `category="financial report"` is deliberately NOT set; that filter
    biases Exa toward SEC EDGAR + IR pages, which return structured
    earnings data rather than commentary.
    """
    query = custom_query or (
        f"What is the recent investment narrative, business momentum, and "
        f"market commentary about {ticker} stock?"
    )

    print(f"--- EXA SCOUTING: {query} ---")

    search_response = exa.search(
        query,
        num_results=5,
        type="neural",
    )

    results = []
    for res in search_response.results:
        results.append({
            "title": res.title,
            "url": res.url,
            "snippet": res.text[:1000] if hasattr(res, "text") else "No snippet.",
            # Exa returns `published_date` (ISO-8601) when it can extract one
            # from the source; otherwise None. Keeping it on the row lets the
            # report show "Most recent source: YYYY-MM-DD" deterministically.
            "published_date": getattr(res, "published_date", None),
        })
    return results
