"""Test package initialization."""

import os
import sys
from pathlib import Path

# Add src to Python path for testing
src_path = Path(__file__).parent.parent / 'src'
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Set test environment variables
os.environ.setdefault('TENDERAI_ENVIRONMENT', 'test')
os.environ.setdefault('TENDERAI_DEBUG', 'true')
os.environ.setdefault('TENDERAI_DATABASE_URL', 'sqlite:///test.db')