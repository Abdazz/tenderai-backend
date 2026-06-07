"""Extract individual tender notices from a Tavily-extracted listing page.

Strategy: one LLM call that receives the raw page text and returns all tender
notices it finds, each with embedded domain classification.  This mirrors the
approach used by parse_pdf_structured for DGCMEF quotidien PDFs.

Classification is embedded in the extraction pass so classify_node skips these
items (classification_embedded=True).
"""

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ...logging import get_logger
from ...utils.llm_utils import get_llm_instance

logger = get_logger(__name__)

# Safety cap: ~70 K tokens at 5.5 ch/token, leaves room for prompt + output.
_MAX_INPUT_CHARS = 200_000


class TenderItem(BaseModel):
    """A single tender notice extracted from a listing page."""

    title: str = Field(default="", description="Titre / objet de l'appel d'offres")
    entity: str = Field(default="", description="Entité ou organisme émetteur")
    reference: str = Field(default="", description="Numéro de référence si présent")
    deadline: str | None = Field(
        default=None,
        description="Date limite de soumission au format YYYY-MM-DD ou DD-MM-YYYY si disponible",
    )
    description: str = Field(
        default="", description="Description courte (150 mots max)"
    )
    tender_url: str | None = Field(
        default=None,
        description="URL directe vers la fiche de l'appel d'offres si visible dans le texte",
    )
    is_results_notice: bool = Field(
        default=False,
        description=(
            "True si c'est un résultat d'attribution, PV de dépouillement, "
            "contrat déjà octroyé — pas un appel ouvert"
        ),
    )
    is_relevant: bool = Field(
        default=False,
        description=(
            "True uniquement si l'objet concerne les domaines IT de YULCOM : "
            "services IT, matériel informatique ou conseil/ingénierie IT"
        ),
    )
    domain: Literal[
        "it_services", "it_hardware", "it_consulting", "hors_perimetre"
    ] = Field(
        default="hors_perimetre",
        description="Domaine IT ou hors_perimetre",
    )
    relevance_score: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Score 1-5 : 5=cœur de métier YULCOM, 3=pertinent, 1=hors périmètre",
    )


class TenderItemList(BaseModel):
    tenders: list[TenderItem] = Field(default_factory=list)


_EXTRACTION_PROMPT = """\
Tu es un expert en marchés publics. Tu reçois le contenu textuel d'une page de \
listing d'appels d'offres (portail gouvernemental, organisation internationale, etc.).

TEXTE DE LA PAGE :
{page_text}

SOURCE : {source_name}

Ta mission :
1. Identifier TOUS les appels d'offres listés dans ce texte (même partiellement).
2. Pour chaque appel d'offres, extraire les informations disponibles.
3. Classifier chaque appel selon sa pertinence pour YULCOM Technologies.

DOMAINES IT YULCOM (is_relevant = true) :
- it_services : développement logiciel, systèmes d'information, ERP, CRM, SIG, \
cybersécurité, cloud, hébergement, infogérance, réseau, fibre optique, wifi, \
vidéoconférence, intelligence artificielle
- it_hardware : ordinateurs, serveurs, imprimantes, scanners, photocopieurs, \
routeurs, switches, modems, écrans, onduleurs, accessoires informatiques
- it_consulting : études informatiques, audits de sécurité, assistance technique IT, \
schémas directeurs, formation IT, déploiement/intégration de systèmes

RÈGLES :
- is_results_notice = true pour contrats déjà octroyés, résultats d'appels d'offres, \
PV de dépouillement
- is_relevant = false pour : BTP, génie civil, agriculture, santé, véhicules, \
carburant, fournitures générales, gardiennage, nettoyage
- Si la page ne contient aucun appel d'offres identifiable, retourne une liste vide.
- N'invente pas d'informations absentes du texte.

Retourne UNIQUEMENT du JSON valide (pas de markdown, pas d'explication) :
{{
  "tenders": [
    {{
      "title": "Titre de l'appel d'offres",
      "entity": "Organisation émettrice",
      "reference": "",
      "deadline": null,
      "description": "Description courte",
      "tender_url": null,
      "is_results_notice": false,
      "is_relevant": false,
      "domain": "hors_perimetre",
      "relevance_score": 1
    }}
  ]
}}\
"""


_VALID_DOMAINS = {"it_services", "it_hardware", "it_consulting", "hors_perimetre"}


def _normalize_tender_dict(raw: dict) -> TenderItem | None:
    """Clamp/normalize LLM output before Pydantic validation.

    The LLM occasionally returns relevance_score > 5 or domain values outside
    the allowed set.  Rather than discarding the whole batch, we normalize
    per-item so valid items are preserved.
    """
    try:
        # Clamp relevance_score to 1-5
        score = raw.get("relevance_score", 1)
        try:
            raw["relevance_score"] = max(1, min(5, int(score)))
        except (TypeError, ValueError):
            raw["relevance_score"] = 1

        # Map unknown domain values to hors_perimetre
        if raw.get("domain") not in _VALID_DOMAINS:
            raw["domain"] = "hors_perimetre"

        return TenderItem(**raw)
    except Exception as e:
        logger.debug("Skipping malformed tender item", error=str(e), raw=str(raw)[:200])
        return None


def _extract_tenders_from_page(
    page_text: str, source_name: str, llm_provider: str
) -> list[TenderItem]:
    """Single LLM call to extract all tenders from a listing page."""
    llm = get_llm_instance(temperature=0.0, max_tokens=8000)
    if not llm:
        logger.error("LLM not available for tavily listing extraction")
        return []

    prompt = _EXTRACTION_PROMPT.format(
        page_text=page_text[:_MAX_INPUT_CHARS],
        source_name=source_name,
    )

    if llm_provider.lower() == "groq":
        try:
            response = llm.invoke(prompt)
            raw = response.content.strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                else:
                    logger.error(
                        "No valid JSON in LLM response",
                        source=source_name,
                        preview=raw[:300],
                    )
                    return []
            # Normalize each item individually so one bad item doesn't discard all
            tenders = []
            for raw_item in data.get("tenders", []):
                item = _normalize_tender_dict(raw_item)
                if item:
                    tenders.append(item)
            return tenders
        except Exception as e:
            logger.error("LLM extraction failed (Groq)", source=source_name, error=str(e))
            return []
    else:
        try:
            structured_llm = llm.with_structured_output(TenderItemList)
            result = structured_llm.invoke(prompt)
            return result.tenders
        except Exception as e:
            logger.error("Structured LLM extraction failed", source=source_name, error=str(e))
            return []


def parse_tavily_listing(
    page_content: str,
    source_url: str,
    source_name: str,
    run_id: str,
    llm_cfg: dict | None = None,
) -> list[dict]:
    """Parse the text content of a Tavily-extracted listing page into individual notices.

    One LLM call extracts all visible tenders from the page and embeds domain
    classification.  Returns items with classification_embedded=True so
    classify_node passes them through without re-classifying.

    Falls back to an empty list if the LLM finds nothing or fails.
    """
    if not page_content or not page_content.strip():
        logger.warning("Empty page content for tavily listing", source=source_name, run_id=run_id)
        return []

    logger.info(
        "Extracting tenders from Tavily listing page",
        source=source_name,
        chars=len(page_content),
        run_id=run_id,
    )

    llm_provider = (llm_cfg or {}).get("provider", "groq")
    tenders = _extract_tenders_from_page(page_content, source_name, llm_provider)

    logger.info(
        f"LLM returned {len(tenders)} notices from listing page",
        source=source_name,
        run_id=run_id,
    )

    results = []
    for i, tender in enumerate(tenders):
        is_actionable = tender.is_relevant and not tender.is_results_notice

        # Use the tender's own URL if extracted, otherwise fall back to source listing URL
        item_url = tender.tender_url or source_url

        item = {
            "id": str(uuid.uuid4()),
            "url": item_url,
            "source_url": source_url,
            "content_hash": hashlib.sha256(
                f"{source_name}:{tender.reference}:{tender.title}".encode()
            ).hexdigest(),
            "source_type": "tavily_listing",
            "source_name": source_name,
            "published_at": datetime.utcnow().isoformat(),
            # Extracted fields
            "title": tender.title,
            "tender_object": tender.title,
            "entity": tender.entity,
            "reference": tender.reference,
            "ref_no": tender.reference,
            "deadline": tender.deadline,
            "deadline_at": tender.deadline,
            "description": tender.description,
            "category": tender.domain,
            # Embedded classification — classify_node passes these through
            "classification_embedded": True,
            "is_relevant": is_actionable,
            "is_results_notice": tender.is_results_notice,
            "domain": tender.domain,
            "relevance_score": tender.relevance_score / 5.0,
            "classification_method": "llm_tavily_listing_extraction",
        }
        results.append(item)

        logger.info(
            f"Listing item {i + 1}/{len(tenders)}",
            source=source_name,
            title=(tender.title or "")[:80],
            entity=(tender.entity or "")[:50],
            is_relevant=tender.is_relevant,
            domain=tender.domain,
            score=tender.relevance_score,
            run_id=run_id,
        )

    relevant_count = sum(1 for r in results if r["is_relevant"])
    logger.info(
        "Tavily listing extraction complete",
        source=source_name,
        total=len(results),
        relevant=relevant_count,
        run_id=run_id,
    )
    return results
