import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")


def test_tenderai_state_has_country_fields():
    from tenderai_bf.agents.graph import TenderAIState
    state = TenderAIState(country_id=1)
    assert state.country_id == 1
    assert state.country_name == ""
    assert state.country_locale == "fr"
    assert state.country_config == {}


def test_run_sets_country_id_on_state():
    """run() must inject country context into state before graph execution."""
    from tenderai_bf.agents.graph import TenderAIGraph

    mock_country = MagicMock()
    mock_country.id = 1
    mock_country.name = "Burkina Faso"
    mock_country.locale = "fr"

    mock_config = {"pipeline": {"min_relevance_score": 0.5}, "email": {"to_address": "x@y.com"}}

    with patch("tenderai_bf.agents.graph.get_db_context") as mock_db_ctx, \
         patch("tenderai_bf.agents.graph.CountryStore") as mock_store:

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_country
        mock_db_ctx.return_value.__enter__ = lambda s: mock_session
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_store.get_all_with_fallback.return_value = mock_config

        graph = TenderAIGraph()

        captured_state = {}
        original_invoke = graph.app.invoke

        def mock_invoke(state, *a, **kw):
            captured_state["country_id"] = state.country_id
            captured_state["country_name"] = state.country_name
            captured_state["country_config"] = state.country_config
            return state

        graph.app.invoke = mock_invoke
        graph.run(country_id=1, triggered_by="test")

        assert captured_state["country_id"] == 1
        assert captured_state["country_name"] == "Burkina Faso"
        assert captured_state["country_config"] == mock_config
