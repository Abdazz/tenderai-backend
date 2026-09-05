"""Extract individual tender notices from a Tavily-extracted listing page.

Strategy: one LLM call that receives the raw page text and returns all tender
notices' structural fields.  This mirrors the approach used by
parse_pdf_structured for DGCMEF quotidien PDFs.

Relevance is judged later, per-company, by classify_node in the delivery graph.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime

import httpx
from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser

from ...logging import get_logger
from ...utils.dates import parse_flexible_date
from ...utils.llm_utils import get_llm_instance

logger = get_logger(__name__)

# Safety cap: ~70 K tokens at 5.5 ch/token, leaves room for prompt + output.
_MAX_INPUT_CHARS = 200_000

# Bilingual "deadline" label patterns seen on tender detail pages (e.g.
# Palladium's "Closing date: 12 August 2026") — constat #21: listing pages
# for some tavily_extract sources don't carry reference/deadline, only the
# individual detail page does.
_DEADLINE_LABEL_RE = re.compile(
    r"(?:closing date|deadline|date limite|date but[oô]ir)\s*[:\-]?\s*"
    r"([0-9]{1,2}[\s/-][A-Za-zÀ-ÿ]+[\s/-][0-9]{2,4}|[0-9]{4}[/-][0-9]{1,2}[/-][0-9]{1,2})",
    re.IGNORECASE,
)


def _fetch_detail_deadline(url: str, source_name: str, run_id: str) -> str | None:
    """Best-effort fetch of a tender's detail page to recover a deadline the
    listing page didn't carry. Never raises — returns None on any failure."""
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TenderAI/1.0)"},
            timeout=10.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        text = HTMLParser(resp.text).body.text(separator=" ", strip=True)
    except Exception as e:
        logger.debug(
            "Detail page fetch for deadline enrichment failed",
            url=url,
            source=source_name,
            error=str(e),
            run_id=run_id,
        )
        return None

    match = _DEADLINE_LABEL_RE.search(text)
    if not match:
        return None

    raw_date = match.group(1).strip()
    parsed = parse_flexible_date(raw_date)
    if not parsed:
        return None

    logger.info(
        "Recovered deadline from detail page",
        url=url,
        source=source_name,
        raw_date=raw_date,
        run_id=run_id,
    )
    return parsed.strftime("%Y-%m-%d")


class TenderItem(BaseModel):
    """A single tender notice's structural fields, extracted from a listing page.

    No relevance judgment — classify_node (delivery graph) is the sole place
    relevance is decided, per-company.
    """

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


class TenderItemList(BaseModel):
    tenders: list[TenderItem] = Field(default_factory=list)


_EXTRACTION_PROMPT = """\
Tu es un expert en marchés publics. Tu reçois le contenu textuel d'une page de \
listing d'appels d'offres (portail gouvernemental, organisation internationale, etc.).

TEXTE DE LA PAGE :
{page_text}

SOURCE : {source_name}
URL_DE_BASE : {source_url}

Ta mission :
1. Identifier TOUS les appels d'offres listés dans ce texte (même partiellement).
2. Pour chaque appel d'offres, extraire les informations disponibles.

RÈGLES :
- is_results_notice = true pour contrats déjà octroyés, résultats d'appels d'offres, \
PV de dépouillement
- Si la page ne contient aucun appel d'offres identifiable, retourne une liste vide.
- N'invente pas d'informations absentes du texte.
- Pour tender_url : le texte peut contenir des liens au format [Titre](/chemin/vers/fiche). \
Extrais le chemin (ex: /fr/occasions-de-marche/appels-d-offres/ID) pour chaque appel. \
Si le chemin est relatif (commence par /), le retourner tel quel — il sera rendu absolu \
automatiquement avec l'URL_DE_BASE fournie. Si l'URL complète est visible, l'utiliser directement.

Retourne UNIQUEMENT du JSON valide (pas de markdown, pas d'explication) :
{{
  "tenders": [
    {{
      "title": "Titre de l'appel d'offres",
      "entity": "Organisation émettrice",
      "reference": "",
      "deadline": null,
      "description": "Description courte",
      "tender_url": "/chemin/vers/fiche-ou-null",
      "is_results_notice": false
    }}
  ]
}}\
"""


def _normalize_tender_dict(raw: dict) -> TenderItem | None:
    """Validate/convert a raw LLM output dict into a TenderItem.

    Rather than discarding the whole batch on one malformed item, we
    validate per-item so valid items are preserved.
    """
    try:
        return TenderItem(**raw)
    except Exception as e:
        logger.debug("Skipping malformed tender item", error=str(e), raw=str(raw)[:200])
        return None


def _extract_tenders_from_page(
    page_text: str, source_name: str, source_url: str, llm_provider: str
) -> list[TenderItem]:
    """Single LLM call to extract all tenders from a listing page."""
    llm = get_llm_instance(temperature=0.0, max_tokens=8000)
    if not llm:
        logger.error("LLM not available for tavily listing extraction")
        return []

    prompt = _EXTRACTION_PROMPT.format(
        page_text=page_text[:_MAX_INPUT_CHARS],
        source_name=source_name,
        source_url=source_url,
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
            logger.error(
                "LLM extraction failed (Groq)", source=source_name, error=str(e)
            )
            return []
    else:
        try:
            structured_llm = llm.with_structured_output(TenderItemList)
            result = structured_llm.invoke(prompt)
            return result.tenders
        except Exception as e:
            logger.error(
                "Structured LLM extraction failed", source=source_name, error=str(e)
            )
            return []


def parse_tavily_listing(
    page_content: str,
    source_url: str,
    source_name: str,
    run_id: str,
    llm_cfg: dict | None = None,
) -> list[dict]:
    """Parse the text content of a Tavily-extracted listing page into individual notices.

    One LLM call extracts all visible tenders' structural fields from the page.
    Relevance is judged later, per-company, by classify_node in the delivery graph.

    Falls back to an empty list if the LLM finds nothing or fails.
    """
    if not page_content or not page_content.strip():
        logger.warning(
            "Empty page content for tavily listing", source=source_name, run_id=run_id
        )
        return []

    logger.info(
        "Extracting tenders from Tavily listing page",
        source=source_name,
        chars=len(page_content),
        run_id=run_id,
    )

    llm_provider = (llm_cfg or {}).get("provider", "groq")
    tenders = _extract_tenders_from_page(
        page_content, source_name, source_url, llm_provider
    )

    logger.info(
        f"LLM returned {len(tenders)} notices from listing page",
        source=source_name,
        run_id=run_id,
    )

    # Pre-compute base origin from source_url for resolving relative paths
    from urllib.parse import urlparse

    _parsed_base = urlparse(source_url)
    _base_origin = f"{_parsed_base.scheme}://{_parsed_base.netloc}"

    results = []
    for i, tender in enumerate(tenders):
        # Resolve tender URL: make relative paths absolute, fall back to source listing URL
        raw_url = tender.tender_url
        if raw_url:
            if raw_url.startswith("/"):
                raw_url = _base_origin + raw_url
            elif not raw_url.startswith("http"):
                from urllib.parse import urljoin

                raw_url = urljoin(source_url, raw_url)
        item_url = raw_url or source_url

        deadline = tender.deadline
        if not deadline and item_url != source_url:
            deadline = _fetch_detail_deadline(item_url, source_name, run_id)

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
            "deadline": deadline,
            "deadline_at": deadline,
            "description": tender.description,
            "is_results_notice": tender.is_results_notice,
        }
        results.append(item)

        logger.info(
            f"Listing item {i + 1}/{len(tenders)}",
            source=source_name,
            title=(tender.title or "")[:80],
            entity=(tender.entity or "")[:50],
            run_id=run_id,
        )

    logger.info(
        "Tavily listing extraction complete",
        source=source_name,
        total=len(results),
        run_id=run_id,
    )
    return results
