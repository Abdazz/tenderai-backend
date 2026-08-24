"""Integration tests for TenderAI BF."""

from unittest.mock import MagicMock, patch

import pytest

from tenderai_bf.agents.graph import TenderAIState, create_pipeline_graph


class TestPipelineIntegration:
    """Test pipeline integration."""

    def test_pipeline_state_creation(self):
        """Test creating pipeline state."""

        state = TenderAIState(
            run_id="test-run-123",
            sources=[
                {
                    "name": "Test Source",
                    "list_url": "https://example.com/rfps",
                    "parser": "html",
                }
            ],
            raw_listings=[],
            item_links=[],
            raw_items=[],
            parsed_items=[],
            classified_items=[],
            deduplicated_items=[],
            final_items=[],
            report_content="",
            report_url="",
            errors=[],
        )

        assert state.run_id == "test-run-123"
        assert len(state.sources) == 1
        assert state.sources[0]["name"] == "Test Source"

    def test_pipeline_graph_creation(self):
        """Test creating pipeline graph."""

        graph = create_pipeline_graph()

        assert graph is not None
        # The underlying LangGraph StateGraph should have nodes defined
        assert hasattr(graph.graph, "nodes")
        assert len(graph.graph.nodes) > 0
        # The compiled app is what actually runs the pipeline
        assert graph.app is not None

    # NOTE: test_load_sources_node and test_fetch_listings_node were removed here.
    # Both mocked functions (load_sources_from_config, fetch_page_content) and
    # TenderAIState fields (raw_listings, item_links, raw_items, parsed_items,
    # classified_items, deduplicated_items, final_items, report_content) that no
    # longer exist — this file predates the DB-first / multi-country refactor.
    # Current, correct coverage for these nodes lives in tests/nodes/test_load_sources.py
    # and tests/nodes/test_fetch_html_tender.py / test_fetch_tavily.py / test_fetch_crawl4ai.py.


class TestConfigIntegration:
    """Test configuration integration."""

    # NOTE: test_settings_yaml_loading was removed here. It relied on a
    # TENDERAI_SETTINGS_FILE env var to point Settings() at an arbitrary YAML
    # file — that override mechanism no longer exists. Current config.py always
    # reads the project-root settings.yaml as an infra-only supplement layered
    # under env-var-driven Pydantic BaseSettings, a fundamentally different
    # loading model than what this test exercised.


class TestDatabaseIntegration:
    """Test database integration."""

    def test_database_session_creation(self):
        """Test database session creation.

        Exercises the real engine/session path against the test sqlite DB
        (see conftest.py's TENDERAI_DATABASE_URL override) rather than
        mocking create_engine/sessionmaker: get_engine() now registers a
        real SQLAlchemy event listener on the engine
        (before_cursor_execute, for query logging), which a plain
        MagicMock engine can't satisfy — mocking at that level fights the
        implementation instead of testing behavior.
        """

        from tenderai_bf.db import get_db_context, init_database

        init_database()

        with get_db_context() as session:
            assert session is not None


class TestStorageIntegration:
    """Test storage integration."""

    @patch("boto3.client")
    def test_minio_client_creation(self, mock_boto_client):
        """Test MinIO client creation."""

        from tenderai_bf.storage.minio_client import MinIOClient

        # Mock boto3 client
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        # Create MinIO client
        minio_client = MinIOClient(
            endpoint="http://localhost:9000",
            access_key="testkey",
            secret_key="testsecret",
            bucket_name="test-bucket",
        )

        assert minio_client is not None
        mock_boto_client.assert_called_once()

    @patch("boto3.client")
    def test_file_upload(self, mock_boto_client):
        """Test file upload to storage."""

        from tenderai_bf.storage.minio_client import MinIOClient

        # Mock boto3 client. head_bucket succeeding (a plain MagicMock, no
        # ClientError raised) means ensure_bucket_exists() short-circuits to
        # True without needing to mock the create_bucket branch.
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        # Create MinIO client
        minio_client = MinIOClient(
            endpoint="http://localhost:9000",
            access_key="testkey",
            secret_key="testsecret",
            bucket_name="test-bucket",
        )

        # Upload content via the client's actual method — put_object() takes
        # the object key and raw content, and uploads via upload_fileobj().
        success = minio_client.put_object(
            key="test-file.txt", data="Test content", content_type="text/plain"
        )

        assert success is True
        mock_client.upload_fileobj.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
