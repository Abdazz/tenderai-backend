"""Structured PDF parser for DGCMEF Quotidien des Marchés Publics.

Replaces the RAG+chunking pipeline with a single LLM-as-Extractor pass per
notice block. Extraction and domain classification happen in one LLM call,
eliminating the separate classify step for quotidien PDF sources.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from ...config import settings
from ...logging import get_logger
from ...utils.llm_utils import get_llm_instance
from ...utils.pdf import extract_pdf_text_from_bytes

logger = get_logger(__name__)

# Markers for the open-tender section (AVIS), after which RESULTATS section ends
_AVIS_SECTION_MARKERS = [
    "Fournitures et Services courants",
    "FOURNITURES ET SERVICES COURANTS",
    "Fournitures et services courants",
    "fournitures et services courants",
]

# Matches the header line of any notice type followed by N° — used to split into blocks.
# Covers Avis de demande de prix, Avis d'Appel d'Offres, Avis à Manifestation d'Intérêt,
# Avis d'attribution, prorogation, rectificatif, annulation.
_AVIS_SPLIT_PATTERN = re.compile(
    r"Avis\s+(?:"
    r"de\s+demande\s+de\s+prix\s+N"
    r"|d['’]appel\s+d['’]offres\s+N"
    r"|[àa]\s+manifestation\s+d['’]int[ée]r[êe]t\s+N"
    r"|de\s+manifestation\s+d['’]int[ée]r[êe]t\s+N"
    r"|d['’]attribution\s+N"
    r"|de\s+prorogation\s+N"
    r"|de\s+rectificatif\s+N"
    r"|d['’]annulation\s+N"
    r")",
    re.IGNORECASE,
)

# Fallback: match bare reference numbers when no Avis markers are found
_REF_PATTERN = re.compile(r"N[°o]\s*\d{4}[-–]\d+", re.IGNORECASE)


class TenderBlock(BaseModel):
    """Extraction + classification result for a single quotidien notice block."""

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


_BLOCK_PROMPT = """\
Tu es un expert en marchés publics du Burkina Faso. Analyse ce bloc de texte extrait du \
Quotidien des Marchés Publics (DGCMEF) et extrais les informations structurées.

BLOC DE TEXTE :
{block_text}

DOMAINES IT de YULCOM Technologies (is_relevant = true uniquement pour ces domaines) :
- it_services : développement logiciel, systèmes d'information, ERP, CRM, SIG, cybersécurité, \
cloud, hébergement, infogérance, réseau, fibre optique, wifi, vidéoconférence, intelligence artificielle
- it_hardware : ordinateurs, serveurs, imprimantes, scanners, photocopieurs, routeurs, switches, \
modems, écrans, onduleurs, accessoires informatiques
- it_consulting : études informatiques, audits de sécurité, assistance technique IT, \
schémas directeurs, formation informatique, déploiement de systèmes

RÈGLES DE CLASSIFICATION :
- is_results_notice = true si c'est un PV de dépouillement, résultat d'attribution, \
annulation, prorogation ou rectificatif (pas un appel actif ouvert)
- is_relevant = true UNIQUEMENT pour les 3 domaines IT de YULCOM ci-dessus
- is_relevant = false pour : BTP, génie civil, travaux, agriculture, santé, mobilier de bureau, \
véhicules, carburant, fournitures générales, inscription de fournisseurs/prestataires
- relevance_score 1-5 : 5=cœur de métier (ex: développement SIG), 4=très pertinent (ex: serveurs), \
3=pertinent (ex: imprimantes), 2=tangentiel, 1=hors périmètre ou non pertinent
- domain = "hors_perimetre" si is_relevant = false

Retournez UNIQUEMENT du JSON valide (pas de markdown, pas d'explication) :
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
}}\
"""


def _find_avis_section_start(text: str) -> int:
    """Return char position of the open-tender section, or 0 as fallback."""
    for marker in _AVIS_SECTION_MARKERS:
        pos = text.find(marker)
        if pos != -1:
            logger.debug(f"AVIS section marker '{marker}' found at char {pos}")
            return pos
    logger.warning("AVIS section markers not found — processing full document text")
    return 0


def _split_into_blocks(avis_text: str) -> List[Tuple[str, str]]:
    """Split AVIS section text into individual notice blocks.

    Each block extends 600 chars before the notice header to capture the entity name
    that precedes each "Avis XXX N°..." marker. The block ends at the start of
    the next notice marker.

    Returns list of (ref_string, block_text) tuples.
    Falls back to raw reference-number splitting if no Avis markers are found.
    """
    markers = list(_AVIS_SPLIT_PATTERN.finditer(avis_text))

    if not markers:
        logger.warning("No Avis notice markers found — falling back to reference number split")
        markers = list(_REF_PATTERN.finditer(avis_text))

    if not markers:
        logger.error("No split markers found in AVIS section")
        return []

    blocks = []
    for i, marker in enumerate(markers):
        # Extract the reference number from the text immediately after the marker
        context_end = min(len(avis_text), marker.end() + 120)
        ref_context = avis_text[marker.start(): context_end]
        ref_match = _REF_PATTERN.search(ref_context)
        ref_str = ref_match.group(0).strip() if ref_match else f"REF-{i + 1}"

        # Extend backward to capture entity name and avis type header
        block_start = max(0, marker.start() - 600)

        # End at the start of the next marker (gives complete current notice body)
        if i + 1 < len(markers):
            block_end = markers[i + 1].start()
        else:
            block_end = min(len(avis_text), marker.start() + 3000)

        block_text = avis_text[block_start:block_end].strip()
        if len(block_text) > 80:
            blocks.append((ref_str, block_text))

    return blocks


def _extract_block_with_llm(block_text: str, ref_number: str) -> Optional[TenderBlock]:
    """Call LLM to extract and classify a single notice block.

    Returns a validated TenderBlock or None if extraction fails.
    """
    llm = get_llm_instance(temperature=0.0, max_tokens=600)
    if not llm:
        logger.error("LLM not available for structured block extraction")
        return None

    provider = settings.llm.provider
    prompt = _BLOCK_PROMPT.format(block_text=block_text[:3000])

    if provider.lower() == "groq":
        try:
            response = llm.invoke(prompt)
            text = response.content.strip()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                else:
                    logger.warning(
                        "No valid JSON in LLM response for block",
                        ref=ref_number,
                        response_preview=text[:200],
                    )
                    return None
            return TenderBlock(**data)
        except Exception as e:
            logger.warning(
                "Block extraction failed (Groq)", ref=ref_number, error=str(e)
            )
            return None
    else:
        try:
            structured_llm = llm.with_structured_output(TenderBlock)
            return structured_llm.invoke(prompt)
        except Exception as e:
            logger.warning(
                "Structured block extraction failed",
                ref=ref_number,
                error=str(e),
            )
            return None


def parse_quotidien_structured(
    pdf_content: bytes,
    source_url: str,
    quotidien_title: str,
    run_id: str,
) -> List[Dict]:
    """Parse quotidien PDF with a single LLM extraction+classification pass per block.

    Replaces the RAG+chunking + separate classify pipeline for DGCMEF quotidien PDFs.
    Each notice block is processed in one LLM call that simultaneously extracts
    structured fields and assigns domain + relevance classification.

    Items returned carry classification_embedded=True so classify_node skips them.
    """
    logger.info(
        "Parsing quotidien with structured LLM extractor",
        title=quotidien_title,
        size_mb=round(len(pdf_content) / (1024 * 1024), 2),
        run_id=run_id,
    )

    # Force pdfminer — Docling adds latency without benefit for plain text extraction
    text = extract_pdf_text_from_bytes(pdf_content, method="pdfminer")
    logger.info("PDF text extracted", chars=len(text), run_id=run_id)

    avis_start = _find_avis_section_start(text)
    avis_text = text[avis_start:]
    logger.info(f"AVIS section starts at char {avis_start}", run_id=run_id)

    blocks = _split_into_blocks(avis_text)
    logger.info(f"Split into {len(blocks)} notice blocks", run_id=run_id)

    results = []
    for i, (ref_str, block_text) in enumerate(blocks):
        logger.debug(f"Processing block {i + 1}/{len(blocks)}", ref=ref_str)

        tender = _extract_block_with_llm(block_text, ref_str)
        if tender is None:
            logger.warning(
                f"Skipping block {i + 1} — LLM extraction failed", ref=ref_str
            )
            continue

        # An item is actionable only if it's both relevant AND not a results notice
        is_actionable = tender.is_relevant and not tender.is_results_notice

        item = {
            "id": str(uuid.uuid4()),
            "url": source_url,
            "content_hash": hashlib.sha256(block_text.encode()).hexdigest(),
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
            # Embedded classification — classify_node will pass these through unchanged
            "classification_embedded": True,
            "is_relevant": is_actionable,
            "is_results_notice": tender.is_results_notice,
            "domain": tender.domain,
            # Normalize 1-5 to 0.0-1.0 for downstream score compatibility
            "relevance_score": tender.relevance_score / 5.0,
            "classification_method": "llm_structured_extraction",
        }
        results.append(item)

        logger.info(
            f"Block {i + 1}/{len(blocks)} extracted",
            ref=tender.reference,
            entity=(tender.entity or "")[:50],
            tender_object=(tender.tender_object or "")[:80],
            is_relevant=tender.is_relevant,
            is_results_notice=tender.is_results_notice,
            domain=tender.domain,
            score=tender.relevance_score,
        )

    logger.info(
        "Quotidien structured parsing complete",
        total_blocks=len(blocks),
        extracted=len(results),
        run_id=run_id,
    )
    return results
