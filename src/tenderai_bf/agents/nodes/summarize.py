"""Generate summaries for items."""

import time
from typing import Dict

from ...logging import get_logger

logger = get_logger(__name__)


def summarize_node(state) -> Dict:
    """Generate French summaries for unique items."""
    
    logger.info("Starting summarize step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        summaries = {}
        
        for item in state.unique_items:
            # Generate mock summary (TODO: implement LLM-based summarization)
            summary_fr = f"""
**Objet :** {item.get('title', 'N/A')}
**Entité :** {item.get('entity', 'N/A')}
**Référence :** {item.get('ref_no', 'N/A')}
**Catégorie :** {item.get('category', 'N/A')}
**Localisation :** {item.get('location', 'N/A')}
**Date limite :** {item.get('deadline_at', 'N/A')}

**Résumé :** Cet appel d'offres concerne des services informatiques et d'ingénierie pour le secteur public au Burkina Faso. Les détails spécifiques incluent les exigences techniques, les critères d'éligibilité et les modalités de soumission.

**URL Source :** {item.get('url', 'N/A')}
""".strip()
            
            summaries[item['id']] = summary_fr
            item['summary_fr'] = summary_fr
        
        state.summaries = summaries
        
        duration = time.time() - start_time
        logger.info(
            "Summarize completed",
            summaries_generated=len(summaries),
            duration_seconds=duration,
            run_id=state.run_id
        )
        
        return state
    
    except Exception as e:
        logger.error("Summarize step failed", error=str(e), run_id=state.run_id, exc_info=True)
        state.add_error("summarize", str(e))
        return state