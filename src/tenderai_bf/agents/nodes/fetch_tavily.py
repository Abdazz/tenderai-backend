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


def _error_result(source: dict, parser_type: str, error: str) -> dict:
    return {
        "source": source,
        "content": None,
        "listings": [],
        "url": source["list_url"],
        "status": "failed",
        "error": error,
        "fetched_at": datetime.utcnow().isoformat(),
        "parser_type": parser_type,
    }


async def fetch_tavily_search(source: dict, run_id: str) -> dict:
    """Call Tavily /search for each query configured in source.patterns.queries."""
    source_name = source["name"]
    api_key = settings.tavily.api_key.get_secret_value()

    if not api_key:
        logger.warning("TAVILY_API_KEY not set — skipping", source=source_name, run_id=run_id)
        return _error_result(source, "tavily_search", "TAVILY_API_KEY not set")

    patterns = source.get("patterns", {})
    queries = patterns.get("queries", [])
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

    include_domains: list[str] = patterns.get("include_domains", [])
    exclude_domains: list[str] = patterns.get("exclude_domains", [])
    exclude_url_patterns: list[str] = patterns.get("exclude_url_patterns", [])
    # days=N restricts Tavily to results published/indexed within the last N days.
    # Prevents stale procurement notices (already closed) from appearing in results.
    days: int | None = patterns.get("days")

    all_results: list[dict] = []
    seen_urls: set[str] = set()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            for query in queries:
                payload: dict = {
                    "api_key": api_key,
                    "query": query,
                    "search_depth": settings.tavily.search_depth,
                    "max_results": settings.tavily.max_results,
                    "include_raw_content": False,
                }
                if include_domains:
                    payload["include_domains"] = include_domains
                if exclude_domains:
                    payload["exclude_domains"] = exclude_domains
                if days is not None:
                    payload["days"] = days

                response = await client.post(TAVILY_SEARCH_URL, json=payload)
                response.raise_for_status()
                data = response.json()

                for item in data.get("results", []):
                    url = item.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    if exclude_url_patterns and any(pat in url for pat in exclude_url_patterns):
                        logger.debug("Tavily result excluded by URL pattern", url=url, run_id=run_id)
                        continue
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
        return _error_result(source, "tavily_search", error_msg)
    except Exception as e:
        logger.error("Tavily search failed", source=source_name, error=str(e), run_id=run_id)
        return _error_result(source, "tavily_search", str(e))

    logger.info("Tavily search completed", source=source_name, total=len(all_results), run_id=run_id)

    normalized = [
        {
            "url": r.get("url", ""),
            "content": r.get("content") or r.get("raw_content", ""),
            "title": r.get("title", ""),
            "score": r.get("score"),
        }
        for r in all_results
    ]

    return {
        "source": source,
        "content": json.dumps(normalized, ensure_ascii=False),
        "listings": normalized,
        "url": source["list_url"],
        "status": "success",
        "parser_type": "tavily_search",
        "fetched_at": datetime.utcnow().isoformat(),
    }


def _build_page_url(base_url: str, page_param: str, page_number: int) -> str:
    """Append a pagination parameter to a URL."""
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{page_param}={page_number}"


async def fetch_tavily_extract(source: dict, run_id: str) -> dict:
    """Call Tavily /extract with source.list_url to get structured page content.

    Supports pagination via source.patterns:
      max_pages  (int, default 1)   : number of pages to fetch
      page_param (str, default "page") : URL query param name for the page number
      page_start (int, default 0)   : value of page_param for the SECOND page
                                      (0-indexed: page 2 → page_param=1;
                                       1-indexed: page 2 → page_param=2)
    """
    source_name = source["name"]
    api_key = settings.tavily.api_key.get_secret_value()

    if not api_key:
        logger.warning("TAVILY_API_KEY not set — skipping", source=source_name, run_id=run_id)
        return _error_result(source, "tavily_extract", "TAVILY_API_KEY not set")

    patterns = source.get("patterns", {})
    include_raw_content = patterns.get("include_raw_content", True)
    extract_depth = patterns.get("extract_depth", "basic")
    max_pages: int = int(patterns.get("max_pages", 1))
    page_param: str = patterns.get("page_param", "page")
    # page_start: value of page_param for the SECOND page.
    # Drupal (0-indexed): second page = ?page=1 → page_start=1
    # 1-indexed sites:    second page = ?page=2 → page_start=2
    page_start: int = int(patterns.get("page_start", 1))

    base_url = source["list_url"]
    all_normalized: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            for page_idx in range(max_pages):
                if page_idx == 0:
                    url = base_url
                else:
                    # page_start is the param value for page 2; page 3 = page_start+1, etc.
                    url = _build_page_url(base_url, page_param, page_start + page_idx - 1)

                payload = {
                    "api_key": api_key,
                    "urls": [url],
                    "include_raw_content": include_raw_content,
                    "extract_depth": extract_depth,
                }

                try:
                    response = await client.post(TAVILY_EXTRACT_URL, json=payload)
                    response.raise_for_status()
                    data = response.json()
                except httpx.HTTPStatusError as e:
                    logger.warning(
                        "Tavily extract HTTP error on page",
                        source=source_name,
                        page=page_idx + 1,
                        error=f"HTTP {e.response.status_code}",
                        run_id=run_id,
                    )
                    break
                except Exception as e:
                    logger.warning(
                        "Tavily extract failed on page",
                        source=source_name,
                        page=page_idx + 1,
                        error=str(e),
                        run_id=run_id,
                    )
                    break

                results = data.get("results", [])
                if not results:
                    logger.info(
                        "No results on page, stopping pagination",
                        source=source_name,
                        page=page_idx + 1,
                        run_id=run_id,
                    )
                    break

                for r in results:
                    all_normalized.append({
                        "url": r.get("url", url),
                        "content": r.get("raw_content", ""),
                        "title": source_name,
                        "score": None,
                    })

                logger.info(
                    "Tavily extract page fetched",
                    source=source_name,
                    page=page_idx + 1,
                    results=len(results),
                    run_id=run_id,
                )

    except Exception as e:
        logger.error("Tavily extract failed", source=source_name, error=str(e), run_id=run_id)
        return _error_result(source, "tavily_extract", str(e))

    logger.info(
        "Tavily extract completed",
        source=source_name,
        total_pages=min(max_pages, page_idx + 1),
        results=len(all_normalized),
        run_id=run_id,
    )

    return {
        "source": source,
        "content": json.dumps(all_normalized, ensure_ascii=False),
        "listings": all_normalized,
        "url": base_url,
        "status": "success",
        "parser_type": "tavily_extract",
        "fetched_at": datetime.utcnow().isoformat(),
    }
