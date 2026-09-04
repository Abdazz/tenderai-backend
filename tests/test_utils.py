"""Unit tests for utility functions."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tenderai.utils.dates import (
    format_french_date,
    get_burkina_faso_now,
    is_deadline_urgent,
    parse_deadline,
    parse_flexible_date,
    parse_french_date,
)
from tenderai.utils.robots import (
    RobotsChecker,
    get_default_user_agent,
    validate_user_agent,
)


class TestDateUtils:
    """Test date utility functions."""

    def test_parse_french_date_formats(self):
        """Test parsing various French date formats."""

        # DD/MM/YYYY format
        date = parse_french_date("15/12/2024")
        assert date.day == 15
        assert date.month == 12
        assert date.year == 2024

        # DD-MM-YYYY format
        date = parse_french_date("25-01-2025")
        assert date.day == 25
        assert date.month == 1
        assert date.year == 2025

        # DD.MM.YYYY format
        date = parse_french_date("05.06.2024")
        assert date.day == 5
        assert date.month == 6
        assert date.year == 2024

        # French month names
        date = parse_french_date("31 décembre 2024")
        assert date.day == 31
        assert date.month == 12
        assert date.year == 2024

    def test_parse_french_date_invalid(self):
        """Test parsing invalid dates."""

        assert parse_french_date("") is None
        assert parse_french_date("invalid") is None
        assert parse_french_date("32/13/2024") is None
        assert parse_french_date(None) is None

    def test_parse_deadline_relative(self):
        """Test parsing relative deadlines."""

        ref_date = datetime(2024, 1, 15, 12, 0, 0)

        # "dans X jours"
        deadline = parse_deadline("dans 5 jours", ref_date)
        assert deadline.day == 20
        assert deadline.month == 1

        # "dans X semaines"
        deadline = parse_deadline("dans 2 semaines", ref_date)
        assert deadline.day == 29
        assert deadline.month == 1

    def test_format_french_date(self):
        """Test formatting dates in French."""

        date = datetime(2024, 12, 25, 10, 30, 0)
        formatted = format_french_date(date)

        assert "25" in formatted
        assert "décembre" in formatted
        assert "2024" in formatted

    def test_is_deadline_urgent(self):
        """Test deadline urgency detection."""

        now = get_burkina_faso_now()

        # Deadline in 3 days (urgent)
        urgent_deadline = now + timedelta(days=3)
        assert is_deadline_urgent(urgent_deadline, urgency_days=7) is True

        # Deadline in 10 days (not urgent)
        normal_deadline = now + timedelta(days=10)
        assert is_deadline_urgent(normal_deadline, urgency_days=7) is False

    def test_parse_flexible_date_day_first_never_swapped(self):
        """UNGM-style DD-MM-YYYY must stay day-first — this is the finding #11
        regression: Postgres's own datestyle would silently swap day<->month
        for day <= 12 if a raw string like this reached the DB unparsed."""
        date = parse_flexible_date("29-09-2026")
        assert (date.day, date.month, date.year) == (29, 9, 2026)

        date = parse_flexible_date("05-11-2026")
        assert (date.day, date.month, date.year) == (5, 11, 2026)

    def test_parse_flexible_date_formats(self):
        assert parse_flexible_date("2026-09-29").day == 29
        assert parse_flexible_date("29/09/2026").day == 29
        assert parse_flexible_date("29-Sep-2026").month == 9

    def test_parse_flexible_date_invalid_returns_none(self):
        assert parse_flexible_date("not a date") is None
        assert parse_flexible_date("") is None
        assert parse_flexible_date(None) is None


class TestRobotsUtils:
    """Test robots.txt utility functions."""

    def test_validate_user_agent(self):
        """Test user agent validation."""

        # Valid user agents
        assert validate_user_agent("TenderAI-BF/1.0") is True
        assert validate_user_agent("Mozilla/5.0") is True
        assert validate_user_agent("Bot/1.0 (compatible)") is True

        # Invalid user agents
        assert validate_user_agent("") is False
        assert validate_user_agent("   ") is False
        assert validate_user_agent(None) is False

    def test_get_default_user_agent(self):
        """Test default user agent generation."""

        user_agent = get_default_user_agent()

        assert "TenderAI-BF" in user_agent
        assert "/" in user_agent  # Should have version
        assert validate_user_agent(user_agent) is True

    @patch("urllib.robotparser.RobotFileParser")
    def test_robots_checker_can_fetch(self, mock_parser_class):
        """Test robots.txt checking."""

        # Mock parser
        mock_parser = MagicMock()
        mock_parser.can_fetch.return_value = True
        mock_parser_class.return_value = mock_parser

        checker = RobotsChecker()

        # Test URL checking
        can_fetch = checker.can_fetch("https://example.com/page")

        assert can_fetch is True
        mock_parser.can_fetch.assert_called_once()

    @patch("urllib.robotparser.RobotFileParser")
    def test_robots_checker_crawl_delay(self, mock_parser_class):
        """Test crawl delay retrieval."""

        # Mock parser
        mock_parser = MagicMock()
        mock_parser.crawl_delay.return_value = 2.0
        mock_parser_class.return_value = mock_parser

        checker = RobotsChecker()

        # Test crawl delay
        delay = checker.get_crawl_delay("https://example.com")

        assert delay == 2.0
        mock_parser.crawl_delay.assert_called_once()


class TestPDFUtils:
    """Test PDF utility functions."""

    def test_pdf_file_detection(self):
        """Test PDF file detection."""

        from tenderai.utils.pdf import is_pdf_file

        # Test file extension
        assert is_pdf_file("document.pdf") is False  # File doesn't exist
        assert is_pdf_file("document.txt") is False
        assert is_pdf_file("") is False

    def test_clean_extracted_text(self):
        """Test text cleaning."""

        from tenderai.utils.pdf import clean_extracted_text

        # Test text cleaning
        dirty_text = (
            "   Text  with    multiple   spaces   \n\n\n\nAnd newlines\n\n\n   "
        )
        clean_text = clean_extracted_text(dirty_text)

        assert "  " not in clean_text  # No double spaces
        assert clean_text.strip() == clean_text  # No leading/trailing whitespace
        assert "\n\n\n" not in clean_text  # No triple newlines


def test_tavily_settings_defaults():
    from tenderai.config import settings

    assert hasattr(settings, "tavily")
    assert settings.tavily.max_results == 10
    assert settings.tavily.search_depth == "basic"


def test_tavily_settings_api_key_from_env(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
    from tenderai.config import TavilySettings

    s = TavilySettings()
    assert s.api_key.get_secret_value() == "tvly-test-key"


if __name__ == "__main__":
    pytest.main([__file__])
