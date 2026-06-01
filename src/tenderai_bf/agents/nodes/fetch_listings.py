"""Fetch listing pages from sources."""

import asyncio
import json
import time
from datetime import datetime

import httpx

from ...config import settings
from ...db import get_db_context
from ...logging import get_logger, log_source_fetch
from ...models import Source
from ...storage import get_storage_client
from ...utils.http_retry import fetch_with_retry
from ...utils.node_logger import clear_node_output, log_node_output
from .fetch_joffres import extract_joffres_listings
from .fetch_quotidien import download_quotidien_pdf, fetch_dgcmef_quotidien
from .fetch_ungm import COUNTRY_BURKINA_FASO, fetch_ungm_listings

logger = get_logger(__name__)


async def fetch_single_listing(
    client: httpx.AsyncClient, source: dict, run_id: str
) -> dict:
    """Fetch a single listing page from a source.

    Handles two types of sources:
    - Standard HTML listings: Fetch listing page with links
    - PDF quotidiens (DGCMEF): Fetch latest daily bulletin PDF link
    """

    source_name = source["name"]
    list_url = source["list_url"]
    parser_type = source.get(
        "parser_type", "html"
    )  # Changed from 'parser' to 'parser_type'

    logger.info(
        "fetch_single_listing called",
        source_name=source_name,
        parser_type=parser_type,
        run_id=run_id,
    )

    # Special handling for DGCMEF quotidiens
    if parser_type == "pdf_quotidien":
        logger.info(
            "Fetching PDF quotidien source",
            source=source_name,
            url=list_url,
            run_id=run_id,
        )

        # Use specialized quotidien fetcher
        result = await fetch_dgcmef_quotidien(source, run_id)

        if result["status"] == "success":
            # Download the PDF
            pdf_result = await download_quotidien_pdf(
                result["pdf_url"], source_name, run_id
            )

            if pdf_result["status"] == "success":
                # Store the PDF for processing
                try:
                    storage_client = get_storage_client()
                    pdf_key = storage_client.store_snapshot(
                        content=pdf_result["content"],
                        source_name=source_name,
                        url=result["pdf_url"],
                        run_id=run_id,
                        content_type="application/pdf",
                    )

                    logger.info(
                        "PDF quotidien stored successfully",
                        source=source_name,
                        pdf_key=pdf_key,
                        run_id=run_id,
                    )

                except Exception as storage_error:
                    logger.error(
                        "Failed to store PDF snapshot",
                        source_name=source_name,
                        error=str(storage_error),
                    )

                log_source_fetch(
                    source_name, list_url, "success", size=pdf_result["size_bytes"]
                )

                return {
                    "source": source,
                    "content": pdf_result["content"],
                    "content_type": "application/pdf",
                    "url": result["pdf_url"],
                    "status": "success",
                    "fetched_at": datetime.utcnow().isoformat(),
                    "size": pdf_result["size_bytes"],
                    "quotidien_title": result["title"],
                    "quotidien_filename": result["pdf_filename"],
                }
            else:
                # PDF download failed
                log_source_fetch(
                    source_name, result["pdf_url"], "failed", error=pdf_result["error"]
                )
                return {
                    "source": source,
                    "status": "failed",
                    "error": f"Failed to download PDF: {pdf_result['error']}",
                    "url": result["pdf_url"],
                }
        else:
            # Quotidien fetching failed
            log_source_fetch(source_name, list_url, "failed", error=result["error"])
            return {
                "source": source,
                "status": "failed",
                "error": result["error"],
                "url": list_url,
            }

    # Special handling for RAG-based PDF parsing
    if parser_type == "pdf_rag":
        logger.info(
            "Fetching PDF for RAG parsing",
            source=source_name,
            url=list_url,
            run_id=run_id,
        )

        # Use the same quotidien fetcher (both fetch from DGCMEF)
        result = await fetch_dgcmef_quotidien(source, run_id)

        if result["status"] == "success":
            # Download the PDF
            pdf_result = await download_quotidien_pdf(
                result["pdf_url"], source_name, run_id
            )

            if pdf_result["status"] == "success":
                logger.info(
                    "PDF downloaded for RAG",
                    source=source_name,
                    size_bytes=pdf_result["size_bytes"],
                    run_id=run_id,
                )

                log_source_fetch(
                    source_name, list_url, "success", size=pdf_result["size_bytes"]
                )

                return {
                    "source": source,
                    "source_name": source_name,  # Add explicit source_name for downstream processing
                    "content": pdf_result["content"],
                    "content_type": "application/pdf",
                    "url": result["pdf_url"],
                    "status": "success",
                    "fetched_at": datetime.utcnow().isoformat(),
                    "size": pdf_result["size_bytes"],
                    "parser_type": "pdf_rag",
                    "quotidien_title": result["title"],
                    "quotidien_filename": result["pdf_filename"],
                }
            else:
                log_source_fetch(
                    source_name, result["pdf_url"], "failed", error=pdf_result["error"]
                )
                return {
                    "source": source,
                    "status": "failed",
                    "error": f"Failed to download PDF: {pdf_result['error']}",
                    "url": result["pdf_url"],
                }
        else:
            log_source_fetch(source_name, list_url, "failed", error=result["error"])
            return {
                "source": source,
                "status": "failed",
                "error": result["error"],
                "url": list_url,
            }

    # Google Custom Search source
    if parser_type == "google_search":
        return await fetch_google_search_listings(source, run_id)

    # UNGM source — uses POST API filtered by country
    if parser_type == "ungm":
        try:
            country_ids = source.get("ungm_settings", {}).get(
                "country_ids", [COUNTRY_BURKINA_FASO]
            )
            page_size = source.get("ungm_settings", {}).get("page_size", 50)
            listings = await fetch_ungm_listings(country_ids, page_size=page_size)
            logger.info(
                "UNGM listings fetched",
                source=source_name,
                count=len(listings),
                run_id=run_id,
            )
            log_source_fetch(source_name, list_url, "success", size=len(listings))
            return {
                "source": source,
                "content": json.dumps(listings, ensure_ascii=False),
                "listings": listings,
                "url": list_url,
                "status": "success",
                "parser_type": "ungm",
                "fetched_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(
                "UNGM fetch failed", source=source_name, error=str(e), run_id=run_id
            )
            log_source_fetch(source_name, list_url, "failed", error=str(e))
            return {
                "source": source,
                "content": None,
                "url": list_url,
                "status": "failed",
                "error": str(e),
                "fetched_at": datetime.utcnow().isoformat(),
            }

    # Standard HTML listing source (ARCOP and others)
    try:
        # Respect rate limits
        rate_limit = source.get("rate_limit", "10/m")
        # TODO: Implement proper rate limiting

        # Fetch the listing page with exponential-backoff retries on
        # transient errors (timeouts, connection resets, 5xx, 429).
        response = await fetch_with_retry(
            client,
            list_url,
            timeout=60.0,
            label=f"listing:{source_name}",
        )

        # Get content
        content = response.text
        content_type = response.headers.get("content-type", "").lower()

        # Special handling for joffres.net (html-listing parser)
        if parser_type == "html-listing" and "joffres" in source_name.lower():
            logger.info(
                "Parsing joffres.net HTML listing",
                source=source_name,
                url=list_url,
                run_id=run_id,
            )

            # Extract tender listings from HTML
            listings = extract_joffres_listings(content, list_url)

            logger.info(
                f"Extracted {len(listings)} listings from joffres.net",
                source=source_name,
                count=len(listings),
                run_id=run_id,
            )

            # For joffres.net, we'll return the listings to be fetched as detail pages
            # Store the listings data in content for extraction step to process
            listings_json = json.dumps(listings)

            # Store the raw HTML too
            try:
                storage_client = get_storage_client()
                storage_client.store_snapshot(
                    content=content,
                    source_name=source_name,
                    url=list_url,
                    run_id=run_id,
                    content_type="text/html",
                )
            except Exception as storage_error:
                logger.error(
                    "Failed to store joffres listing snapshot",
                    source_name=source_name,
                    error=str(storage_error),
                )

            log_source_fetch(source_name, list_url, "success", size=len(content))

            return {
                "source": source,
                "content": listings_json,  # JSON array of listings
                "content_type": "application/json",
                "url": list_url,
                "status": "success",
                "fetched_at": datetime.utcnow().isoformat(),
                "size": len(content),
                "parser_type": "html-listing",
                "listings": listings,
            }

        # Update source last_seen_at
        try:

            with get_db_context() as session:
                db_source = (
                    session.query(Source).filter(Source.id == source.get("id")).first()
                )
                if db_source:
                    db_source.last_seen_at = datetime.utcnow()
                    db_source.last_success_at = datetime.utcnow()
                    session.commit()
        except Exception as db_error:
            logger.error(
                "Failed to update source timestamp",
                source_name=source_name,
                error=str(db_error),
            )

        # Store snapshot for audit
        try:
            storage_client = get_storage_client()
            storage_client.store_snapshot(
                content=content,
                source_name=source_name,
                url=list_url,
                run_id=run_id,
                content_type="text/html" if "html" in content_type else "text/plain",
            )
        except Exception as storage_error:
            logger.error(
                "Failed to store snapshot",
                source_name=source_name,
                error=str(storage_error),
            )

        log_source_fetch(source_name, list_url, "success", size=len(content))

        return {
            "source": source,
            "content": content,
            "content_type": content_type,
            "url": list_url,
            "status": "success",
            "fetched_at": datetime.utcnow().isoformat(),
            "size": len(content),
        }

    except httpx.TimeoutException:
        error_msg = "Request timeout"
        logger.error("Source fetch timeout", source_name=source_name, url=list_url)
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP {e.response.status_code}: {e.response.reason_phrase}"
        logger.error(
            "Source fetch HTTP error",
            source_name=source_name,
            url=list_url,
            status_code=e.response.status_code,
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(
            "Source fetch failed",
            source_name=source_name,
            url=list_url,
            error=error_msg,
            exc_info=True,
        )

    # Update source with error
    try:
        with get_db_context() as session:
            db_source = (
                session.query(Source).filter(Source.id == source.get("id")).first()
            )
            if db_source:
                db_source.last_seen_at = datetime.utcnow()
                db_source.last_error_at = datetime.utcnow()
                db_source.last_error_message = error_msg
                session.commit()
    except Exception as db_error:
        logger.error(
            "Failed to update source error",
            source_name=source_name,
            error=str(db_error),
        )

    log_source_fetch(source_name, list_url, "failed", error=error_msg)

    return {
        "source": source,
        "content": None,
        "url": list_url,
        "status": "failed",
        "error": error_msg,
        "fetched_at": datetime.utcnow().isoformat(),
    }


async def fetch_google_search_listings(source: dict, run_id: str) -> dict:
    """Call Google Custom Search API for each configured query and aggregate results."""
    source_name = source["name"]
    api_key = settings.google_search.api_key.get_secret_value()
    engine_id = settings.google_search.engine_id
    max_results = settings.google_search.max_results_per_query

    if not api_key or not engine_id:
        logger.warning(
            "Google Search API not configured — skipping",
            source=source_name,
            run_id=run_id,
        )
        return {
            "source": source,
            "content": None,
            "url": source["list_url"],
            "status": "failed",
            "error": "GOOGLE_API_KEY or GOOGLE_SEARCH_ENGINE_ID not set",
            "fetched_at": datetime.utcnow().isoformat(),
        }

    queries = source.get("google_search_settings", {}).get(
        "queries",
        [
            '"appel d\'offres" "Burkina Faso" informatique',
        ],
    )

    all_results = []
    seen_urls: set = set()

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0), follow_redirects=True
    ) as client:
        for query in queries:
            try:
                resp = await client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": api_key,
                        "cx": engine_id,
                        "q": query,
                        "num": min(max_results, 10),
                        "lr": "lang_fr",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("items", []):
                    url = item.get("link", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(
                            {
                                "url": url,
                                "title": item.get("title", ""),
                                "snippet": item.get("snippet", ""),
                                "query": query,
                            }
                        )

                logger.info(
                    "Google Search query completed",
                    query=query,
                    results=len(data.get("items", [])),
                    run_id=run_id,
                )

            except Exception as e:
                logger.warning(
                    "Google Search query failed",
                    query=query,
                    error=str(e),
                    run_id=run_id,
                )

    logger.info(
        "Google Search listings fetched",
        source=source_name,
        total_urls=len(all_results),
        run_id=run_id,
    )
    log_source_fetch(source_name, source["list_url"], "success", size=len(all_results))

    return {
        "source": source,
        "content": json.dumps(all_results, ensure_ascii=False),
        "url": source["list_url"],
        "status": "success",
        "parser_type": "google_search",
        "fetched_at": datetime.utcnow().isoformat(),
    }


async def fetch_all_listings(sources: list[dict], run_id: str) -> list[dict]:
    """Fetch all listing pages concurrently."""

    # Configure HTTP client
    headers = {
        "User-Agent": "TenderAI-BF/1.0 (+https://yulcom.com/tenderai)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    # Create async HTTP client
    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(
            60.0
        ),  # Increased from 30s to 60s for slow sites like joffres.net
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        follow_redirects=True,
    ) as client:
        # Create tasks for all sources
        tasks = []
        for source in sources:
            task = fetch_single_listing(client, source, run_id)
            tasks.append(task)

        # Execute all fetches concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                source = sources[i]
                logger.error(
                    "Async fetch failed",
                    source_name=source["name"],
                    error=str(result),
                    exc_info=True,
                )
                processed_results.append(
                    {
                        "source": source,
                        "content": None,
                        "url": source["list_url"],
                        "status": "failed",
                        "error": str(result),
                        "fetched_at": datetime.utcnow().isoformat(),
                    }
                )
            else:
                processed_results.append(result)

        return processed_results


def fetch_listings_node(state) -> dict:
    """Fetch listing pages from all active sources."""

    # Clear output file at start
    clear_node_output("fetch_listings")

    if state.error_occurred:
        return state

    logger.info("Starting fetch_listings step", run_id=state.run_id)
    start_time = time.time()

    try:
        if not state.sources:
            logger.error("No sources to fetch", run_id=state.run_id)
            state.add_error("fetch_listings", "No sources available to fetch")
            state.should_continue = False
            return state

        logger.info(
            "Fetching listings from sources",
            sources_count=len(state.sources),
            run_id=state.run_id,
        )

        # Fetch all listings concurrently
        # Always run in a new event loop (safer in LangGraph context)
        listings = asyncio.run(fetch_all_listings(state.sources, state.run_id))

        # Process results
        successful_fetches = [l for l in listings if l["status"] == "success"]
        failed_fetches = [l for l in listings if l["status"] == "failed"]

        # Store raw listings data
        state.items_raw = listings

        # Log output to JSON
        log_node_output("fetch_listings", listings, run_id=state.run_id)

        # Update statistics
        fetch_time = time.time() - start_time
        state.update_stats(
            fetch_time_seconds=fetch_time, sources_checked=len(state.sources)
        )

        # Log results
        logger.info(
            "Fetch listings completed",
            total_sources=len(state.sources),
            successful=len(successful_fetches),
            failed=len(failed_fetches),
            duration_seconds=fetch_time,
            run_id=state.run_id,
        )

        # If at least one source succeeded, treat partial failures as non-fatal warnings
        # so the pipeline keeps running with the data we did manage to fetch.
        if successful_fetches:
            for failed in failed_fetches:
                state.add_warning(
                    "fetch_listings",
                    f"Failed to fetch {failed['source']['name']}: {failed.get('error', 'Unknown error')}",
                    source_name=failed["source"]["name"],
                    url=failed["url"],
                )
        else:
            # All sources failed → fatal
            for failed in failed_fetches:
                state.add_error(
                    "fetch_listings",
                    f"Failed to fetch {failed['source']['name']}: {failed.get('error', 'Unknown error')}",
                    source_name=failed["source"]["name"],
                    url=failed["url"],
                )
            logger.error("All source fetches failed", run_id=state.run_id)
            state.add_error("fetch_listings", "All source fetches failed")
            state.should_continue = False

        return state

    except Exception as e:
        logger.error(
            "Fetch listings step failed",
            error=str(e),
            run_id=state.run_id,
            exc_info=True,
        )
        state.add_error("fetch_listings", str(e))
        state.should_continue = False
        return state
