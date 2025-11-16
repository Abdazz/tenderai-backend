"""PDF parsing using Docling for better structure extraction."""

import re
from io import BytesIO
from typing import Dict, List

from docling.document_converter import DocumentConverter

from ..logging import get_logger

logger = get_logger(__name__)


def extract_quotidien_with_docling(pdf_bytes: bytes) -> Dict:
    """
    Extract structured content from DGCMEF quotidien PDF using Docling.
    
    Args:
        pdf_bytes: PDF file content as bytes
        
    Returns:
        Dict with extracted tenders and metadata
    """
    try:
        logger.info("Starting Docling PDF extraction")
        
        # Initialize Docling converter
        converter = DocumentConverter()
        
        # Convert PDF bytes to document
        # Docling needs a file-like object or path
        pdf_file = BytesIO(pdf_bytes)
        result = converter.convert(pdf_file)
        
        # Extract text content
        text = result.document.export_to_text()
        
        logger.info(
            "Docling extraction complete",
            text_length=len(text),
            num_pages=len(result.document.pages) if hasattr(result.document, 'pages') else 'N/A'
        )
        
        # Extract markdown for better structure
        markdown = result.document.export_to_markdown()
        
        # Parse the extracted content
        tenders = parse_quotidien_text(text, markdown)
        
        return {
            'status': 'success',
            'tenders': tenders,
            'text': text,
            'markdown': markdown,
            'num_tenders': len(tenders)
        }
        
    except Exception as e:
        logger.error(
            "Docling extraction failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )
        return {
            'status': 'error',
            'error': str(e),
            'tenders': []
        }


def parse_quotidien_text(text: str, markdown: str = None) -> List[Dict]:
    """
    Parse quotidien text to extract individual tender notices.
    
    Strategy:
    1. Find "Fournitures et Services courants" section (AVIS section)
    2. Split by reference numbers (N°20XX-XXX/...)
    3. Extract details for each tender
    
    Args:
        text: Extracted text from PDF
        markdown: Optional markdown version for better structure
        
    Returns:
        List of tender dictionaries
    """
    tenders = []
    
    # Find the AVIS section (Fournitures et Services courants)
    avis_markers = [
        "Fournitures et Services courants",
        "FOURNITURES ET SERVICES COURANTS",
        "AVIS DE DEMANDE DE PRIX",
        "AVIS D'APPEL D'OFFRES"
    ]
    
    avis_start = -1
    for marker in avis_markers:
        pos = text.find(marker)
        if pos != -1:
            avis_start = pos
            logger.debug(f"Found AVIS section at position {pos} with marker: {marker}")
            break
    
    if avis_start == -1:
        logger.error("Could not find AVIS section in quotidien")
        # Try to parse the whole document
        avis_section = text
    else:
        avis_section = text[avis_start:]
    
    logger.info(f"AVIS section length: {len(avis_section)} characters")
    
    # Strategy: Split by reference numbers (N°20XX-XXX/...)
    # This is more reliable than entity names
    ref_pattern = r'N[°o]\s*(\d{4}[-–]\d+[^\n]{0,100})'
    
    # Find all reference numbers and their positions
    references = []
    for match in re.finditer(ref_pattern, avis_section):
        references.append({
            'ref': match.group(0).strip(),
            'pos': match.start(),
            'end': match.end()
        })
    
    logger.info(f"Found {len(references)} reference numbers in AVIS section")
    
    # Extract tender blocks between reference numbers
    for i, ref_info in enumerate(references):
        # Get text from this reference to the next one (or end of section)
        start_pos = ref_info['pos']
        end_pos = references[i + 1]['pos'] if i + 1 < len(references) else len(avis_section)
        
        tender_block = avis_section[start_pos:end_pos]
        
        # Extract tender information from block
        tender_info = extract_tender_from_block(tender_block, ref_info['ref'])
        
        if tender_info:
            tenders.append(tender_info)
    
    logger.info(f"Extracted {len(tenders)} tenders from quotidien")
    
    return tenders


def extract_tender_from_block(block: str, ref_no: str) -> Dict:
    """
    Extract tender details from a text block.
    
    Args:
        block: Text block containing one tender
        ref_no: Reference number already extracted
        
    Returns:
        Dict with tender information
    """
    lines = [line.strip() for line in block.split('\n') if line.strip()]
    
    # Extract entity (usually in first few lines, ALL CAPS)
    entity = None
    for line in lines[:10]:
        if line.isupper() and len(line) > 20 and len(line) < 200:
            # Check it's not a section header
            if not any(skip in line for skip in [
                'AVIS', 'SOURCE', 'FINANCEMENT', 'OBJECTIFS', 
                'PRESENTATION', 'MODALITES', 'BUDGET'
            ]):
                entity = line
                break
    
    # Extract title/object (look for "Acquisition", "Travaux", "Fourniture", etc.)
    title = None
    title_keywords = [
        'Acquisition', 'Travaux', 'Fourniture', 'Construction',
        'Réhabilitation', 'Aménagement', 'Installation'
    ]
    for line in lines[:15]:
        if any(keyword in line for keyword in title_keywords):
            # Clean up the line
            title = line.replace(':', '').strip()
            if len(title) > 200:
                title = title[:200] + "..."
            break
    
    # Extract deadline
    deadline = None
    deadline_patterns = [
        r"(?:au plus tard |jusqu'au |limite |avant )?le\s+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\s+à\s+\d{1,2}[h:]\d{2}',
        r'(?:deadline|échéance|date limite).*?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})'
    ]
    
    block_lower = block.lower()
    for pattern in deadline_patterns:
        match = re.search(pattern, block_lower, re.IGNORECASE)
        if match:
            deadline = match.group(1)
            break
    
    # Extract budget (look for "CFA" or numbers)
    budget = None
    budget_patterns = [
        r'(\d[\d\s\.]{6,})\s*(?:F\.?CFA|francs?)',
        r'Budget.*?:\s*(\d[\d\s\.]{6,})',
        r'Montant.*?:\s*(\d[\d\s\.]{6,})'
    ]
    for pattern in budget_patterns:
        match = re.search(pattern, block, re.IGNORECASE)
        if match:
            budget = match.group(1).strip()
            break
    
    # Get description (first 500 chars after title)
    description_start = 0
    if title:
        title_pos = block.find(title)
        if title_pos != -1:
            description_start = title_pos + len(title)
    
    description = block[description_start:description_start + 500].strip()
    # Clean up description
    description = ' '.join(description.split())
    
    return {
        'ref_no': ref_no,
        'entity': entity or 'Unknown Entity',
        'title': title or 'Untitled Tender',
        'description': description,
        'deadline': deadline,
        'budget': budget,
        'raw_text': block[:1000]  # Store first 1000 chars for reference
    }
