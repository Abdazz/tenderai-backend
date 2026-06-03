"""Fetch listings using the Tavily web search/extract API.

Supports two parser_type values:
- tavily_search  : POST /search with configured queries (source without stable listing URL)
- tavily_extract : POST /extract with source.list_url (stable URL, content extracted by Tavily)
"""

import json
from datetime import datetime

import httpx

from ...config import settings
from ...logging import get_logger

logger = get_logger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


async def fetch_tavily_search(source: dict, run_id: str) -> dict:
    """Call Tavily /search for each query configured in source.patterns.queries."""
    source_name = source["name"]
    api_key = settings.tavily.api_key.get_secret_value()

    if not api_key:
        logger.warning("TAVILY_API_KEY not set — skipping", source=source_name, run_id=run_id)
        return {
            "source": source,
            "content": None,
            "url": source["list_url"],
            "status": "failed",
            "error": "TAVILY_API_KEY not set",
            "fetched_at": datetime.utcnow().isoformat(),
            "parser_type": "tavily_search",
        }

    queries = source.get("patterns", {}).get("queries", [])
    if not queries:
        logger.warning("No queries configured for tavily_search source", source=source_name, run_id=run_id)
        return {
            "source": source,
            "content": json.dumps([]),
            "listings": [],
            "url": source["list_url"],
            "status": "success",
            "parser_type": "tavily_search",
            "fetched_at": datetime.utcnow().isoformat(),
        }

    all_results: list[dict] = []
    seen_urls: set[str] = set()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            for query in queries:
                payload = {
                    "api_key": api_key,
                    "query": query,
                    "search_depth": settings.tavily.search_depth,
                    "max_results": settings.tavily.max_results,
                    "include_raw_content": False,
                }
                response = await client.post(TAVILY_SEARCH_URL, json=payload)
                response.raise_for_status()
                data = response.json()

                for item in data.get("results", []):
                    url = item.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(item)

                logger.info(
                    "Tavily search query completed",
                    query=query,
                    results=len(data.get("results", [])),
                    run_id=run_id,
                )

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP {e.response.status_code}"
        logger.error("Tavily search HTTP error", source=source_name, error=error_msg, run_id=run_id)
        return {
            "source": source,
            "content": None,
            "url": source["list_url"],
            "status": "failed",
            "error": error_msg,
            "fetched_at": datetime.utcnow().isoformat(),
            "parser_type": "tavily_search",
        }
    except Exception as e:
        logger.error("Tavily search failed", source=source_name, error=str(e), run_id=run_id)
        return {
            "source": source,
            "content": None,
            "url": source["list_url"],
            "status": "failed",
            "error": str(e),
            "fetched_at": datetime.utcnow().isoformat(),
            "parser_type": "tavily_search",
        }

    logger.info("Tavily search completed", source=source_name, total=len(all_results), run_id=run_id)

    return {
        "source": source,
        "content": json.dumps(all_results, ensure_ascii=False),
        "listings": all_results,
        "url": source["list_url"],
        "status": "success",
        "parser_type": "tavily_search",
        "fetched_at": datetime.utcnow().isoformat(),
    }


async def fetch_tavily_extract(source: dict, run_id: str) -> dict:
    """Call Tavily /extract with source.list_url to get structured page content."""
    source_name = source["name"]
    api_key = settings.tavily.api_key.get_secret_value()

    if not api_key:
        logger.warning("TAVILY_API_KEY not set — skipping", source=source_name, run_id=run_id)
        return {
            "source": source,
            "content": None,
            "url": source["list_url"],
            "status": "failed",
            "error": "TAVILY_API_KEY not set",
            "fetched_at": datetime.utcnow().isoformat(),
            "parser_type": "tavily_extract",
        }

    patterns = source.get("patterns", {})
    payload = {
        "api_key": api_key,
        "urls": [source["list_url"]],
        "include_raw_content": patterns.get("include_raw_content", True),
        "extract_depth": patterns.get("extract_depth", settings.tavily.search_depth),
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(TAVILY_EXTRACT_URL, json=payload)
            response.raise_for_status()
            data = response.json()

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP {e.response.status_code}"
        logger.error("Tavily extract HTTP error", source=source_name, error=error_msg, run_id=run_id)
        return {
            "source": source,
            "content": None,
            "url": source["list_url"],
            "status": "failed",
            "error": error_msg,
            "fetched_at": datetime.utcnow().isoformat(),
            "parser_type": "tavily_extract",
        }
    except Exception as e:
        logger.error("Tavily extract failed", source=source_name, error=str(e), run_id=run_id)
        return {
            "source": source,
            "content": None,
            "url": source["list_url"],
            "status": "failed",
            "error": str(e),
            "fetched_at": datetime.utcnow().isoformat(),
            "parser_type": "tavily_extract",
        }

    results = data.get("results", [])
    normalized = [
        {
            "url": r.get("url", source["list_url"]),
            "content": r.get("raw_content", ""),
            "title": source_name,
            "score": None,
        }
        for r in results
    ]

    logger.info("Tavily extract completed", source=source_name, results=len(normalized), run_id=run_id)

    return {
        "source": source,
        "content": json.dumps(normalized, ensure_ascii=False),
        "listings": normalized,
        "url": source["list_url"],
        "status": "success",
        "parser_type": "tavily_extract",
        "fetched_at": datetime.utcnow().isoformat(),
    }
