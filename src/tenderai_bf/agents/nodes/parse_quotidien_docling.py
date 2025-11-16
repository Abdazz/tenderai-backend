"""Parse quotidien PDF using Docling."""

import re
import uuid
from datetime import datetime
from io import BytesIO
from typing import Dict, List

from ...logging import get_logger

logger = get_logger(__name__)


def parse_quotidien_with_docling(pdf_content: bytes, source_url: str, quotidien_title: str) -> List[Dict]:
    """
    Parse a quotidien PDF using Docling to extract individual tender notices.
    
    Args:
        pdf_content: PDF file content as bytes
        source_url: Source URL of the quotidien
        quotidien_title: Title of the quotidien
        
    Returns:
        List of parsed tender dicts
    """
    from docling.document_converter import DocumentConverter
    from docling.datamodel.pipeline_options import PipelineOptions, EasyOcrOptions
    from tempfile import NamedTemporaryFile
    
    logger.info(
        "Parsing quotidien PDF with Docling",
        title=quotidien_title,
        size_mb=round(len(pdf_content) / (1024 * 1024), 2)
    )
    
    try:
        # Configure Docling
        ocr_options = EasyOcrOptions(
            lang=['fr', 'en'],
            use_gpu=False,
            model_storage_directory='/app/cache/easyocr',
            download_enabled=False  # Models should already be downloaded
        )
        
        pipeline_options = PipelineOptions(
            do_table_structure=True,
            do_ocr=True,
            ocr_options=ocr_options
        )
        
        converter = DocumentConverter(
            artifacts_path='/app/cache/huggingface',
            pipeline_options=pipeline_options
        )
        
        # Save PDF to temp file (Docling requires a file path)
        with NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(pdf_content)
            tmp_path = tmp_file.name
        
        try:
            # Convert PDF to markdown
            result = converter.convert_single(tmp_path)
            text = result.render_as_markdown()  # Fixed: render_as_markdown() instead of document.export_to_markdown()
            
            logger.info(
                "Docling extraction complete",
                chars_extracted=len(text),
                title=quotidien_title
            )
            
            # Now parse the markdown text to extract tenders
            tenders = extract_tenders_from_text(text, source_url, quotidien_title)
            
            return tenders
            
        finally:
            # Clean up temp file
            import os
            try:
                os.unlink(tmp_path)
            except:
                pass
                
    except Exception as e:
        logger.error(
            "Docling parsing failed",
            error=str(e),
            title=quotidien_title
        )
        raise


def extract_tenders_from_text(text: str, source_url: str, quotidien_title: str) -> List[Dict]:
    """
    Extract individual tender notices from extracted text.
    
    Args:
        text: Extracted text from PDF
        source_url: Source URL
        quotidien_title: Title of quotidien
        
    Returns:
        List of tender dicts
    """
    tenders = []
    
    # Find the "Fournitures et Services courants" section
    fournitures_match = re.search(r'Fournitures et Services courants', text, re.IGNORECASE)
    if not fournitures_match:
        logger.error("Could not find 'Fournitures et Services courants' section")
        return tenders
    
    fournitures_start = fournitures_match.start()
    avis_section = text[fournitures_start:]
    
    # Split by tender entries
    # Look for patterns like:
    # - SOCIETE NATIONALE BURKINABE D'HYDROCARBURES (SONABHY)
    # - Avis d'Appel d'Offres / Avis de Demande de Prix
    # - Reference number: N°2025-XXX/...
    
    # Strategy: Split by entity names in all caps followed by procurement type
    entity_pattern = r"([A-ZÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇ\s\-']{10,})\s*(?:Avis d['\"]|Demande de)"
    
    entities = list(re.finditer(entity_pattern, avis_section))
    logger.info(
        f"Found {len(entities)} potential tender entities in quotidien",
        title=quotidien_title
    )
    
    for i, match in enumerate(entities):
        entity_name = match.group(1).strip()
        start_pos = match.start()
        
        # Find end position (start of next entity or end of text)
        if i + 1 < len(entities):
            end_pos = entities[i + 1].start()
        else:
            end_pos = len(avis_section)
        
        tender_block = avis_section[start_pos:end_pos]
        
        # Extract tender information
        tender_info = extract_tender_info(tender_block, entity_name)
        
        if tender_info:
            tender_info.update({
                'id': str(uuid.uuid4()),
                'url': source_url,
                'quotidien_source': quotidien_title,
                'source_type': 'quotidien_pdf'
            })
            tenders.append(tender_info)
            
            # Log each tender found
            logger.info(
                f"Tender {i+1}/{len(entities)} extracted",
                entity=tender_info.get('entity', 'Unknown')[:50],
                title=tender_info.get('title', 'No title')[:80],
                ref_no=tender_info.get('ref_no', 'No ref'),
                category=tender_info.get('category', 'Unknown')
            )
    
    logger.info(
        f"✅ Successfully extracted {len(tenders)} tenders from quotidien",
        title=quotidien_title,
        total_entities_found=len(entities)
    )
    
    return tenders


def extract_tender_info(text: str, entity_name: str) -> Dict:
    """
    Extract structured information from a tender block.
    
    Args:
        text: Tender text block
        entity_name: Detected entity name
        
    Returns:
        Dict with tender information
    """
    info = {
        'entity': entity_name,
        'title': '',
        'ref_no': '',
        'description': '',
        'category': '',
        'deadline_at': None,
        'published_at': datetime.utcnow().isoformat(),
        'location': 'Burkina Faso'
    }
    
    # Extract reference number
    ref_match = re.search(r'N[°o]\s*(\d{4}[-–]\d+[^\n]{0,100})', text)
    if ref_match:
        info['ref_no'] = ref_match.group(0).strip()
    
    # Extract title (usually after "Avis" and before reference)
    title_match = re.search(r"Avis\s+(?:d[''])?([^\n]{10,150})", text, re.IGNORECASE)
    if title_match:
        info['title'] = title_match.group(1).strip()
    else:
        info['title'] = f"Appel d'offres - {entity_name[:50]}"
    
    # Detect procurement type
    if re.search(r"Appel d['']Offres", text, re.IGNORECASE):
        info['category'] = 'Appel d\'Offres'
    elif re.search(r'Demande de Prix', text, re.IGNORECASE):
        info['category'] = 'Demande de Prix'
    elif re.search(r"Manifestation d['']Int[ée]r[êe]t", text, re.IGNORECASE):
        info['category'] = 'Manifestation d\'Intérêt'
    else:
        info['category'] = 'Autre'
    
    # Extract description (first 500 chars of text)
    info['description'] = text[:500].strip()
    
    # Extract deadline if present
    deadline_patterns = [
        r'date limite[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})',
        r'au plus tard le[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})',
        r'd[ée]lai[:\s]+.*?(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})'
    ]
    
    for pattern in deadline_patterns:
        deadline_match = re.search(pattern, text, re.IGNORECASE)
        if deadline_match:
            try:
                date_str = deadline_match.group(1)
                # Parse date (assuming DD/MM/YYYY or DD-MM-YYYY)
                parts = re.split(r'[/\-]', date_str)
                if len(parts) == 3:
                    day, month, year = parts
                    info['deadline_at'] = f"{year}-{month.zfill(2)}-{day.zfill(2)}T23:59:59"
                    break
            except:
                pass
    
    return info
