"""Send the report via email."""

import time
from datetime import datetime
from typing import Dict

from ...config import settings
from ...email import send_report_email
from ...logging import get_logger
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def email_report_node(state) -> Dict:
    """Send the generated report via email."""
    
    # Clear output file at start
    clear_node_output("email_report")
    
    logger.info("Starting email_report step", run_id=state.run_id)
    start_time = time.time()
    
    # Check if email should be sent (access as dict or object attribute)
    send_email = getattr(state, 'send_email', True) if hasattr(state, 'send_email') else state.get('send_email', True)
    
    if not send_email:
        logger.info("Email sending disabled, skipping", run_id=state.run_id)
        state.email_status = {
            'success': True,
            'skipped': True,
            'reason': 'send_email flag is False'
        }
        return state
    
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
        
        # Calculate email time
        email_time = time.time() - start_time
        
        # Update stats (including emails_sent, email_time, and total_time)
        if success:
            emails_sent = len(recipients)
        else:
            emails_sent = 0
            state.add_error("email_report", "Failed to send report email")
        
        # Calculate total pipeline time (including all nodes)
        total_time_seconds = (datetime.utcnow() - state.started_at).total_seconds()
        
        # Format total time as "X h Y m Z s"
        hours = int(total_time_seconds // 3600)
        minutes = int((total_time_seconds % 3600) // 60)
        seconds = int(total_time_seconds % 60)
        total_time_formatted = f"{hours} h, {minutes} m, {seconds} s"
        
        # Update all final stats at once
        state.update_stats(
            emails_sent=emails_sent,
            email_time_seconds=email_time,
            total_time_seconds=total_time_seconds,
            total_time_formatted=total_time_formatted
        )
        
        # Log output to JSON (including final statistics)
        log_node_output("email_report", {
            **state.email_status,
            'final_statistics': state.stats.dict()  # Include complete final stats
        }, run_id=state.run_id)
        
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