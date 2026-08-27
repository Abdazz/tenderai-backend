"""TenderAI BF - Multi-agent RFP harvester for Burkina Faso.

A production-grade system that autonomously monitors and harvests
RFP/tender opportunities in IT/Engineering domains across Burkina Faso.
"""

# bcrypt 4.x removed __about__; passlib 1.7.4 requires it for version detection.
import types as _types

import bcrypt as _bcrypt

if not hasattr(_bcrypt, "__about__"):
    _bcrypt.__about__ = _types.SimpleNamespace(__version__=_bcrypt.__version__)
del _bcrypt, _types

__version__ = "0.1.0"
__author__ = "YULCOM Technologies"
__email__ = "dev@yulcom.com"
__license__ = "Proprietary"

# Re-export commonly used components
from .config import settings  # noqa: E402
from .db import get_db, get_engine  # noqa: E402

# Both imports above must run after the bcrypt/passlib compat shim.

__all__ = ["settings", "get_db", "get_engine"]
