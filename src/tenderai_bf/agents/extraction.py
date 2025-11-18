"""LLM-based extraction with Pydantic schema enforcement."""

import json

from tenderai_bf.logging import get_logger
from tenderai_bf.utils.llm_utils import get_llm_instance
from tenderai_bf.schemas import TenderExtraction
from tenderai_bf.config import settings

logger = get_logger(__name__)


def extract_tenders_structured(
    context: str,
    source_name: str,
    max_retries: int = 2
) -> TenderExtraction:
    """
    Extract tenders from context using LLM with structured output validation.
    
    Uses Pydantic schema with LangChain's with_structured_output() to enforce 
    valid tender structure directly in the LLM call.
    
    Args:
        context: Text context to extract tenders from
        source_name: Name of the source
        max_retries: Number of retry attempts on parse failure
    
    Returns:
        TenderExtraction with validated tenders
    """
    
    try:
        # Get LLM instance
        llm = get_llm_instance(temperature=0.1, max_tokens=4096)
        if not llm:
            logger.error("LLM not available for structured extraction")
            return TenderExtraction(tenders=[], total_extracted=0)
        
        # Get LLM model name for logging
        llm_model = getattr(llm, 'model_name', getattr(llm, 'model', 'unknown'))
        llm_provider = settings.llm.provider
        
        # For Groq, skip tool_calling and go straight to JSON fallback
        # Groq wraps parameters in nested objects causing validation failures
        if llm_provider.lower() == "groq":
            logger.info(
                "Using JSON fallback mode for Groq (tool_calling unreliable)",
                llm_provider=llm_provider,
                llm_model=llm_model
            )
            return _extract_tenders_json_fallback(context, source_name, llm, max_retries)
        
        # For other providers, try structured output
        try:
            # Use method='function_calling' for other providers
            structured_llm = llm.with_structured_output(
                TenderExtraction,
                method="function_calling"
            )
        except TypeError:
            # Fallback if method parameter not supported
            try:
                structured_llm = llm.with_structured_output(TenderExtraction)
            except AttributeError:
                # Fallback to JSON mode if with_structured_output not available
                logger.error("LLM does not support with_structured_output, using JSON mode fallback")
                return _extract_tenders_json_fallback(context, source_name, llm, max_retries)
        except AttributeError:
            # Fallback to JSON mode if with_structured_output not available
            logger.error("LLM does not support with_structured_output, using JSON mode fallback")
            return _extract_tenders_json_fallback(context, source_name, llm, max_retries)
        
        # Get prompts from configuration
        extraction_prompts = settings.prompts.get('extraction', {})
        system_prompt = extraction_prompts.get('system', '')
        user_template = extraction_prompts.get('user_template', '{context}')
        
        # Build the complete prompt
        prompt = f"""{system_prompt}

{user_template.format(context=context)}"""
        
        logger.info(
            "Calling LLM for structured tender extraction",
            source=source_name,
            llm_provider=llm_provider,
            llm_model=llm_model,
            max_retries=max_retries,
            mode="structured_output"
        )
        
        # Try extraction with retries
        for attempt in range(max_retries):
            try:
                # Invoke structured LLM - returns TenderExtraction directly
                extraction = structured_llm.invoke(prompt)
                
                # Validate that we got a TenderExtraction instance
                if not isinstance(extraction, TenderExtraction):
                    logger.error(
                        "LLM returned unexpected type",
                        attempt=attempt + 1,
                        type=type(extraction).__name__,
                        value=str(extraction)[:200]
                    )
                    continue
                
                # Log each tender details
                for idx, tender in enumerate(extraction.tenders, 1):
                    logger.info(
                        f"Tender {idx} extracted",
                        source=source_name,
                        type=tender.type,
                        entity=tender.entity,
                        reference=tender.reference,
                        tender_object=tender.tender_object[:100] if tender.tender_object else None,
                        deadline=tender.deadline,
                        description=tender.description[:100] if tender.description else None,
                        category=tender.category,
                        keywords=tender.keywords,
                        relevance_score=tender.relevance_score,
                        budget=tender.budget,
                        location=tender.location,
                        source_url=tender.source_url
                    )
                
                logger.info(
                    "Structured extraction successful",
                    source=source_name,
                    tenders_extracted=extraction.total_extracted,
                    confidence=extraction.confidence,
                    attempt=attempt + 1
                )
                
                return extraction
                
            except Exception as e:
                error_msg = str(e)
                logger.error(
                    "Structured extraction attempt failed",
                    attempt=attempt + 1,
                    error=error_msg,
                    error_type=type(e).__name__
                )
                
                # If it's a validation error from Groq tool calling, try JSON fallback
                if 'tool_use_failed' in error_msg or 'did not match schema' in error_msg:
                    logger.error("Tool schema validation failed, falling back to JSON mode")
                    return _extract_tenders_json_fallback(context, source_name, llm, max_retries)
                
                if attempt < max_retries - 1:
                    logger.info("Retrying extraction...")
                    continue
                else:
                    logger.error("Max retries exceeded, returning empty extraction")
                    return TenderExtraction(tenders=[], total_extracted=0)
        
        return TenderExtraction(tenders=[], total_extracted=0)
        
    except Exception as e:
        logger.error(
            "Structured tender extraction failed",
            source=source_name,
            error=str(e),
            exc_info=True
        )
        return TenderExtraction(tenders=[], total_extracted=0)


def _extract_tenders_json_fallback(
    context: str,
    source_name: str,
    llm,
    max_retries: int
) -> TenderExtraction:
    """Fallback JSON parsing method when structured output is not available."""
    
    # Get prompts from configuration
    extraction_prompts = settings.prompts.get('extraction', {})
    system_prompt = extraction_prompts.get('system', '')
    user_template = extraction_prompts.get('user_template', '{context}')
    
    # Build prompt with JSON formatting instructions
    prompt = f"""{system_prompt}

IMPORTANT : Retournez UNIQUEMENT un objet JSON valide avec cette structure exacte :
{{
  "tenders": [
    {{
      "type": "appel_offres/rectificatif/prorogation/communique/annulation/autre",
      "entity": "Nom de l'organisation",
      "reference": "Numéro de référence",
      "tender_object": "Objet de l'appel d'offres tel qu'il apparaît dans le document",
      "deadline": "Date limite au format DD-MM-YYYY",
      "description": "Description détaillée incluant nature des travaux, lieux, lots, conditions",
      "category": "IT/Ingénierie/Services/Biens/Travaux/Autre",
      "keywords": ["mot-clé1", "mot-clé2"],
      "relevance_score": 0.8,
      "budget": null ou "montant",
      "location": null ou "localisation",
      "source_url": null ou "URL"
    }}
  ],
  "total_extracted": 1,
  "confidence": 1.0
}}

{user_template.format(context=context)}

RETOURNEZ UNIQUEMENT DU JSON VALIDE, rien d'autre. Commencez par {{ et terminez par }}"""
    
    for attempt in range(max_retries):
        try:
            response = llm.invoke(prompt)
            response_text = response.content.strip()
            
            logger.debug(
                "LLM response received (JSON fallback)",
                attempt=attempt + 1,
                response_length=len(response_text),
                response_preview=response_text[:300]
            )
            
            # Parse JSON response
            try:
                result_json = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to extract JSON from response if parsing fails
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    result_json = json.loads(json_match.group())
                else:
                    logger.error(
                        "No valid JSON found in LLM response",
                        attempt=attempt + 1,
                        response=response_text[:500]
                    )
                    continue
            
            # Validate with Pydantic
            extraction = TenderExtraction(**result_json)
            
            # Log each tender details
            for idx, tender in enumerate(extraction.tenders, 1):
                logger.info(
                    f"Tender {idx} extracted (JSON fallback)",
                    source=source_name,
                    type=tender.type,
                    entity=tender.entity,
                    reference=tender.reference,
                    tender_object=tender.tender_object[:100] if tender.tender_object else None,
                    deadline=tender.deadline,
                    description=tender.description[:100] if tender.description else None,
                    category=tender.category,
                    keywords=tender.keywords,
                    relevance_score=tender.relevance_score,
                    budget=tender.budget,
                    location=tender.location,
                    source_url=tender.source_url
                )
            
            logger.info(
                "JSON fallback extraction successful",
                source=source_name,
                tenders_extracted=extraction.total_extracted,
                confidence=extraction.confidence,
                attempt=attempt + 1
            )
            
            return extraction
            
        except ValueError as ve:
            logger.error(
                "Pydantic validation failed (JSON fallback)",
                attempt=attempt + 1,
                error=str(ve)
            )
            if attempt < max_retries - 1:
                logger.info("Retrying extraction...")
                continue
            else:
                logger.error("Max retries exceeded, returning empty extraction")
                return TenderExtraction(tenders=[], total_extracted=0)
    
    return TenderExtraction(tenders=[], total_extracted=0)
