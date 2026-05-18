"""Classify items for IT/Engineering relevance."""

import time
from typing import Dict

from ...config import settings
from ...logging import get_logger, log_classification
from ...utils.llm_utils import get_llm_instance
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)

_ATTRIBUTION_SIGNALS = [
    # Attribution / marché attribué
    "résultats provisoires", "résultats définitifs",
    "résultat provisoire", "résultat définitif",
    "avis d'attribution", "attribution du marché",
    "recours préalable", "adjudicataire", "attributaire",
    "marché attribué", "contrat attribué",
    "rectificatif des résultats",
    # PV de dépouillement / ouverture des plis — soumissions déjà reçues et comptées
    "nombre de plis reçus",
    "plis reçus",
    "nombre d'offres reçues",
    "offres reçues",
    "candidats retenus",
    "soumissionnaires retenus",
    "nombre de candidats retenus",
    "procès-verbal de dépouillement",
    "pv de dépouillement",
    "séance de dépouillement",
    "avis d'appel à la concurrence annulé",
    "infructueux",
]

# Signals that identify supplier/provider registration calls (not actionable IT tenders)
_SUPPLIER_REGISTRATION_SIGNALS = [
    "constitution d'une base de données de fournisseurs",
    "constitution d'une base de données des fournisseurs",
    "constitution d'une base de données de prestataires",
    "constitution d'une base de données des prestataires",
    "constitution d'une base de données complémentaire",
    "constitution d'une base de donnees",
    "base de données de fournisseurs",
    "base de données des fournisseurs",
    "base de données de prestataires",
    "base de données des prestataires",
    "liste de fournisseurs agréés",
    "fichier de fournisseurs",
    "répertoire de fournisseurs",
    "répertoire de prestataires",
    "préqualification de fournisseurs",
    "préqualification de prestataires",
]


def _is_attribution_notice(item: dict) -> bool:
    """Return True if this item concerns attribution results, not an open procurement."""
    text = " ".join([
        item.get("title") or "",
        item.get("tender_object") or "",
        item.get("description") or "",
    ]).lower()
    return any(signal in text for signal in _ATTRIBUTION_SIGNALS)


def _is_supplier_registration(item: dict) -> bool:
    """Return True if this item is a supplier/provider registration call, not an IT tender.

    These are administrative calls for companies to register as approved vendors —
    they are not procurement contracts YULCOM can bid on as an IT provider.
    """
    text = " ".join([
        item.get("title") or "",
        item.get("tender_object") or "",
        item.get("description") or "",
    ]).lower()
    return any(signal in text for signal in _SUPPLIER_REGISTRATION_SIGNALS)


def classify_node(state) -> Dict:
    """Classify items for IT/Engineering relevance."""
    
    # Clear output file at start
    clear_node_output("classify")

    if state.error_occurred:
        return state

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
            # Items from structured PDF extraction carry embedded classification — pass through
            if item.get('classification_embedded'):
                if item.get('is_relevant') and not item.get('is_results_notice'):
                    relevant_items.append(item)
                    logger.debug(
                        "Pass-through: structured extraction pre-classified item as relevant",
                        item_id=item.get('id'),
                        domain=item.get('domain'),
                        score=item.get('relevance_score'),
                        run_id=state.run_id,
                    )
                continue

            # Exclude attribution/results notices regardless of content
            if _is_attribution_notice(item):
                item['relevance_score'] = 0.0
                item['is_relevant'] = False
                item['classification_method'] = 'attribution_filter'
                logger.debug("Excluded attribution notice", item_id=item.get('id'), run_id=state.run_id)
                continue

            # Exclude supplier/provider registration calls (not actionable IT tenders)
            if _is_supplier_registration(item):
                item['relevance_score'] = 0.0
                item['is_relevant'] = False
                item['classification_method'] = 'supplier_registration_filter'
                logger.debug("Excluded supplier registration call", item_id=item.get('id'), run_id=state.run_id)
                continue

            # Check if item already has relevance_score from extraction (LLM-scored items)
            existing_score = item.get('relevance_score')
            
            if existing_score is not None and existing_score >= settings.processing.min_relevance_score:
                # Item already scored by LLM extraction, preserve that score
                relevant_items.append(item)
                logger.debug(
                    "Using existing LLM relevance score",
                    item_id=item.get('id'),
                    score=existing_score,
                    run_id=state.run_id
                )
                continue
            
            # Perform keyword-based classification for items without scores
            # Get all text fields for matching
            title_lower = item.get('title', '').lower()
            description_lower = item.get('description', '').lower()
            tender_object_lower = item.get('tender_object', '').lower()
            category_lower = item.get('category', '').lower()
            
            # Combine all text for search
            all_text = f"{title_lower} {description_lower} {tender_object_lower} {category_lower}"
            
            # Calculate relevance score (0.0 to 1.0)
            # Score based on: any keyword match = 1.0, no match = 0.0
            # This is a simpler approach: if ANY keyword matches, it's relevant
            keyword_matches = sum(1 for keyword in it_keywords 
                                if keyword.lower() in all_text)
            
            # For keyword matching: if ANY keyword matches, consider it relevant
            # Otherwise score is proportional to number of matches
            if keyword_matches > 0:
                relevance_score = min(1.0, 0.5 + (keyword_matches / len(it_keywords) * 0.5))
            else:
                relevance_score = 0.0
            
            # Use a lower threshold for keyword-based classification
            # (LLM-scored items already passed through extraction with 0.7 threshold)
            keyword_threshold = min(0.3, settings.processing.min_relevance_score)
            is_relevant = relevance_score >= keyword_threshold
            
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
    """Classify items using LLM-based analysis with keyword fallback."""
    start_time = time.time()
    relevant_items = []
    
    try:
        # Get LLM instance
        llm = get_llm_instance(temperature=0.1, max_tokens=200)
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
        
        # Get keywords for keyword-based fallback
        it_keywords = []
        if hasattr(settings, 'classification') and hasattr(settings.classification, 'relevant_keywords'):
            relevant_keywords = settings.classification.relevant_keywords
            for category, keywords in relevant_keywords.items():
                it_keywords.extend(keywords)
        
        # Classification prompt — scoped to YULCOM's actual business domains
        classification_prompt = """Vous êtes un expert en marchés publics IT au Burkina Faso. Analysez cet appel d'offres.

Entité : {entity}
Référence : {reference}
Objet : {objet}
Description : {description}

DOMAINES CIBLÉS (répondez OUI uniquement si l'objet correspond à l'un de ces domaines) :
1. Services IT : développement logiciel, systèmes d'information, ERP, CRM, SIG, cybersécurité, cloud, hébergement, infogérance, réseau informatique, fibre optique, wifi, vidéoconférence, intelligence artificielle
2. Matériel informatique : ordinateurs, serveurs, imprimantes, scanners, photocopieurs, routeurs, switches, modems, écrans, onduleurs, accessoires informatiques
3. Conseil/ingénierie IT : études informatiques, audits de sécurité, assistance technique IT, schémas directeurs informatiques, formation informatique, déploiement/intégration de systèmes

Répondez NON si l'objet concerne :
- Travaux de génie civil, construction, BTP, routes, bâtiments, hydraulique, assainissement
- Agriculture, élevage, alimentation, nettoyage, gardiennage
- Véhicules, carburant, mobilier de bureau non informatique
- Fournitures générales de bureau (papier, stylos, mobilier)
- Matériel médical, pharmaceutique ou agricole
- Constitution d'une base de données de fournisseurs/prestataires (inscription administrative)
- Publication de résultats, attribution de marchés, PV de dépouillement

Répondez UNIQUEMENT par "OUI" ou "NON" suivi d'une explication en une phrase."""
        
        # Classify each item
        for item in state.items_parsed:
            # Items from structured PDF extraction carry embedded classification — pass through
            if item.get('classification_embedded'):
                if item.get('is_relevant') and not item.get('is_results_notice'):
                    relevant_items.append(item)
                    logger.debug(
                        "Pass-through: structured extraction pre-classified item as relevant",
                        item_id=item.get('id'),
                        domain=item.get('domain'),
                        score=item.get('relevance_score'),
                        run_id=state.run_id,
                    )
                continue

            # Exclude attribution/results notices regardless of content
            if _is_attribution_notice(item):
                item['relevance_score'] = 0.0
                item['classification_method'] = 'attribution_filter'
                logger.debug("Excluded attribution notice", item_id=item.get('id'), run_id=state.run_id)
                continue

            # Exclude supplier/provider registration calls (not actionable IT tenders)
            if _is_supplier_registration(item):
                item['relevance_score'] = 0.0
                item['classification_method'] = 'supplier_registration_filter'
                logger.debug("Excluded supplier registration call", item_id=item.get('id'), run_id=state.run_id)
                continue

            llm_error = None
            try:
                # Prepare item data
                entity = item.get('entity', item.get('title', '')) or 'Inconnu'
                reference = item.get('reference', item.get('ref_no', '')) or 'N/A'
                objet = (item.get('tender_object') or item.get('title') or '')[:300]
                description = (item.get('description') or '')[:800]
                keywords_val = item.get('keywords') or []
                keywords = ', '.join(keywords_val) if isinstance(keywords_val, list) else str(keywords_val)
                
                # Build the prompt message
                message = classification_prompt.format(
                    entity=entity,
                    reference=reference,
                    objet=objet,
                    description=description,
                    keywords=keywords
                )
                
                # Get LLM response
                try:
                    response = llm.invoke(message)
                    response_text = response.content.strip().upper() if hasattr(response, 'content') else str(response).upper()
                except Exception as e:
                    llm_error = e
                    logger.warning(f"LLM invocation failed for item {item.get('id')}, using keyword fallback: {e}")
                    response_text = "FALLBACK"
                
                # Parse response - check for OUI/NON indicators
                is_relevant = "OUI" in response_text or "YES" in response_text
                
                # Use keyword-based scoring as confidence check
                # Only use content fields (tender_object, description, keywords), not entity/reference
                all_text = f"{objet} {description} {keywords}".lower()
                keyword_matches = sum(1 for keyword in it_keywords if keyword.lower() in all_text)
                
                # Calculate relevance score
                if "FALLBACK" in response_text or llm_error:
                    # Use keyword-based score for fallback cases
                    if keyword_matches > 0:
                        relevance_score = min(1.0, 0.5 + (keyword_matches / max(len(it_keywords), 1) * 0.5))
                    else:
                        relevance_score = 0.0
                    logger.debug(f"Using keyword fallback for item {item.get('id')}: score={relevance_score}")
                else:
                    # Use LLM response-based score
                    if is_relevant:
                        # Higher score if LLM says OUI, but still consider keyword matches
                        if keyword_matches > 0:
                            relevance_score = min(1.0, 0.8 + (keyword_matches / max(len(it_keywords), 1) * 0.2))
                        else:
                            relevance_score = 0.8
                    else:
                        # LLM says NON → reject; keywords cannot override LLM judgment
                        relevance_score = 0.1
                
                # Clamp score to 0-1 range
                item['relevance_score'] = min(1.0, max(0.0, relevance_score))
                item['classification_method'] = 'llm_with_keyword_fallback'
                item['keyword_matches'] = keyword_matches
                
                logger.debug(
                    "LLM classification complete",
                    item_id=item.get('id'),
                    llm_result=is_relevant,
                    score=item['relevance_score'],
                    keyword_matches=keyword_matches
                )
                
                # When LLM says OUI, be permissive. When LLM says NON, always be strict.
                if is_relevant and keyword_matches > 0:
                    threshold = 0.3  # LLM OUI + keywords
                elif is_relevant:
                    threshold = 0.5  # LLM OUI alone
                else:
                    threshold = 0.7  # LLM NON → strict regardless of keyword count
                
                # Include item if score meets threshold
                if item['relevance_score'] >= threshold:
                    relevant_items.append(item)
                    log_classification(
                        item['id'],
                        item['relevance_score'],
                        True,
                        keyword_matches=keyword_matches,
                        method='llm'
                    )
                else:
                    log_classification(
                        item['id'],
                        item['relevance_score'],
                        False,
                        keyword_matches=keyword_matches,
                        method='llm'
                    )
                    
            except Exception as e:
                logger.error(f"Failed to classify item {item.get('id')} with LLM: {e}")
                # Fallback: use keyword matching for this item
                # Only use content fields, not entity/reference
                all_text = f"{item.get('tender_object', '')} {item.get('description', '')}".lower()
                keyword_matches = sum(1 for keyword in it_keywords if keyword.lower() in all_text)
                if keyword_matches > 0:
                    item['relevance_score'] = min(1.0, 0.5 + (keyword_matches / max(len(it_keywords), 1) * 0.5))
                    item['classification_method'] = 'keyword_fallback_on_error'
                    if item['relevance_score'] >= 0.3:
                        relevant_items.append(item)
                else:
                    item['relevance_score'] = 0.0
        
        # Set state
        state.relevant_items = relevant_items
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