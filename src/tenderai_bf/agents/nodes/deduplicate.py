"""Deduplicate items across sources."""

import time
from typing import Dict, List

from rapidfuzz import fuzz

from ...config import settings
from ...logging import get_logger
from ...utils.llm_utils import get_llm_instance
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def check_duplicate_with_llm(item1: Dict, item2: Dict) -> tuple[bool, float, str]:
    """
    Use LLM to determine if two tenders are duplicates.
    Returns: (is_duplicate, confidence, reasoning)
    """
    try:
        from langchain.prompts import PromptTemplate
        
        # Get LLM instance
        llm = get_llm_instance(temperature=0.0, max_tokens=100)
        if not llm:
            return False, 0.0, "LLM not available"
        
        # Get LLM model name for logging
        llm_model = getattr(llm, 'model_name', getattr(llm, 'model', 'unknown'))
        llm_provider = settings.llm.provider
        
        logger.debug(
            "Checking duplicates with LLM",
            llm_provider=llm_provider,
            llm_model=llm_model,
            item1_id=item1.get('id'),
            item2_id=item2.get('id')
        )
        
        # Get deduplication prompts from configuration
        dedup_prompts = settings.prompts.get('deduplication', {})
        system_prompt = dedup_prompts.get('system', '')
        user_template = dedup_prompts.get('user_template', '')
        
        # Fallback to hardcoded prompt if not configured
        if not user_template:
            user_template = """Comparez ces deux appels d'offres et déterminez s'il s'agit d'un doublon :

APPEL D'OFFRES 1 :
{tender1}

APPEL D'OFFRES 2 :
{tender2}

Répondez avec : is_duplicate (true/false), confidence (0.0-1.0), reasoning (explication)"""
        
        # Format tender data - use new field names with fallbacks
        tender1_str = f"""Entité: {item1.get('entity', 'N/A')}
Référence: {item1.get('reference', item1.get('ref_no', 'N/A'))}
Objet: {item1.get('tender_object', item1.get('title', 'N/A'))}
Date limite: {item1.get('deadline', item1.get('deadline_at', 'N/A'))}"""
        
        tender2_str = f"""Entité: {item2.get('entity', 'N/A')}
Référence: {item2.get('reference', item2.get('ref_no', 'N/A'))}
Objet: {item2.get('tender_object', item2.get('title', 'N/A'))}
Date limite: {item2.get('deadline', item2.get('deadline_at', 'N/A'))}"""
        
        # Create LLM prompt
        prompt = PromptTemplate(
            input_variables=["tender1", "tender2"],
            template=f"{system_prompt}\n\n{user_template}" if system_prompt else user_template
        )
        
        # Get LLM response
        message = prompt.format(tender1=tender1_str, tender2=tender2_str)
        response = llm.invoke(message)
        response_text = response.content.strip()
        
        # Parse response
        is_duplicate = "true" in response_text.lower() or "doublon" in response_text.lower()
        
        # Try to extract confidence
        confidence = 0.8 if is_duplicate else 0.2
        if "confidence" in response_text.lower():
            try:
                # Look for patterns like "confidence: 0.95" or "confiance: 0.95"
                import re
                conf_match = re.search(r'(?:confidence|confiance)[:\s]+([0-9.]+)', response_text.lower())
                if conf_match:
                    confidence = float(conf_match.group(1))
            except (ValueError, AttributeError):
                pass
        
        reasoning = response_text[:200]  # First 200 chars
        
        return is_duplicate, confidence, reasoning
        
    except Exception as e:
        logger.error("LLM deduplication check failed", error=str(e))
        return False, 0.0, f"Error: {str(e)}"


def deduplicate_node(state) -> Dict:
    """Remove duplicate items using content similarity."""
    
    # Clear output file at start
    clear_node_output("deduplicate")
    
    logger.info("Starting deduplicate step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        if not state.relevant_items:
            state.unique_items = []
            return state
        
        method = settings.processing.deduplication_method
        logger.info(f"Using deduplication method: {method}", run_id=state.run_id)
        
        unique_items = []
        seen_hashes = set()
        similar_items = []
        
        threshold = settings.processing.deduplication_threshold * 100  # Convert to percentage
        
        for item in state.relevant_items:
            content_hash = item.get('content_hash')
            # Use tender_object if available, otherwise fall back to title
            item_text = item.get('tender_object', item.get('title', ''))
            
            is_duplicate = False
            duplicate_reason = ""
            
            # Method 1: Hash-based deduplication only
            if method == "hash_only":
                if content_hash and content_hash in seen_hashes:
                    is_duplicate = True
                    duplicate_reason = "exact_hash_match"
            
            # Method 2: Similarity-based deduplication only
            elif method == "similarity_only":
                for unique_item in unique_items:
                    unique_text = unique_item.get('tender_object', unique_item.get('title', ''))
                    similarity = fuzz.ratio(item_text, unique_text)
                    if similarity >= threshold:
                        is_duplicate = True
                        duplicate_reason = f"similarity_{similarity}%"
                        item['duplicate_of_id'] = unique_item.get('id', 'unknown')
                        break
            
            # Method 3: Hash + Similarity (default)
            elif method == "hash_similarity":
                # Check exact hash duplicates first
                if content_hash and content_hash in seen_hashes:
                    is_duplicate = True
                    duplicate_reason = "exact_hash_match"
                else:
                    # Check similarity with existing items
                    for unique_item in unique_items:
                        unique_text = unique_item.get('tender_object', unique_item.get('title', ''))
                        similarity = fuzz.ratio(item_text, unique_text)
                        if similarity >= threshold:
                            is_duplicate = True
                            duplicate_reason = f"similarity_{similarity}%"
                            item['duplicate_of_id'] = unique_item.get('id', 'unknown')
                            break
            
            # Method 4: LLM-based deduplication only
            elif method == "llm_only":
                for unique_item in unique_items:
                    is_dup_llm, conf, reason = check_duplicate_with_llm(item, unique_item)
                    if is_dup_llm and conf > 0.7:
                        is_duplicate = True
                        duplicate_reason = f"llm_confidence_{conf:.2f}"
                        item['duplicate_of_id'] = unique_item.get('id', 'unknown')
                        logger.debug(
                            f"LLM marked as duplicate",
                            item_id=item.get('id'),
                            duplicate_of=unique_item.get('id'),
                            confidence=conf,
                            reason=reason[:100]
                        )
                        break
            
            # Method 5: Hybrid (Hash + Similarity + LLM for edge cases)
            elif method == "hybrid":
                # Check exact hash duplicates first
                if content_hash and content_hash in seen_hashes:
                    is_duplicate = True
                    duplicate_reason = "exact_hash_match"
                else:
                    # Check similarity
                    for unique_item in unique_items:
                        unique_text = unique_item.get('tender_object', unique_item.get('title', ''))
                        similarity = fuzz.ratio(item_text, unique_text)
                        
                        # High similarity - definitely duplicate
                        if similarity >= threshold:
                            is_duplicate = True
                            duplicate_reason = f"high_similarity_{similarity}%"
                            item['duplicate_of_id'] = unique_item.get('id', 'unknown')
                            break
                        
                        # Moderate similarity - use LLM to decide
                        elif 70 <= similarity < threshold:
                            is_dup_llm, conf, reason = check_duplicate_with_llm(item, unique_item)
                            if is_dup_llm and conf > 0.7:
                                is_duplicate = True
                                duplicate_reason = f"llm_moderate_sim_{similarity}%_conf_{conf:.2f}"
                                item['duplicate_of_id'] = unique_item.get('id', 'unknown')
                                logger.debug(
                                    f"LLM confirmed duplicate with moderate similarity",
                                    item_id=item.get('id'),
                                    similarity=similarity,
                                    llm_confidence=conf,
                                    reason=reason[:100]
                                )
                                break
            
            else:
                logger.warning(f"Unknown deduplication method: {method}, using hash_similarity")
                # Fallback to hash_similarity
                if content_hash and content_hash in seen_hashes:
                    is_duplicate = True
                    duplicate_reason = "exact_hash_match"
                else:
                    for unique_item in unique_items:
                        unique_text = unique_item.get('tender_object', unique_item.get('title', ''))
                        similarity = fuzz.ratio(item_text, unique_text)
                        if similarity >= threshold:
                            is_duplicate = True
                            duplicate_reason = f"similarity_{similarity}%"
                            item['duplicate_of_id'] = unique_item.get('id', 'unknown')
                            break
            
            # Mark and categorize item
            if is_duplicate:
                item['is_duplicate'] = True
                item['duplicate_reason'] = duplicate_reason
                similar_items.append(item)
                logger.debug(
                    "Marked as duplicate",
                    item_id=item.get('id'),
                    reason=duplicate_reason,
                    method=method
                )
            else:
                item['is_duplicate'] = False
                unique_items.append(item)
                # Only add hash to seen_hashes if it exists and is not None
                if content_hash:
                    seen_hashes.add(content_hash)
        
        state.unique_items = unique_items
        state.update_stats(
            unique_items=len(unique_items),
            duplicates_removed=len(similar_items),
            dedupe_time_seconds=time.time() - start_time
        )
        
        # Log output to JSON
        log_node_output("deduplicate", unique_items, run_id=state.run_id)
        
        logger.info(
            "Deduplicate completed",
            method=method,
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