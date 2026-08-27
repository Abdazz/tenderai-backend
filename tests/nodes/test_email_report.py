import os

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tenderai_bf.agents.graph import TenderAIState
from tenderai_bf.agents.nodes.email_report import email_report_node
from tenderai_bf.db import Base
from tenderai_bf.models import Recipient


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all([
        Recipient(id=1, email="yulcom@example.com", country_id=1, company_id=1, enabled=True),
        Recipient(id=2, email="other-company@example.com", country_id=1, company_id=2, enabled=True),
    ])
    session.commit()

    def _fake_get_db_context():
        class _Ctx:
            def __enter__(self):
                return session
            def __exit__(self, *a):
                pass
        return _Ctx()

    monkeypatch.setattr(
        "tenderai_bf.agents.nodes.email_report.get_db_context", _fake_get_db_context
    )
    yield session
    session.close()


@patch("tenderai_bf.agents.nodes.email_report.send_report_email")
@patch("tenderai_bf.agents.nodes.email_report.cfg")
def test_email_report_filters_recipients_by_company(mock_cfg, mock_send, db_session):
    mock_cfg.return_value = None  # no extra "to_address" recipient
    mock_send.return_value = True

    state = TenderAIState(
        country_id=1,
        company_id=1,
        report_bytes=b"fake docx",
        report_url="https://minio/report.docx",
    )
    email_report_node(state)

    sent_recipients = mock_send.call_args.kwargs["recipients"]
    assert "yulcom@example.com" in sent_recipients
    assert "other-company@example.com" not in sent_recipients
