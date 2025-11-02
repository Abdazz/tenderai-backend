"""Deduplicate items across sources."""

import time
from typing import Dict, List

from rapidfuzz import fuzz

from ...config import settings
from ...logging import get_logger

logger = get_logger(__name__)


def deduplicate_node(state) -> Dict:
    """Remove duplicate items using content similarity."""
    
    logger.info("Starting deduplicate step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        if not state.relevant_items:
            state.unique_items = []
            return state
        
        unique_items = []
        seen_hashes = set()
        similar_items = []
        
        threshold = settings.processing.deduplication_threshold * 100  # Convert to percentage
        
        for item in state.relevant_items:
            content_hash = item.get('content_hash')
            title = item.get('title', '')
            
            # Check exact hash duplicates first
            if content_hash in seen_hashes:
                item['is_duplicate'] = True
                similar_items.append(item)
                continue
            
            # Check similarity with existing items
            is_duplicate = False
            for unique_item in unique_items:
                similarity = fuzz.ratio(title, unique_item.get('title', ''))
                if similarity >= threshold:
                    item['is_duplicate'] = True
                    item['duplicate_of_id'] = unique_item['id']
                    similar_items.append(item)
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                item['is_duplicate'] = False
                unique_items.append(item)
                seen_hashes.add(content_hash)
        
        state.unique_items = unique_items
        state.update_stats(
            unique_items=len(unique_items),
            duplicates_removed=len(similar_items),
            dedupe_time_seconds=time.time() - start_time
        )
        
        logger.info(
            "Deduplicate completed",
            relevant_items=len(state.relevant_items),
            unique_items=len(unique_items),
            duplicates_removed=len(similar_items),
            run_id=state.run_id
        )
        
        return state
    
    except Exception as e:
        logger.error("Deduplicate step failed", error=str(e), run_id=state.run_id, exc_info=True)
        state.add_error("deduplicate", str(e))
        return state