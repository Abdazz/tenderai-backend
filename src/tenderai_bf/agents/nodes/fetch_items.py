"""Fetch individual item pages from discovered links."""

import asyncio
import time
from datetime import datetime
from typing import Dict, List

import httpx

from ...config import settings
from ...logging import get_logger
from ...utils.node_logger import clear_node_output, log_node_output
from .fetch_joffres import extract_joffres_detail

logger = get_logger(__name__)


async def fetch_single_item(
    client: httpx.AsyncClient,
    url: str,
    run_id: str,
    parser_type: str = 'html'
) -> Dict:
    """Fetch a single item page with proper error handling."""
    
    try:
        logger.debug(
            "Fetching item",
            url=url,
            parser_type=parser_type,
            run_id=run_id
        )
        
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
        
        content = response.text
        content_type = response.headers.get('content-type', '').lower()
        
        logger.debug(
            "Item fetched successfully",
            url=url,
            status_code=response.status_code,
            size_bytes=len(content),
            run_id=run_id
        )
        
        return {
            'url': url,
            'content': content,
            'content_type': content_type,
            'status': 'success',
            'fetched_at': datetime.utcnow().isoformat(),
            'size': len(content),
            'parser_type': parser_type
        }
    
    except httpx.HTTPStatusError as e:
        logger.error(
            "HTTP error fetching item",
            url=url,
            status_code=e.response.status_code,
            error=str(e),
            run_id=run_id
        )
        return {
            'url': url,
            'content': None,
            'status': 'failed',
            'error': f"HTTP {e.response.status_code}",
            'fetched_at': datetime.utcnow().isoformat(),
            'parser_type': parser_type
        }
    
    except httpx.ConnectError as e:
        logger.error(
            "Connection error fetching item",
            url=url,
            error=str(e),
            run_id=run_id
        )
        return {
            'url': url,
            'content': None,
            'status': 'failed',
            'error': f"Connection error: {str(e)}",
            'fetched_at': datetime.utcnow().isoformat(),
            'parser_type': parser_type
        }
    
    except httpx.TimeoutException as e:
        logger.error(
            "Timeout fetching item",
            url=url,
            error=str(e),
            run_id=run_id
        )
        return {
            'url': url,
            'content': None,
            'status': 'failed',
            'error': "Request timeout",
            'fetched_at': datetime.utcnow().isoformat(),
            'parser_type': parser_type
        }
    
    except Exception as e:
        logger.error(
            "Unexpected error fetching item",
            url=url,
            error=str(e),
            run_id=run_id,
            exc_info=True
        )
        return {
            'url': url,
            'content': None,
            'status': 'failed',
            'error': str(e),
            'fetched_at': datetime.utcnow().isoformat(),
            'parser_type': parser_type
        }


async def fetch_joffres_item_detail(
    client: httpx.AsyncClient,
    url: str,
    slug: str,
    run_id: str
) -> Dict:
    """Fetch and extract details from a Joffres item."""
    
    try:
        logger.debug(
            "Fetching Joffres detail page",
            url=url,
            slug=slug,
            run_id=run_id
        )
        
        response = await client.get(url, timeout=60.0)
        response.raise_for_status()
        
        html_content = response.text
        
        # Extract structured data from the HTML
        details = extract_joffres_detail(html_content, url)
        
        logger.debug(
            "Joffres detail extracted",
            url=url,
            slug=slug,
            run_id=run_id
        )
        
        return {
            'url': url,
            'slug': slug,
            'content': html_content,
            'content_type': 'text/html',
            'status': 'success',
            'details': details,  # Structured data
            'fetched_at': datetime.utcnow().isoformat(),
            'size': len(html_content),
            'parser_type': 'html-listing',
            'source': 'joffres.net'
        }
    
    except Exception as e:
        logger.error(
            "Failed to fetch Joffres detail",
            url=url,
            slug=slug,
            error=str(e),
            run_id=run_id,
            exc_info=True
        )
        return {
            'url': url,
            'slug': slug,
            'content': None,
            'status': 'failed',
            'error': str(e),
            'fetched_at': datetime.utcnow().isoformat(),
            'parser_type': 'html-listing',
            'source': 'joffres.net'
        }


def fetch_items_node(state) -> Dict:
    """Fetch individual item pages from discovered links."""
    
    # Clear output file at start
    clear_node_output("fetch_items")
    
    logger.info("Starting fetch_items step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        if not state.discovered_links:
            logger.info("No links to fetch", run_id=state.run_id)
            state.items_raw = []
            return state
        
        logger.info(
            "Fetching items",
            links_count=len(state.discovered_links),
            run_id=state.run_id
        )
        
        items = []
        
        # Separate items by type
        quotidien_pdfs = []
        rag_pdfs = []
        joffres_items = []
        regular_urls = []
        
        for link in state.discovered_links:
            if isinstance(link, dict) and link.get('type') == 'quotidien_pdf':
                quotidien_pdfs.append(link)
            elif isinstance(link, dict) and link.get('type') == 'pdf_rag':
                rag_pdfs.append(link)
            elif isinstance(link, dict) and link.get('source') == 'joffres.net':
                joffres_items.append(link)
            else:
                # Regular URL
                url = link if isinstance(link, str) else link.get('url')
                regular_urls.append(url)
        
        # Process quotidien PDFs (already downloaded, no need to fetch)
        for link in quotidien_pdfs:
            items.append({
                'url': link['url'],
                'content': link['content'],  # PDF bytes
                'content_type': 'application/pdf',
                'status': 'success',
                'fetched_at': datetime.utcnow().isoformat(),
                'size': len(link['content']),
                'parser_type': 'pdf_quotidien',
                'type': 'quotidien_pdf',
                'title': link.get('title', 'Quotidien'),
                'filename': link.get('filename', 'quotidien.pdf')
            })
            logger.info(
                "Quotidien PDF ready for parsing",
                title=link.get('title'),
                size_mb=round(len(link['content']) / (1024 * 1024), 2),
                run_id=state.run_id
            )
        
        # Process RAG PDFs (already downloaded, no need to fetch)
        for link in rag_pdfs:
            items.append({
                'url': link['url'],
                'source_name': link.get('source_name', 'Unknown'),  # Preserve source_name
                'content': link['content'],  # PDF bytes
                'content_type': 'application/pdf',
                'status': 'success',
                'fetched_at': datetime.utcnow().isoformat(),
                'size': len(link['content']),
                'parser_type': 'pdf_rag',
                'type': 'pdf_rag',
                'title': link.get('title', 'PDF Document'),
                'filename': link.get('filename', 'document.pdf')
            })
            logger.info(
                "RAG PDF ready for parsing",
                title=link.get('title'),
                size_mb=round(len(link['content']) / (1024 * 1024), 2),
                run_id=state.run_id
            )
        
        # Fetch regular URLs asynchronously
        if regular_urls:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def fetch_all_regular():
                    async with httpx.AsyncClient(
                        headers={'User-Agent': settings.fetch.user_agent},
                        timeout=settings.fetch.timeout
                    ) as client:
                        tasks = [
                            fetch_single_item(client, url, state.run_id, 'html')
                            for url in regular_urls
                        ]
                        return await asyncio.gather(*tasks, return_exceptions=True)
                
                results = loop.run_until_complete(fetch_all_regular())
                loop.close()
                
                for result in results:
                    if isinstance(result, Exception):
                        logger.error("Error fetching item", error=str(result), run_id=state.run_id)
                    else:
                        items.append(result)
                
                logger.info(
                    "Regular URLs fetched",
                    count=len(regular_urls),
                    successful=len([r for r in results if not isinstance(r, Exception)]),
                    run_id=state.run_id
                )
            
            except Exception as e:
                logger.error(
                    "Failed to fetch regular URLs",
                    error=str(e),
                    run_id=state.run_id,
                    exc_info=True
                )
        
        # Fetch Joffres items asynchronously
        if joffres_items:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def fetch_all_joffres():
                    async with httpx.AsyncClient(
                        headers={'User-Agent': settings.fetch.user_agent},
                        timeout=settings.fetch.timeout
                    ) as client:
                        tasks = [
                            fetch_joffres_item_detail(
                                client,
                                link['url'],
                                link.get('slug', ''),
                                state.run_id
                            )
                            for link in joffres_items
                        ]
                        return await asyncio.gather(*tasks, return_exceptions=True)
                
                results = loop.run_until_complete(fetch_all_joffres())
                loop.close()
                
                for result in results:
                    if isinstance(result, Exception):
                        logger.error("Error fetching Joffres item", error=str(result), run_id=state.run_id)
                    else:
                        items.append(result)
                
                logger.info(
                    "Joffres items fetched",
                    count=len(joffres_items),
                    successful=len([r for r in results if not isinstance(r, Exception)]),
                    run_id=state.run_id
                )
            
            except Exception as e:
                logger.error(
                    "Failed to fetch Joffres items",
                    error=str(e),
                    run_id=state.run_id,
                    exc_info=True
                )
        
        state.items_raw = items
        state.update_stats(items_fetched=len(items))
        
        # Log output to JSON
        log_node_output("fetch_items", items, run_id=state.run_id)
        
        duration = time.time() - start_time
        logger.info(
            "Fetch items completed",
            items_fetched=len(items),
            duration_seconds=round(duration, 2),
            run_id=state.run_id
        )
        
        return state
    
    except Exception as e:
        logger.error(
            "Fetch items step failed",
            error=str(e),
            run_id=state.run_id,
            exc_info=True
        )
        state.add_error("fetch_items", str(e))
        return state