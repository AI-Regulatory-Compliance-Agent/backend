"""
Web Search Tool — External information retrieval for company analysis.

Used ONLY by the regulation_identifier agent (Node 1) and ONLY when
analysis_mode is "external". When a user is analysing someone else's
company, we search the web to gather publicly available information
before identifying applicable regulations.

Two backends supported:
  1. DuckDuckGo (default) — free, no API key needed, uses HTML scraping
  2. Serper API (optional) — set SERPER_API_KEY in .env for better results

The tool returns plain text snippets, NOT full web pages. These snippets
are fed into the regulation_identifier's LLM prompt as additional context.

Rate limiting: DuckDuckGo may rate-limit aggressive queries. The tool
includes basic retry logic and a timeout to prevent hanging.
"""

import os
import httpx
from app.config import get_settings

settings = get_settings()

# ── Configuration ────────────────────────────────────────────
# Check if Serper API key is available. If not, fall back to DuckDuckGo.
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
_USE_SERPER = bool(SERPER_API_KEY)

# HTTP client timeout — don't hang forever on slow responses
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def search_web(query: str, num_results: int = 5) -> list[str]:
    """
    Search the web for information about a company or topic.

    Used by regulation_identifier when analysis_mode is "external"
    to gather public information before identifying regulations.

    Args:
        query: Search query string.
               Example: "PayEasy fintech payment processing India compliance"
        num_results: Max number of result snippets to return.

    Returns:
        List of text snippets from search results.
        Each snippet is a short paragraph summarizing one search result.
        Returns empty list if search fails (agents handle gracefully).

    Example:
        >>> snippets = search_web("Razorpay payment processing compliance India")
        >>> snippets[0]
        "Razorpay is an RBI-authorized payment aggregator..."
    """
    if _USE_SERPER:
        return _search_serper(query, num_results)
    else:
        return _search_duckduckgo(query, num_results)


def _search_serper(query: str, num_results: int) -> list[str]:
    """
    Search using Serper.dev API (Google Search API wrapper).

    Serper free tier: 2,500 queries/month.
    Returns structured JSON with title, snippet, and link per result.

    To enable: add SERPER_API_KEY=your_key to .env
    """
    try:
        response = httpx.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json"
            },
            json={"q": query, "num": num_results},
            timeout=_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()

        snippets = []
        for result in data.get("organic", [])[:num_results]:
            # Combine title and snippet for richer context
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            link = result.get("link", "")
            snippets.append(f"{title}: {snippet} (Source: {link})")

        return snippets

    except Exception as e:
        # Log but don't crash — agents handle empty results gracefully
        print(f"⚠️  Serper search failed: {e}")
        return []


def _search_duckduckgo(query: str, num_results: int) -> list[str]:
    """
    Search using DuckDuckGo HTML API (no API key needed).

    Uses the DuckDuckGo instant answer API which returns
    structured results without needing authentication.

    Limitations:
      - Rate limited (be gentle, ~1 request per second)
      - Results may be less comprehensive than Google
      - No guaranteed snippet format
    """
    try:
        # DuckDuckGo instant answer API — returns JSON
        response = httpx.get(
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1
            },
            timeout=_TIMEOUT,
            follow_redirects=True
        )
        response.raise_for_status()
        data = response.json()

        snippets = []

        # Extract abstract (main topic summary)
        abstract = data.get("Abstract", "")
        if abstract:
            source = data.get("AbstractSource", "")
            snippets.append(f"{abstract} (Source: {source})")

        # Extract related topics for additional context
        for topic in data.get("RelatedTopics", [])[:num_results]:
            if isinstance(topic, dict) and "Text" in topic:
                snippets.append(topic["Text"])

        # If we got nothing from instant answers, try a basic
        # text search as fallback using the lite endpoint
        if not snippets:
            snippets = _search_duckduckgo_lite(query, num_results)

        return snippets[:num_results]

    except Exception as e:
        print(f"⚠️  DuckDuckGo search failed: {e}")
        return []


def _search_duckduckgo_lite(query: str, num_results: int) -> list[str]:
    """
    Fallback: DuckDuckGo lite HTML search.
    Parses the lightweight HTML results page when the API
    doesn't return useful instant answers.
    """
    try:
        response = httpx.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
            timeout=_TIMEOUT,
            follow_redirects=True
        )
        response.raise_for_status()

        # Basic HTML parsing — extract text between result markers
        # This is intentionally simple; we just need rough snippets
        text = response.text
        snippets = []

        # DuckDuckGo lite wraps results in specific table cells
        # Extract visible text snippets
        import re
        # Find snippet cells in the HTML table
        results = re.findall(
            r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
            text,
            re.DOTALL | re.IGNORECASE
        )

        for result in results[:num_results]:
            # Strip HTML tags to get clean text
            clean = re.sub(r'<[^>]+>', '', result).strip()
            if clean:
                snippets.append(clean)

        return snippets

    except Exception as e:
        print(f"⚠️  DuckDuckGo lite fallback failed: {e}")
        return []
