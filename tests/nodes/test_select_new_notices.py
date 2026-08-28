import hashlib
import os
import uuid
from datetime import datetime

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

# Imports below must follow the env var setup above (config validates on import).
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from tenderai_bf.agents.graph import TenderAIState  # noqa: E402
from tenderai_bf.agents.nodes.select_new_notices import (  # noqa: E402
    select_new_notices_node,
)
from tenderai_bf.db import Base  # noqa: E402
from tenderai_bf.models import (  # noqa: E402
    Company,
    CompanyNoticeStatus,
    Country,
    Notice,
    Run,
    Source,
)


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)

    session.add_all(
        [
            Country(id=1, name="Burkina Faso", code="BF", locale="fr", active=True),
            Source(
                id=10,
                name="DGCMEF Burkina Faso",
                base_url="https://x",
                list_url="https://x/l",
                parser_type="html",
                enabled=True,
                country_id=1,
            ),
            Company(id=1, name="YULCOM Technologies", slug="yulcom", active=True),
            Run(
                id="run-1",
                status="completed",
                triggered_by="test",
                country_id=1,
                run_type="harvest",
            ),
        ]
    )
    session.commit()

    notice_rejected = Notice(
        id="notice-rejected",
        source_id=10,
        run_id="run-1",
        title="Classified as not relevant",
        content_hash=hashlib.sha256(b"rejected").hexdigest(),
        url="https://x/1",
    )
    notice_new = Notice(
        id="notice-new",
        source_id=10,
        run_id="run-1",
        title="Not yet classified",
        content_hash=hashlib.sha256(b"new").hexdigest(),
        url="https://x/2",
    )
    notice_undelivered = Notice(
        id="notice-undelivered",
        source_id=10,
        run_id="run-1",
        title="Relevant but never delivered (failed prior attempt)",
        content_hash=hashlib.sha256(b"undelivered").hexdigest(),
        url="https://x/3",
    )
    notice_delivered = Notice(
        id="notice-delivered",
        source_id=10,
        run_id="run-1",
        title="Relevant and already delivered",
        content_hash=hashlib.sha256(b"delivered").hexdigest(),
        url="https://x/4",
    )
    session.add_all([notice_rejected, notice_new, notice_undelivered, notice_delivered])
    session.add_all(
        [
            CompanyNoticeStatus(
                id=str(uuid.uuid4()),
                company_id=1,
                notice_id="notice-rejected",
                is_relevant=False,
            ),
            CompanyNoticeStatus(
                id=str(uuid.uuid4()),
                company_id=1,
                notice_id="notice-undelivered",
                is_relevant=True,
                delivered_at=None,
            ),
            CompanyNoticeStatus(
                id=str(uuid.uuid4()),
                company_id=1,
                notice_id="notice-delivered",
                is_relevant=True,
                delivered_at=datetime(2026, 1, 1, 12, 0, 0),
            ),
        ]
    )
    session.commit()

    def _fake_get_db_context():
        class _Ctx:
            def __enter__(self):
                return session

            def __exit__(self, *a):
                pass

        return _Ctx()

    monkeypatch.setattr(
        "tenderai_bf.agents.nodes.select_new_notices.get_db_context",
        _fake_get_db_context,
    )
    yield session
    session.close()


def test_select_new_notices_excludes_rejected(db_session):
    state = TenderAIState(run_id="run-2", country_id=1, company_id=1)
    result = select_new_notices_node(state)
    assert not result.error_occurred
    ids = [i["id"] for i in result.items_parsed]
    assert "notice-new" in ids
    assert "notice-rejected" not in ids


def test_select_new_notices_retries_relevant_but_undelivered(db_session):
    """A notice judged relevant but never successfully delivered (e.g. a prior
    SMTP/MinIO failure after classify wrote its status row) must be retried."""
    state = TenderAIState(run_id="run-2", country_id=1, company_id=1)
    result = select_new_notices_node(state)
    ids = [i["id"] for i in result.items_parsed]
    assert "notice-undelivered" in ids


def test_select_new_notices_excludes_relevant_and_delivered(db_session):
    state = TenderAIState(run_id="run-2", country_id=1, company_id=1)
    result = select_new_notices_node(state)
    ids = [i["id"] for i in result.items_parsed]
    assert "notice-delivered" not in ids


def test_select_new_notices_returns_classify_compatible_dicts(db_session):
    state = TenderAIState(run_id="run-2", country_id=1, company_id=1)
    result = select_new_notices_node(state)
    item = next(i for i in result.items_parsed if i["id"] == "notice-new")
    assert item["title"] == "Not yet classified"
    assert "entity" in item
    assert "description" in item
    assert "location" in item
    assert "reference" in item
    assert "deadline" in item
