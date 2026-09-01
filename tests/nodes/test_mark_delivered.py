import os

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

# Imports below must follow the env var setup above (config validates on import).
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from tenderai.agents.graph import TenderAIState  # noqa: E402
from tenderai.agents.nodes.mark_delivered import mark_delivered_node  # noqa: E402
from tenderai.db import Base  # noqa: E402
from tenderai.models import Company, CompanyNoticeStatus  # noqa: E402


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Company(id=1, name="YULCOM Technologies", slug="yulcom", active=True))
    session.add(
        CompanyNoticeStatus(
            id="cns-1",
            company_id=1,
            notice_id="notice-a",
            is_relevant=True,
            delivered_at=None,
        )
    )
    session.add(
        CompanyNoticeStatus(
            id="cns-2",
            company_id=1,
            notice_id="notice-b",
            is_relevant=False,
            delivered_at=None,
        )
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
        "tenderai.agents.nodes.mark_delivered.get_db_context", _fake_get_db_context
    )
    yield session
    session.close()


def test_mark_delivered_sets_delivered_at_for_reported_items(db_session):
    state = TenderAIState(
        run_id="run-1",
        company_id=1,
        unique_items=[{"id": "notice-a", "title": "A"}],
    )
    result = mark_delivered_node(state)
    assert not result.error_occurred

    row_a = (
        db_session.query(CompanyNoticeStatus).filter_by(notice_id="notice-a").first()
    )
    row_b = (
        db_session.query(CompanyNoticeStatus).filter_by(notice_id="notice-b").first()
    )
    assert row_a.delivered_at is not None
    assert row_b.delivered_at is None
