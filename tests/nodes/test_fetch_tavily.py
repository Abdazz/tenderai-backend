"""Tests for fetch_tavily.py — Tavily API calls are always mocked."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

sys.path.insert(0, "src")

SOURCE_SEARCH = {
    "name": "Test Tavily Search",
    "base_url": "https://example.com",
    "list_url": "https://example.com/tenders",
    "parser_type": "tavily_search",
    "patterns": {"queries": ["appel d'offres Sénégal informatique"]},
}

SOURCE_EXTRACT = {
    "name": "Test Tavily Extract",
    "base_url": "https://example.com",
    "list_url": "https://example.com/tenders",
    "parser_type": "tavily_extract",
    "patterns": {"include_raw_content": True, "extract_depth": "advanced"},
}

TAVILY_SEARCH_RESPONSE = {
    "query": "appel d'offres Sénégal informatique",
    "results": [
        {
            "title": "Appel d'offres réseau MEFP",
            "url": "https://example.com/tenders/123",
            "content": "Fourniture équipements réseau pour le MEFP...",
            "raw_content": None,
            "score": 0.91,
        },
        {
            "title": "Marché public SIG gouvernement",
            "url": "https://example.com/tenders/124",
            "content": "Développement système SIG...",
            "raw_content": None,
            "score": 0.85,
        },
    ],
    "response_time": 1.2,
}

TAVILY_EXTRACT_RESPONSE = {
    "results": [
        {
            "url": "https://example.com/tenders",
            "raw_content": "Liste des appels d'offres en cours...\n- Réseau MEFP\n- SIG gouvernement",
        }
    ],
    "failed_results": [],
}


def test_tavily_search_success():
    """fetch_tavily_search returns listings with parser_type=tavily_search."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = TAVILY_SEARCH_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("tenderai_bf.agents.nodes.fetch_tavily.settings") as mock_settings:
        mock_settings.tavily.api_key.get_secret_value.return_value = "tvly-test-key"
        mock_settings.tavily.max_results = 10
        mock_settings.tavily.search_depth = "basic"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            from tenderai_bf.agents.nodes.fetch_tavily import fetch_tavily_search

            result = asyncio.run(fetch_tavily_search(SOURCE_SEARCH, "run-001"))

    assert result["status"] == "success"
    assert result["parser_type"] == "tavily_search"
    listings = result["listings"]
    assert len(listings) == 2
    assert listings[0]["title"] == "Appel d'offres réseau MEFP"
    assert listings[0]["url"] == "https://example.com/tenders/123"


def test_tavily_extract_success():
    """fetch_tavily_extract returns listings with parser_type=tavily_extract."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = TAVILY_EXTRACT_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("tenderai_bf.agents.nodes.fetch_tavily.settings") as mock_settings:
        mock_settings.tavily.api_key.get_secret_value.return_value = "tvly-test-key"
        mock_settings.tavily.max_results = 10
        mock_settings.tavily.search_depth = "basic"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            from tenderai_bf.agents.nodes.fetch_tavily import fetch_tavily_extract

            result = asyncio.run(fetch_tavily_extract(SOURCE_EXTRACT, "run-001"))

    assert result["status"] == "success"
    assert result["parser_type"] == "tavily_extract"
    listings = result["listings"]
    assert len(listings) == 1
    assert listings[0]["url"] == "https://example.com/tenders"
    assert "appel" in listings[0].get("content", "").lower()


def test_tavily_missing_api_key():
    """Returns status=failed cleanly when TAVILY_API_KEY is not set."""
    with patch("tenderai_bf.agents.nodes.fetch_tavily.settings") as mock_settings:
        mock_settings.tavily.api_key.get_secret_value.return_value = ""

        from tenderai_bf.agents.nodes.fetch_tavily import fetch_tavily_search

        result = asyncio.run(fetch_tavily_search(SOURCE_SEARCH, "run-001"))

    assert result["status"] == "failed"
    assert "TAVILY_API_KEY" in result["error"]


def test_tavily_rate_limit_non_fatal():
    """HTTP 429 does not raise — returns status=failed with error message."""
    import httpx

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=mock_response
    )

    with patch("tenderai_bf.agents.nodes.fetch_tavily.settings") as mock_settings:
        mock_settings.tavily.api_key.get_secret_value.return_value = "tvly-test-key"
        mock_settings.tavily.max_results = 10
        mock_settings.tavily.search_depth = "basic"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            from tenderai_bf.agents.nodes.fetch_tavily import fetch_tavily_search

            result = asyncio.run(fetch_tavily_search(SOURCE_SEARCH, "run-001"))

    assert result["status"] == "failed"
    assert "429" in result["error"]


def test_tavily_empty_results():
    """Empty results list → status=success but listings=[]."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"query": "...", "results": [], "response_time": 0.5}
    mock_response.raise_for_status = MagicMock()

    with patch("tenderai_bf.agents.nodes.fetch_tavily.settings") as mock_settings:
        mock_settings.tavily.api_key.get_secret_value.return_value = "tvly-test-key"
        mock_settings.tavily.max_results = 10
        mock_settings.tavily.search_depth = "basic"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            from tenderai_bf.agents.nodes.fetch_tavily import fetch_tavily_search

            result = asyncio.run(fetch_tavily_search(SOURCE_SEARCH, "run-001"))

    assert result["status"] == "success"
    assert result["listings"] == []
