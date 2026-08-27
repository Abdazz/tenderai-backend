"""Select Notice rows a company hasn't classified yet, for one country.

A CompanyNoticeStatus row's absence is the delivery cursor — a Notice with
no row for this (company_id, notice_id) pair hasn't been classified/seen by
this company yet.
"""

import time

from sqlalchemy import and_, not_, select

from ...db import get_db_context
from ...logging import get_logger
from ...models import CompanyNoticeStatus, Notice, Source
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def _notice_to_classify_dict(notice: Notice) -> dict:
    """Shape a Notice row into the dict format classify_node already consumes."""
    return {
        "id": notice.id,
        "title": notice.title,
        "tender_object": notice.title,
        "ref_no": notice.ref_no,
        "reference": notice.ref_no,
        "entity": notice.entity,
        "category": notice.category,
        "published_at": notice.published_at.isoformat()
        if notice.published_at
        else None,
        "deadline_at": notice.deadline_at.isoformat() if notice.deadline_at else None,
        "deadline": notice.deadline_at.isoformat() if notice.deadline_at else None,
        "location": notice.location,
        "budget_xof": notice.budget_xof,
        "currency": notice.currency,
        "description": notice.description,
        "url": notice.url,
        "content_hash": notice.content_hash,
        "keywords": [],
    }


def select_new_notices_node(state) -> dict:
    """Load unclassified Notice rows for this (company, country) pair."""

    clear_node_output("select_new_notices")

    if state.error_occurred:
        return state

    logger.info(
        "Starting select_new_notices step",
        company_id=state.company_id,
        country_id=state.country_id,
        run_id=state.run_id,
    )
    start_time = time.time()

    try:
        with get_db_context() as db:
            already_classified = select(CompanyNoticeStatus.notice_id).where(
                CompanyNoticeStatus.company_id == state.company_id
            )
            notices = (
                db.query(Notice)
                .join(Source, Notice.source_id == Source.id)
                .filter(
                    and_(
                        Source.country_id == state.country_id,
                        not_(Notice.id.in_(already_classified)),
                    )
                )
                .all()
            )
            items = [_notice_to_classify_dict(n) for n in notices]

        state.items_parsed = items
        state.update_stats(items_parsed=len(items))

        log_node_output("select_new_notices", items, run_id=state.run_id)

        logger.info(
            "Select new notices completed",
            count=len(items),
            company_id=state.company_id,
            country_id=state.country_id,
            duration_seconds=time.time() - start_time,
            run_id=state.run_id,
        )

        return state

    except Exception as e:
        logger.error(
            "Select new notices step failed",
            error=str(e),
            run_id=state.run_id,
            exc_info=True,
        )
        state.add_error("select_new_notices", str(e))
        return state
