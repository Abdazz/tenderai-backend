"""Fetch individual item pages from discovered links."""

import asyncio
import time
from datetime import datetime
from typing import Dict, List

import httpx

from ...config import settings
from ...logging import get_logger

logger = get_logger(__name__)


async def fetch_single_item(client: httpx.AsyncClient, url: str, run_id: str) -> Dict:
    """Fetch a single item page."""
    
    try:
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
        
        content = response.text
        content_type = response.headers.get('content-type', '').lower()
        
        return {
            'url': url,
            'content': content,
            'content_type': content_type,
            'status': 'success',
            'fetched_at': datetime.utcnow().isoformat(),
            'size': len(content)
        }
    
    except Exception as e:
        logger.warning(
            "Failed to fetch item",
            url=url,
            error=str(e)
        )
        return {
            'url': url,
            'content': None,
            'status': 'failed',
            'error': str(e),
            'fetched_at': datetime.utcnow().isoformat()
        }


def fetch_items_node(state) -> Dict:
    """Fetch individual item pages from discovered links."""
    
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
        
        # Create mock data for now (TODO: implement actual fetching)
        items = []
        for i, url in enumerate(state.discovered_links[:10]):  # Limit for demo
            # Mock item data
            items.append({
                'url': url,
                'content': f"<html><body><h1>Mock tender item {i+1}</h1><p>This is mock content for {url}</p></body></html>",
                'content_type': 'text/html',
                'status': 'success',
                'fetched_at': datetime.utcnow().isoformat(),
                'size': 200
            })
        
        state.items_raw = items
        state.update_stats(items_fetched=len(items))
        
        duration = time.time() - start_time
        logger.info(
            "Fetch items completed",
            items_fetched=len(items),
            duration_seconds=duration,
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