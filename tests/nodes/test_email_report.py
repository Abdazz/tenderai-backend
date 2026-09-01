import os

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

# Imports below must follow the env var setup above (config validates on import).
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from tenderai.agents.graph import TenderAIState  # noqa: E402
from tenderai.agents.nodes.email_report import email_report_node  # noqa: E402
from tenderai.db import Base  # noqa: E402
from tenderai.models import Recipient  # noqa: E402


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all(
        [
            Recipient(
                id=1,
                email="yulcom@example.com",
                country_id=1,
                company_id=1,
                enabled=True,
            ),
            Recipient(
                id=2,
                email="other-company@example.com",
                country_id=1,
                company_id=2,
                enabled=True,
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
        "tenderai.agents.nodes.email_report.get_db_context", _fake_get_db_context
    )
    yield session
    session.close()


@patch("tenderai.agents.nodes.email_report.send_report_email")
@patch("tenderai.agents.nodes.email_report.cfg")
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
