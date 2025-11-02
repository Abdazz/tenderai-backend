"""Integration tests for TenderAI BF."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from tenderai_bf.agents.graph import TenderAIState, create_pipeline_graph


class TestPipelineIntegration:
    """Test pipeline integration."""
    
    def test_pipeline_state_creation(self):
        """Test creating pipeline state."""
        
        state = TenderAIState(
            run_id="test-run-123",
            sources=[{
                "name": "Test Source",
                "list_url": "https://example.com/rfps",
                "parser": "html"
            }],
            raw_listings=[],
            item_links=[],
            raw_items=[],
            parsed_items=[],
            classified_items=[],
            deduplicated_items=[],
            final_items=[],
            report_content="",
            report_url="",
            errors=[]
        )
        
        assert state.run_id == "test-run-123"
        assert len(state.sources) == 1
        assert state.sources[0]["name"] == "Test Source"
    
    def test_pipeline_graph_creation(self):
        """Test creating pipeline graph."""
        
        graph = create_pipeline_graph()
        
        assert graph is not None
        # Graph should have nodes defined
        assert hasattr(graph, 'nodes')
    
    @patch('tenderai_bf.agents.nodes.load_sources.load_sources_from_config')
    def test_load_sources_node(self, mock_load_sources):
        """Test load sources node."""
        
        from tenderai_bf.agents.nodes.load_sources import load_sources
        
        # Mock sources loading
        mock_sources = [{
            "name": "Test Ministry",
            "list_url": "https://ministry.gov.bf/rfps",
            "parser": "html",
            "rate_limit": "10/m"
        }]
        mock_load_sources.return_value = mock_sources
        
        # Test state
        state = TenderAIState(
            run_id="test",
            sources=[],
            raw_listings=[],
            item_links=[],
            raw_items=[],
            parsed_items=[],
            classified_items=[],
            deduplicated_items=[],
            final_items=[],
            report_content="",
            report_url="",
            errors=[]
        )
        
        # Execute node
        result = load_sources(state)
        
        assert len(result["sources"]) == 1
        assert result["sources"][0]["name"] == "Test Ministry"
    
    @patch('tenderai_bf.agents.nodes.fetch_listings.fetch_page_content')
    def test_fetch_listings_node(self, mock_fetch):
        """Test fetch listings node."""
        
        from tenderai_bf.agents.nodes.fetch_listings import fetch_listings
        
        # Mock page content
        mock_fetch.return_value = """
        <html>
            <body>
                <div class="rfp-item">
                    <h3>Software Development RFP</h3>
                    <p>Development services needed</p>
                </div>
            </body>
        </html>
        """
        
        # Test state with sources
        state = TenderAIState(
            run_id="test",
            sources=[{
                "name": "Test Source",
                "list_url": "https://example.com/rfps",
                "parser": "html"
            }],
            raw_listings=[],
            item_links=[],
            raw_items=[],
            parsed_items=[],
            classified_items=[],
            deduplicated_items=[],
            final_items=[],
            report_content="",
            report_url="",
            errors=[]
        )
        
        # Execute node
        result = fetch_listings(state)
        
        assert len(result["raw_listings"]) == 1
        assert "Software Development RFP" in result["raw_listings"][0]["content"]


class TestConfigIntegration:
    """Test configuration integration."""
    
    def test_settings_yaml_loading(self, tmp_path):
        """Test loading settings from YAML file."""
        
        from tenderai_bf.config import Settings
        
        # Create test YAML file
        yaml_content = """
        app_name: "TenderAI BF Test"
        debug: true
        
        email:
          smtp_server: "smtp.test.com"
          smtp_port: 587
          from_address: "test@example.com"
        
        pipeline:
          max_items_per_source: 20
          
        sources:
          - name: "Test Ministry"
            list_url: "https://test.gov.bf/rfps"
            parser: "html"
        """
        
        yaml_file = tmp_path / "test_settings.yaml"
        yaml_file.write_text(yaml_content)
        
        # Load settings with custom YAML file
        with patch.dict('os.environ', {'TENDERAI_SETTINGS_FILE': str(yaml_file)}):
            settings = Settings()
        
        assert settings.app_name == "TenderAI BF Test"
        assert settings.debug is True
        assert settings.email.smtp_server == "smtp.test.com"
        assert settings.pipeline.max_items_per_source == 20


class TestDatabaseIntegration:
    """Test database integration."""
    
    @patch('tenderai_bf.db.create_engine')
    @patch('tenderai_bf.db.sessionmaker')
    def test_database_session_creation(self, mock_sessionmaker, mock_create_engine):
        """Test database session creation."""
        
        from tenderai_bf.db import get_database_session, init_database
        
        # Mock engine and session
        mock_engine = MagicMock()
        mock_session_class = MagicMock()
        mock_session = MagicMock()
        
        mock_create_engine.return_value = mock_engine
        mock_sessionmaker.return_value = mock_session_class
        mock_session_class.return_value = mock_session
        
        # Initialize database
        init_database()
        
        # Get session
        session = get_database_session()
        
        assert session is not None
        mock_create_engine.assert_called_once()
        mock_sessionmaker.assert_called_once()


class TestStorageIntegration:
    """Test storage integration."""
    
    @patch('boto3.client')
    def test_minio_client_creation(self, mock_boto_client):
        """Test MinIO client creation."""
        
        from tenderai_bf.storage.minio_client import MinIOClient
        
        # Mock boto3 client
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        
        # Create MinIO client
        minio_client = MinIOClient(
            endpoint_url="http://localhost:9000",
            access_key="testkey",
            secret_key="testsecret",
            bucket_name="test-bucket"
        )
        
        assert minio_client is not None
        mock_boto_client.assert_called_once()
    
    @patch('boto3.client')
    def test_file_upload(self, mock_boto_client):
        """Test file upload to storage."""
        
        from tenderai_bf.storage.minio_client import MinIOClient
        import tempfile
        
        # Mock boto3 client
        mock_client = MagicMock()
        mock_client.upload_file.return_value = None
        mock_client.generate_presigned_url.return_value = "https://example.com/file.txt"
        mock_boto_client.return_value = mock_client
        
        # Create MinIO client
        minio_client = MinIOClient(
            endpoint_url="http://localhost:9000",
            access_key="testkey",
            secret_key="testsecret",
            bucket_name="test-bucket"
        )
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("Test content")
            temp_file = f.name
        
        # Upload file
        url = minio_client.upload_file(temp_file, "test-file.txt")
        
        assert url == "https://example.com/file.txt"
        mock_client.upload_file.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])