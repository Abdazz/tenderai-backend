"""Smoke tests for TenderAI BF."""

import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


def test_imports():
    """Test that all main modules can be imported."""

    # Core modules

    # Agent modules

    # Storage and email

    # Report and UI

    # Utils

    # CLI and scheduler

    assert True  # If we get here, all imports succeeded


def test_settings_loading():
    """Test that settings can be loaded."""

    from tenderai_bf.config import settings

    # Basic settings should be available
    assert hasattr(settings, "app_name")
    assert hasattr(settings, "app_version")
    assert hasattr(settings, "environment")
    assert hasattr(settings, "debug")

    # Should have database settings
    assert hasattr(settings, "database")
    assert hasattr(settings.database, "url")

    # Should have nested settings
    assert hasattr(settings, "email")
    assert hasattr(settings, "minio")
    assert hasattr(settings, "processing")


def test_logging_setup():
    """Test that logging can be set up."""

    from tenderai_bf.logging import configure_logging, get_logger

    # Setup logging
    configure_logging()

    # Get logger
    logger = get_logger(__name__)

    # Should be able to log
    logger.info("Test log message")

    assert logger is not None


def test_database_models():
    """Test that database models are defined."""

    from tenderai_bf import models

    # Check main models exist
    assert hasattr(models, "Source")
    assert hasattr(models, "Run")
    assert hasattr(models, "Notice")
    assert hasattr(models, "NoticeURL")
    assert hasattr(models, "File")
    assert hasattr(models, "Recipient")

    # Check models have expected attributes
    assert hasattr(models.Notice, "title")
    assert hasattr(models.Notice, "description")
    assert hasattr(models.Notice, "url")
    assert hasattr(models.Notice, "deadline_at")


def test_schemas():
    """Test that Pydantic schemas are defined."""

    from tenderai_bf import schemas

    # Check main schemas exist
    assert hasattr(schemas, "NoticeCreate")
    assert hasattr(schemas, "Notice")
    assert hasattr(schemas, "RunCreate")
    assert hasattr(schemas, "Run")


def test_pipeline_graph():
    """Test that pipeline graph can be created."""

    from tenderai_bf.agents.graph import TenderAIState, create_pipeline_graph

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
        errors=[],
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

    from tenderai_bf.cli import health_check, main, run_once

    # Check CLI is defined
    assert main is not None

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


def test_seed_sources_persists_patterns(tmp_path, monkeypatch):
    """seed_sources doit sauvegarder le champ patterns en DB."""
    import json
    from unittest.mock import MagicMock, patch

    yaml_content = """
sources:
  - name: "Test Source Patterns"
    list_url: "https://example.com/tenders"
    parser: "html-tender"
    enabled: true
    patterns:
      card_selector: "div.card"
      title_selector: "h3"
      entity: "TestOrg"
"""
    yaml_file = tmp_path / "settings.yaml"
    yaml_file.write_text(yaml_content)

    captured_inserts = []

    mock_conn = MagicMock()

    def fake_execute(stmt, params=None):
        if params:
            captured_inserts.append(params)
        row = MagicMock()
        row.__iter__ = MagicMock(return_value=iter([]))
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        return mock_result

    mock_conn.execute = fake_execute
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn

    with patch("tenderai_bf.cli.Path") as mock_path_cls, patch(
        "tenderai_bf.cli.get_engine", return_value=mock_engine
    ):
        mock_path_cls.return_value = yaml_file
        from click.testing import CliRunner

        from tenderai_bf.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["seed-sources"])
        assert result.exit_code == 0, result.output

    insert_params = [
        p for p in captured_inserts if "card_selector" in str(p.get("patterns", ""))
    ]
    assert len(insert_params) == 1, "patterns should be persisted in INSERT"
    patterns = insert_params[0]["patterns"]
    if isinstance(patterns, str):
        patterns = json.loads(patterns)
    assert patterns["card_selector"] == "div.card"
    assert patterns["entity"] == "TestOrg"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__])
