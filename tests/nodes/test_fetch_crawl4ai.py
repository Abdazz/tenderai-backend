"""Tests for fetch_crawl4ai — AsyncWebCrawler always mocked."""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")
sys.path.insert(0, "src")

SOURCE = {
    "name": "UEMOA - Appels d'offres",
    "list_url": "https://www.uemoa.int/appel-d-offre",
    "parser_type": "crawl4ai",
    "patterns": {
        "ssl_verify": False,
        "entity": "UEMOA",
        "max_pages": 1,
    },
}

EXTRACTED_ITEMS = [
    {
        "title": "Appel d'offres matériel informatique CUEMOA",
        "reference": "AO-012-2026",
        "deadline": "2026-07-15",
        "entity": "UEMOA",
        "country": "Zone UEMOA",
        "description": "Acquisition matériel informatique",
        "document_url": "https://www.uemoa.int/sites/default/files/opportunite_affaire/AO_info.pdf",
    }
]


def _run(coro):
    return asyncio.run(coro)


def _make_crawler_mock(extracted_content):
    mock_result = MagicMock()
    mock_result.extracted_content = (
        json.dumps(extracted_content) if extracted_content is not None else None
    )

    mock_crawler = AsyncMock()
    mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
    mock_crawler.__aexit__ = AsyncMock(return_value=False)
    mock_crawler.arun = AsyncMock(return_value=mock_result)
    return mock_crawler


def test_crawl4ai_extracts_listings():
    """crawl4ai fetcher retourne listings avec champs standards."""
    mock_crawler = _make_crawler_mock(EXTRACTED_ITEMS)

    with patch(
        "tenderai_bf.agents.nodes.fetch_crawl4ai._CRAWL4AI_AVAILABLE", True
    ), patch(
        "tenderai_bf.agents.nodes.fetch_crawl4ai.AsyncWebCrawler",
        return_value=mock_crawler,
    ), patch("tenderai_bf.agents.nodes.fetch_crawl4ai.LLMExtractionStrategy"), patch(
        "tenderai_bf.agents.nodes.fetch_crawl4ai._get_llm_config",
        return_value=("groq/llama-3.3-70b-versatile", "test-key"),
    ):
        result = _run(
            __import__(
                "tenderai_bf.agents.nodes.fetch_crawl4ai", fromlist=["fetch_crawl4ai"]
            ).fetch_crawl4ai(SOURCE, "run-test")
        )

    assert result["status"] == "success"
    assert result["parser_type"] == "crawl4ai"
    listings = result["listings"]
    assert len(listings) == 1
    assert listings[0]["title"] == "Appel d'offres matériel informatique CUEMOA"
    assert listings[0]["reference"] == "AO-012-2026"
    assert listings[0]["deadline"] == "2026-07-15"
    assert listings[0]["parser_type"] == "crawl4ai"


def test_crawl4ai_not_installed_returns_failed():
    """Si crawl4ai n'est pas installé → status failed avec message clair."""
    import tenderai_bf.agents.nodes.fetch_crawl4ai as mod

    original = mod._CRAWL4AI_AVAILABLE
    try:
        mod._CRAWL4AI_AVAILABLE = False
        result = _run(mod.fetch_crawl4ai(SOURCE, "run-test"))
        assert result["status"] == "failed"
        assert "crawl4ai" in result["error"].lower()
    finally:
        mod._CRAWL4AI_AVAILABLE = original


def test_crawl4ai_empty_extraction_returns_failed():
    """extracted_content vide → status failed."""
    mock_crawler = _make_crawler_mock(None)

    with patch(
        "tenderai_bf.agents.nodes.fetch_crawl4ai.AsyncWebCrawler",
        return_value=mock_crawler,
    ), patch("tenderai_bf.agents.nodes.fetch_crawl4ai.LLMExtractionStrategy"), patch(
        "tenderai_bf.agents.nodes.fetch_crawl4ai._get_llm_config",
        return_value=("groq/llama-3.3-70b-versatile", "test-key"),
    ):
        result = _run(
            __import__(
                "tenderai_bf.agents.nodes.fetch_crawl4ai", fromlist=["fetch_crawl4ai"]
            ).fetch_crawl4ai(SOURCE, "run-test")
        )

    assert result["status"] == "failed"
