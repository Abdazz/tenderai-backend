"""Config-driven HTML tender fetcher.

Tous les paramètres d'extraction sont lus depuis source["patterns"] :
  card_selector, title_selector, deadline_selector, deadline_attribute,
  deadline_text_prefix, pdf_selector, entity, location,
  ssl_verify, max_pages, pagination_url
"""

import re
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from ...logging import get_logger

logger = get_logger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def _txt(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.text(strip=True)).strip()


async def fetch_html_tender(source: dict, run_id: str) -> dict:
    """Fetch tender listings from a config-driven HTML source."""
    source_name = source["name"]
    list_url = source["list_url"]
    patterns = source.get("patterns") or {}

    ssl_verify = patterns.get("ssl_verify", True)
    max_pages = int(patterns.get("max_pages", 1))
    pagination_url = patterns.get("pagination_url")

    urls = [list_url]
    if max_pages > 1 and pagination_url:
        for page in range(2, max_pages + 1):
            urls.append(pagination_url.format(page=page))

    listings: list[dict] = []

    async with httpx.AsyncClient(
        verify=ssl_verify,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
        headers=_HEADERS,
    ) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                listings.extend(_extract_cards(resp.text, url, patterns, source_name))
            except Exception as e:
                logger.warning(
                    "html-tender page fetch failed",
                    url=url,
                    error=str(e),
                    run_id=run_id,
                )

    logger.info(
        "html-tender fetch complete",
        source=source_name,
        listings=len(listings),
        run_id=run_id,
    )

    return {
        "source": source,
        "content": None,
        "listings": listings,
        "url": list_url,
        "status": "success" if listings else "failed",
        "error": None if listings else "No listings extracted",
        "parser_type": "html-tender",
        "fetched_at": _now(),
    }


def _extract_cards(html: str, page_url: str, patterns: dict, source_name: str) -> list[dict]:
    """Extraire les blocs tender d'une page HTML selon les patterns configurés."""
    p = HTMLParser(html)

    card_sel = patterns.get("card_selector", "article")
    title_sel = patterns.get("title_selector", "h1,h2,h3,p")
    deadline_sel = patterns.get("deadline_selector", "time")
    deadline_attr = patterns.get("deadline_attribute")
    deadline_prefix = patterns.get("deadline_text_prefix")
    pdf_sel = patterns.get("pdf_selector")
    fixed_entity = patterns.get("entity", "")
    fixed_location = patterns.get("location", "")

    items = []
    for card in p.css(card_sel):
        # --- Titre ---
        title_node = card.css_first(title_sel)
        title = _txt(title_node)
        if not title:
            continue

        # --- Deadline ---
        deadline = ""
        if deadline_prefix:
            for node in card.css(deadline_sel):
                t = _txt(node)
                if deadline_prefix.lower() in t.lower():
                    parts = t.split(":", 1)
                    deadline = parts[1].strip() if len(parts) > 1 else t
                    break
        else:
            d_node = card.css_first(deadline_sel)
            if d_node:
                deadline = d_node.attributes.get(deadline_attr, "") if deadline_attr else _txt(d_node)

        # --- URL / PDF ---
        item_url = page_url
        if pdf_sel:
            pdf_node = card.css_first(pdf_sel)
            if pdf_node:
                href = pdf_node.attributes.get("href", "")
                if href:
                    item_url = urljoin(page_url, href)

        # --- Référence (extraite du titre si présente) ---
        ref_match = re.search(r"\b([A-Z]{2,}\d{4,}[-\d/]*)\b", title)
        reference = ref_match.group(1) if ref_match else ""

        items.append({
            "url": item_url,
            "title": title,
            "tender_object": title,
            "reference": reference,
            "ref_no": reference,
            "entity": fixed_entity,
            "location": fixed_location,
            "deadline": deadline,
            "description": title,
            "category": "Autre",
            "type": "appel_offres",
            "source": source_name,
            "parser_type": "html-tender",
        })

    return items


def _now() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat()
