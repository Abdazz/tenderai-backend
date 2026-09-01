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
    item_link_selector: str | None = patterns.get("item_link_selector")
    pagination_selector: str | None = patterns.get("pagination_selector")
    pagination_url_template: str | None = patterns.get("pagination_url_template")
    max_pages: int = int(patterns.get("max_pages", 5))

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
                await page.evaluate(
                    """async () => {
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
                }"""
                )

            if extra_wait > 0:
                await page.wait_for_timeout(extra_wait)

            if item_link_selector:
                # ── Link-extraction mode ─────────────────────────────────────
                # Extract individual item links from the rendered HTML and
                # follow pagination links up to max_pages.  Returns URL strings
                # so each detail page is fetched and parsed separately by
                # fetch_items / parse_extract (no LLM needed for listing page).
                import json
                from urllib.parse import urljoin as _urljoin, urlparse as _urlparse

                _parsed = _urlparse(url)
                _base_origin = f"{_parsed.scheme}://{_parsed.netloc}"

                all_links: list[str] = []
                seen_hrefs: set[str] = set()

                async def _collect_links(pg) -> int:
                    elems = await pg.query_selector_all(item_link_selector)
                    count = 0
                    for elem in elems:
                        href = await elem.get_attribute("href")
                        if not href:
                            continue
                        if href.startswith("/"):
                            href = _base_origin + href
                        elif not href.startswith("http"):
                            href = _urljoin(url, href)
                        if href not in seen_hrefs:
                            seen_hrefs.add(href)
                            all_links.append(href)
                            count += 1
                    return count

                new_count = await _collect_links(page)
                logger.info(
                    "Playwright links: page 1",
                    source=source_name,
                    new_links=new_count,
                    run_id=run_id,
                )

                if pagination_url_template:
                    # URL-template pagination: navigate directly to page N via a
                    # URL pattern like "https://example.com/list?page={page_num}"
                    for page_num in range(2, max_pages + 1):
                        next_url = pagination_url_template.format(page_num=page_num)
                        await page.goto(
                            next_url,
                            wait_until="domcontentloaded",
                            timeout=wait_timeout,
                        )
                        try:
                            await page.wait_for_selector(
                                wait_selector, timeout=wait_timeout
                            )
                        except Exception as e:
                            logger.debug(
                                "Selector wait timed out, continuing anyway",
                                selector=wait_selector,
                                page_num=page_num,
                                error=str(e),
                            )
                        if extra_wait > 0:
                            await page.wait_for_timeout(extra_wait)

                        new_count = await _collect_links(page)
                        logger.info(
                            f"Playwright links: page {page_num}",
                            source=source_name,
                            new_links=new_count,
                            total=len(all_links),
                            run_id=run_id,
                        )
                        if new_count == 0:
                            logger.info(
                                "Playwright pagination: no new links on page",
                                page=page_num,
                                source=source_name,
                                run_id=run_id,
                            )
                            break

                elif pagination_selector:
                    for page_num in range(2, max_pages + 1):
                        next_elem = await page.query_selector(pagination_selector)
                        if not next_elem:
                            logger.info(
                                "Playwright pagination: no more pages",
                                last_page=page_num - 1,
                                source=source_name,
                                run_id=run_id,
                            )
                            break

                        next_href = await next_elem.get_attribute("href")
                        if next_href:
                            if next_href.startswith("/"):
                                next_href = _base_origin + next_href
                            elif not next_href.startswith("http"):
                                next_href = _urljoin(url, next_href)
                            await page.goto(
                                next_href,
                                wait_until="domcontentloaded",
                                timeout=wait_timeout,
                            )
                        else:
                            await next_elem.click()
                            await page.wait_for_load_state(
                                "domcontentloaded", timeout=wait_timeout
                            )

                        try:
                            await page.wait_for_selector(
                                wait_selector, timeout=wait_timeout
                            )
                        except Exception as e:
                            logger.debug(
                                "Selector wait timed out, continuing anyway",
                                selector=wait_selector,
                                page_num=page_num,
                                error=str(e),
                            )

                        if extra_wait > 0:
                            await page.wait_for_timeout(extra_wait)

                        new_count = await _collect_links(page)
                        logger.info(
                            f"Playwright links: page {page_num}",
                            source=source_name,
                            new_links=new_count,
                            total=len(all_links),
                            run_id=run_id,
                        )
                        if new_count == 0:
                            logger.info(
                                "Playwright pagination: no new links on page",
                                page=page_num,
                                source=source_name,
                                run_id=run_id,
                            )
                            break

                await browser.close()

                logger.info(
                    "Playwright link extraction complete",
                    source=source_name,
                    total_links=len(all_links),
                    run_id=run_id,
                )

                return {
                    "source": source,
                    "content": json.dumps(all_links, ensure_ascii=False),
                    "listings": all_links,
                    "url": url,
                    "status": "success",
                    "parser_type": "playwright_links",
                    "fetched_at": datetime.utcnow().isoformat(),
                }

            else:
                # ── Text-blob mode (legacy, no item_link_selector) ───────────
                # Capture the rendered page text and return as a single blob
                # for LLM extraction in parse_tavily_listing.
                text_content = await page.inner_text("body")
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
