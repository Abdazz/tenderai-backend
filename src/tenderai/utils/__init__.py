"""Utility functions package."""

from .dates import (
    BURKINA_FASO_TZ,
    format_deadline,
    format_french_date,
    get_burkina_faso_now,
    get_next_business_day,
    is_business_day,
    is_deadline_urgent,
    parse_deadline,
    parse_french_date,
    time_until_deadline,
    to_burkina_faso_time,
)
from .pdf import (
    PDFProcessor,
    clean_extracted_text,
    extract_pdf_metadata,
    extract_pdf_text,
    extract_pdf_text_from_bytes,
    get_pdf_info,
    is_pdf_file,
    validate_pdf_file,
)
from .robots import (
    RobotsChecker,
    can_fetch_url,
    get_crawl_delay,
    get_default_user_agent,
    get_request_rate,
    is_respectful_delay,
    validate_user_agent,
)

__all__ = [
    # Date utilities
    "parse_french_date",
    "parse_deadline",
    "get_burkina_faso_now",
    "to_burkina_faso_time",
    "format_french_date",
    "format_deadline",
    "is_business_day",
    "get_next_business_day",
    "time_until_deadline",
    "is_deadline_urgent",
    "BURKINA_FASO_TZ",
    # PDF utilities
    "extract_pdf_text",
    "extract_pdf_text_from_bytes",
    "get_pdf_info",
    "validate_pdf_file",
    "is_pdf_file",
    "clean_extracted_text",
    "extract_pdf_metadata",
    "PDFProcessor",
    # Robots utilities
    "can_fetch_url",
    "get_crawl_delay",
    "get_request_rate",
    "is_respectful_delay",
    "validate_user_agent",
    "get_default_user_agent",
    "RobotsChecker",
]
