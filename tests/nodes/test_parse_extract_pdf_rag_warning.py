"""constat #4 regression: parse_pdf_with_rag() catches every per-chunk
exception internally and returns [] without ever raising — so a total
extraction failure (e.g. DGCMEF's 0/27```) was previously invisible, no
warning, no alert. parse_extract must surface it explicitly."""

import os
import sys
from unittest.mock import patch

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")
sys.path.insert(0, "src")

from tenderai.agents.graph import TenderAIState  # noqa: E402
from tenderai.agents.nodes.parse_extract import parse_extract_node  # noqa: E402


def _pdf_rag_item():
    return {
        "status": "success",
        "content": b"%PDF-1.4 fake pdf bytes",
        "url": "https://www.dgcmef.gov.bf/quotidien.pdf",
        "parser_type": "pdf_rag",
        "source_name": "DGCMEF RAG - PDF Quotidien avec RAG",
        "title": "Quotidien du jour",
    }


def test_zero_tenders_from_rag_produces_warning():
    state = TenderAIState(run_id="run-test", country_id=1, items_raw=[_pdf_rag_item()])

    with patch(
        "tenderai.agents.nodes.parse_pdf_rag.parse_pdf_with_rag", return_value=[]
    ):
        result = parse_extract_node(state)

    assert not result.error_occurred
    assert result.items_parsed == []
    matching = [w for w in result.warnings if w["step"] == "parse_extract"]
    assert len(matching) == 1
    assert matching[0]["source_name"] == "DGCMEF RAG - PDF Quotidien avec RAG"
    assert "0 tenders" in matching[0]["warning"]


def test_successful_rag_extraction_produces_no_warning():
    state = TenderAIState(run_id="run-test", country_id=1, items_raw=[_pdf_rag_item()])
    fake_tender = {"id": "x", "title": "Fourniture de matériel", "content_hash": "h"}

    with patch(
        "tenderai.agents.nodes.parse_pdf_rag.parse_pdf_with_rag",
        return_value=[fake_tender],
    ):
        result = parse_extract_node(state)

    assert not result.error_occurred
    assert result.items_parsed == [fake_tender]
    assert result.warnings == []
