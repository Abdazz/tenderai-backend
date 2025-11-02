"""TenderAI BF - Multi-agent RFP harvester for Burkina Faso.

A production-grade system that autonomously monitors and harvests
RFP/tender opportunities in IT/Engineering domains across Burkina Faso.
"""

__version__ = "0.1.0"
__author__ = "YULCOM Technologies"
__email__ = "dev@yulcom.com"
__license__ = "Proprietary"

# Re-export commonly used components
from .config import settings
from .db import get_db, get_db_context, get_engine

__all__ = ["settings", "get_db", "get_engine"]