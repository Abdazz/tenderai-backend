"""Structured PDF parser for DGCMEF Quotidien des Marchés Publics.

Strategy: extract the full PDF text with pdfminer, locate the open-tender
section (best-effort, multiple fallback markers), then send it in ONE LLM call.
The LLM extracts all notices simultaneously with embedded domain classification.

This eliminates regex-based block splitting entirely — the approach is robust
to day-to-day formatting changes in the Quotidien publication.

Fallback when AVIS section is not locatable: send the full document.
The LLM uses is_results_notice=True to mark attribution results, which the
pipeline filters out just like explicitly skipped content.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ...config import settings
from ...logging import get_logger
from ...utils.llm_utils import get_llm_instance
from ...utils.pdf import extract_pdf_text_from_bytes

logger = get_logger(__name__)

# Ordered list of markers that signal the start of the open-tender section.
# The first one found wins. If none match, the full document is used.
_AVIS_SECTION_MARKERS = [
    "Fournitures et Services courants",
    "FOURNITURES ET SERVICES COURANTS",
    "Fournitures et services courants",
    # Fallback: first open notice header
    "Avis de demande de prix",
    "Avis d'Appel d'Offres",
    "Avis à Manifestation d'Intérêt",
    "AVIS DE DEMANDE DE PRIX",
    "AVIS D'APPEL D'OFFRES",
]

# Safety cap on characters sent to LLM (~70 K tokens at 5.5 ch/token).
# Leaves ample room for prompt + structured output within a 128 K context window.
_MAX_INPUT_CHARS = 385_000


class TenderBlock(BaseModel):
    """Extraction + classification result for a single quotidien notice."""

    entity: str = Field(default="Inconnu", description="Entité émettrice de l'avis")
    reference: str = Field(
        default="Inconnu",
        description="Numéro de référence (ex: N°2026-001/MINEFID/SG/DPCL)",
    )
    tender_object: str = Field(default="Inconnu", description="Objet de l'appel d'offres")
    deadline: Optional[str] = Field(
        default=None, description="Date limite au format DD-MM-YYYY"
    )
    description: str = Field(
        default="", description="Description du marché (300 mots maximum)"
    )
    budget: Optional[str] = Field(
        default=None, description="Montant estimé si mentionné (ex: 50 000 000 FCFA)"
    )
    location: Optional[str] = Field(
        default=None, description="Localisation géographique si mentionnée"
    )
    is_results_notice: bool = Field(
        default=False,
        description=(
            "True si cet avis est un PV de dépouillement, résultat d'attribution, "
            "prorogation, rectificatif ou annulation — pas un appel actif ouvert"
        ),
    )
    is_relevant: bool = Field(
        default=False,
        description=(
            "True si pertinent pour YULCOM (IT services, matériel informatique, conseil IT). "
            "False pour tout le reste."
        ),
    )
    domain: Literal["it_services", "it_hardware", "it_consulting", "hors_perimetre"] = Field(
        default="hors_perimetre",
        description="Domaine : it_services, it_hardware, it_consulting, ou hors_perimetre",
    )
    relevance_score: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Score de pertinence 1-5 : 5=cœur de métier YULCOM, 3=pertinent, 1=hors périmètre",
    )


class TenderList(BaseModel):
    """Wrapper for bulk LLM extraction — all notices in one call."""

    tenders: List[TenderBlock] = Field(
        default_factory=list,
        description="Liste complète de tous les avis extraits du document",
    )


_EXTRACTION_PROMPT = """\
Tu es un expert en marchés publics du Burkina Faso. Extrait TOUS les avis contenus \
dans ce texte du Quotidien des Marchés Publics (DGCMEF). Ne manque aucun avis.

TEXTE DU DOCUMENT :
{document_text}

Pour chaque avis trouvé, remplis les champs et détermine la pertinence pour YULCOM Technologies.

DOMAINES IT de YULCOM (is_relevant = true uniquement pour ces domaines) :
- it_services : développement logiciel, systèmes d'information, ERP, CRM, SIG, cybersécurité, \
cloud, hébergement, infogérance, réseau, fibre optique, wifi, vidéoconférence, intelligence artificielle
- it_hardware : ordinateurs, serveurs, imprimantes, scanners, photocopieurs, routeurs, switches, \
modems, écrans, onduleurs, accessoires informatiques
- it_consulting : études informatiques, audits de sécurité, assistance technique IT, \
schémas directeurs, formation informatique, déploiement/intégration de systèmes

RÈGLES DE CLASSIFICATION :
- is_results_notice = true pour : PV de dépouillement, résultats d'attribution, annulations, \
prorogations, rectificatifs (tout ce qui n'est pas un appel actif ouvert)
- is_relevant = false pour : BTP, génie civil, travaux, agriculture, santé, mobilier, \
véhicules, carburant, fournitures générales, inscriptions de fournisseurs/prestataires
- relevance_score 1-5 : 5=cœur de métier (ex: développement SIG), 4=très pertinent (ex: serveurs), \
3=pertinent (ex: imprimantes), 2=tangentiel, 1=hors périmètre
- domain = "hors_perimetre" si is_relevant = false

Retournez UNIQUEMENT du JSON valide (pas de markdown, pas d'explication) :
{{
  "tenders": [
    {{
      "entity": "Nom de l'organisation",
      "reference": "N°2026-XXX/...",
      "tender_object": "Objet de l'avis",
      "deadline": null,
      "description": "Description courte (200 mots max)",
      "budget": null,
      "location": null,
      "is_results_notice": false,
      "is_relevant": false,
      "domain": "hors_perimetre",
      "relevance_score": 1
    }}
  ]
}}\
"""


def _find_avis_section_start(text: str) -> int:
    """Return char position of the open-tender section start.

    Returns 0 (full document) when no marker is found — the LLM will handle
    attribution results via is_results_notice=True.
    """
    for marker in _AVIS_SECTION_MARKERS:
        pos = text.find(marker)
        if pos != -1:
            logger.info(f"AVIS section marker '{marker}' found at char {pos}")
            return pos
    logger.warning(
        "No AVIS section markers found — sending full document to LLM. "
        "Attribution results will be filtered via is_results_notice."
    )
    return 0


def _extract_all_tenders_with_llm(document_text: str) -> List[TenderBlock]:
    """Single LLM call to extract all tenders from the document text.

    Returns a (possibly empty) list of TenderBlock objects.
    """
    llm = get_llm_instance(temperature=0.0, max_tokens=8000)
    if not llm:
        logger.error("LLM not available for quotidien extraction")
        return []

    provider = settings.llm.provider
    prompt = _EXTRACTION_PROMPT.format(
        document_text=document_text[:_MAX_INPUT_CHARS]
    )

    if provider.lower() == "groq":
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
                        response_preview=raw[:300],
                    )
                    return []
            return TenderList(**data).tenders
        except Exception as e:
            logger.error("LLM extraction failed (Groq)", error=str(e))
            return []
    else:
        try:
            structured_llm = llm.with_structured_output(TenderList)
            result = structured_llm.invoke(prompt)
            return result.tenders
        except Exception as e:
            logger.error("Structured LLM extraction failed", error=str(e))
            return []


def parse_quotidien_structured(
    pdf_content: bytes,
    source_url: str,
    quotidien_title: str,
    run_id: str,
) -> List[Dict]:
    """Parse quotidien PDF with a single LLM call that extracts all notices at once.

    1. Extract full PDF text (pdfminer — fast, no OCR overhead for text PDFs)
    2. Locate the open-tender section (multiple fallback markers; sends full doc if none match)
    3. One LLM call → TenderList with all notices, each with embedded classification
    4. Convert to pipeline dict format with classification_embedded=True

    Items returned have classification_embedded=True so classify_node skips them.
    """
    logger.info(
        "Parsing quotidien with single-call LLM extractor",
        title=quotidien_title,
        size_mb=round(len(pdf_content) / (1024 * 1024), 2),
        run_id=run_id,
    )

    # pdfminer: fast, reliable for text-based PDFs, no ML overhead
    text = extract_pdf_text_from_bytes(pdf_content, method="pdfminer")
    logger.info("PDF text extracted", chars=len(text), run_id=run_id)

    avis_start = _find_avis_section_start(text)
    document_text = text[avis_start:]

    chars_sent = min(len(document_text), _MAX_INPUT_CHARS)
    logger.info(
        f"Sending {chars_sent:,} chars to LLM "
        f"({'full doc' if avis_start == 0 else 'AVIS section only'})",
        run_id=run_id,
    )

    tenders = _extract_all_tenders_with_llm(document_text)
    logger.info(
        f"LLM returned {len(tenders)} notices",
        run_id=run_id,
    )

    results = []
    for i, tender in enumerate(tenders):
        is_actionable = tender.is_relevant and not tender.is_results_notice

        item = {
            "id": str(uuid.uuid4()),
            "url": source_url,
            "content_hash": hashlib.sha256(
                f"{tender.reference}:{tender.tender_object}".encode()
            ).hexdigest(),
            "source_type": "quotidien_pdf",
            "quotidien_title": quotidien_title,
            "published_at": datetime.utcnow().isoformat(),
            "location": tender.location or "Burkina Faso",
            # Extracted fields
            "entity": tender.entity,
            "reference": tender.reference,
            "ref_no": tender.reference,
            "tender_object": tender.tender_object,
            "title": tender.tender_object,
            "deadline": tender.deadline,
            "deadline_at": tender.deadline,
            "description": tender.description,
            "budget": tender.budget,
            "category": tender.domain,
            # Embedded classification — classify_node passes these through unchanged
            "classification_embedded": True,
            "is_relevant": is_actionable,
            "is_results_notice": tender.is_results_notice,
            "domain": tender.domain,
            # Normalize 1-5 to 0.0-1.0 for downstream score compatibility
            "relevance_score": tender.relevance_score / 5.0,
            "classification_method": "llm_single_pass_extraction",
        }
        results.append(item)

        logger.info(
            f"Notice {i + 1}/{len(tenders)}",
            ref=tender.reference,
            entity=(tender.entity or "")[:50],
            is_relevant=tender.is_relevant,
            is_results_notice=tender.is_results_notice,
            domain=tender.domain,
            score=tender.relevance_score,
        )

    relevant_count = sum(1 for r in results if r["is_relevant"])
    logger.info(
        "Quotidien extraction complete",
        total_notices=len(results),
        relevant=relevant_count,
        results_notices=len(results) - relevant_count,
        run_id=run_id,
    )
    return results
