"""Extract individual item links from listing pages."""

import re
import time
from datetime import datetime
from typing import Dict, List, Set
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from ...config import settings
from ...logging import get_logger
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def extract_links_from_html(content: str, base_url: str, patterns: Dict) -> List[str]:
    """Extract item links from HTML content using CSS selectors."""
    
    try:
        parser = HTMLParser(content)
        links = []
        
        # Get link selector from patterns
        link_selector = patterns.get('item_link_selector') or patterns.get('item_selector')
        if not link_selector:
            # Try common selectors
            selectors_to_try = [
                'a[href*="appel"]',
                'a[href*="offre"]',
                'a[href*="avis"]',
                'a[href*="tender"]',
                '.item a',
                '.post a',
                '.entry a',
                'article a',
                '.tender-item a'
            ]
        else:
            selectors_to_try = [link_selector]
        
        for selector in selectors_to_try:
            try:
                elements = parser.css(selector)
                for element in elements:
                    href = element.attributes.get('href')
                    if href:
                        # Make absolute URL
                        absolute_url = urljoin(base_url, href)
                        
                        # Basic filtering - avoid common non-tender links
                        if is_likely_tender_link(absolute_url, element.text()):
                            links.append(absolute_url)
                
                if links:
                    logger.debug(
                        "Found links with selector",
                        selector=selector,
                        count=len(links)
                    )
                    break
                    
            except Exception as e:
                logger.debug(
                    "Selector failed",
                    selector=selector,
                    error=str(e)
                )
                continue
        
        return list(set(links))  # Remove duplicates
    
    except Exception as e:
        logger.error(
            "HTML link extraction failed",
            error=str(e),
            exc_info=True
        )
        return []


def extract_links_from_pdf_list(content: str, base_url: str, patterns: Dict) -> List[str]:
    """Extract PDF links that might contain tender information."""
    
    try:
        parser = HTMLParser(content)
        links = []
        
        # Look for PDF links
        pdf_selectors = [
            'a[href$=".pdf"]',
            'a[href*=".pdf"]',
            patterns.get('pdf_links_selector', 'a[href$=".pdf"]')
        ]
        
        for selector in pdf_selectors:
            try:
                elements = parser.css(selector)
                for element in elements:
                    href = element.attributes.get('href')
                    if href and href.lower().endswith('.pdf'):
                        absolute_url = urljoin(base_url, href)
                        
                        # Filter for likely tender PDFs
                        link_text = element.text().lower()
                        if any(keyword in link_text for keyword in [
                            'appel', 'offre', 'avis', 'tender', 'dao', 'aoo', 'consultation'
                        ]):
                            links.append(absolute_url)
                
                if links:
                    logger.debug(
                        "Found PDF links with selector",
                        selector=selector,
                        count=len(links)
                    )
                    break
                    
            except Exception as e:
                logger.debug("PDF selector failed", selector=selector, error=str(e))
                continue
        
        return list(set(links))
    
    except Exception as e:
        logger.error("PDF link extraction failed", error=str(e), exc_info=True)
        return []


def is_likely_tender_link(url: str, link_text: str = "") -> bool:
    """Check if a URL is likely to be a tender/RFP link."""
    
    url_lower = url.lower()
    text_lower = link_text.lower()
    
    # Include patterns
    include_patterns = [
        'appel', 'offre', 'avis', 'tender', 'rfp', 'dao', 'aoo',
        'consultation', 'marche', 'contract', 'procurement'
    ]
    
    # Exclude patterns
    exclude_patterns = [
        'contact', 'about', 'accueil', 'home', 'login', 'admin',
        'search', 'recherche', 'menu', 'nav', 'footer', 'header',
        'javascript:', 'mailto:', '#', 'tel:'
    ]
    
    # Check for include patterns
    has_include = any(pattern in url_lower or pattern in text_lower 
                      for pattern in include_patterns)
    
    # Check for exclude patterns
    has_exclude = any(pattern in url_lower or pattern in text_lower 
                      for pattern in exclude_patterns)
    
    # Must have include pattern and not have exclude pattern
    return has_include and not has_exclude


def extract_item_links_node(state) -> Dict:
    """Extract individual item links from fetched listing pages."""
    
    # Clear output file at start
    clear_node_output("extract_item_links")
    
    logger.info("Starting extract_item_links step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        if not state.items_raw:
            logger.error("No raw items to process", run_id=state.run_id)
            state.add_error("extract_item_links", "No raw items available to process")
            state.should_continue = False
            return state
        
        all_links = []  # Changed from set to list to support dict items
        seen_urls = set()  # Track URLs to avoid duplicates
        seen_pdf_parsers = set()  # Track (url, parser_type) tuples for PDFs to allow different parsers
        source_link_counts = {}
        
        # Process each successful fetch
        for item in state.items_raw:
            if item['status'] != 'success' or not item['content']:
                continue
            
            source = item['source']
            source_name = source['name']
            base_url = source.get('base_url', item['url'])
            content = item['content']
            patterns = source.get('patterns', {})
            parser_type = source.get('parser_type', 'html')  # Changed from 'parser' to 'parser_type'
            
            try:
                # Extract links based on parser type
                if parser_type == 'pdf_quotidien':
                    # For quotidiens (DGCMEF), the PDF is already downloaded
                    # Create a single "link" representing the quotidien PDF
                    links = [{
                        'url': item['url'],
                        'type': 'quotidien_pdf',
                        'title': item.get('quotidien_title', 'Quotidien'),
                        'filename': item.get('quotidien_filename', 'quotidien.pdf'),
                        'content': content  # Pass the PDF content directly
                    }]
                    logger.info(
                        "Quotidien PDF ready for parsing",
                        source_name=source_name,
                        title=item.get('quotidien_title'),
                        size_mb=round(len(content) / (1024 * 1024), 2),
                        run_id=state.run_id
                    )
                
                elif parser_type == 'pdf_rag':
                    # For RAG-based PDF parsing (DGCMEF RAG), the PDF is already downloaded
                    # Create a single "link" representing the RAG PDF
                    links = [{
                        'url': item['url'],
                        'source_name': source_name,  # Preserve source_name for downstream processing
                        'type': 'pdf_rag',
                        'title': item.get('quotidien_title', 'PDF Document'),
                        'filename': item.get('quotidien_filename', 'document.pdf'),
                        'content': content  # Pass the PDF content directly
                    }]
                    logger.info(
                        "RAG PDF ready for parsing",
                        source_name=source_name,
                        title=item.get('quotidien_title'),
                        size_mb=round(len(content) / (1024 * 1024), 2),
                        run_id=state.run_id
                    )
                    logger.debug(
                        "DEBUG: RAG PDF link created",
                        links_count=len(links),
                        first_link_type=links[0].get('type') if links else None,
                        first_link_url=links[0].get('url') if links else None,
                        run_id=state.run_id
                    )
                
                elif parser_type == 'html-listing' and 'joffres' in source_name.lower():
                    # For joffres.net listings (already parsed)
                    import json
                    try:
                        listings = json.loads(content) if isinstance(content, str) else item.get('listings', [])
                        links = listings
                        logger.info(
                            f"Processing {len(listings)} joffres.net listings",
                            source_name=source_name,
                            count=len(listings),
                            run_id=state.run_id
                        )
                    except json.JSONDecodeError:
                        logger.error(
                            "Failed to parse joffres listings JSON",
                            source_name=source_name
                        )
                        links = []
                elif parser_type == 'html':
                    links = extract_links_from_html(content, base_url, patterns)
                elif parser_type == 'html-pdf-mixed':
                    # Try both HTML and PDF extraction
                    html_links = extract_links_from_html(content, base_url, patterns)
                    pdf_links = extract_links_from_pdf_list(content, base_url, patterns)
                    links = html_links + pdf_links
                elif parser_type == 'pdf':
                    # For direct PDF sources, use the source URL itself
                    links = [item['url']]
                else:
                    logger.error(
                        "Unknown parser type",
                        parser_type=parser_type,
                        source_name=source_name
                    )
                    links = []
                
                # Filter and validate links
                valid_links = []
                for link in links:
                    # Handle quotidien PDFs (already dict format)
                    if isinstance(link, dict) and link.get('type') == 'quotidien_pdf':
                        url = link.get('url')
                        url_parser_key = (url, 'quotidien_pdf')
                        if url and url_parser_key not in seen_pdf_parsers:
                            valid_links.append(link)
                            seen_urls.add(url)
                            seen_pdf_parsers.add(url_parser_key)
                    # Handle joffres.net listings (dict format with url, title, slug)
                    elif isinstance(link, dict) and link.get('source') == 'joffres.net':
                        url = link.get('url')
                        if url and url not in seen_urls:
                            # Add the joffres listing dict as-is for fetch_items to process
                            valid_links.append(link)
                            seen_urls.add(url)
                    # Handle RAG PDFs (dict format with type='pdf_rag')
                    elif isinstance(link, dict) and link.get('type') == 'pdf_rag':
                        url = link.get('url')
                        url_parser_key = (url, 'pdf_rag')
                        if url and url_parser_key not in seen_pdf_parsers:
                            # Add the RAG PDF dict for fetch_items to process
                            valid_links.append(link)
                            seen_urls.add(url)
                            seen_pdf_parsers.add(url_parser_key)
                    # Handle quotidien PDFs (dict format with type='quotidien_pdf')
                    elif isinstance(link, dict) and link.get('type') == 'quotidien_pdf':
                        url = link.get('url')
                        if url and url not in seen_urls:
                            # Add the quotidien PDF dict for fetch_items to process
                            valid_links.append(link)
                            seen_urls.add(url)
                    # Handle regular URL strings
                    elif isinstance(link, str):
                        # Basic URL validation
                        parsed = urlparse(link)
                        if parsed.scheme in ('http', 'https') and parsed.netloc:
                            if link not in seen_urls:
                                valid_links.append(link)
                                seen_urls.add(link)
                
                # Add to global list
                all_links.extend(valid_links)
                source_link_counts[source_name] = len(valid_links)
                
                logger.info(
                    "Extracted links from source",
                    source_name=source_name,
                    links_found=len(valid_links),
                    run_id=state.run_id
                )
            
            except Exception as e:
                logger.error(
                    "Failed to extract links from source",
                    source_name=source_name,
                    error=str(e),
                    run_id=state.run_id,
                    exc_info=True
                )
                state.add_error(
                    "extract_item_links",
                    f"Failed to extract links from {source_name}: {str(e)}",
                    source_name=source_name
                )
        
        # Use the list as-is (already contains validated items)
        discovered_links = all_links
        
        # Apply max items limit
        max_items = settings.processing.max_items_per_run
        if len(discovered_links) > max_items:
            logger.error(
                "Too many links discovered, limiting",
                total_found=len(discovered_links),
                limit=max_items,
                run_id=state.run_id
            )
            discovered_links = discovered_links[:max_items]
        
        # Update state
        state.discovered_links = discovered_links
        state.update_stats(links_discovered=len(discovered_links))
        
        # Log output to JSON
        log_node_output("extract_item_links", discovered_links, run_id=state.run_id)
        
        # Log completion
        duration = time.time() - start_time
        logger.info(
            "Extract item links completed",
            total_links=len(discovered_links),
            sources_processed=len([item for item in state.items_raw if item['status'] == 'success']),
            source_breakdown=source_link_counts,
            duration_seconds=duration,
            run_id=state.run_id
        )
        
        # Check if we found any links
        if not discovered_links:
            logger.error("No item links discovered", run_id=state.run_id)
            state.add_error(
                "extract_item_links",
                "No item links discovered from any source",
                sources_processed=len([item for item in state.items_raw if item['status'] == 'success'])
            )
            # Don't stop pipeline, continue with empty list
        
        return state
    
    except Exception as e:
        logger.error(
            "Extract item links step failed",
            error=str(e),
            run_id=state.run_id,
            exc_info=True
        )
        state.add_error("extract_item_links", str(e))
        state.should_continue = False
        return state