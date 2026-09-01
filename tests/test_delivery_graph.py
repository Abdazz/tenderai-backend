import hashlib
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

# Imports below must follow the env var setup above (config validates on import).
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from tenderai.db import Base  # noqa: E402
from tenderai.models import (  # noqa: E402
    Company,
    CompanyNoticeStatus,
    Country,
    Notice,
    Source,
)


def test_delivery_graph_node_sequence():
    from tenderai.agents.delivery_graph import DeliveryGraph

    graph = DeliveryGraph()
    node_names = set(graph.graph.nodes.keys())
    assert node_names == {
        "select_new_notices",
        "classify",
        "summarize",
        "compose_report",
        "email_report",
        "mark_delivered",
        "error_handler",
    }


@pytest.fixture
def db_session():
    """A single shared, in-memory SQLite session that every get_db_context
    patch below yields — so writes made by one node (e.g. classify's
    CompanyNoticeStatus upsert) are visible to a later node in the same run
    (e.g. mark_delivered), exactly like the real pipeline sharing one DB."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def test_delivery_graph_runs_end_to_end(db_session):
    """Exercise the real graph — select_new_notices, classify (keyword path,
    no LLM), summarize, compose_report, email_report, mark_delivered — against
    a real in-memory DB. Only genuinely external boundaries (MinIO, SMTP) are
    mocked; the delivery-cursor fix (Finding #1) and the sources/stats fixes
    (Finding #3) are exercised through the whole graph, not just their own
    unit tests."""
    from tenderai.agents.delivery_graph import DeliveryGraph

    country = Country(id=1, name="Burkina Faso", code="BF", locale="fr", active=True)
    company = Company(id=1, name="YULCOM Technologies", slug="yulcom", active=True)
    source = Source(
        id=10,
        name="DGCMEF Burkina Faso",
        base_url="https://x",
        list_url="https://x/l",
        parser_type="html",
        enabled=True,
        country_id=1,
    )
    db_session.add_all([country, company, source])
    db_session.commit()

    notice_relevant = Notice(
        id="notice-relevant",
        source_id=10,
        run_id="run-harvest-1",
        title="Acquisition de serveurs et équipement réseau informatique",
        entity="Ministère du Numérique",
        category="IT",
        description="Fourniture de serveurs et de matériel informatique",
        content_hash=hashlib.sha256(b"relevant").hexdigest(),
        url="https://x/1",
    )
    notice_irrelevant = Notice(
        id="notice-irrelevant",
        source_id=10,
        run_id="run-harvest-1",
        title="Construction de routes rurales",
        entity="Mairie",
        category="BTP",
        description="Travaux de génie civil",
        content_hash=hashlib.sha256(b"irrelevant").hexdigest(),
        url="https://x/2",
    )
    db_session.add_all([notice_relevant, notice_irrelevant])
    db_session.commit()

    @contextmanager
    def _shared_db_context():
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    mock_storage_client = MagicMock()
    mock_storage_client.store_report.return_value = "https://minio/fake-report.docx"

    with patch(
        "tenderai.agents.delivery_graph.get_db_context", _shared_db_context
    ), patch(
        "tenderai.agents.nodes.select_new_notices.get_db_context",
        _shared_db_context,
    ), patch(
        "tenderai.agents.nodes.classify.get_db_context", _shared_db_context
    ), patch(
        "tenderai.agents.nodes.mark_delivered.get_db_context", _shared_db_context
    ), patch(
        "tenderai.agents.delivery_graph.CountryStore"
    ) as mock_country_store, patch(
        "tenderai.agents.delivery_graph.CompanyStore"
    ) as mock_company_store, patch(
        "tenderai.agents.nodes.compose_report.get_storage_client",
        return_value=mock_storage_client,
    ), patch(
        "tenderai.agents.nodes.email_report.send_report_email", return_value=True
    ) as mock_send_email:
        mock_country_store.get_all_with_fallback.return_value = {
            "pipeline": {"use_llm_classification": False},
            "llm": {"provider": "groq"},
            "email": {"to_address": ""},
        }
        mock_company_store.get_all_with_fallback.return_value = {
            "classification": {
                "min_relevance_score": 0.3,
                "relevant_keywords": {
                    "it_services": ["informatique", "serveur", "réseau"],
                },
            },
        }

        graph = DeliveryGraph()
        final_state = graph.run(
            company_id=1, country_id=1, triggered_by="test", test_mode=True
        )

    assert not final_state.error_occurred, final_state.errors

    # Finding #3: state.sources must be populated from the country's enabled
    # sources, and classify must set the unique_items stat — both previously
    # silently empty/zero in every delivered report.
    assert len(final_state.sources) == 1
    assert final_state.sources[0]["id"] == 10
    assert final_state.stats.unique_items == 1

    # The relevant notice was classified, reported, and (via test_mode's
    # admin-only send path) considered delivered; the irrelevant one was
    # rejected and never delivered.
    relevant_status = (
        db_session.query(CompanyNoticeStatus)
        .filter_by(company_id=1, notice_id="notice-relevant")
        .first()
    )
    irrelevant_status = (
        db_session.query(CompanyNoticeStatus)
        .filter_by(company_id=1, notice_id="notice-irrelevant")
        .first()
    )
    assert relevant_status is not None
    assert relevant_status.is_relevant is True
    # Finding #1: mark_delivered must actually set delivered_at for the item
    # that made it into the sent report — this is the field select_new_notices
    # now reads back to decide whether a relevant item still needs retrying.
    assert relevant_status.delivered_at is not None

    assert irrelevant_status is not None
    assert irrelevant_status.is_relevant is False
    assert irrelevant_status.delivered_at is None

    assert mock_send_email.called
    assert mock_storage_client.store_report.called
