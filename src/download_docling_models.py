#!/usr/bin/env python3
"""Download Docling models."""

from pathlib import Path
from docling.document_converter import DocumentConverter

cache_dir = Path('/app/cache/huggingface')
print(f"Downloading Docling models to {cache_dir}...")

try:
    result_path = DocumentConverter.download_models_hf(local_dir=cache_dir, force=True)
    print(f"✅ Models downloaded successfully to: {result_path}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
