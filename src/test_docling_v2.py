#!/usr/bin/env python3
"""Test Docling PDF extraction."""

import os
import sys
from pathlib import Path

print("Testing Docling...")
print(f"Cache directory: {os.getenv('HF_HOME', 'Not set')}")

try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.pipeline_options import PipelineOptions, EasyOcrOptions
    
    # Configure pipeline to use our cache directory
    ocr_options = EasyOcrOptions(
        lang=['fr', 'en'],
        use_gpu=False,  # CPU mode for compatibility
        model_storage_directory='/app/cache/easyocr',
        download_enabled=True
    )
    
    pipeline_options = PipelineOptions(
        do_table_structure=True,
        do_ocr=True,
        ocr_options=ocr_options
    )
    
    # Initialize converter
    print("Initializing DocumentConverter...")
    converter = DocumentConverter(
        artifacts_path='/app/cache/huggingface',
        pipeline_options=pipeline_options
    )
    
    # Test with sample PDF
    pdf_path = Path('/app/src/quotidien_sample.pdf')
    if not pdf_path.exists():
        print(f"❌ PDF file not found: {pdf_path}")
        sys.exit(1)
    
    print(f"Processing PDF: {pdf_path}")
    print(f"File size: {pdf_path.stat().st_size / (1024*1024):.2f} MB")
    
    # Convert PDF
    print("Converting PDF (this may take a while on first run)...")
    result = converter.convert_single(str(pdf_path))
    
    # Extract text
    text = result.document.export_to_markdown()
    
    print(f"\n✅ Success! Extracted {len(text)} characters")
    print(f"First 500 characters:\n{text[:500]}")
    
    # Count "AVIS" occurrences
    avis_count = text.count('AVIS')
    print(f"\n'AVIS' found: {avis_count} times")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
