"""Test load_sources node uses DB only."""
import os

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

# Imports below must follow the env var setup above (config validates on import).
from unittest.mock import MagicMock, patch  # noqa: E402

from tenderai_bf.agents.graph import TenderAIState  # noqa: E402
from tenderai_bf.agents.nodes.load_sources import load_sources_node  # noqa: E402


def test_load_sources_uses_db_not_yaml():
    """load_sources must query the DB, not settings.yaml."""
    state = TenderAIState(country_id=1, country_config={})

    mock_source = MagicMock()
    mock_source.id = 1
    mock_source.name = "Test Source"
    mock_source.base_url = "https://example.com"
    mock_source.list_url = "https://example.com/tenders"
    mock_source.parser_type = "html"
    mock_source.rate_limit = "10/m"
    mock_source.patterns = {}
    mock_source.enabled = True
    mock_source.last_seen_at = None
    mock_source.last_success_at = None
    mock_source.last_error_at = None
    mock_source.last_error_message = None

    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.all.return_value = [mock_source]

    with patch("tenderai_bf.agents.nodes.load_sources.get_db_context") as mock_ctx:
        mock_ctx.return_value.__enter__ = lambda s: mock_session
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        result = load_sources_node(state)

    assert len(result.sources) == 1
    assert result.sources[0]["name"] == "Test Source"


def test_load_sources_fails_if_no_sources():
    """Pipeline should stop if no active sources exist for country."""
    state = TenderAIState(country_id=1, country_config={})

    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.all.return_value = []

    with patch("tenderai_bf.agents.nodes.load_sources.get_db_context") as mock_ctx:
        mock_ctx.return_value.__enter__ = lambda s: mock_session
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        result = load_sources_node(state)

    assert result.should_continue is False
    assert result.error_occurred is True
