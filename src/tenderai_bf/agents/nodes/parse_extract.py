"""Parse and extract structured data from item pages."""

import hashlib
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from selectolax.parser import HTMLParser

from ...logging import get_logger
from ...utils.pdf import extract_pdf_text_from_bytes
from ...utils.docling_parser import extract_tender_from_block
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def split_quotidien_into_tenders(text: str) -> List[Dict]:
    """Split quotidien text into individual tender notices.
    
    The quotidien structure is:
    - Header/Table of contents
    - RESULTATS PROVISOIRES (past tender results - IGNORE)
    - Fournitures et Services courants (NEW TENDERS - this is what we want)
    
    Each tender typically has:
    - Entity name (often in ALL CAPS)
    - Tender title/object
    - "Avis d'Appel d'Offres" or "Avis de Demande de Prix"
    - Reference number N°YYYY-XXX/...
    """
    import re
    
    tenders = []
    
    # Find the "Fournitures et Services courants" section (new tenders)
    # This is where the AVIS (new tenders) are, not the RESULTATS
    fournitures_start = text.find("Fournitures et Services courants")
    if fournitures_start == -1:
        fournitures_start = text.find("FOURNITURES ET SERVICES COURANTS")
    
    if fournitures_start == -1:
        logger.error("Could not find 'Fournitures et Services courants' section in quotidien")
        return []
    
    # Extract only the AVIS section
    avis_section = text[fournitures_start:]
    
    # Strategy: Split by reference numbers (N°20XX-XXX/...)
    # This is more reliable than entity names
    ref_pattern = r'N[°o]\s*(\d{4}[-–]\d+[^\\n]{0,100})'
    
    # Find all reference numbers and their positions
    references = []
    for match in re.finditer(ref_pattern, avis_section):
        references.append({
            'ref': match.group(0).strip(),
            'pos': match.start(),
            'end': match.end()
        })
    
    logger.debug(f"Found {len(references)} reference numbers in AVIS section")
    
    # Extract tender blocks between reference numbers
    for i, ref_info in enumerate(references):
        # Start from the reference number
        start_pos = ref_info['pos']
        
        # Find previous entity name (backtrack to find ALL CAPS line)
        # Look backwards max 500 chars
        search_start = max(0, start_pos - 500)
        pre_text = avis_section[search_start:start_pos]
        pre_lines = pre_text.split('\n')
        
        entity = "Unknown Entity"
        for line in reversed(pre_lines):
            line_stripped = line.strip()
            # Entity names are usually ALL CAPS, 25-150 chars
            if (line_stripped.isupper() and 
                25 < len(line_stripped) < 150 and
                not any(skip in line_stripped for skip in [
                    'AVIS', 'SOURCE', 'FINANCEMENT', 'OBJECTIFS', 
                    'PRESENTATION', 'MODALITES', 'REMARQUES'
                ])):
                entity = line_stripped
                break
        
        # End is either next reference or end of section
        if i + 1 < len(references):
            end_pos = references[i + 1]['pos']
        else:
            # Last tender - take next 2000 chars or end of section
            end_pos = min(len(avis_section), start_pos + 2000)
        
        # Extract tender content
        tender_content = avis_section[start_pos:end_pos].strip()
        
        # Only keep if substantial content
        if len(tender_content) > 200:
            tenders.append({
                'entity': entity,
                'ref_no': ref_info['ref'],
                'content': tender_content
            })
    
    return tenders
    
    return tenders


def parse_quotidien_pdf(pdf_content: bytes, quotidien_url: str, quotidien_title: str, run_id: str) -> List[Dict]:
    """Parse quotidien PDF and extract individual tender notices.
    
    Uses Docling for better PDF extraction with OCR support.
    
    Args:
        pdf_content: PDF file content as bytes
        quotidien_url: URL of the quotidien PDF
        quotidien_title: Title of the quotidien
        run_id: Current run ID
        
    Returns:
        List of parsed tender dictionaries
    """
    logger.info(
        "Parsing quotidien PDF with Docling",
        title=quotidien_title,
        size_mb=round(len(pdf_content) / (1024 * 1024), 2),
        run_id=run_id
    )
    
    try:
        # Import Docling (only when needed to avoid startup overhead)
        from .parse_quotidien_docling import parse_quotidien_with_docling
        
        # Use Docling to extract and parse
        tenders = parse_quotidien_with_docling(
            pdf_content=pdf_content,
            source_url=quotidien_url,
            quotidien_title=quotidien_title
        )
        
        logger.info(
            f"Extracted {len(tenders)} tenders from quotidien",
            title=quotidien_title,
            run_id=run_id
        )
        
        return tenders
        
    except Exception as e:
        logger.error(
            "Docling parsing failed, falling back to pdfminer",
            error=str(e),
            run_id=run_id
        )
        
        # Fallback to pdfminer-based extraction
        return parse_quotidien_pdf_fallback(pdf_content, quotidien_url, quotidien_title, run_id)


def parse_quotidien_pdf_fallback(pdf_content: bytes, quotidien_url: str, quotidien_title: str, run_id: str) -> List[Dict]:
    """Fallback parser using pdfminer (original implementation).
    
    Args:
        pdf_content: PDF file content as bytes
        quotidien_url: URL of the quotidien PDF
        quotidien_title: Title of the quotidien
        run_id: Current run ID
        
    Returns:
        List of parsed tender dictionaries
    """
    logger.info(
        "Using fallback pdfminer parser",
        title=quotidien_title,
        run_id=run_id
    )
    
    try:
        # Extract text from PDF using pdfminer
        text = extract_pdf_text_from_bytes(pdf_content)
        
        logger.info(
            "PDF text extracted",
            text_length=len(text),
            run_id=run_id
        )
        
        # Find the AVIS section (Fournitures et Services courants)
        avis_start = text.find("Fournitures et Services courants")
        if avis_start == -1:
            avis_start = text.find("FOURNITURES ET SERVICES COURANTS")
        
        if avis_start == -1:
            logger.error("Could not find AVIS section in quotidien", run_id=run_id)
            avis_section = text  # Use whole document as fallback
        else:
            avis_section = text[avis_start:]
            logger.info(f"Found AVIS section at position {avis_start}", run_id=run_id)
        
        # Split by reference numbers (N°20XX-XXX/...)
        ref_pattern = r'N[°o]\s*(\d{4}[-–]\d+[^\n]{0,100})'
        
        references = []
        for match in re.finditer(ref_pattern, avis_section):
            references.append({
                'ref': match.group(0).strip(),
                'pos': match.start(),
                'end': match.end()
            })
        
        logger.info(
            f"Found {len(references)} reference numbers",
            run_id=run_id
        )
        
        # Extract tender blocks
        parsed_items = []
        for i, ref_info in enumerate(references):
            start_pos = ref_info['pos']
            end_pos = references[i + 1]['pos'] if i + 1 < len(references) else len(avis_section)
            
            tender_block = avis_section[start_pos:end_pos]
            
            # Extract tender information
            tender_info = extract_tender_from_block(tender_block, ref_info['ref'])
            
            if tender_info:
                parsed_item = {
                    'id': str(uuid.uuid4()),
                    'url': quotidien_url,
                    'title': tender_info.get('title', 'Untitled Tender'),
                    'ref_no': tender_info.get('ref_no', ref_info['ref']),
                    'entity': tender_info.get('entity', 'Unknown Entity'),
                    'category': 'Fournitures et Services',
                    'description': tender_info.get('description', '')[:1000],  # Limit description
                    'published_at': datetime.utcnow().isoformat(),
                    'deadline_at': tender_info.get('deadline'),
                    'location': "Burkina Faso",
                    'content_hash': hashlib.sha256(tender_block[:1000].encode()).hexdigest(),
                    'source_type': 'quotidien_pdf',
                    'quotidien_title': quotidien_title,
                    'budget': tender_info.get('budget')
                }
                parsed_items.append(parsed_item)
                
                # Log each tender found (fallback parser)
                logger.info(
                    f"[FALLBACK] Tender {i+1}/{len(references)} extracted",
                    entity=parsed_item['entity'][:50],
                    title=parsed_item['title'][:80],
                    ref_no=parsed_item['ref_no'],
                    run_id=run_id
                )
        
        logger.info(
            "✅ Quotidien parsing complete (fallback pdfminer)",
            tenders_extracted=len(parsed_items),
            title=quotidien_title,
            run_id=run_id
        )
        
        return parsed_items
        
    except Exception as e:
        logger.error(
            "Failed to parse quotidien PDF",
            error=str(e),
            title=quotidien_title,
            run_id=run_id,
            exc_info=True
        )
        return []


def extract_tender_info(section_text: str, index: int) -> Dict:
    """Extract structured information from a tender section.
    
    Args:
        section_text: Text content of the tender section
        index: Section index for reference
        
    Returns:
        Dictionary with extracted tender information
    """
    
    info = {}
    
    # Extract title (usually the first significant line after entity name)
    lines = [line.strip() for line in section_text.split('\n') if line.strip()]
    
    # Find the title line (usually after entity, before "Avis")
    title_lines = []
    for i, line in enumerate(lines):
        if i == 0:  # Skip entity name
            continue
        if any(keyword in line for keyword in ['Avis', 'AVIS', 'N°', 'Source']):
            break
        if len(line) > 20 and not line.isupper():  # Likely title
            title_lines.append(line)
            if len(title_lines) >= 2:  # Max 2 lines for title
                break
    
    if title_lines:
        info['title'] = ' '.join(title_lines).strip()[:200]
    else:
        info['title'] = lines[0][:200] if lines else 'Appel d\'offres'
    
    # Extract reference number (N°YYYY-XXX/...)
    ref_pattern = r'N[°o]\s*(\d{4}[-–]\d+[^\s]*)'
    ref_match = re.search(ref_pattern, section_text)
    if ref_match:
        info['ref_no'] = ref_match.group(1).strip()
    else:
        # Try alternative patterns
        ref_pattern2 = r'(?:N[°o]|R[ée]f[ée]rence)\s*[:\.]?\s*([A-Z0-9\-\/]+)'
        ref_match2 = re.search(ref_pattern2, section_text, re.IGNORECASE)
        if ref_match2:
            info['ref_no'] = ref_match2.group(1).strip()
        else:
            info['ref_no'] = f'DGCMEF-{index:04d}'
    
    # Entity is passed separately, no need to extract again
    
    # Extract deadline
    deadline_patterns = [
        r'(?:date\s+limite|d[ée]lai|avant\s+le|au\s+plus\s+tard\s+le)\s*:?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
        r'(\d{1,2}\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre)\s+\d{4})'
    ]
    
    for pattern in deadline_patterns:
        deadline_match = re.search(pattern, section_text, re.IGNORECASE)
        if deadline_match:
            info['deadline_at'] = deadline_match.group(1).strip()
            break
    
    # Extract category based on keywords
    if re.search(r'travaux|construction|r[ée]habilitation|am[ée]nagement', section_text, re.IGNORECASE):
        info['category'] = 'Travaux'
    elif re.search(r'fourniture|acquisition|achat|[ée]quipement|licence', section_text, re.IGNORECASE):
        info['category'] = 'Fournitures'
    elif re.search(r'service|prestation|consultation|[ée]tude', section_text, re.IGNORECASE):
        info['category'] = 'Services'
    elif re.search(r'manifestation\s+d.int[ée]r[êe]t', section_text, re.IGNORECASE):
        info['category'] = 'Manifestation d\'intérêt'
    else:
        info['category'] = 'Non spécifié'
    
    # Extract location
    location_match = re.search(r'(?:Ouagadougou|Bobo-Dioulasso|Koudougou|Banfora|Tenkodogo|Fada N.Gourma|Burkina Faso)', section_text, re.IGNORECASE)
    if location_match:
        info['location'] = location_match.group(0).strip()
    
    # Description is the cleaned section text
    info['description'] = section_text[:1000].strip()
    
    return info


def parse_html_item(
    content: str,
    url: str,
    title: str,
    details: Optional[Dict] = None,
    run_id: Optional[str] = None
) -> Optional[Dict]:
    """Parse HTML content from Joffres or other sources.
    
    Args:
        content: HTML content
        url: Source URL
        title: Item title
        details: Pre-extracted details (from Joffres extraction)
        run_id: Current run ID for logging
        
    Returns:
        Parsed tender item or None if parsing fails
    """
    try:
        # Use pre-extracted details if available (from Joffres)
        if details:
            return {
                'id': str(uuid.uuid4()),
                'url': url,
                'title': details.get('title', title),
                'ref_no': details.get('reference', f"REF-{hashlib.md5(url.encode()).hexdigest()[:8].upper()}"),
                'entity': details.get('entity', 'Unknown'),
                'category': details.get('category', 'Services'),
                'description': details.get('description', content[:500]),
                'published_at': details.get('published_at', datetime.utcnow().isoformat()),
                'deadline_at': details.get('deadline', None),
                'location': details.get('location', 'Burkina Faso'),
                'content_hash': hashlib.sha256(content.encode()).hexdigest(),
                'parser_type': 'html-listing',
                'source': 'joffres.net'
            }
        
        # Otherwise, try to parse HTML using selectolax
        parser = HTMLParser(content)
        
        # Try to extract title from various locations
        title_elem = parser.select_first('h1, h2, .title, [data-title]')
        if title_elem:
            title = title_elem.text(strip=True)
        
        # Try to extract entity/organization
        entity = "Unknown"
        entity_elem = parser.select_first('.entity, .organization, .company, [data-entity]')
        if entity_elem:
            entity = entity_elem.text(strip=True)
        
        # Try to extract deadline
        deadline = None
        deadline_patterns = [r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})', r'(\d{4}-\d{2}-\d{2})']
        for elem in parser.select('[data-deadline], .deadline, .date-limite'):
            text = elem.text(strip=True)
            for pattern in deadline_patterns:
                match = re.search(pattern, text)
                if match:
                    deadline = match.group(1)
                    break
            if deadline:
                break
        
        # Extract description from paragraphs or divs
        description_parts = []
        for elem in parser.select('p, .description, .content')[:3]:
            text = elem.text(strip=True)
            if len(text) > 20:
                description_parts.append(text)
        
        description = ' '.join(description_parts)[:500] if description_parts else content[:500]
        
        return {
            'id': str(uuid.uuid4()),
            'url': url,
            'title': title,
            'ref_no': f"REF-{hashlib.md5(url.encode()).hexdigest()[:8].upper()}",
            'entity': entity,
            'category': 'Services',
            'description': description,
            'published_at': datetime.utcnow().isoformat(),
            'deadline_at': deadline,
            'location': 'Burkina Faso',
            'content_hash': hashlib.sha256(content.encode()).hexdigest(),
            'parser_type': 'html'
        }
    
    except Exception as e:
        logger.error(
            "Failed to parse HTML item",
            url=url,
            error=str(e),
            run_id=run_id,
            exc_info=True
        )
        return None


def parse_extract_node(state) -> Dict:
    """Parse and extract structured data from fetched items."""
    
    # Clear output file at start
    clear_node_output("parse_extract")
    
    logger.info("Starting parse_extract step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        parsed_items = []
        
        for item in state.items_raw:
            if item['status'] != 'success' or not item['content']:
                continue
            
            # Handle both string (HTML) and bytes (PDF) content
            content = item['content']
            if isinstance(content, bytes):
                content_hash = hashlib.sha256(content).hexdigest()
            else:
                content_hash = hashlib.sha256(content.encode()).hexdigest()
            
            # Check parser type and route accordingly
            parser_type = item.get('parser_type', 'html')
            
            # Handle RAG-based PDF parsing
            if parser_type == 'pdf_rag':
                try:
                    from .parse_pdf_rag import parse_pdf_with_rag
                    
                    rag_tenders = parse_pdf_with_rag(
                        pdf_path=item['url'],  # For logging/reference
                        source_name=item.get('source_name', 'Unknown'),
                        filename=item.get('title', 'document.pdf'),
                        metadata={
                            'url': item['url'],
                            'content_hash': content_hash,
                            'title': item.get('title', '')  # Include quotidien title for date extraction
                        },
                        use_llm=True,
                        pdf_content=content  # Pass the actual PDF bytes
                    )
                    parsed_items.extend(rag_tenders)
                except Exception as e:
                    logger.error(
                        "RAG parsing failed, falling back to standard parsing",
                        error=str(e),
                        run_id=state.run_id
                    )
                    # Continue with other items
                    continue
            
            # Handle quotidien PDFs (legacy parser)
            elif parser_type == 'pdf_quotidien' or item.get('type') == 'quotidien_pdf':
                quotidien_tenders = parse_quotidien_pdf(
                    pdf_content=content,
                    quotidien_url=item['url'],
                    quotidien_title=item.get('title', 'Quotidien des Marchés Publics'),
                    run_id=state.run_id
                )
                parsed_items.extend(quotidien_tenders)
            
            # Handle regular PDF parsing
            elif parser_type == 'pdf':
                # For generic PDFs without special parsing, just log
                logger.info(
                    "PDF content received but no specific parser",
                    url=item['url'],
                    parser_type='pdf'
                )
                # Skip generic PDFs - they need specific handling
                continue
            
            # Handle HTML parsing
            else:
                # Parse HTML content from joffres or other sources
                parsed_item = parse_html_item(
                    content=content,
                    url=item['url'],
                    title=item.get('title', 'Tender'),
                    details=item.get('details'),  # From Joffres extraction
                    run_id=state.run_id
                )
                
                if parsed_item:
                    parsed_items.append(parsed_item)
                else:
                    logger.error(
                        "Failed to parse HTML item",
                        url=item['url'],
                        run_id=state.run_id
                    )
        
        state.items_parsed = parsed_items
        state.update_stats(
            items_parsed=len(parsed_items),
            parse_time_seconds=time.time() - start_time
        )
        
        # Log output to JSON
        log_node_output("parse_extract", parsed_items, run_id=state.run_id)
        
        logger.info(
            "Parse extract completed",
            items_parsed=len(parsed_items),
            run_id=state.run_id
        )
        
        return state
    
    except Exception as e:
        logger.error("Parse extract step failed", error=str(e), run_id=state.run_id, exc_info=True)
        state.add_error("parse_extract", str(e))
        return state