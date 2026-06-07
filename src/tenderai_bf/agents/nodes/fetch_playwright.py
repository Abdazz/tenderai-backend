"""Playwright-based fetcher for JavaScript-rendered listing pages.

Used when a procurement portal is a SPA (Single Page Application) or relies
on JavaScript to render its tender listings.  Playwright launches a headless
Chromium browser, executes the page JS, waits for the content to stabilise,
and returns the rendered HTML — which is then processed by parse_tavily_listing.

Source configuration (source.patterns):
    wait_for_selector  (str)  : CSS selector to wait for before capturing HTML.
                                Defaults to "body".
    wait_timeout_ms    (int)  : Max ms to wait for the selector. Default 15000.
    scroll_to_bottom   (bool) : If true, auto-scroll to trigger lazy-loading.
                                Default false.
    extra_wait_ms      (int)  : Additional wait after selector is found.
                                Useful for AJAX-heavy pages. Default 1000.
    block_media        (bool) : Block images/fonts to speed up loading.
                                Default true.
"""

from datetime import datetime

from ...logging import get_logger

logger = get_logger(__name__)


async def fetch_playwright(source: dict, run_id: str) -> dict:
    """Render a SPA listing page with Playwright and return its text content."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error(
            "Playwright not installed. Run: poetry install --extras full && "
            "poetry run playwright install chromium",
            run_id=run_id,
        )
        return _error(source, "playwright not installed")

    source_name = source["name"]
    url = source["list_url"]
    patterns = source.get("patterns", {})

    wait_selector: str = patterns.get("wait_for_selector", "body")
    wait_timeout: int = int(patterns.get("wait_timeout_ms", 15_000))
    scroll: bool = bool(patterns.get("scroll_to_bottom", False))
    extra_wait: int = int(patterns.get("extra_wait_ms", 1_000))
    block_media: bool = bool(patterns.get("block_media", True))

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="fr-CA",
                viewport={"width": 1280, "height": 900},
            )

            if block_media:
                await context.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf}",
                    lambda route: route.abort(),
                )

            page = await context.new_page()

            logger.info(
                "Playwright: loading page",
                source=source_name,
                url=url,
                run_id=run_id,
            )

            await page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout)

            # Wait for the content selector
            try:
                await page.wait_for_selector(wait_selector, timeout=wait_timeout)
            except Exception:
                logger.warning(
                    "Playwright: wait_for_selector timed out, proceeding anyway",
                    selector=wait_selector,
                    source=source_name,
                    run_id=run_id,
                )

            if scroll:
                # Scroll incrementally to trigger lazy loading
                await page.evaluate("""async () => {
                    await new Promise(resolve => {
                        let totalHeight = 0;
                        const distance = 400;
                        const timer = setInterval(() => {
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if (totalHeight >= document.body.scrollHeight) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 150);
                    });
                }""")

            if extra_wait > 0:
                await page.wait_for_timeout(extra_wait)

            # Get full rendered text content (cleaner than raw HTML for LLM)
            text_content = await page.inner_text("body")
            html_content = await page.content()

            await browser.close()

        logger.info(
            "Playwright: page rendered",
            source=source_name,
            text_chars=len(text_content),
            run_id=run_id,
        )

        import json

        normalized = [
            {
                "url": url,
                "content": text_content,
                "title": source_name,
                "score": None,
            }
        ]

        return {
            "source": source,
            "content": json.dumps(normalized, ensure_ascii=False),
            "listings": normalized,
            "url": url,
            "status": "success",
            "parser_type": "playwright",
            "fetched_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(
            "Playwright fetch failed",
            source=source_name,
            url=url,
            error=str(e),
            run_id=run_id,
        )
        return _error(source, str(e))


def _error(source: dict, error: str) -> dict:
    import json

    return {
        "source": source,
        "content": json.dumps([]),
        "listings": [],
        "url": source.get("list_url", ""),
        "status": "failed",
        "error": error,
        "parser_type": "playwright",
        "fetched_at": datetime.utcnow().isoformat(),
    }
