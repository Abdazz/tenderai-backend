"""Classify items for IT/Engineering relevance."""

import time
from typing import Dict, List

from ...config import settings
from ...logging import get_logger, log_classification

logger = get_logger(__name__)


def classify_node(state) -> Dict:
    """Classify items for IT/Engineering relevance."""
    
    logger.info("Starting classify step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        relevant_items = []
        
        # IT/Engineering keywords
        it_keywords = [
            'informatique', 'logiciel', 'réseau', 'serveur', 'ordinateur',
            'internet', 'site web', 'application', 'base de données',
            'cybersécurité', 'cloud', 'données', 'numérique', 'digital',
            'ERP', 'CRM', 'SIG', 'GIS', 'télécommunication', 'fibre optique'
        ]
        
        for item in state.items_parsed:
            # Simple keyword-based classification (mock)
            title_lower = item.get('title', '').lower()
            description_lower = item.get('description', '').lower()
            
            # Calculate relevance score
            keyword_matches = sum(1 for keyword in it_keywords 
                                if keyword in title_lower or keyword in description_lower)
            
            relevance_score = min(keyword_matches / len(it_keywords), 1.0)
            is_relevant = relevance_score >= settings.processing.min_relevance_score
            
            # Update item with classification
            item['relevance_score'] = relevance_score
            item['is_relevant'] = is_relevant
            item['classification_method'] = 'rules'
            
            if is_relevant:
                relevant_items.append(item)
            
            log_classification(
                item['id'],
                relevance_score,
                is_relevant,
                keyword_matches=keyword_matches
            )
        
        state.relevant_items = relevant_items
        state.update_stats(
            relevant_items=len(relevant_items),
            classify_time_seconds=time.time() - start_time
        )
        
        logger.info(
            "Classify completed",
            total_items=len(state.items_parsed),
            relevant_items=len(relevant_items),
            run_id=state.run_id
        )
        
        return state
    
    except Exception as e:
        logger.error("Classify step failed", error=str(e), run_id=state.run_id, exc_info=True)
        state.add_error("classify", str(e))
        return state