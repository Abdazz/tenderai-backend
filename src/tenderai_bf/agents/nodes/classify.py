"""Classify items for IT/Engineering relevance."""

import time
from typing import Dict, List

from ...config import settings
from ...logging import get_logger, log_classification
from ...utils.llm_utils import get_llm_instance
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def classify_node(state) -> Dict:
    """Classify items for IT/Engineering relevance."""
    
    # Clear output file at start
    clear_node_output("classify")
    
    logger.info("Starting classify step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        # Choose classification method based on configuration
        if settings.processing.use_llm_classification:
            # Use LLM-based classification (requires LLM setup)
            logger.info("Using LLM-based classification", run_id=state.run_id)
            return classify_with_llm(state)
        else:
            # Use keyword-based classification (default)
            logger.info("Using keyword-based classification", run_id=state.run_id)
            return classify_with_keywords(state)
    
    except Exception as e:
        logger.error("Classification failed", error=str(e), run_id=state.run_id, exc_info=True)
        state.add_error("classify", str(e))
        return state


def classify_with_keywords(state) -> Dict:
    """Classify items using keyword-based matching."""
    start_time = time.time()
    relevant_items = []
    
    try:
        # Get keywords from configuration
        # Combine all keywords from different categories
        it_keywords = []
        
        if hasattr(settings, 'classification') and hasattr(settings.classification, 'relevant_keywords'):
            # Load from settings
            relevant_keywords = settings.classification.relevant_keywords
            for category, keywords in relevant_keywords.items():
                it_keywords.extend(keywords)
        else:
            # Fallback to default keywords if not in config
            it_keywords = [
                'informatique', 'logiciel', 'réseau', 'serveur', 'ordinateur',
                'internet', 'site web', 'application', 'base de données',
                'cybersécurité', 'cloud', 'données', 'numérique', 'digital',
                'ERP', 'CRM', 'SIG', 'GIS', 'télécommunication', 'fibre optique'
            ]
        
        logger.debug(
            f"Using {len(it_keywords)} keywords for classification",
            keywords_count=len(it_keywords),
            run_id=state.run_id
        )
        
        for item in state.items_parsed:
            # Simple keyword-based classification
            title_lower = item.get('title', '').lower()
            description_lower = item.get('description', '').lower()
            
            # Calculate relevance score (0.0 to 1.0)
            keyword_matches = sum(1 for keyword in it_keywords 
                                if keyword.lower() in title_lower or keyword.lower() in description_lower)
            
            relevance_score = min(keyword_matches / len(it_keywords), 1.0) if it_keywords else 0.0
            is_relevant = relevance_score >= settings.processing.min_relevance_score
            
            # Update item with classification
            item['relevance_score'] = relevance_score
            item['is_relevant'] = is_relevant
            item['classification_method'] = 'keyword_matching'
            
            if is_relevant:
                relevant_items.append(item)
            
            log_classification(
                item['id'],
                relevance_score,
                is_relevant,
                keyword_matches=keyword_matches,
                method='keyword'
            )
        
        state.relevant_items = relevant_items
        state.update_stats(
            relevant_items=len(relevant_items),
            classify_time_seconds=time.time() - start_time
        )
        
        # Log output to JSON
        log_node_output("classify", relevant_items, run_id=state.run_id)
        
        logger.info(
            "Keyword-based classification completed",
            total_items=len(state.items_parsed),
            relevant_items=len(relevant_items),
            threshold=settings.processing.min_relevance_score,
            run_id=state.run_id
        )
        
        return state
        
    except Exception as e:
        logger.error("Keyword classification failed", error=str(e), run_id=state.run_id, exc_info=True)
        state.add_error("classify", str(e))
        return state


def classify_with_llm(state) -> Dict:
    """Classify items using LLM-based analysis."""
    start_time = time.time()
    relevant_items = []
    
    try:
        from langchain.prompts import PromptTemplate
        
        # Get LLM instance
        llm = get_llm_instance(temperature=0.1, max_tokens=50)
        if not llm:
            logger.error("LLM not available, falling back to keyword classification")
            return classify_with_keywords(state)
        
        # Get LLM model name for logging
        llm_model = getattr(llm, 'model_name', getattr(llm, 'model', 'unknown'))
        llm_provider = settings.llm.provider
        
        logger.info(
            "Starting LLM-based classification",
            llm_provider=llm_provider,
            llm_model=llm_model,
            items_to_classify=len(state.items_parsed),
            run_id=state.run_id
        )
        
        # Get classification prompts from configuration
        classification_prompts = settings.prompts.get('classification', {})
        system_prompt = classification_prompts.get('system', '')
        user_template = classification_prompts.get('user_template', '')
        
        # Fallback to hardcoded prompt if not configured
        if not user_template:
            user_template = """Analysez la pertinence de cet appel d'offres :

Entité : {entity}
Référence : {reference}
Description : {description}
Mots-clés : {keywords}

Est-ce pertinent pour les secteurs IT ou Ingénierie ?"""
        
        # Create classification prompt
        prompt = PromptTemplate(
            input_variables=["entity", "reference", "description", "keywords"],
            template=f"{system_prompt}\n\n{user_template}" if system_prompt else user_template
        )
        
        # Classify each item
        for item in state.items_parsed:
            try:
                # Prepare item data
                entity = item.get('entity', item.get('title', '')) or ''
                reference = item.get('reference', item.get('ref_no', '')) or ''
                objet = (item.get('tender_object') or item.get('title') or '')[:200]  # Use tender_object, fallback to title
                description = (item.get('description') or '')[:500]  # Limit context
                keywords_val = item.get('keywords') or []
                keywords = ', '.join(keywords_val) if isinstance(keywords_val, list) else str(keywords_val)
                
                # Get LLM classification
                message = prompt.format(
                    entity=entity,
                    reference=reference,
                    objet=objet,
                    description=description,
                    keywords=keywords
                )
                response = llm.invoke(message)
                response_text = response.content.strip()
                
                # Parse response
                is_relevant = "OUI" in response_text.upper()
                
                # Extract score if available
                score = 0.0
                if "SCORE:" in response_text:
                    try:
                        score_str = response_text.split("SCORE:")[1].strip().split()[0]
                        score = float(score_str) / 100.0  # Convert to 0-1 range
                    except (ValueError, IndexError):
                        score = 0.8 if is_relevant else 0.2
                else:
                    score = 0.8 if is_relevant else 0.2
                
                item['relevance_score'] = min(1.0, max(0.0, score))  # Clamp to 0-1
                
                logger.debug(
                    "LLM classification",
                    item_id=item.get('id'),
                    relevant=is_relevant,
                    score=item['relevance_score']
                )
                
                # Filter by threshold
                if item['relevance_score'] >= settings.processing.min_relevance_score:
                    relevant_items.append(item)
                    
            except Exception as e:
                logger.error("Failed to classify item with LLM", error=str(e), item_id=item.get('id'))
                # Fall back to keyword classification for this item
                item['relevance_score'] = 0.6
                relevant_items.append(item)
        
        # Set both for pipeline flow
        state.relevant_items = relevant_items
        state.unique_items = relevant_items
        
        # Update statistics
        state.update_stats(
            relevant_items=len(relevant_items),
            classify_time_seconds=time.time() - start_time
        )
        
        # Log output to JSON
        log_node_output("classify", relevant_items, run_id=state.run_id)
        
        duration = time.time() - start_time
        logger.info(
            "LLM-based classification completed",
            total_items=len(state.items_parsed),
            relevant_items=len(relevant_items),
            provider=settings.llm.provider,
            duration_seconds=duration,
            run_id=state.run_id
        )
        
        return state
        
    except Exception as e:
        logger.error("LLM classification failed", error=str(e), run_id=state.run_id, exc_info=True)
        logger.info("Falling back to keyword-based classification")
        return classify_with_keywords(state)