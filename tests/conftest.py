"""Test configuration and fixtures."""

import os
import pytest
from unittest.mock import MagicMock

# Set test environment
os.environ['TENDERAI_ENVIRONMENT'] = 'test'
os.environ['TENDERAI_DATABASE_URL'] = 'sqlite:///test.db'
os.environ['TENDERAI_DEBUG'] = 'true'


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    from unittest.mock import MagicMock
    
    settings = MagicMock()
    settings.environment = 'test'
    settings.debug = True
    settings.database_url = 'sqlite:///test.db'
    
    # Email settings
    settings.email.smtp_server = 'localhost'
    settings.email.smtp_port = 587
    settings.email.smtp_username = 'test@example.com'
    settings.email.smtp_password = 'password'
    settings.email.from_address = 'test@example.com'
    settings.email.to_address = 'recipient@example.com'
    
    # Storage settings
    settings.storage.endpoint_url = 'http://localhost:9000'
    settings.storage.access_key = 'minioadmin'
    settings.storage.secret_key = 'minioadmin'
    settings.storage.bucket_name = 'test-bucket'
    
    # Pipeline settings
    settings.pipeline.max_items_per_source = 10
    settings.pipeline.max_total_items = 50
    
    return settings


@pytest.fixture
def mock_database():
    """Mock database for testing."""
    from unittest.mock import MagicMock
    
    db = MagicMock()
    db.health_check.return_value = True
    return db


@pytest.fixture
def mock_storage():
    """Mock storage client for testing."""
    from unittest.mock import MagicMock
    
    storage = MagicMock()
    storage.health_check.return_value = True
    storage.upload_file.return_value = 'http://localhost:9000/test-bucket/test-file.txt'
    return storage


@pytest.fixture
def sample_notice_data():
    """Sample notice data for testing."""
    return {
        'title': 'Test RFP Notice',
        'description': 'This is a test RFP for software development services.',
        'url': 'https://example.com/rfp/123',
        'deadline': '2024-12-31T23:59:59+00:00',
        'organization': 'Test Ministry',
        'category': 'IT Services',
        'estimated_value': '500,000 FCFA',
        'location': 'Ouagadougou, Burkina Faso'
    }


@pytest.fixture
def sample_html_content():
    """Sample HTML content for testing."""
    return """
    <html>
    <head>
        <title>Test RFP Page</title>
    </head>
    <body>
        <div class="rfp-notice">
            <h2>Software Development Services RFP</h2>
            <p>Description: Development of web application for ministry</p>
            <p>Deadline: 31/12/2024</p>
            <p>Organization: Ministry of Digital Economy</p>
            <a href="/download/rfp-details.pdf">Download Details</a>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_pdf_content():
    """Sample PDF content (as bytes) for testing."""
    # Simple PDF header (minimal valid PDF)
    return b'%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n'