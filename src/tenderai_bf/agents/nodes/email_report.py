"""Send the report via email."""

import time
from typing import Dict

from ...config import settings
from ...email import send_report_email
from ...logging import get_logger

logger = get_logger(__name__)


def email_report_node(state) -> Dict:
    """Send the generated report via email."""
    
    logger.info("Starting email_report step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        if not state.report_bytes or not state.report_url:
            raise Exception("No report available to send")
        
        # Prepare email data
        stats = state.stats.dict()
        recipients = [settings.email.to_address]  # TODO: Load from database
        
        # Send email
        success = send_report_email(
            report_data=state.report_bytes,
            report_url=state.report_url,
            run_id=state.run_id,
            stats=stats,
            recipients=recipients
        )
        
        # Update state
        state.email_status = {
            'success': success,
            'recipients_count': len(recipients),
            'sent_at': time.time()
        }
        
        if success:
            state.update_stats(emails_sent=len(recipients))
        else:
            state.add_error("email_report", "Failed to send report email")
        
        state.update_stats(email_time_seconds=time.time() - start_time)
        
        logger.info(
            "Email report completed",
            success=success,
            recipients_count=len(recipients),
            run_id=state.run_id
        )
        
        return state
    
    except Exception as e:
        logger.error("Email report step failed", error=str(e), run_id=state.run_id, exc_info=True)
        state.add_error("email_report", str(e))
        return state