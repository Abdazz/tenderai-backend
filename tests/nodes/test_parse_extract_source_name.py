"""constat #9 regression: the generic HTML parse branch must preserve
source_name onto the parsed item, or persist_notices can never resolve a
source_id for playwright detail-page items (unique_items > 0, notices_persisted
stays 0)."""

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
from tenderai.agents.nodes.parse_extract import parse_extract_node  # noqa: E402


def test_generic_html_branch_preserves_source_name():
    items_raw = [
        {
            "status": "success",
            "content": "<html><body><h1>Police Goods and Services</h1></body></html>",
            "url": "https://achatscanada.canada.ca/notice/1",
            "parser_type": "html",
            "source_name": "Achats Canada",
        }
    ]
    state = TenderAIState(run_id="run-test", country_id=1, items_raw=items_raw)

    result = parse_extract_node(state)

    assert not result.error_occurred
    assert len(result.items_parsed) == 1
    assert result.items_parsed[0]["source_name"] == "Achats Canada"
