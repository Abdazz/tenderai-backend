"""constat #12 regression: a silently-dead collection (0 persisted despite
real unique items, or a source failing outright) must email the admin —
previously nothing ever alerted, which is why BF stayed broken 3+ weeks and
CA never worked, unnoticed."""

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

from tenderai.agents.graph import TenderAIState  # noqa: E402
from tenderai.agents.nodes.collection_alert import check_and_alert  # noqa: E402


def _mock_smtp_client():
    instance = MagicMock()
    instance.send_email.return_value = True
    return patch(
        "tenderai.agents.nodes.collection_alert.SMTPClient", return_value=instance
    )


def test_alerts_when_persisted_zero_despite_unique_items():
    state = TenderAIState(run_id="run-1", country_id=1, country_name="Burkina Faso")
    state.update_stats(unique_items=89, notices_persisted=0)

    with _mock_smtp_client() as mock_cls:
        check_and_alert(state, "run-1")

    instance = mock_cls.return_value
    instance.send_email.assert_called_once()
    body = instance.send_email.call_args.kwargs["body_text"]
    assert "89 avis uniques" in body
    assert "0 persisté" in body


def test_alerts_on_total_source_fetch_failure():
    state = TenderAIState(run_id="run-1", country_id=1, country_name="Burkina Faso")
    state.add_warning(
        "fetch_listings",
        "Failed to fetch DGCMEF quotidien: HTTP error 500",
        source_name="DGCMEF RAG - PDF Quotidien avec RAG",
    )

    with _mock_smtp_client() as mock_cls:
        check_and_alert(state, "run-1")

    instance = mock_cls.return_value
    instance.send_email.assert_called_once()
    body = instance.send_email.call_args.kwargs["body_text"]
    assert "DGCMEF RAG" in body


def test_no_alert_on_healthy_run():
    state = TenderAIState(run_id="run-1", country_id=1, country_name="Burkina Faso")
    state.update_stats(unique_items=10, notices_persisted=10)

    with _mock_smtp_client() as mock_cls:
        check_and_alert(state, "run-1")

    mock_cls.return_value.send_email.assert_not_called()


def test_alert_check_never_raises_on_smtp_failure():
    """A broken alert must not blow up the run it's reporting on."""
    state = TenderAIState(run_id="run-1", country_id=1, country_name="Burkina Faso")
    state.update_stats(unique_items=5, notices_persisted=0)

    with patch(
        "tenderai.agents.nodes.collection_alert.SMTPClient",
        side_effect=Exception("SMTP down"),
    ):
        check_and_alert(state, "run-1")  # must not raise
