"""Parse and extract structured data from item pages."""

import hashlib
import time
import uuid
from datetime import datetime
from typing import Dict, List

from selectolax.parser import HTMLParser

from ...logging import get_logger

logger = get_logger(__name__)


def parse_extract_node(state) -> Dict:
    """Parse and extract structured data from fetched items."""
    
    logger.info("Starting parse_extract step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        parsed_items = []
        
        for item in state.items_raw:
            if item['status'] != 'success' or not item['content']:
                continue
            
            # Create mock parsed data (TODO: implement real parsing)
            content_hash = hashlib.sha256(item['content'].encode()).hexdigest()
            
            parsed_item = {
                'id': str(uuid.uuid4()),
                'url': item['url'],
                'title': f"Mock Tender Title for {item['url'][-10:]}",
                'ref_no': f"REF-{len(parsed_items) + 1:04d}",
                'entity': "Mock Government Entity",
                'category': "Services",
                'description': "Mock tender description extracted from HTML content",
                'published_at': datetime.utcnow().isoformat(),
                'deadline_at': datetime.utcnow().isoformat(),
                'location': "Ouagadougou, Burkina Faso",
                'content_hash': content_hash
            }
            
            parsed_items.append(parsed_item)
        
        state.items_parsed = parsed_items
        state.update_stats(
            items_parsed=len(parsed_items),
            parse_time_seconds=time.time() - start_time
        )
        
        logger.info(
            "Parse extract completed",
            items_parsed=len(parsed_items),
            run_id=state.run_id
        )
        
        return state
    
    except Exception as e:
        logger.error("Parse extract step failed", error=str(e), run_id=state.run_id, exc_info=True)
        state.add_error("parse_extract", str(e))
        return state