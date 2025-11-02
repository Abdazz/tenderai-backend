"""Compose the final DOCX report."""

import time
from datetime import datetime
from typing import Dict

from ...logging import get_logger
from ...report.docx_report import build_report
from ...storage import get_storage_client

logger = get_logger(__name__)


def compose_report_node(state) -> Dict:
    """Generate and store the final DOCX report."""
    
    logger.info("Starting compose_report step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        # Prepare report data
        report_data = {
            'run_id': state.run_id,
            'generated_at': datetime.utcnow(),
            'statistics': state.stats.dict(),
            'notices': state.unique_items,
            'sources': state.sources,
            'errors': state.errors
        }
        
        # Generate DOCX report
        report_bytes = build_report(report_data)
        
        if not report_bytes:
            raise Exception("Report generation failed - no bytes returned")
        
        # Store report in MinIO
        storage_client = get_storage_client()
        report_url = storage_client.store_report(
            report_data=report_bytes,
            run_id=state.run_id,
            timestamp=datetime.utcnow()
        )
        
        if not report_url:
            raise Exception("Failed to store report in MinIO")
        
        # Update state
        state.report_bytes = report_bytes
        state.report_url = report_url
        state.update_stats(
            reports_generated=1,
            report_time_seconds=time.time() - start_time
        )
        
        logger.info(
            "Compose report completed",
            report_size=len(report_bytes),
            report_url=report_url,
            run_id=state.run_id
        )
        
        return state
    
    except Exception as e:
        logger.error("Compose report step failed", error=str(e), run_id=state.run_id, exc_info=True)
        state.add_error("compose_report", str(e))
        return state