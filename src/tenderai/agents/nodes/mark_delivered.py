"""Mark CompanyNoticeStatus rows as delivered for whichever notices made it
into the sent report."""

import time
from datetime import datetime

from ...db import get_db_context
from ...logging import get_logger
from ...models import CompanyNoticeStatus
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def mark_delivered_node(state) -> dict:
    """Set delivered_at on the CompanyNoticeStatus rows for reported items."""

    clear_node_output("mark_delivered")

    if state.error_occurred:
        return state

    logger.info("Starting mark_delivered step", run_id=state.run_id)
    start_time = time.time()

    reported_items = getattr(state, "unique_items", None) or []
    notice_ids = [item["id"] for item in reported_items if item.get("id")]

    if not notice_ids:
        logger.info("No delivered items to mark", run_id=state.run_id)
        return state

    try:
        with get_db_context() as db:
            rows = (
                db.query(CompanyNoticeStatus)
                .filter(
                    CompanyNoticeStatus.company_id == state.company_id,
                    CompanyNoticeStatus.notice_id.in_(notice_ids),
                )
                .all()
            )
            now = datetime.utcnow()
            for row in rows:
                row.delivered_at = now
            db.commit()

        log_node_output(
            "mark_delivered", {"marked_count": len(rows)}, run_id=state.run_id
        )

        logger.info(
            "Mark delivered completed",
            marked_count=len(rows),
            duration_seconds=time.time() - start_time,
            run_id=state.run_id,
        )

        return state

    except Exception as e:
        logger.error(
            "Mark delivered step failed",
            error=str(e),
            run_id=state.run_id,
            exc_info=True,
        )
        state.add_error("mark_delivered", str(e))
        return state
