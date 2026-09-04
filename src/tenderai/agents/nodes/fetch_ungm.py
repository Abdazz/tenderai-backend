"""Fetch and parse listings from UNGM (United Nations Global Marketplace).

UNGM aggregates procurement notices from 40+ UN agencies (UNDP, UNICEF, WHO, WFP, etc.)
The public search endpoint accepts POST requests with country filters.
"""

import re

import httpx
from selectolax.parser import HTMLParser

from ...logging import get_logger

logger = get_logger(__name__)

UNGM_SEARCH_URL = "https://www.ungm.org/Public/Notice/Search"
UNGM_NOTICE_URL = "https://www.ungm.org/Public/Notice/{notice_id}"

# Country IDs in UNGM's referential
COUNTRY_BURKINA_FASO = 2324


async def fetch_ungm_listings(
    country_ids: list[int], page_size: int = 50, max_pages: int = 10
) -> list[dict]:
    """Call UNGM's public search endpoint and return parsed notices.

    The endpoint caps results at ~15 rows/page regardless of PageSize, so a
    single request only ever returns a fraction of the active notices —
    loop PageIndex until a page comes back empty (end of results) or
    max_pages is hit, whichever happens first.
    """
    all_items: list[dict] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0), follow_redirects=True
    ) as client:
        for page_index in range(max_pages):
            payload = {
                "PageIndex": page_index,
                "PageSize": page_size,
                "Title": "",
                "Description": "",
                "Reference": "",
                "PublishedFrom": "",
                "PublishedTo": "",
                "DeadlineFrom": "",
                "DeadlineTo": "",
                "Countries": country_ids,
                "Agencies": [],
                "UNSPSCs": [],
                "NoticeTypes": [],
                "SortField": "DatePublished",
                "SortAscending": False,
                "isPicker": False,
                "NoticeTypeIds": [],
                "NoticeStatuses": [],
            }
            resp = await client.post(
                UNGM_SEARCH_URL,
                json=payload,
                headers={
                    "Accept": "text/html, */*; q=0.01",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": "https://www.ungm.org/Public/Notice",
                },
            )
            resp.raise_for_status()
            page_items = extract_ungm_listings(resp.text)
            if not page_items:
                break
            all_items.extend(page_items)

    return all_items


def extract_ungm_listings(html_content: str) -> list[dict]:
    """Parse the HTML rows returned by /Public/Notice/Search into structured items."""
    items: list[dict] = []
    parser = HTMLParser(html_content)

    rows = parser.css("div.tableRow.dataRow")
    logger.info(f"UNGM: found {len(rows)} notice rows")

    def _cell_text(row, selector: str, fallback_index: int = -1) -> str:
        """Pick cell text by class name, fall back to positional access."""
        cell = row.css_first(selector)
        if cell is None and fallback_index >= 0:
            cells = row.css("div.tableCell")
            if fallback_index < len(cells):
                cell = cells[fallback_index]
        if cell is None:
            return ""
        text = cell.text(strip=True)
        # Strip trailing relevance score (a float number) from deadline cells
        text = re.sub(r"\d+\.\d{6,}\s*$", "", text)
        return re.sub(r"\s+", " ", text).strip()

    for row in rows:
        notice_id = row.attributes.get("data-noticeid", "").strip()
        if not notice_id:
            continue

        cells = row.css("div.tableCell")
        if len(cells) < 7:
            continue

        # Cell layout: [0]=actions, [1]=title, [2]=deadline,
        # [3]=posted, [4]=agency, [5]=notice type, [6]=reference, [7]=country
        title_cell = row.css_first("div.resultTitle")
        title = ""
        if title_cell is not None:
            title_span = title_cell.css_first("span.ungm-title")
            if title_span:
                title = title_span.text(strip=True)
        if not title and len(cells) > 1:
            title = cells[1].text(strip=True)
        title = re.sub(r"\s*Open in a new window\s*$", "", title)
        title = re.sub(r"\s+", " ", title).strip()
        deadline_raw = _cell_text(row, "div.resultInfo1.deadline", 2)
        posted_raw = cells[3].text(strip=True) if len(cells) > 3 else ""
        agency = _cell_text(row, "div.resultAgency", 4)
        notice_type = cells[5].text(strip=True) if len(cells) > 5 else ""
        reference = cells[6].text(strip=True) if len(cells) > 6 else ""
        country = cells[7].text(strip=True) if len(cells) > 7 else ""

        # Deadline cell sometimes contains "DD-Mon-YYYY HH:MM (GMT ...)" → keep date part only
        deadline_raw = re.sub(r"\s+", " ", deadline_raw).strip()
        m = re.match(r"(\d{2}-[A-Za-z]{3}-\d{4})", deadline_raw)
        deadline = m.group(1) if m else deadline_raw[:11]
        posted = re.sub(r"\s+", " ", posted_raw).strip()

        item = {
            "url": UNGM_NOTICE_URL.format(notice_id=notice_id),
            "notice_id": notice_id,
            "title": title,
            "tender_object": title,
            "reference": reference or notice_id,
            "entity": agency or "UN Agency",
            "deadline": _normalize_ungm_date(deadline),
            "published_at": _normalize_ungm_date(posted),
            "location": country,
            "description": f"{title}. Agence: {agency}. Type: {notice_type}. Référence: {reference}. Destination: {country}.",
            "category": "Autre",
            "type": "appel_offres",
            "source": "ungm",
        }
        items.append(item)

    return items


def _normalize_ungm_date(raw: str) -> str:
    """Convert UNGM date strings like '22-May-2026 23:59' into 'DD-MM-YYYY'."""
    if not raw:
        return ""
    # Match DD-Mon-YYYY pattern
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", raw.strip())
    if not m:
        return raw[:10]
    day, mon, year = m.groups()
    months = {
        "Jan": "01",
        "Feb": "02",
        "Mar": "03",
        "Apr": "04",
        "May": "05",
        "Jun": "06",
        "Jul": "07",
        "Aug": "08",
        "Sep": "09",
        "Oct": "10",
        "Nov": "11",
        "Dec": "12",
    }
    return f"{day}-{months.get(mon, mon)}-{year}"
