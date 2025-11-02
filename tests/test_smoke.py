"""Smoke tests for TenderAI BF."""

import os
import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(src_path))


def test_imports():
    """Test that all main modules can be imported."""
    
    # Core modules
    from tenderai_bf import config
    from tenderai_bf import logging
    from tenderai_bf import db
    from tenderai_bf import models
    from tenderai_bf import schemas
    
    # Agent modules
    from tenderai_bf.agents import graph
    from tenderai_bf.agents.nodes import load_sources
    from tenderai_bf.agents.nodes import fetch_listings
    
    # Storage and email
    from tenderai_bf import storage
    from tenderai_bf import email
    
    # Report and UI
    from tenderai_bf import report
    from tenderai_bf import ui
    
    # Utils
    from tenderai_bf import utils
    from tenderai_bf.utils import dates
    from tenderai_bf.utils import pdf
    from tenderai_bf.utils import robots
    
    # CLI and scheduler
    from tenderai_bf import cli
    from tenderai_bf import scheduler
    
    assert True  # If we get here, all imports succeeded


def test_settings_loading():
    """Test that settings can be loaded."""
    
    from tenderai_bf.config import settings
    
    # Basic settings should be available
    assert hasattr(settings, 'app_name')
    assert hasattr(settings, 'app_version')
    assert hasattr(settings, 'environment')
    assert hasattr(settings, 'debug')
    
    # Should have database settings
    assert hasattr(settings, 'database_url')
    
    # Should have nested settings
    assert hasattr(settings, 'email')
    assert hasattr(settings, 'storage')
    assert hasattr(settings, 'pipeline')


def test_logging_setup():
    """Test that logging can be set up."""
    
    from tenderai_bf.logging import get_logger, setup_logging
    
    # Setup logging
    setup_logging()
    
    # Get logger
    logger = get_logger(__name__)
    
    # Should be able to log
    logger.info("Test log message")
    
    assert logger is not None


def test_database_models():
    """Test that database models are defined."""
    
    from tenderai_bf import models
    
    # Check main models exist
    assert hasattr(models, 'Source')
    assert hasattr(models, 'Run')
    assert hasattr(models, 'Notice')
    assert hasattr(models, 'NoticeURL')
    assert hasattr(models, 'File')
    assert hasattr(models, 'Recipient')
    
    # Check models have expected attributes
    assert hasattr(models.Notice, 'title')
    assert hasattr(models.Notice, 'description')
    assert hasattr(models.Notice, 'url')
    assert hasattr(models.Notice, 'deadline')


def test_schemas():
    """Test that Pydantic schemas are defined."""
    
    from tenderai_bf import schemas
    
    # Check main schemas exist
    assert hasattr(schemas, 'NoticeCreate')
    assert hasattr(schemas, 'NoticeResponse')
    assert hasattr(schemas, 'RunCreate')
    assert hasattr(schemas, 'RunResponse')


def test_pipeline_graph():
    """Test that pipeline graph can be created."""
    
    from tenderai_bf.agents.graph import create_pipeline_graph, TenderAIState
    
    # Create graph
    graph = create_pipeline_graph()
    
    assert graph is not None
    
    # Test state schema
    state = TenderAIState(
        run_id="test-run",
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
    
    assert state.run_id == "test-run"
    assert state.sources == []


def test_utility_functions():
    """Test that utility functions work."""
    
    from tenderai_bf.utils.dates import get_burkina_faso_now, parse_french_date
    from tenderai_bf.utils.robots import get_default_user_agent, validate_user_agent
    
    # Date utilities
    now = get_burkina_faso_now()
    assert now is not None
    
    date = parse_french_date("15/12/2024")
    assert date is not None
    assert date.day == 15
    assert date.month == 12
    assert date.year == 2024
    
    # Robots utilities
    user_agent = get_default_user_agent()
    assert "TenderAI-BF" in user_agent
    
    assert validate_user_agent("TenderAI-BF/1.0") is True
    assert validate_user_agent("") is False


def test_cli_commands():
    """Test that CLI commands are defined."""
    
    from tenderai_bf.cli import cli, run_once, health_check
    
    # Check CLI is defined
    assert cli is not None
    
    # Check commands exist
    assert run_once is not None
    assert health_check is not None


def test_file_structure():
    """Test that expected files exist."""
    
    project_root = Path(__file__).parent.parent
    
    # Core files
    assert (project_root / "README.md").exists()
    assert (project_root / "pyproject.toml").exists()
    assert (project_root / "docker-compose.yml").exists()
    assert (project_root / ".gitignore").exists()
    
    # Source structure
    src_dir = project_root / "src" / "tenderai_bf"
    assert src_dir.exists()
    assert (src_dir / "__init__.py").exists()
    assert (src_dir / "config.py").exists()
    assert (src_dir / "models.py").exists()
    
    # Agent nodes
    agents_dir = src_dir / "agents" / "nodes"
    assert agents_dir.exists()
    assert (agents_dir / "load_sources.py").exists()
    assert (agents_dir / "fetch_listings.py").exists()
    
    # Utilities
    utils_dir = src_dir / "utils"
    assert utils_dir.exists()
    assert (utils_dir / "dates.py").exists()
    assert (utils_dir / "pdf.py").exists()
    assert (utils_dir / "robots.py").exists()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__])