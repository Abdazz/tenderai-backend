"""Tests for fetch_ungm's PageIndex loop — HTTP calls always mocked."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")
sys.path.insert(0, "src")


def _row_html(notice_id: str) -> str:
    return f"""
<div class="tableRow dataRow" data-noticeid="{notice_id}">
  <div class="tableCell"></div>
  <div class="tableCell">Title {notice_id}</div>
  <div class="tableCell">01-Jan-2027</div>
  <div class="tableCell">01-Dec-2026</div>
  <div class="tableCell">Agency</div>
  <div class="tableCell">RFP</div>
  <div class="tableCell">REF-{notice_id}</div>
</div>
"""


def _page_html(*notice_ids: str) -> str:
    rows = "".join(_row_html(nid) for nid in notice_ids)
    return f"<html><body>{rows}</body></html>"


def _make_mock_response(html: str):
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


def _run(coro):
    return asyncio.run(coro)


def test_fetch_ungm_accumulates_until_empty_page():
    """constat #7: PageIndex must loop, accumulating pages, and stop once a
    page comes back with zero rows — not just fetch PageIndex=0 forever."""
    from tenderai.agents.nodes.fetch_ungm import fetch_ungm_listings

    responses = [
        _make_mock_response(_page_html("1", "2")),
        _make_mock_response(_page_html("3", "4")),
        _make_mock_response(_page_html()),  # empty — end of results
    ]
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=responses)

    with patch(
        "tenderai.agents.nodes.fetch_ungm.httpx.AsyncClient",
        return_value=mock_client,
    ):
        items = _run(fetch_ungm_listings([2324], page_size=15, max_pages=10))

    assert mock_client.post.call_count == 3  # stopped after the empty page
    assert {i["notice_id"] for i in items} == {"1", "2", "3", "4"}
    # PageIndex must actually increment across calls
    page_indexes = [call.kwargs["json"]["PageIndex"] for call in mock_client.post.call_args_list]
    assert page_indexes == [0, 1, 2]


def test_fetch_ungm_stops_at_max_pages():
    """Never loops forever even if every page keeps returning rows."""
    from tenderai.agents.nodes.fetch_ungm import fetch_ungm_listings

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(
        return_value=_make_mock_response(_page_html("1"))
    )

    with patch(
        "tenderai.agents.nodes.fetch_ungm.httpx.AsyncClient",
        return_value=mock_client,
    ):
        items = _run(fetch_ungm_listings([2324], page_size=15, max_pages=3))

    assert mock_client.post.call_count == 3
    assert len(items) == 3
