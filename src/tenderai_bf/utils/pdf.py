"""PDF processing utilities."""

import io
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pdfminer.high_level import extract_text as pdfminer_extract_text
from pdfminer.layout import LAParams
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.layout import LTTextContainer

try:
    from docling import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PipelineOptions
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False

from ..logging import get_logger

logger = get_logger(__name__)


class PDFProcessor:
    """PDF processing and text extraction."""
    
    def __init__(self):
        self.docling_converter = None
        if DOCLING_AVAILABLE:
            try:
                # Initialize Docling converter with options
                pipeline_options = PipelineOptions(
                    do_ocr=True,
                    do_table_structure=True,
                    table_structure_options={"do_cell_matching": True}
                )
                self.docling_converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: pipeline_options
                    }
                )
                logger.info("Docling converter initialized successfully")
            except Exception as e:
                logger.error("Failed to initialize Docling converter", error=str(e))
                self.docling_converter = None
    
    def extract_text(self, pdf_path: str, method: str = "auto") -> str:
        """Extract text from PDF file.
        
        Args:
            pdf_path: Path to PDF file
            method: Extraction method ("auto", "pdfminer", "docling")
            
        Returns:
            Extracted text content
        """
        
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        if method == "auto":
            # Try Docling first if available, fallback to pdfminer
            if self.docling_converter is not None:
                try:
                    return self._extract_with_docling(pdf_path)
                except Exception as e:
                    logger.error(
                        "Docling extraction failed, falling back to pdfminer",
                        pdf_path=pdf_path,
                        error=str(e)
                    )
            
            return self._extract_with_pdfminer(pdf_path)
        
        elif method == "docling":
            if self.docling_converter is None:
                raise RuntimeError("Docling not available")
            return self._extract_with_docling(pdf_path)
        
        elif method == "pdfminer":
            return self._extract_with_pdfminer(pdf_path)
        
        else:
            raise ValueError(f"Unknown extraction method: {method}")
    
    def _extract_with_docling(self, pdf_path: str) -> str:
        """Extract text using Docling (with OCR support).
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted text content
        """
        
        try:
            # Convert PDF
            result = self.docling_converter.convert(pdf_path)
            
            # Extract text content
            text_content = result.document.export_to_markdown()
            
            logger.debug(
                "Docling extraction completed",
                pdf_path=pdf_path,
                text_length=len(text_content)
            )
            
            return text_content
        
        except Exception as e:
            logger.error(
                "Docling extraction failed",
                pdf_path=pdf_path,
                error=str(e)
            )
            raise
    
    def _extract_with_pdfminer(self, pdf_path: str) -> str:
        """Extract text using pdfminer.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted text content
        """
        
        try:
            # Configure layout analysis parameters
            laparams = LAParams(
                line_margin=0.5,
                word_margin=0.1,
                char_margin=2.0,
                boxes_flow=0.5,
                all_texts=False
            )
            
            text = pdfminer_extract_text(pdf_path, laparams=laparams)
            
            logger.debug(
                "PDFMiner extraction completed",
                pdf_path=pdf_path,
                text_length=len(text)
            )
            
            return text
        
        except Exception as e:
            logger.error(
                "PDFMiner extraction failed",
                pdf_path=pdf_path,
                error=str(e)
            )
            raise
    
    def extract_text_from_bytes(self, pdf_bytes: bytes, method: str = "auto") -> str:
        """Extract text from PDF bytes.
        
        Args:
            pdf_bytes: PDF file content as bytes
            method: Extraction method ("auto", "pdfminer", "docling")
            
        Returns:
            Extracted text content
        """
        
        # Write to temporary file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(pdf_bytes)
            tmp_path = tmp_file.name
        
        try:
            return self.extract_text(tmp_path, method=method)
        finally:
            # Clean up temporary file
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    
    def get_pdf_info(self, pdf_path: str) -> Dict[str, any]:
        """Get PDF metadata and basic info.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Dictionary with PDF information
        """
        
        info = {
            'file_path': pdf_path,
            'file_size': 0,
            'page_count': 0,
            'title': None,
            'author': None,
            'subject': None,
            'creator': None,
            'creation_date': None,
            'modification_date': None
        }
        
        try:
            # Get file size
            if os.path.exists(pdf_path):
                info['file_size'] = os.path.getsize(pdf_path)
            
            # Get page count and metadata
            with open(pdf_path, 'rb') as file:
                pages = list(PDFPage.get_pages(file))
                info['page_count'] = len(pages)
                
                # Try to get metadata (basic attempt)
                # Note: Full metadata extraction would require more complex parsing
                
        except Exception as e:
            logger.error(
                "Failed to get PDF info",
                pdf_path=pdf_path,
                error=str(e)
            )
        
        return info
    
    def validate_pdf(self, pdf_path: str) -> Tuple[bool, Optional[str]]:
        """Validate PDF file.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        
        try:
            if not os.path.exists(pdf_path):
                return False, "File does not exist"
            
            if os.path.getsize(pdf_path) == 0:
                return False, "File is empty"
            
            # Try to read first page
            with open(pdf_path, 'rb') as file:
                pages = list(PDFPage.get_pages(file, maxpages=1))
                if not pages:
                    return False, "No pages found"
            
            return True, None
        
        except Exception as e:
            return False, str(e)


# Global instance
_pdf_processor = PDFProcessor()


def extract_pdf_text(pdf_path: str, method: str = "auto") -> str:
    """Extract text from PDF file.
    
    Args:
        pdf_path: Path to PDF file
        method: Extraction method ("auto", "pdfminer", "docling")
        
    Returns:
        Extracted text content
    """
    return _pdf_processor.extract_text(pdf_path, method=method)


def extract_pdf_text_from_bytes(pdf_bytes: bytes, method: str = "auto") -> str:
    """Extract text from PDF bytes.
    
    Args:
        pdf_bytes: PDF file content as bytes
        method: Extraction method ("auto", "pdfminer", "docling")
        
    Returns:
        Extracted text content
    """
    return _pdf_processor.extract_text_from_bytes(pdf_bytes, method=method)


def get_pdf_info(pdf_path: str) -> Dict[str, any]:
    """Get PDF metadata and basic info.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Dictionary with PDF information
    """
    return _pdf_processor.get_pdf_info(pdf_path)


def validate_pdf_file(pdf_path: str) -> Tuple[bool, Optional[str]]:
    """Validate PDF file.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    return _pdf_processor.validate_pdf(pdf_path)


def is_pdf_file(file_path: str) -> bool:
    """Check if file is a PDF based on extension and magic bytes.
    
    Args:
        file_path: Path to file
        
    Returns:
        True if file appears to be a PDF
    """
    
    # Check extension
    if not file_path.lower().endswith('.pdf'):
        return False
    
    # Check magic bytes
    try:
        with open(file_path, 'rb') as f:
            header = f.read(4)
            return header == b'%PDF'
    except:
        return False


def clean_extracted_text(text: str) -> str:
    """Clean and normalize extracted PDF text.
    
    Args:
        text: Raw extracted text
        
    Returns:
        Cleaned text
    """
    
    if not text:
        return ""
    
    # Remove excessive whitespace
    import re
    
    # Replace multiple spaces with single space
    text = re.sub(r' +', ' ', text)
    
    # Replace multiple newlines with double newline
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Remove trailing/leading whitespace from lines
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    
    # Remove excessive leading/trailing whitespace
    text = text.strip()
    
    return text


def extract_pdf_metadata(pdf_path: str) -> Dict[str, str]:
    """Extract metadata from PDF file.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Dictionary with metadata fields
    """
    
    metadata = {}
    
    try:
        info = get_pdf_info(pdf_path)
        
        # Convert relevant fields to strings
        for key, value in info.items():
            if value is not None:
                metadata[key] = str(value)
        
    except Exception as e:
        logger.error(
            "Failed to extract PDF metadata",
            pdf_path=pdf_path,
            error=str(e)
        )
    
    return metadata