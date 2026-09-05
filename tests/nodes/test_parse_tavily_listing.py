"""Tests for detail-page deadline enrichment in parse_tavily_listing (constat #21).

Palladium's listing page lists titles only; the deadline ("Closing date: ...")
only appears on each tender's individual detail page. When the listing
extraction doesn't find a deadline but did find a distinct detail URL, the
node should fetch that page and try to recover one.
"""
from unittest.mock import MagicMock, patch

from tenderai.agents.nodes.parse_tavily_listing import (
    _DEADLINE_LABEL_RE,
    _fetch_detail_deadline,
)


def _mock_response(html: str):
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


def test_deadline_label_regex_matches_palladium_style():
    text = "Details Moldova Closing date: 12 August 2026 Download Document"
    match = _DEADLINE_LABEL_RE.search(text)
    assert match and match.group(1).strip() == "12 August 2026"


def test_fetch_detail_deadline_recovers_and_normalizes_date():
    html = "<html><body><p>Closing date: 12 August 2026</p></body></html>"
    with patch("httpx.get", return_value=_mock_response(html)):
        result = _fetch_detail_deadline(
            "https://thepalladiumgroup.com/tender/foo", "Palladium", "run-1"
        )
    assert result == "2026-08-12"


def test_fetch_detail_deadline_returns_none_when_absent():
    html = "<html><body><p>No dates here.</p></body></html>"
    with patch("httpx.get", return_value=_mock_response(html)):
        result = _fetch_detail_deadline(
            "https://thepalladiumgroup.com/tender/foo", "Palladium", "run-1"
        )
    assert result is None


def test_fetch_detail_deadline_never_raises_on_network_error():
    with patch("httpx.get", side_effect=ConnectionError("boom")):
        result = _fetch_detail_deadline(
            "https://thepalladiumgroup.com/tender/foo", "Palladium", "run-1"
        )
    assert result is None
