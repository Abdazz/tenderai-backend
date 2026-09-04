"""Tests for _fetch_playwright_detail_items — constat #9 regression.

CA's playwright detail-page items reached persist_notices with no source_id
resolvable at all (unique_items > 0 but notices_persisted stayed 0) because
this function discarded which pipeline Source each URL belonged to. These
tests confirm source_name now survives every return path.
"""

import asyncio
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

from tenderai.agents.nodes import fetch_items as fi  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _mock_playwright_chain(page_content="<html>ok</html>", goto_side_effect=None):
    """Build the async_playwright()...page.content() mock chain."""
    page = AsyncMock()
    if goto_side_effect:
        page.goto = AsyncMock(side_effect=goto_side_effect)
    page.content = AsyncMock(return_value=page_content)

    context = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.route = AsyncMock()

    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)

    chromium = AsyncMock()
    chromium.launch = AsyncMock(return_value=browser)

    pw = MagicMock()
    pw.chromium = chromium

    pw_cm = AsyncMock()
    pw_cm.__aenter__ = AsyncMock(return_value=pw)
    pw_cm.__aexit__ = AsyncMock(return_value=False)

    return pw_cm


def test_source_name_survives_successful_fetch():
    links = [
        {
            "url": "https://achatscanada.canada.ca/notice/1",
            "source_name": "Achats Canada",
        },
        {
            "url": "https://montreal.ca/notice/2",
            "source_name": "Ville de Montréal - Appels d'offres",
        },
    ]
    pw_cm = _mock_playwright_chain()

    with patch("playwright.async_api.async_playwright", return_value=pw_cm):
        results = _run(fi._fetch_playwright_detail_items(links, "run-test"))

    assert len(results) == 2
    assert results[0]["status"] == "success"
    assert results[0]["source_name"] == "Achats Canada"
    assert results[1]["source_name"] == "Ville de Montréal - Appels d'offres"


def test_source_name_survives_per_page_failure():
    links = [
        {
            "url": "https://achatscanada.canada.ca/notice/1",
            "source_name": "Achats Canada",
        }
    ]
    pw_cm = _mock_playwright_chain(goto_side_effect=Exception("timeout"))

    with patch("playwright.async_api.async_playwright", return_value=pw_cm):
        results = _run(fi._fetch_playwright_detail_items(links, "run-test"))

    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert results[0]["source_name"] == "Achats Canada"


def test_source_name_survives_playwright_not_installed():
    links = [
        {
            "url": "https://achatscanada.canada.ca/notice/1",
            "source_name": "Achats Canada",
        }
    ]

    with patch.dict(sys.modules, {"playwright.async_api": None}):
        results = _run(fi._fetch_playwright_detail_items(links, "run-test"))

    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert results[0]["error"] == "playwright not installed"
    assert results[0]["source_name"] == "Achats Canada"
