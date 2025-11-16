"""Generate summaries for items using LLM (Groq or OpenAI)."""

import time
from typing import Dict

from ...config import settings
from ...logging import get_logger
from ...utils.llm_utils import get_llm_instance
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def generate_summary_with_llm(item: Dict) -> str:
    """Generate LLM-based tender summary in French."""
    try:
        from langchain.prompts import PromptTemplate
        
        # Get LLM instance
        llm = get_llm_instance(temperature=0.3, max_tokens=300)
        if not llm:
            logger.error("LLM not available, using fallback summary")
            return _generate_fallback_summary(item)
        
        # Get LLM model name for logging
        llm_model = getattr(llm, 'model_name', getattr(llm, 'model', 'unknown'))
        llm_provider = settings.llm.provider
        
        logger.debug(
            "Generating summary with LLM",
            llm_provider=llm_provider,
            llm_model=llm_model,
            item_id=item.get('id')
        )
        
        # Get summarization prompts from configuration
        summarization_prompts = settings.prompts.get('summarization', {})
        system_prompt = summarization_prompts.get('system', '')
        user_template = summarization_prompts.get('user_template', '')
        
        # Fallback to hardcoded prompt if not configured
        if not user_template:
            user_template = """Créez un résumé concis (2-3 phrases) pour cet appel d'offres :

{tender_details}"""
        
        # Prepare item context
        tender_details = f"""
**Titre:** {item.get('title', 'N/A')}
**Entité:** {item.get('entity', 'N/A')}
**Référence:** {item.get('ref_no', 'N/A')}
**Catégorie:** {item.get('category', 'N/A')}
**Localisation:** {item.get('location', 'N/A')}
**Date limite:** {item.get('deadline_at', 'N/A')}
**Description:** {item.get('description', 'N/A')[:500]}
""".strip()
        
        # Create LLM prompt
        prompt = PromptTemplate(
            input_variables=["tender_details"],
            template=f"{system_prompt}\n\n{user_template}" if system_prompt else user_template
        )
        
        # Generate summary
        message = prompt.format(tender_details=tender_details)
        response = llm.invoke(message)
        summary = response.content.strip()
        
        # Ensure structured format
        if not summary.startswith("**"):
            summary = f"**Résumé:**\n{summary}"
        
        return summary
        
    except Exception as e:
        logger.error("LLM summary generation failed", error=str(e))
        return _generate_fallback_summary(item)


def _generate_fallback_summary(item: Dict) -> str:
    """Generate structured summary without LLM (fallback)."""
    return f"""
**Objet :** {item.get('title', 'N/A')}
**Entité :** {item.get('entity', 'N/A')}
**Référence :** {item.get('ref_no', 'N/A')}
**Catégorie :** {item.get('category', 'N/A')}
**Localisation :** {item.get('location', 'N/A')}
**Date limite :** {item.get('deadline_at', 'N/A')}
""".strip()


def summarize_node(state) -> Dict:
    """Generate French summaries for unique items using LLM."""
    
    # Clear output file at start
    clear_node_output("summarize")
    
    logger.info("Starting summarize step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        summaries = {}
        summarized_items = []
        
        for item in state.unique_items:
            # Generate LLM-based summary
            summary_fr = generate_summary_with_llm(item)
            
            # Add summary to the summaries dict
            summaries[item['id']] = summary_fr
            
            # Add summary as a field to the item
            item['summary_fr'] = summary_fr
            summarized_items.append(item)
            
            logger.debug(
                "Summary generated",
                item_id=item['id'],
                source=item.get('source', 'unknown')
            )
        
        # Update state with both summaries dict and items with summaries
        state.summaries = summaries
        state.unique_items = summarized_items
        
        # Log the full items with summaries (not just the summaries dict)
        log_node_output("summarize", summarized_items, run_id=state.run_id)
        
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