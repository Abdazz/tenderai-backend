"""Tests for fetch_html_tender — HTTP calls always mocked."""

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

UEMOA_HTML = """
<html><body>
<div class="swiper-slide">
  <div class="news-box">
    <div class="new-txt">
      <p class="pb-2">Appel d'offres acquisition matériel informatique CUEMOA</p>
      <small><time datetime="2026-07-15T10:00:00Z">15/07/2026 - 10:00</time></small>
    </div>
    <div class="news-box-f">
      <a href="/sites/default/files/opportunite_affaire/AO_materiel_info.pdf">Télécharger</a>
    </div>
  </div>
</div>
<div class="swiper-slide">
  <div class="news-box">
    <div class="new-txt">
      <p class="pb-2">Fourniture véhicules SUV UEMOA</p>
      <small><time datetime="2026-08-01T10:00:00Z">01/08/2026 - 10:00</time></small>
    </div>
    <div class="news-box-f">
      <a href="/sites/default/files/opportunite_affaire/AO_vehicules.pdf">Télécharger</a>
    </div>
  </div>
</div>
</body></html>
"""

ENABEL_HTML = """
<html><body>
<div class="card--news card--tenders" data-open="false">
  <div class="news__botton">
    <p class="h5"><span>BFA23004-10487 &#8211; Fourniture d'équipements hydromécaniques ONEA Koupéla.</span></p>
    <p><strong>Pays : </strong> Burkina Faso</p>
    <p><strong>Date de clôture : </strong> 30 June 2026 12:00</p>
    <div class="hidden__card">
      <p><strong>Status :</strong> Ouvert</p>
    </div>
  </div>
</div>
</body></html>
"""

SOURCE_UEMOA = {
    "name": "UEMOA - Appels d'offres",
    "list_url": "https://www.uemoa.int/appel-d-offre",
    "parser_type": "html-tender",
    "patterns": {
        "ssl_verify": False,
        "card_selector": "div.swiper-slide div.news-box",
        "title_selector": "div.new-txt p",
        "deadline_selector": "time",
        "deadline_attribute": "datetime",
        "pdf_selector": "a[href*='opportunite_affaire']",
        "entity": "UEMOA",
        "location": "Zone UEMOA",
        "max_pages": 1,
    },
}

SOURCE_ENABEL = {
    "name": "Enabel - Marchés publics Burkina Faso",
    "list_url": "https://www.enabel.be/fr/marches-publics/?in_country=1726&is_status=0",
    "parser_type": "html-tender",
    "patterns": {
        "card_selector": "div.card--news.card--tenders",
        "title_selector": "p.h5 span",
        "deadline_selector": "p",
        "deadline_text_prefix": "Date de clôture",
        "entity": "Enabel",
        "location": "Burkina Faso",
        "max_pages": 1,
    },
}


def _make_mock_response(html: str, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


def _run(coro):
    return asyncio.run(coro)


def test_uemoa_extracts_two_items():
    """UEMOA source: extrait titre, deadline ISO et URL PDF pour chaque slide."""
    from tenderai_bf.agents.nodes.fetch_html_tender import fetch_html_tender

    mock_resp = _make_mock_response(UEMOA_HTML)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "tenderai_bf.agents.nodes.fetch_html_tender.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = _run(fetch_html_tender(SOURCE_UEMOA, "run-test"))

    assert result["status"] == "success"
    assert result["parser_type"] == "html-tender"
    listings = result["listings"]
    assert len(listings) == 2
    assert "matériel informatique" in listings[0]["title"]
    assert listings[0]["deadline"] == "2026-07-15T10:00:00Z"
    assert "AO_materiel_info.pdf" in listings[0]["url"]
    assert listings[0]["entity"] == "UEMOA"
    assert listings[0]["location"] == "Zone UEMOA"


def test_enabel_extracts_reference_and_deadline():
    """Enabel source: extrait référence depuis titre et deadline via deadline_text_prefix."""
    from tenderai_bf.agents.nodes.fetch_html_tender import fetch_html_tender

    mock_resp = _make_mock_response(ENABEL_HTML)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "tenderai_bf.agents.nodes.fetch_html_tender.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = _run(fetch_html_tender(SOURCE_ENABEL, "run-test"))

    assert result["status"] == "success"
    listings = result["listings"]
    assert len(listings) == 1
    assert "BFA23004-10487" in listings[0]["reference"]
    assert "30 June 2026" in listings[0]["deadline"]
    assert listings[0]["entity"] == "Enabel"


def test_ssl_verify_false_passed_to_client():
    """ssl_verify=false dans patterns doit être transmis au AsyncClient."""
    from tenderai_bf.agents.nodes.fetch_html_tender import fetch_html_tender

    mock_resp = _make_mock_response(UEMOA_HTML)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "tenderai_bf.agents.nodes.fetch_html_tender.httpx.AsyncClient",
        return_value=mock_client,
    ) as mock_cls:
        _run(fetch_html_tender(SOURCE_UEMOA, "run-test"))
        call_kwargs = mock_cls.call_args
        assert call_kwargs.kwargs.get("verify") is False


def test_empty_page_returns_failed():
    """Page sans cards → status failed."""
    from tenderai_bf.agents.nodes.fetch_html_tender import fetch_html_tender

    mock_resp = _make_mock_response("<html><body></body></html>")
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "tenderai_bf.agents.nodes.fetch_html_tender.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = _run(fetch_html_tender(SOURCE_UEMOA, "run-test"))

    assert result["status"] == "failed"
    assert result["listings"] == []


def test_pagination_fetches_multiple_pages():
    """max_pages=2 doit déclencher deux requêtes GET avec pagination_url."""
    from tenderai_bf.agents.nodes.fetch_html_tender import fetch_html_tender

    source = {
        "name": "Enabel - Test Pagination",
        "list_url": "https://www.enabel.be/fr/marches-publics/?in_country=1726&is_status=0",
        "parser_type": "html-tender",
        "patterns": {
            "card_selector": "div.card--news.card--tenders",
            "title_selector": "p.h5 span",
            "deadline_selector": "p",
            "deadline_text_prefix": "Date de clôture",
            "entity": "Enabel",
            "location": "Burkina Faso",
            "max_pages": 2,
            "pagination_url": "https://www.enabel.be/fr/marches-publics/page/{page}/?in_country=1726&is_status=0",
        },
    }

    mock_resp = _make_mock_response(ENABEL_HTML)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "tenderai_bf.agents.nodes.fetch_html_tender.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = _run(fetch_html_tender(source, "run-test"))

    # Should have fetched 2 pages
    assert mock_client.get.call_count == 2
    called_urls = [str(call.args[0]) for call in mock_client.get.call_args_list]
    assert any(
        "is_status=0" in u and "page" not in u for u in called_urls
    ), "page 1 URL should be the base URL"
    assert any(
        "page/2" in u for u in called_urls
    ), "page 2 URL should use pagination_url template"
    # Both pages return the same HTML so 2 listings total
    assert len(result["listings"]) == 2
