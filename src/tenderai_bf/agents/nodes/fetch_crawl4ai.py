"""Crawl4AI-based tender fetcher.

Utilise LLMExtractionStrategy pour extraire les données sans sélecteurs CSS.
Le provider LLM est déterminé depuis settings.llm (Groq/OpenAI/Ollama).

Dépendance optionnelle : poetry install --extras "full"
"""

import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from ...logging import get_logger

logger = get_logger(__name__)

try:
    from crawl4ai import AsyncWebCrawler
    from crawl4ai.extraction_strategy import LLMExtractionStrategy
    _CRAWL4AI_AVAILABLE = True
except ImportError:
    AsyncWebCrawler = None  # type: ignore
    LLMExtractionStrategy = None  # type: ignore
    _CRAWL4AI_AVAILABLE = False


class TenderItem(BaseModel):
    """Schéma d'extraction LLM partagé html-tender / crawl4ai."""
    title: str
    reference: Optional[str] = None
    deadline: Optional[str] = None
    entity: Optional[str] = None
    country: Optional[str] = None
    description: Optional[str] = None
    document_url: Optional[str] = None


_EXTRACTION_INSTRUCTION = (
    "Extrais tous les appels d'offres ou marchés publics présents sur cette page. "
    "Pour chaque appel d'offres, retourne un objet JSON avec les champs : "
    "title (intitulé complet), reference (numéro de référence si présent), "
    "deadline (date limite de dépôt), entity (organisme émetteur), "
    "country (pays concerné), description (résumé court), "
    "document_url (URL du PDF ou document si présent)."
)


async def fetch_crawl4ai(source: dict, run_id: str) -> dict:
    """Fetch tenders using Crawl4AI LLM extraction strategy."""
    if not _CRAWL4AI_AVAILABLE:
        logger.error(
            "crawl4ai not installed — run: poetry install --extras full && crawl4ai-setup",
            run_id=run_id,
        )
        return _error(source, "crawl4ai not installed — run: poetry install --extras full")

    source_name = source["name"]
    list_url = source["list_url"]
    patterns = source.get("patterns") or {}

    ssl_verify = patterns.get("ssl_verify", True)
    max_pages = int(patterns.get("max_pages", 1))
    pagination_url = patterns.get("pagination_url")

    urls = [list_url]
    if max_pages > 1 and pagination_url:
        for page in range(2, max_pages + 1):
            urls.append(pagination_url.format(page=page))

    provider, api_token = _get_llm_config()
    strategy = LLMExtractionStrategy(
        provider=provider,
        api_token=api_token,
        schema=TenderItem.model_json_schema(),
        extraction_type="schema",
        instruction=_EXTRACTION_INSTRUCTION,
    )

    crawler_kwargs: dict = {}
    if not ssl_verify:
        try:
            from crawl4ai import BrowserConfig
            crawler_kwargs["config"] = BrowserConfig(ignore_https_errors=True)
        except Exception:
            pass

    listings: list[dict] = []

    async with AsyncWebCrawler(**crawler_kwargs) as crawler:
        for url in urls:
            try:
                result = await crawler.arun(url=url, extraction_strategy=strategy)
                if not result.extracted_content:
                    logger.warning("crawl4ai: aucun contenu extrait", url=url, run_id=run_id)
                    continue

                raw = json.loads(result.extracted_content)
                items = raw if isinstance(raw, list) else [raw]

                for item in items:
                    if not item.get("title"):
                        continue
                    listings.append({
                        "url": item.get("document_url") or url,
                        "title": item.get("title", ""),
                        "tender_object": item.get("title", ""),
                        "reference": item.get("reference", ""),
                        "ref_no": item.get("reference", ""),
                        "entity": item.get("entity") or patterns.get("entity", source_name),
                        "location": item.get("country") or patterns.get("location", ""),
                        "deadline": item.get("deadline", ""),
                        "description": item.get("description", ""),
                        "category": "Autre",
                        "type": "appel_offres",
                        "source": source_name,
                        "parser_type": "crawl4ai",
                    })
            except Exception as e:
                logger.warning("crawl4ai fetch failed", url=url, error=str(e), run_id=run_id)

    logger.info(
        "crawl4ai fetch complete",
        source=source_name,
        listings=len(listings),
        run_id=run_id,
    )

    return {
        "source": source,
        "content": None,
        "listings": listings,
        "url": list_url,
        "status": "success" if listings else "failed",
        "parser_type": "crawl4ai",
        "fetched_at": datetime.utcnow().isoformat(),
    }


def _get_llm_config() -> tuple[str, str]:
    """Retourne (provider_string, api_token) depuis settings.llm."""
    from ...config import settings
    llm = settings.llm
    if llm.provider == "groq":
        return (f"groq/{llm.groq_model}", llm.groq_api_key.get_secret_value())
    if llm.provider == "openai":
        return (f"openai/{llm.openai_model}", llm.openai_api_key.get_secret_value())
    if llm.provider == "ollama":
        return (f"ollama/{llm.ollama_model}", "")
    return (f"openai/{llm.openai_model}", llm.openai_api_key.get_secret_value())


def _error(source: dict, msg: str) -> dict:
    return {
        "source": source,
        "content": None,
        "listings": [],
        "url": source["list_url"],
        "status": "failed",
        "error": msg,
        "parser_type": "crawl4ai",
        "fetched_at": datetime.utcnow().isoformat(),
    }
