"""Select Notice rows a company still needs classified/delivered, for one country.

The delivery cursor is NOT simply "does a CompanyNoticeStatus row exist" —
that row is written at classify time, before summarize/compose_report/
email_report run, so a mid-pipeline failure (MinIO down, SMTP misconfigured,
no recipients) would otherwise strand the notice with a row but no actual
delivery, and it would never be re-offered. A notice is excluded only when
it was judged not relevant (is_relevant=False, regardless of delivered_at),
or it was judged relevant AND already delivered (is_relevant=True and
delivered_at IS NOT NULL). Everything else — no row at all, or a row with
is_relevant=True and delivered_at IS NULL (classified but never
successfully delivered) — is returned again.
"""

import time

from sqlalchemy import and_, not_, or_, select

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
            # A notice is excluded only if it was rejected (is_relevant=False,
            # regardless of delivered_at) or it was judged relevant and has
            # already been successfully delivered. A relevant-but-undelivered
            # row (delivered_at IS NULL) is NOT excluded — it's retried.
            excluded_notice_ids = select(CompanyNoticeStatus.notice_id).where(
                CompanyNoticeStatus.company_id == state.company_id,
                or_(
                    CompanyNoticeStatus.is_relevant.is_(False),
                    and_(
                        CompanyNoticeStatus.is_relevant.is_(True),
                        CompanyNoticeStatus.delivered_at.isnot(None),
                    ),
                ),
            )
            notices = (
                db.query(Notice)
                .join(Source, Notice.source_id == Source.id)
                .filter(
                    and_(
                        Source.country_id == state.country_id,
                        not_(Notice.id.in_(excluded_notice_ids)),
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
