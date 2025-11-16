"""Fetch and parse listings from joffres.net."""

import re
from typing import Dict, List
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from ...logging import get_logger

logger = get_logger(__name__)


def extract_joffres_listings(html_content: str, source_url: str) -> List[Dict]:
    """
    Extract tender listings from joffres.net HTML page.
    
    Args:
        html_content: HTML page content
        source_url: URL of the listing page
        
    Returns:
        List of tender item URLs and information
    """
    items = []
    
    try:
        parser = HTMLParser(html_content)
        
        # Find all tender cards
        # Looking for: <a class="job-title" href="...">TITLE</a>
        tender_links = parser.css('a.job-title')
        
        logger.info(
            f"Found {len(tender_links)} tender listings",
            source_url=source_url
        )
        
        for i, link in enumerate(tender_links):
            href = link.attributes.get('href', '')
            title = link.text()
            
            if not href:
                continue
            
            # Make absolute URL
            detail_url = urljoin(source_url, href)
            
            # Extract slug from URL (last part of the path)
            slug = href.split('/')[-1]
            
            item_info = {
                'url': detail_url,
                'title': title.strip() if title else f"Tender {i+1}",
                'slug': slug,
                'source': 'joffres.net'
            }
            
            items.append(item_info)
            
            logger.debug(
                f"Extracted listing {i+1}",
                title=item_info['title'][:50],
                url=detail_url
            )
        
        return items
        
    except Exception as e:
        logger.error(f"Error extracting joffres listings: {e}")
        return []


def extract_joffres_detail(html_content: str, detail_url: str) -> Dict:
    """
    Extract tender details from joffres.net detail page.
    
    Args:
        html_content: HTML page content of detail page
        detail_url: URL of the detail page
        
    Returns:
        Dict with tender details
    """
    try:
        parser = HTMLParser(html_content)
        
        # Extract title from the main heading in small-section-tittle
        title = "Unknown"
        title_elem = parser.css_first('.small-section-tittle h3')
        if title_elem:
            title = title_elem.text(strip=True)
        
        # Extract all the detail fields from the small-section-tittle div
        details_div = parser.css_first('.small-section-tittle')
        entity = ""
        category = ""
        
        if details_div:
            # Get all text content to parse
            text_content = details_div.text()
            
            # Extract structure/entity - look for "Structure :" pattern
            entity_match = re.search(r'Structure\s*:\s*([^\n]+?)(?:\s*(?:Secteur|Localité|$))', text_content, re.IGNORECASE)
            if entity_match:
                entity = entity_match.group(1).strip()
            
            # Extract category - look for "Catégorie :" pattern  
            category_match = re.search(r'Catégorie\s*:\s*([^\n]+?)(?:\s*(?:Domaine|Structure|$))', text_content, re.IGNORECASE)
            if category_match:
                category = category_match.group(1).strip()
        
        # Extract deadline from "Expire le :" in the right sidebar
        deadline = ""
        for strong_elem in parser.css('.offre-detail-right strong, .offre-detail-ight strong'):
            if 'Expire le' in strong_elem.text(strip=True):
                parent = strong_elem.parent
                if parent:
                    span = parent.css_first('.item-detail-color')
                    if span:
                        deadline = span.text(strip=True)
                        break
        
        # Extract reference number from the description content
        ref_no = ""
        desc_elem = parser.css_first('.post-details1 p')
        if desc_elem:
            desc_text = desc_elem.text()
            # Look for patterns like "N°2026-01/CO/M/DCP" or "DAO 146-2025"
            ref_patterns = [
                r'(?:N°|N\s*°)\s*([0-9-/A-Z]+)',
                r'DAO\s+([0-9-]+)',
                r'Demande de prix\s+N[°\s]*([0-9-/A-Z]+)'
            ]
            for pattern in ref_patterns:
                match = re.search(pattern, desc_text, re.IGNORECASE)
                if match:
                    ref_no = match.group(0).strip()
                    break
        
        # Extract description from the main content area
        description = ""
        desc_elem = parser.css_first('.post-details1')
        if desc_elem:
            # Get all paragraph text
            paragraphs = desc_elem.css('p')
            desc_parts = []
            for p in paragraphs[:3]:  # Take first 3 paragraphs
                text = p.text(strip=True)
                if len(text) > 20:
                    desc_parts.append(text)
            description = ' '.join(desc_parts)[:800]
        
        result = {
            'title': title,
            'tender_object': title,  # Map title to tender_object for consistency with RAG extraction
            'type': 'appel_offres',  # Default type for Joffres listings
            'ref_no': ref_no,
            'reference': ref_no,  # Map ref_no to reference for consistency
            'entity': entity if entity else "Unknown",
            'category': category if category else "Services",
            'deadline': deadline,
            'description': description,
            'url': detail_url,
            'source': 'joffres.net',
            'parser_type': 'joffres_detail'  # Use parser_type instead of type to avoid conflict
        }
        
        logger.debug(
            "Extracted detail page",
            title=title[:50],
            ref=ref_no,
            entity=entity
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error extracting joffres detail page: {e}")
        return {}
