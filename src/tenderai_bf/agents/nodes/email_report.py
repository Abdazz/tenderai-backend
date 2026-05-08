"""Send the report via email.

Email delivery is treated as best-effort: if the report itself was generated
and uploaded to object storage, an SMTP failure must NOT mark the whole run
as failed. Instead, the node records a non-fatal warning via
``state.add_warning(...)`` and the orchestrator finalises the run as
``completed_with_warnings``. Truly fatal cases (e.g. no report to send,
schema-level errors) remain errors via ``state.add_error(...)``.
"""

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

    # Fatal pre-conditions: without a report there is nothing to send and the
    # run is genuinely broken. These remain errors so the pipeline is marked
    # `failed` and the error_handler runs.
    if not state.report_bytes or not state.report_url:
        msg = "No report available to send"
        logger.error(msg, run_id=state.run_id)
        state.add_error("email_report", msg)
        return state

    # Resolve recipients (also fatal if empty: misconfiguration, not transient).
    recipients = []
    if settings.email.to_address:
        recipients.append(settings.email.to_address)
    if settings.recipients:
        for recipient in settings.recipients:
            if 'email' in recipient and recipient['email'] not in recipients:
                recipients.append(recipient['email'])
    if not recipients:
        msg = "No email recipients configured"
        logger.error(msg, run_id=state.run_id)
        state.add_error("email_report", msg)
        return state

    logger.info(
        "Report recipients loaded",
        recipients_count=len(recipients),
        recipients=recipients,
        run_id=state.run_id,
    )

    # Anything from here on is treated as a non-fatal email-delivery issue:
    # the report is already on MinIO and the run produced its expected output.
    success = False
    delivery_error: str = ""
    try:
        success = send_report_email(
            report_data=state.report_bytes,
            report_url=state.report_url,
            run_id=state.run_id,
            stats=state.stats.dict(),
            recipients=recipients,
        )
        if not success:
            delivery_error = "send_report_email returned False (SMTP rejected delivery)"
    except Exception as e:
        delivery_error = str(e)
        logger.error(
            "Email delivery raised an exception — report remains available on MinIO",
            error=delivery_error,
            run_id=state.run_id,
            report_url=state.report_url,
            exc_info=True,
        )

    email_time = time.time() - start_time

    if not success:
        state.add_warning(
            "email_report",
            f"Email delivery failed but report is available on MinIO: {delivery_error}",
            report_url=state.report_url,
            recipients_count=len(recipients),
        )

    state.email_status = {
        'success': success,
        'recipients_count': len(recipients),
        'sent_at': time.time(),
        'error': delivery_error if not success else None,
    }

    # Total pipeline time (formatted) + per-step stats are still useful even
    # when email delivery failed, since the report is still produced.
    total_time_seconds = (datetime.utcnow() - state.started_at).total_seconds()
    hours = int(total_time_seconds // 3600)
    minutes = int((total_time_seconds % 3600) // 60)
    seconds = int(total_time_seconds % 60)
    total_time_formatted = f"{hours} h, {minutes} m, {seconds} s"

    state.update_stats(
        emails_sent=len(recipients) if success else 0,
        email_time_seconds=email_time,
        total_time_seconds=total_time_seconds,
        total_time_formatted=total_time_formatted,
    )

    log_node_output(
        "email_report",
        {
            **state.email_status,
            'final_statistics': state.stats.dict(),
        },
        run_id=state.run_id,
    )

    logger.info(
        "Email report step finished",
        success=success,
        recipients_count=len(recipients),
        run_id=state.run_id,
    )

    return state