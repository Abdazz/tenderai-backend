"""Tests for extract_item_links — constat #19 regression (KeyError: 'content')."""

import os
import sys

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")
sys.path.insert(0, "src")

from tenderai.agents.graph import TenderAIState  # noqa: E402
from tenderai.agents.nodes import extract_item_links as eil  # noqa: E402


def _base_state(items_raw):
    state = TenderAIState(run_id="run-test", country_id=1, items_raw=items_raw)
    state.country_config = {"pipeline": {"max_items_per_run": 1000}}
    return state


def test_failed_fetch_item_with_no_content_key_does_not_crash():
    """A failed fetch (e.g. DGCMEF 500ing) carries no 'content' key at all —
    must be skipped, not KeyError the whole run (constat #19). Paired with a
    working html-tender item so a genuine crash (not just an empty result)
    would surface as a raised exception, not a normal 'no links' return."""
    items_raw = [
        {
            "status": "failed",
            "source": {"name": "DGCMEF", "patterns": {}},
            "error": "HTTP error: 500",
            "url": "https://www.dgcmef.gov.bf/fr/appels-d-offre",
        },
        {
            "status": "success",
            "source": {"name": "Enabel", "patterns": {}},
            "listings": [
                {
                    "title": "Fourniture d'équipements",
                    "url": "https://www.enabel.be/notice/1",
                    "deadline": "2026-12-01",
                }
            ],
            "url": "https://www.enabel.be/fr/marches-publics/",
            "parser_type": "html-tender",
        },
    ]
    state = eil.extract_item_links_node(_base_state(items_raw))

    assert not state.error_occurred
    assert len(state.discovered_links) == 1


def test_html_tender_item_uses_listings_not_content():
    """html-tender items carry data in 'listings', never 'content' — must not
    KeyError when 'content' is entirely absent from a successful item either."""
    items_raw = [
        {
            "status": "success",
            "source": {"name": "Enabel", "patterns": {}},
            "listings": [
                {
                    "title": "Fourniture d'équipements",
                    "url": "https://www.enabel.be/notice/1",
                    "deadline": "2026-12-01",
                }
            ],
            "url": "https://www.enabel.be/fr/marches-publics/",
            "parser_type": "html-tender",
        }
    ]
    state = eil.extract_item_links_node(_base_state(items_raw))

    assert not state.error_occurred
    assert len(state.discovered_links) == 1


def test_playwright_detail_links_carry_source_name():
    """constat #9: playwright_links + fetch_detail_with_playwright must tag
    each detail URL with source_name, or persist_notices can never resolve
    a source_id for it later (unique_items > 0 but notices_persisted stays 0)."""
    import json

    items_raw = [
        {
            "status": "success",
            "source": {
                "name": "Achats Canada",
                "patterns": {"fetch_detail_with_playwright": True},
            },
            "content": json.dumps(
                [
                    "https://achatscanada.canada.ca/notice/1",
                    "https://achatscanada.canada.ca/notice/2",
                ]
            ),
            "url": "https://achatscanada.canada.ca/fr/occasions-de-marche",
            "parser_type": "playwright_links",
        }
    ]
    state = eil.extract_item_links_node(_base_state(items_raw))

    assert not state.error_occurred
    assert len(state.discovered_links) == 2
    for link in state.discovered_links:
        assert link["source_name"] == "Achats Canada"
