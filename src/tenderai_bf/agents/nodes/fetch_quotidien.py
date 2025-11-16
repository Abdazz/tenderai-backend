"""Fetch and parse DGCMEF daily bulletins (quotidiens)."""

import re
from typing import Dict, List
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ...config import settings
from ...logging import get_logger

logger = get_logger(__name__)


async def fetch_dgcmef_quotidien(source: Dict, run_id: str) -> Dict:
    """Fetch the latest quotidien PDF from DGCMEF.
    
    Args:
        source: Source configuration dict
        run_id: Current run ID for tracking
        
    Returns:
        Dict with status and PDF URL or error
    """
    
    list_url = source['list_url']
    source_name = source['name']
    
    logger.info(
        "Fetching DGCMEF quotidien",
        source=source_name,
        url=list_url,
        run_id=run_id
    )
    
    try:
        # Fetch the listing page with SSL verification disabled for expired certificates
        async with httpx.AsyncClient(
            timeout=60.0, 
            follow_redirects=True,
            verify=False  # Disable SSL verification for expired certificates
        ) as client:
            response = await client.get(
                list_url,
                headers={'User-Agent': settings.fetch.user_agent}
            )
            response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the table containing quotidiens
        table = soup.find('table')
        if not table:
            raise Exception("Could not find quotidien table on page")
        
        # Find all rows
        rows = table.find_all('tr')
        if len(rows) < 2:  # Need at least header + 1 data row
            raise Exception("No quotidien entries found in table")
        
        # Get the first data row (most recent quotidien)
        # Skip header row (index 0)
        first_row = rows[1]
        cells = first_row.find_all('td')
        
        if len(cells) < 2:
            raise Exception(f"Invalid table structure: found {len(cells)} columns, expected at least 2")
        
        # Extract title from first column
        title_cell = cells[0]
        title = title_cell.get_text(strip=True)
        
        # Extract PDF link from second column
        pdf_cell = cells[1]
        pdf_link_tag = pdf_cell.find('a')
        
        if not pdf_link_tag or not pdf_link_tag.get('href'):
            raise Exception("Could not find PDF link in second column")
        
        pdf_href = pdf_link_tag.get('href')
        pdf_url = urljoin(list_url, pdf_href)
        
        # Extract PDF filename for metadata
        pdf_filename = pdf_link_tag.get_text(strip=True)
        
        logger.info(
            "Found latest quotidien",
            source=source_name,
            title=title,
            pdf_url=pdf_url,
            filename=pdf_filename,
            run_id=run_id
        )
        
        return {
            'status': 'success',
            'source': source_name,
            'title': title,
            'pdf_url': pdf_url,
            'pdf_filename': pdf_filename,
            'list_url': list_url
        }
        
    except httpx.HTTPError as e:
        logger.error(
            "HTTP error fetching DGCMEF quotidien",
            source=source_name,
            error=str(e),
            url=list_url,
            run_id=run_id
        )
        return {
            'status': 'failed',
            'source': source_name,
            'error': f"HTTP error: {str(e)}",
            'url': list_url
        }
        
    except Exception as e:
        logger.error(
            "Error fetching DGCMEF quotidien",
            source=source_name,
            error=str(e),
            url=list_url,
            run_id=run_id,
            exc_info=True
        )
        return {
            'status': 'failed',
            'source': source_name,
            'error': str(e),
            'url': list_url
        }


async def download_quotidien_pdf(pdf_url: str, source_name: str, run_id: str) -> Dict:
    """Download a quotidien PDF file.
    
    Args:
        pdf_url: URL of the PDF to download
        source_name: Name of the source
        run_id: Current run ID
        
    Returns:
        Dict with status and PDF content or error
    """
    
    logger.info(
        "Downloading quotidien PDF",
        source=source_name,
        pdf_url=pdf_url,
        run_id=run_id
    )
    
    try:
        async with httpx.AsyncClient(
            timeout=60.0, 
            follow_redirects=True,
            verify=False  # Disable SSL verification for expired certificates
        ) as client:
            response = await client.get(
                pdf_url,
                headers={'User-Agent': settings.fetch.user_agent}
            )
            response.raise_for_status()
        
        # Verify content type
        content_type = response.headers.get('content-type', '').lower()
        if 'pdf' not in content_type and 'application/octet-stream' not in content_type:
            logger.error(
                "Unexpected content type for PDF",
                content_type=content_type,
                pdf_url=pdf_url
            )
        
        pdf_content = response.content
        pdf_size_mb = len(pdf_content) / (1024 * 1024)
        
        logger.info(
            "PDF downloaded successfully",
            source=source_name,
            pdf_url=pdf_url,
            size_mb=round(pdf_size_mb, 2),
            run_id=run_id
        )
        
        return {
            'status': 'success',
            'content': pdf_content,
            'size_bytes': len(pdf_content),
            'content_type': content_type
        }
        
    except Exception as e:
        logger.error(
            "Error downloading PDF",
            source=source_name,
            error=str(e),
            pdf_url=pdf_url,
            run_id=run_id,
            exc_info=True
        )
        return {
            'status': 'failed',
            'error': str(e)
        }
