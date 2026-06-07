"""Fetcher for Le Devoir public notices (avis publics).

Le Devoir publishes legal notices including procurement notices as scanned
newspaper page images.  The listing page embeds image URLs in data-src
attributes (not in JavaScript) — making them extractable without a headless
browser.

Strategy:
1. Fetch the HTML listing page directly (not via Tavily, which only sees nav).
2. Parse data-src attributes to collect image URLs for recent editions.
3. Download each image (JPEG).
4. Send each image to the Groq vision LLM (llama-4-scout) for OCR + extraction.
5. Return structured notice dicts compatible with parse_tavily_listing output.
"""

import base64
import re
from datetime import datetime, timedelta, timezone

import httpx

from ...config import settings
from ...logging import get_logger

logger = get_logger(__name__)

_LISTING_URL = "https://www.ledevoir.com/services-et-annonces/avis-publics"
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8",
}

_OCR_PROMPT = """\
Ce scan est une page de journal contenant des avis légaux et appels d'offres publiés au Québec.

Extrais TOUS les appels d'offres et avis de marchés publics que tu vois sur cette image.
Pour chaque appel d'offres trouvé, retourne un objet JSON avec :
- "title": intitulé de l'appel d'offres
- "entity": organisme qui publie l'appel d'offres
- "reference": numéro de référence si présent
- "deadline": date limite de soumission (format YYYY-MM-DD si possible)
- "description": description courte de l'objet du marché (2-3 phrases)
- "is_relevant": true si l'appel d'offres concerne l'informatique, les services numériques, le matériel informatique ou le conseil IT ; false sinon

Retourne UNIQUEMENT un JSON valide de la forme :
{"tenders": [...]}

Si tu ne vois aucun appel d'offres ou avis de marché public sur cette image, retourne {"tenders": []}.\
"""


def _extract_image_urls(html: str, max_days: int = 7) -> list[str]:
    """Parse data-src attributes for recent avis image URLs."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_days)
    urls: list[str] = []
    seen: set[str] = set()

    for url in re.findall(r'data-src="([^"]+/avis/[^"]+\.jpg[^"]*)"', html):
        # Strip query params for dedup key
        base = url.split("?")[0]
        if base in seen:
            continue
        seen.add(base)

        # Try to extract date from URL path (YYYY-MM-DD pattern)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", base)
        if m:
            try:
                img_date = datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                if img_date < cutoff:
                    continue
            except ValueError:
                pass

        urls.append(url)

    logger.info(f"Found {len(urls)} recent avis image URLs (last {max_days} days)")
    return urls


def _image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


async def _ocr_image_with_groq(
    image_bytes: bytes, image_url: str, run_id: str
) -> list[dict]:
    """Send image to Groq vision LLM and extract tender notices."""
    import json

    api_key = settings.llm.groq_api_key.get_secret_value()
    if not api_key:
        logger.error("GROQ_API_KEY not set — cannot do OCR", run_id=run_id)
        return []

    # Use llama-4-scout which supports vision
    vision_model = "meta-llama/llama-4-scout-17b-16e-instruct"

    b64 = _image_to_base64(image_bytes)
    payload = {
        "model": vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {"type": "text", "text": _OCR_PROMPT},
                ],
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.0,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"].strip()

        # Parse JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            data = json.loads(m.group()) if m else {}

        tenders = data.get("tenders", [])
        logger.info(
            f"OCR extracted {len(tenders)} notices from image",
            url=image_url,
            run_id=run_id,
        )
        return tenders

    except Exception as e:
        logger.error(
            "Groq vision OCR failed", url=image_url, error=str(e), run_id=run_id
        )
        return []


async def fetch_ledevoir(source: dict, run_id: str) -> dict:
    """Fetch Le Devoir avis publics by downloading and OCR-ing scanned images."""
    source_name = source["name"]
    patterns = source.get("patterns", {})
    max_days = int(patterns.get("max_days", 7))

    try:
        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(_LISTING_URL)
            resp.raise_for_status()
            html = resp.text

        image_urls = _extract_image_urls(html, max_days=max_days)
        if not image_urls:
            logger.warning(
                "No recent avis images found on Le Devoir", run_id=run_id
            )
            return {
                "source": source,
                "content": "[]",
                "listings": [],
                "url": _LISTING_URL,
                "status": "success",
                "parser_type": "ledevoir",
                "fetched_at": datetime.utcnow().isoformat(),
            }

        all_notices: list[dict] = []
        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS,
            timeout=httpx.Timeout(60.0),
        ) as client:
            for img_url in image_urls:
                try:
                    img_resp = await client.get(img_url)
                    img_resp.raise_for_status()
                    img_bytes = img_resp.content
                    logger.info(
                        "Le Devoir image downloaded",
                        url=img_url,
                        size_kb=round(len(img_bytes) / 1024),
                        run_id=run_id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to download Le Devoir image",
                        url=img_url,
                        error=str(e),
                        run_id=run_id,
                    )
                    continue

                notices = await _ocr_image_with_groq(img_bytes, img_url, run_id)
                for n in notices:
                    n["source_image_url"] = img_url
                all_notices.extend(notices)

        logger.info(
            "Le Devoir fetch complete",
            source=source_name,
            images=len(image_urls),
            total_notices=len(all_notices),
            run_id=run_id,
        )

        # Return in the same format as tavily_extract listings
        import json
        normalized = [
            {
                "url": n.get("source_image_url", _LISTING_URL),
                "content": n.get("description", ""),
                "title": n.get("title", ""),
                "entity": n.get("entity", ""),
                "reference": n.get("reference", ""),
                "deadline": n.get("deadline"),
                "is_relevant": n.get("is_relevant", False),
                "score": None,
                "source": "ledevoir",
            }
            for n in all_notices
        ]

        return {
            "source": source,
            "content": json.dumps(normalized, ensure_ascii=False),
            "listings": normalized,
            "url": _LISTING_URL,
            "status": "success",
            "parser_type": "ledevoir",
            "fetched_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(
            "Le Devoir fetch failed", source=source_name, error=str(e), run_id=run_id
        )
        return {
            "source": source,
            "content": "[]",
            "listings": [],
            "url": _LISTING_URL,
            "status": "failed",
            "error": str(e),
            "parser_type": "ledevoir",
            "fetched_at": datetime.utcnow().isoformat(),
        }
