"""LLM-based extraction with Pydantic schema enforcement."""

import json

from tenderai_bf.config import settings
from tenderai_bf.logging import get_logger
from tenderai_bf.schemas import TenderExtraction
from tenderai_bf.utils.llm_utils import get_llm_instance

logger = get_logger(__name__)


def extract_tenders_structured(
    context: str, source_name: str, max_retries: int = 2
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
        llm_model = getattr(llm, "model_name", getattr(llm, "model", "unknown"))
        llm_provider = settings.llm.provider

        # For Groq, skip tool_calling and go straight to JSON fallback
        # Groq wraps parameters in nested objects causing validation failures.
        # NVIDIA (ChatNVIDIA via langchain-nvidia-ai-endpoints==0.1.7, pinned for
        # langchain-core compatibility) doesn't implement bind_tools/function-calling
        # at all — with_structured_output() binds without error but every .invoke()
        # raises NotImplementedError, which retries deterministically and silently
        # degrades every chunk to zero extracted tenders instead of falling back.
        if llm_provider.lower() in ("groq", "nvidia"):
            logger.info(
                "Using JSON fallback mode (tool_calling unreliable/unsupported for this provider)",
                llm_provider=llm_provider,
                llm_model=llm_model,
            )
            return _extract_tenders_json_fallback(
                context, source_name, llm, max_retries
            )

        # For other providers, try structured output
        try:
            # Use method='function_calling' for other providers
            structured_llm = llm.with_structured_output(
                TenderExtraction, method="function_calling"
            )
        except TypeError:
            # Fallback if method parameter not supported
            try:
                structured_llm = llm.with_structured_output(TenderExtraction)
            except AttributeError:
                # Fallback to JSON mode if with_structured_output not available
                logger.error(
                    "LLM does not support with_structured_output, using JSON mode fallback"
                )
                return _extract_tenders_json_fallback(
                    context, source_name, llm, max_retries
                )
        except AttributeError:
            # Fallback to JSON mode if with_structured_output not available
            logger.error(
                "LLM does not support with_structured_output, using JSON mode fallback"
            )
            return _extract_tenders_json_fallback(
                context, source_name, llm, max_retries
            )

        # Prompts are sourced from country_config at the node level.
        # This extraction helper uses a minimal default prompt.
        system_prompt = ""
        user_template = "{context}"

        # Build the complete prompt
        prompt = f"""{system_prompt}

{user_template.format(context=context)}"""

        logger.info(
            "Calling LLM for structured tender extraction",
            source=source_name,
            llm_provider=llm_provider,
            llm_model=llm_model,
            max_retries=max_retries,
            mode="structured_output",
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
                        value=str(extraction)[:200],
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
                        tender_object=tender.tender_object[:100]
                        if tender.tender_object
                        else None,
                        deadline=tender.deadline,
                        description=tender.description[:100]
                        if tender.description
                        else None,
                        category=tender.category,
                        keywords=tender.keywords,
                        relevance_score=tender.relevance_score,
                        budget=tender.budget,
                        location=tender.location,
                        source_url=tender.source_url,
                    )

                logger.info(
                    "Structured extraction successful",
                    source=source_name,
                    tenders_extracted=extraction.total_extracted,
                    confidence=extraction.confidence,
                    attempt=attempt + 1,
                )

                return extraction

            except Exception as e:
                error_msg = str(e)
                logger.error(
                    "Structured extraction attempt failed",
                    attempt=attempt + 1,
                    error=error_msg,
                    error_type=type(e).__name__,
                )

                # If it's a validation error from Groq tool calling, try JSON fallback
                if (
                    "tool_use_failed" in error_msg
                    or "did not match schema" in error_msg
                ):
                    logger.error(
                        "Tool schema validation failed, falling back to JSON mode"
                    )
                    return _extract_tenders_json_fallback(
                        context, source_name, llm, max_retries
                    )

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
            exc_info=True,
        )
        return TenderExtraction(tenders=[], total_extracted=0)


_HALLUCINATION_SENTINELS = {
    "entity": {"nom de l'organisation", "organization name", "nom organisation"},
    "reference": {"numéro de référence", "reference number", "ref number"},
    "source_url": {"example.com", "paris.fr", "marches-publics.fr"},
}

_MIN_CHUNK_CHARS = 100


def _is_hallucinated(tender: dict) -> bool:
    """Return True if the tender looks like LLM placeholder/example data."""
    entity = (tender.get("entity") or "").lower()
    if any(s in entity for s in _HALLUCINATION_SENTINELS["entity"]):
        return True
    ref = (tender.get("reference") or "").lower()
    if any(s in ref for s in _HALLUCINATION_SENTINELS["reference"]):
        return True
    url = (tender.get("source_url") or "").lower()
    if any(s in url for s in _HALLUCINATION_SENTINELS["source_url"]):
        return True
    # Reject entries where all identifying fields are None/empty
    identifying = [tender.get("entity"), tender.get("reference"), tender.get("tender_object")]
    if all(not v or v in ("Inconnu", "None") for v in identifying):
        return True
    return False


def _coerce_budget(value) -> str | None:
    """Convert budget to string — LLM sometimes returns a dict for multi-lot tenders."""
    if value is None:
        return None
    if isinstance(value, dict):
        return " / ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def _extract_tenders_json_fallback(
    context: str, source_name: str, llm, max_retries: int
) -> TenderExtraction:
    """Fallback JSON parsing method when structured output is not available."""

    # Skip chunks that are too short to contain real tender data
    if len(context.strip()) < _MIN_CHUNK_CHARS:
        return TenderExtraction(tenders=[], total_extracted=0, confidence=0.0)

    prompt = f"""Tu es un extracteur d'appels d'offres officiels. Tu dois analyser le texte fourni et en extraire UNIQUEMENT les appels d'offres, demandes de prix, ou marchés publics qui apparaissent EXPLICITEMENT dans ce texte.

RÈGLES ABSOLUES — INTERDICTIONS FORMELLES :
1. N'invente AUCUNE donnée. Si un champ n'est pas présent dans le texte, mets null.
2. N'utilise JAMAIS d'exemples, de modèles, ou de données fictives.
3. Ne remplis JAMAIS entity avec "Nom de l'organisation" ou toute valeur générique.
4. Ne remplis JAMAIS reference avec "Numéro de référence" ou toute valeur générique.
5. Ne génère JAMAIS une URL source_url qui n'est pas explicitement dans le texte.
6. Si le texte ne contient aucun appel d'offres réel, retourne {{"tenders": [], "total_extracted": 0, "confidence": 1.0}}.
7. N'extrais PAS les résultats de dépouillement (tableaux comparatifs d'offres reçues) comme s'ils étaient de nouveaux appels d'offres.

Structure JSON attendue :
{{
  "tenders": [
    {{
      "type": "appel_offres | demande_de_prix | rectificatif | prorogation | annulation | autre",
      "entity": "<nom réel de l'entité émettrice, extrait du texte, ou null>",
      "reference": "<référence réelle extraite du texte, ou null>",
      "tender_object": "<objet exact extrait du texte, ou null>",
      "deadline": "<date limite DD-MM-YYYY extraite du texte, ou null>",
      "description": "<description factuelle extraite du texte>",
      "category": "IT | Services | Biens | Travaux | Prestations intellectuelles | Autre",
      "keywords": ["<mots-clés réels>"],
      "relevance_score": <0.0 à 1.0>,
      "budget": "<montant exact extrait du texte, ou null>",
      "location": "<localisation extraite du texte, ou null>",
      "source_url": null
    }}
  ],
  "total_extracted": <nombre>,
  "confidence": <0.0 à 1.0>
}}

Texte à analyser :
{context}

RETOURNEZ UNIQUEMENT DU JSON VALIDE. Si aucun appel d'offres réel n'est présent, retournez {{"tenders":[],"total_extracted":0,"confidence":1.0}}"""

    for attempt in range(max_retries):
        try:
            response = llm.invoke(prompt)
            response_text = response.content.strip()

            logger.debug(
                "LLM response received (JSON fallback)",
                attempt=attempt + 1,
                response_length=len(response_text),
                response_preview=response_text[:300],
            )

            # Parse JSON response
            try:
                result_json = json.loads(response_text)
            except json.JSONDecodeError:
                import re

                json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
                if json_match:
                    result_json = json.loads(json_match.group())
                else:
                    logger.error(
                        "No valid JSON found in LLM response",
                        attempt=attempt + 1,
                        response=response_text[:500],
                    )
                    continue

            # Coerce budget field: LLM sometimes returns a dict for multi-lot tenders
            for t in result_json.get("tenders", []):
                if isinstance(t.get("budget"), dict):
                    t["budget"] = _coerce_budget(t["budget"])

            # Filter hallucinated / placeholder tenders before Pydantic validation
            original_count = len(result_json.get("tenders", []))
            result_json["tenders"] = [
                t for t in result_json.get("tenders", [])
                if not _is_hallucinated(t)
            ]
            filtered = original_count - len(result_json["tenders"])
            if filtered:
                logger.warning(
                    "Hallucinated tenders filtered",
                    source=source_name,
                    count=filtered,
                )
            result_json["total_extracted"] = len(result_json["tenders"])

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
                    tender_object=tender.tender_object[:100]
                    if tender.tender_object
                    else None,
                    deadline=tender.deadline,
                    description=tender.description[:100]
                    if tender.description
                    else None,
                    category=tender.category,
                    keywords=tender.keywords,
                    relevance_score=tender.relevance_score,
                    budget=tender.budget,
                    location=tender.location,
                    source_url=tender.source_url,
                )

            logger.info(
                "JSON fallback extraction successful",
                source=source_name,
                tenders_extracted=extraction.total_extracted,
                confidence=extraction.confidence,
                attempt=attempt + 1,
            )

            return extraction

        except ValueError as ve:
            logger.error(
                "Pydantic validation failed (JSON fallback)",
                attempt=attempt + 1,
                error=str(ve),
            )
            if attempt < max_retries - 1:
                logger.info("Retrying extraction...")
                continue
            else:
                logger.error("Max retries exceeded, returning empty extraction")
                return TenderExtraction(tenders=[], total_extracted=0)

    return TenderExtraction(tenders=[], total_extracted=0)
