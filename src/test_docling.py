"""Test script to verify Docling works correctly."""

import os
from pathlib import Path
from docling.document_converter import DocumentConverter

# Set cache directories
os.environ['HF_HOME'] = '/app/cache/huggingface'
os.environ['TORCH_HOME'] = '/app/cache/torch'
os.environ['EASYOCR_MODULE_PATH'] = '/app/cache/easyocr'

print("Testing Docling...")
print(f"Cache directory: {os.environ.get('HF_HOME')}")

# Test with the sample quotidien
pdf_path = Path("/app/src/quotidien_sample.pdf")

if not pdf_path.exists():
    print(f"ERROR: PDF not found at {pdf_path}")
    exit(1)

print(f"Processing PDF: {pdf_path}")
print(f"File size: {pdf_path.stat().st_size / 1024 / 1024:.2f} MB")

try:
    # Use a simpler configuration without GLM model
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_table_structure = False  # Disable table structure detection
    pipeline_options.do_ocr = False  # Disable OCR for faster processing
    
    converter = DocumentConverter(
        format_options={
            "pdf": pipeline_options
        }
    )
    print("Docling converter created successfully")
    
    result = converter.convert(str(pdf_path))
    print(f"Conversion complete!")
    print(f"Document has {len(result.document.pages)} pages")
    
    # Get text from first page
    markdown_text = result.document.export_to_markdown()
    print(f"\nFirst 500 characters of extracted text:")
    print(markdown_text[:500])
    
    print("\n✅ Docling is working correctly!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
