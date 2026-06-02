"""Load and validate active sources for the pipeline."""

import time

from ...db import get_db_context
from ...logging import get_logger
from ...models import Source
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def load_sources_node(state) -> dict:
    """Load active sources from configuration and database."""

    # Clear output file at start
    clear_node_output("load_sources")

    logger.info("Starting load_sources step", run_id=state.run_id)
    start_time = time.time()

    try:
        sources = []

        # If sources are already provided in state, use them
        if state.sources:
            logger.info(
                "Using sources from state",
                count=len(state.sources),
                run_id=state.run_id,
            )
            state.update_stats(sources_checked=len(state.sources))
            return state

        # MODE: Database (DB-first architecture)
        # Sources are seeded into the DB at startup; runtime always reads from DB.
        logger.info("Loading active sources from database", run_id=state.run_id)

        with get_db_context() as session:
            db_sources = (
                session.query(Source)
                .filter(
                    Source.enabled.is_(True),
                    Source.country_id == state.country_id,
                )
                .all()
            )

            for db_source in db_sources:
                source_data = {
                    "id": db_source.id,
                    "name": db_source.name,
                    "base_url": db_source.base_url,
                    "list_url": db_source.list_url,
                    "parser_type": db_source.parser_type,
                    "rate_limit": db_source.rate_limit,
                    "patterns": db_source.patterns or {},
                    "last_seen_at": db_source.last_seen_at.isoformat()
                    if db_source.last_seen_at
                    else None,
                    "last_success_at": db_source.last_success_at.isoformat()
                    if db_source.last_success_at
                    else None,
                    "last_error_at": db_source.last_error_at.isoformat()
                    if db_source.last_error_at
                    else None,
                    "last_error_message": db_source.last_error_message,
                }
                sources.append(source_data)
                logger.debug(
                    "Source loaded from DB",
                    source_name=db_source.name,
                    run_id=state.run_id,
                )

        logger.info(
            "Loaded sources from database",
            count=len(sources),
            run_id=state.run_id,
        )

        # Update state
        state.sources = sources
        state.update_stats(sources_checked=len(sources))

        # Log output to JSON
        log_node_output("load_sources", sources, run_id=state.run_id)

        # Log completion
        duration = time.time() - start_time
        logger.info(
            "Load sources completed (Database mode)",
            sources_loaded=len(sources),
            duration_seconds=duration,
            run_id=state.run_id,
        )

        # If no sources found, this is an error condition
        if not sources:
            state.add_error(
                "load_sources",
                "No active sources found to monitor",
                config_sources_count=len(config_sources),
            )
            state.should_continue = False

        return state

    except Exception as e:
        logger.error(
            "Load sources step failed", error=str(e), run_id=state.run_id, exc_info=True
        )
        state.add_error("load_sources", str(e))
        state.should_continue = False
        return state
