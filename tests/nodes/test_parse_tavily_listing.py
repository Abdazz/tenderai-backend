"""Tests for detail-page deadline enrichment in parse_tavily_listing (constat #21).

Palladium's listing page lists titles only; the deadline ("Closing date: ...")
only appears on each tender's individual detail page. When the listing
extraction doesn't find a deadline but did find a distinct detail URL, the
node should fetch that page and try to recover one.

tender_url comes from LLM-extracted page content, not admin-controlled DB
config, so _is_safe_detail_url must block it from becoming an SSRF vector
(arbitrary absolute URL, private/internal IP) before any fetch happens.
"""
from unittest.mock import MagicMock, patch

from tenderai.agents.nodes.parse_tavily_listing import (
    _DEADLINE_LABEL_RE,
    _fetch_detail_deadline,
    _is_safe_detail_url,
)


def _mock_response(html: str):
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


def _mock_addrinfo(ip: str):
    return [(None, None, None, None, (ip, 0))]


def test_deadline_label_regex_matches_palladium_style():
    text = "Details Moldova Closing date: 12 August 2026 Download Document"
    match = _DEADLINE_LABEL_RE.search(text)
    assert match and match.group(1).strip() == "12 August 2026"


def test_safe_detail_url_accepts_same_host_public_ip():
    with patch("socket.getaddrinfo", return_value=_mock_addrinfo("93.184.216.34")):
        assert _is_safe_detail_url("https://example.com/tender/foo", "example.com")


def test_safe_detail_url_rejects_different_host():
    """The SSRF case: LLM-extracted tender_url points at an absolute URL on
    a different host than the configured source — must not be fetched."""
    with patch("socket.getaddrinfo", return_value=_mock_addrinfo("93.184.216.34")):
        assert not _is_safe_detail_url(
            "https://attacker.example/steal", "thepalladiumgroup.com"
        )


def test_safe_detail_url_rejects_private_ip():
    """Same host resolving to a private/internal address (e.g. via DNS
    rebinding, or a source that happens to be internally hosted) is blocked."""
    with patch("socket.getaddrinfo", return_value=_mock_addrinfo("10.0.0.5")):
        assert not _is_safe_detail_url("https://internal.example/x", "internal.example")


def test_safe_detail_url_rejects_loopback_and_link_local():
    with patch("socket.getaddrinfo", return_value=_mock_addrinfo("127.0.0.1")):
        assert not _is_safe_detail_url("https://x.example/y", "x.example")
    with patch("socket.getaddrinfo", return_value=_mock_addrinfo("169.254.169.254")):
        assert not _is_safe_detail_url("https://x.example/y", "x.example")


def test_safe_detail_url_rejects_non_http_scheme():
    assert not _is_safe_detail_url("file:///etc/passwd", "x.example")


def test_fetch_detail_deadline_recovers_and_normalizes_date():
    html = "<html><body><p>Closing date: 12 August 2026</p></body></html>"
    with (
        patch(
            "tenderai.agents.nodes.parse_tavily_listing._is_safe_detail_url",
            return_value=True,
        ),
        patch("httpx.get", return_value=_mock_response(html)),
    ):
        result = _fetch_detail_deadline(
            "https://thepalladiumgroup.com/tender/foo",
            "thepalladiumgroup.com",
            "Palladium",
            "run-1",
        )
    assert result == "2026-08-12"


def test_fetch_detail_deadline_returns_none_when_absent():
    html = "<html><body><p>No dates here.</p></body></html>"
    with (
        patch(
            "tenderai.agents.nodes.parse_tavily_listing._is_safe_detail_url",
            return_value=True,
        ),
        patch("httpx.get", return_value=_mock_response(html)),
    ):
        result = _fetch_detail_deadline(
            "https://thepalladiumgroup.com/tender/foo",
            "thepalladiumgroup.com",
            "Palladium",
            "run-1",
        )
    assert result is None


def test_fetch_detail_deadline_never_raises_on_network_error():
    with (
        patch(
            "tenderai.agents.nodes.parse_tavily_listing._is_safe_detail_url",
            return_value=True,
        ),
        patch("httpx.get", side_effect=ConnectionError("boom")),
    ):
        result = _fetch_detail_deadline(
            "https://thepalladiumgroup.com/tender/foo",
            "thepalladiumgroup.com",
            "Palladium",
            "run-1",
        )
    assert result is None


def test_fetch_detail_deadline_skips_unsafe_url_without_fetching():
    with (
        patch(
            "tenderai.agents.nodes.parse_tavily_listing._is_safe_detail_url",
            return_value=False,
        ),
        patch("httpx.get") as mock_get,
    ):
        result = _fetch_detail_deadline(
            "https://attacker.example/steal",
            "thepalladiumgroup.com",
            "Palladium",
            "run-1",
        )
    assert result is None
    mock_get.assert_not_called()
