"""Regression test: generated tender ids must fit Notice.id (String(36),
sized for a UUID). The old f"{source_name}_{i}_{j}" format could exceed 36
chars for any source with a longer name (e.g. "DGCMEF RAG - PDF Quotidien
avec RAG_4_1" = 40 chars) — every INSERT then failed with
psycopg2.errors.StringDataRightTruncation, silently (persist_notices skips
failed items with just a log line). This was unreachable until extraction
itself started actually producing tenders, so it was never observed before."""

import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")
sys.path.insert(0, "src")

from tenderai.agents.nodes.parse_pdf_rag import parse_pdf_with_rag  # noqa: E402
from tenderai.schemas import Tender, TenderExtraction  # noqa: E402

LONG_SOURCE_NAME = "DGCMEF RAG - PDF Quotidien avec RAG"  # 36 chars alone


def test_direct_extraction_id_fits_notice_id_column():
    fake_tender = Tender(
        entity="Primature",
        reference="2026-08/PRIM/SG/DMP",
        tender_object="acquisition de matériel de bureau",
        category="Biens",
    )
    fake_extraction = TenderExtraction(tenders=[fake_tender])

    with (
        patch(
            "tenderai.utils.llm_utils.get_llm_instance",
            return_value=MagicMock(model_name="test-model"),
        ),
        patch(
            "tenderai.agents.nodes.parse_pdf_rag.extract_text_from_pdf",
            return_value="short text, one chunk only",
        ),
        patch(
            "tenderai.agents.nodes.parse_pdf_rag.extract_tenders_structured",
            return_value=fake_extraction,
        ),
    ):
        tenders = parse_pdf_with_rag(
            pdf_path="/tmp/fake.pdf",  # noqa: S108 — never written to, pdf_content overrides it
            source_name=LONG_SOURCE_NAME,
            filename="quotidien.pdf",
            pdf_content=b"%PDF-1.4 fake",
            use_llm=True,
            use_direct_extraction=True,
        )

    assert len(tenders) == 1
    assert len(tenders[0]["id"]) <= 36
    # a real UUID, not the old human-readable composite
    import uuid

    uuid.UUID(tenders[0]["id"])
