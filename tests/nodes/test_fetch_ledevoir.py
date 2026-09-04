"""constat #25 regression: an avis image with no date in its filename must
be excluded by max_days, not bypass the window entirely and get reprocessed
on every run forever."""

import os
import sys

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")
sys.path.insert(0, "src")

from tenderai.agents.nodes.fetch_ledevoir import _extract_image_urls  # noqa: E402


def test_dateless_image_excluded():
    html = """
    <img data-src="https://ledevoir.com/avis/70380.jpg" />
    """
    urls = _extract_image_urls(html, max_days=7)
    assert urls == []


def test_dated_recent_image_included():
    from datetime import UTC, datetime, timedelta

    recent = (datetime.now(tz=UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    html = f"""
    <img data-src="https://ledevoir.com/avis/{recent}-12345.jpg" />
    """
    urls = _extract_image_urls(html, max_days=7)
    assert len(urls) == 1


def test_dated_old_image_excluded():
    html = """
    <img data-src="https://ledevoir.com/avis/2020-01-01-99999.jpg" />
    """
    urls = _extract_image_urls(html, max_days=7)
    assert urls == []
