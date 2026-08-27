"""Persist deduplicated harvest items as Notice rows.

Structural persistence only — is_relevant/relevance_score/classification_method
are never written here (harvest has no relevance information; classify_node in
the delivery graph is the sole place relevance is decided, per company).

Source attribution is best-effort: most item types today don't reliably carry
a field that matches a Source.id row (verified directly against the pipeline's
actual fetchers/parsers, not assumed) — see this plan's Global Constraints.
Items whose source can't be confidently resolved are skipped with a non-fatal
warning rather than persisted with a guessed source_id.
"""

import time
import uuid

from ...db import get_db_context
from ...logging import get_logger
from ...models import Notice
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def _resolve_source_id(item: dict, sources: list[dict]) -> int | None:
    """Best-effort source_id resolution. See module docstring for the fallback order."""
    source_name = (item.get("source_name") or "").strip().lower()
    if source_name:
        for s in sources:
            if s["name"].strip().lower() == source_name:
                return s["id"]

    source_tag = (item.get("source") or "").strip().lower()
    if source_tag:
        matches = [s for s in sources if source_tag in s["name"].strip().lower()]
        if len(matches) == 1:
            return matches[0]["id"]

    if len(sources) == 1:
        return sources[0]["id"]

    return None


def persist_notices_node(state) -> dict:
    """Insert a Notice row for each deduplicated harvest item."""

    clear_node_output("persist_notices")

    if state.error_occurred:
        return state

    logger.info("Starting persist_notices step", run_id=state.run_id)
    start_time = time.time()

    items = getattr(state, "unique_items", None) or []
    sources = getattr(state, "sources", None) or []

    persisted_count = 0
    skipped_count = 0

    try:
        with get_db_context() as db:
            for item in items:
                source_id = _resolve_source_id(item, sources)
                if source_id is None:
                    skipped_count += 1
                    state.add_warning(
                        "persist_notices",
                        "Could not resolve source for item — skipped",
                        item_id=item.get("id"),
                        item_source=item.get("source") or item.get("source_name"),
                    )
                    continue

                notice = Notice(
                    id=item.get("id") or str(uuid.uuid4()),
                    source_id=source_id,
                    run_id=state.run_id,
                    title=item.get("title") or item.get("tender_object") or "",
                    ref_no=item.get("ref_no") or item.get("reference"),
                    entity=item.get("entity"),
                    category=item.get("category"),
                    published_at=item.get("published_at"),
                    deadline_at=item.get("deadline_at") or item.get("deadline"),
                    location=item.get("location"),
                    budget_xof=item.get("budget_xof"),
                    currency=item.get("currency"),
                    description=item.get("description"),
                    content_hash=item.get("content_hash") or "",
                    is_duplicate=bool(item.get("is_duplicate", False)),
                    duplicate_of_id=item.get("duplicate_of_id"),
                    url=item.get("url") or "",
                )
                db.add(notice)
                persisted_count += 1

            db.commit()

        state.update_stats(
            notices_persisted=persisted_count,
            persist_time_seconds=time.time() - start_time,
        )

        log_node_output(
            "persist_notices",
            {"persisted": persisted_count, "skipped": skipped_count},
            run_id=state.run_id,
        )

        logger.info(
            "Persist notices completed",
            persisted=persisted_count,
            skipped=skipped_count,
            run_id=state.run_id,
        )

        return state

    except Exception as e:
        logger.error(
            "Persist notices step failed", error=str(e), run_id=state.run_id, exc_info=True
        )
        state.add_error("persist_notices", str(e))
        return state
