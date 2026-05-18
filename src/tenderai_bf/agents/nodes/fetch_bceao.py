"""Fetch and parse listings from BCEAO (Banque Centrale des États de l'Afrique de l'Ouest).

BCEAO publishes regional tenders covering all 8 UEMOA countries (incl. Burkina Faso).
The listing page is plain server-rendered HTML — no API, no JS rendering needed.
"""

import re
from typing import Dict, List

import httpx
from selectolax.parser import HTMLParser

from ...logging import get_logger

logger = get_logger(__name__)

BCEAO_LISTING_URL = "https://www.bceao.int/fr/appels-offres/appels-offres-marches-publics-achats"

_FR_MONTHS = {
    'janvier': '01', 'février': '02', 'mars': '03', 'avril': '04', 'mai': '05', 'juin': '06',
    'juillet': '07', 'août': '08', 'septembre': '09', 'octobre': '10', 'novembre': '11', 'décembre': '12',
}


async def fetch_bceao_listings(list_url: str = BCEAO_LISTING_URL) -> List[Dict]:
    """Download the BCEAO public tenders listing and parse it."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True) as client:
        resp = await client.get(
            list_url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr-FR,fr;q=0.9",
            },
        )
        resp.raise_for_status()
    return extract_bceao_listings(resp.text)


def extract_bceao_listings(html_content: str) -> List[Dict]:
    """Parse BCEAO listing HTML into structured tender items."""
    items: List[Dict] = []
    parser = HTMLParser(html_content)

    rows = parser.css('.views-row')
    logger.info(f"BCEAO: found {len(rows)} listing rows")

    for row in rows:
        link = row.css_first('a[href*="/appels-offres/"]')
        if link is None:
            continue
        href = link.attributes.get('href', '')
        if not href or href.endswith('/appels-offres-marches-publics-achats'):
            continue

        url = href if href.startswith('http') else f"https://www.bceao.int{href}"

        # Title is in <span class="ttr">
        title_el = row.css_first('span.ttr')
        title = title_el.text(strip=True) if title_el else ''
        title = re.sub(r'\s+-\s+Report$', '', title)

        # subTtr contains "REF Date limite le DATE"
        sub_el = row.css_first('span.subTtr')
        sub_text = sub_el.text(strip=True) if sub_el else ''
        deadline_match = re.search(r'Date\s+limite\s+le\s+(.+)$', sub_text, re.IGNORECASE)
        deadline_raw = deadline_match.group(1).strip() if deadline_match else ''
        reference = re.sub(r'\s*Date\s+limite.*$', '', sub_text, flags=re.IGNORECASE).strip()

        # Published date in infoFile
        info_el = row.css_first('span.infoFile')
        info_text = info_el.text(strip=True) if info_el else ''
        published_match = re.search(r'Publié\s+le\s+(.+)$', info_text, re.IGNORECASE)
        published_raw = published_match.group(1).strip() if published_match else ''

        items.append({
            'url': url,
            'title': title,
            'tender_object': title,
            'reference': reference or 'Inconnu',
            'entity': 'BCEAO',
            'category': 'Autre',
            'description': f"{title}. Référence: {reference}. Publié: {published_raw}. Émetteur: BCEAO (zone UEMOA).",
            'deadline': _normalize_fr_date(deadline_raw),
            'published_at': _normalize_fr_date(published_raw),
            'location': 'UEMOA',
            'type': 'appel_offres',
            'source': 'bceao',
        })

    return items


def _normalize_fr_date(raw: str) -> str:
    """Convert French date string '15 mai 2026' to 'DD-MM-YYYY'."""
    if not raw:
        return ''
    m = re.match(r'(\d{1,2})\s+([a-zéûô]+)\s+(\d{4})', raw.strip().lower())
    if not m:
        return raw[:30]
    day, mon_fr, year = m.groups()
    mon = _FR_MONTHS.get(mon_fr, mon_fr)
    return f"{int(day):02d}-{mon}-{year}"
