"""LangGraph pipeline for delivering classified notices to one company.

Mirrors agents/graph.py's TenderAIGraph structure (_route_after_step,
error_handler — imported, not duplicated) but for the delivery side:
select_new_notices -> classify -> summarize -> compose_report ->
email_report -> mark_delivered.
"""

import threading
import time
from datetime import datetime

from langgraph.graph import END, StateGraph

from ..company_store import CompanyStore
from ..country_store import CountryStore
from ..db import get_db_context
from ..logging import get_logger, log_run_complete, log_run_error, log_run_start
from ..models import Company, Country as CountryModel, Run, Source
from .graph import TenderAIGraph, TenderAIState, _route_after_step, error_handler
from .nodes.classify import classify_node
from .nodes.compose_report import compose_report_node
from .nodes.email_report import email_report_node
from .nodes.mark_delivered import mark_delivered_node
from .nodes.select_new_notices import select_new_notices_node
from .nodes.summarize import summarize_node

logger = get_logger(__name__)


class DeliveryGraph:
    """LangGraph pipeline for delivering one company's classified notices."""

    def __init__(self):
        self.graph = self._build_graph()
        self.app = self.graph.compile()
        logger.info("Delivery pipeline graph initialized")

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(TenderAIState)

        workflow.add_node("select_new_notices", select_new_notices_node)
        workflow.add_node("classify", classify_node)
        workflow.add_node("summarize", summarize_node)
        workflow.add_node("compose_report", compose_report_node)
        workflow.add_node("email_report", email_report_node)
        workflow.add_node("mark_delivered", mark_delivered_node)
        workflow.add_node("error_handler", error_handler)

        workflow.set_entry_point("select_new_notices")

        sequential_edges = [
            ("select_new_notices", "classify"),
            ("classify", "summarize"),
            ("summarize", "compose_report"),
            ("compose_report", "email_report"),
        ]
        for src, dst in sequential_edges:
            workflow.add_conditional_edges(
                src,
                _route_after_step,
                {"continue": dst, "error_handler": "error_handler"},
            )

        # mark_delivered runs even after a non-fatal email warning, same
        # rationale as TenderAIGraph's email_report -> END edge.
        workflow.add_conditional_edges(
            "email_report",
            _route_after_step,
            {"continue": "mark_delivered", "error_handler": "error_handler"},
        )
        workflow.add_conditional_edges(
            "mark_delivered",
            _route_after_step,
            {"continue": END, "error_handler": "error_handler"},
        )

        workflow.add_edge("error_handler", END)

        return workflow

    def run(
        self,
        company_id: int,
        country_id: int,
        triggered_by: str = "scheduler",
        triggered_by_user: str | None = None,
        test_mode: bool = False,
    ) -> TenderAIState:
        """Execute the delivery pipeline for one (company, country) pair."""

        state = TenderAIState()
        run_id = state.run_id

        # Load country AND company context — classify needs country_config
        # (llm.provider) and company_config (classification), both.
        try:
            with get_db_context() as _db:
                _country = (
                    _db.query(CountryModel)
                    .filter(CountryModel.id == country_id)
                    .first()
                )
                if not _country:
                    state.add_error("delivery", f"Country {country_id} not found")
                    state.error_occurred = True
                    return state
                _company = _db.query(Company).filter(Company.id == company_id).first()
                if not _company:
                    state.add_error("delivery", f"Company {company_id} not found")
                    state.error_occurred = True
                    return state

                state.country_id = country_id
                state.country_name = _country.name
                state.country_locale = _country.locale
                state.country_config = CountryStore.get_all_with_fallback(
                    _db, country_id
                )

                state.company_id = company_id
                state.company_config = CompanyStore.get_all_with_fallback(
                    _db, company_id
                )

                # compose_report_node/docx_report.py read state.sources to render
                # the "sources consultées" section — without this it always
                # shows 0, since the delivery graph has no load_sources step of
                # its own. Shape matches load_sources_node's dicts exactly.
                db_sources = (
                    _db.query(Source)
                    .filter(
                        Source.country_id == country_id,
                        Source.enabled.is_(True),
                    )
                    .all()
                )
                state.sources = [
                    {
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
                    for db_source in db_sources
                ]
        except Exception as _e:
            state.add_error("delivery", f"Failed to load country/company config: {_e}")
            state.error_occurred = True
            return state

        log_run_start(
            run_id,
            triggered_by=triggered_by,
            triggered_by_user=triggered_by_user,
            sources_count=len(state.sources),
        )

        state.test_mode = test_mode

        try:
            with get_db_context() as session:
                run = Run(
                    id=run_id,
                    status="running",
                    started_at=state.started_at,
                    triggered_by=triggered_by,
                    triggered_by_user=triggered_by_user,
                    country_id=country_id,
                    run_type="delivery",
                    company_id=company_id,
                )
                session.add(run)
                session.commit()
        except Exception as e:
            logger.error("Failed to create run record", error=str(e), run_id=run_id)

        try:
            start_time = time.time()
            raw_final = self.app.invoke(state)
            duration = time.time() - start_time

            final_state = TenderAIGraph._coerce_to_state(raw_final)
            final_state.stats.total_time_seconds = duration

            if final_state.error_occurred:
                run_status = "failed"
            elif final_state.warnings:
                run_status = "completed_with_warnings"
            else:
                run_status = "completed"

            try:
                with get_db_context() as session:
                    run = session.query(Run).filter(Run.id == run_id).first()
                    if run:
                        run.status = run_status
                        run.finished_at = datetime.utcnow()
                        run.counts_json = final_state.stats.dict()
                        run.report_url = final_state.report_url
                        if final_state.errors:
                            run.error_message = final_state.errors[-1]["error"]
                        elif final_state.warnings:
                            run.error_message = final_state.warnings[-1]["warning"]
                        session.commit()
            except Exception as db_error:
                logger.error(
                    "Failed to update run record after delivery completion",
                    error=str(db_error),
                    run_id=run_id,
                )

            if not final_state.error_occurred:
                log_run_complete(
                    run_id,
                    duration,
                    final_state.stats.dict(),
                    status=run_status,
                    warnings_count=len(final_state.warnings),
                )

            return final_state

        except Exception as e:
            logger.error(
                "Delivery execution failed", error=str(e), run_id=run_id, exc_info=True
            )

            try:
                with get_db_context() as session:
                    run = session.query(Run).filter(Run.id == run_id).first()
                    if run:
                        run.status = "failed"
                        run.finished_at = datetime.utcnow()
                        run.error_message = str(e)
                        session.commit()
            except Exception as db_error:
                logger.error("Failed to update failed run record", error=str(db_error))

            log_run_error(run_id, e)

            state.add_error("delivery", str(e))
            state.error_occurred = True
            return state


def create_delivery_graph() -> DeliveryGraph:
    """Create and return a new delivery graph instance."""
    return DeliveryGraph()


_delivery_pipeline: DeliveryGraph | None = None
_delivery_pipeline_lock = threading.Lock()


def get_delivery_pipeline() -> DeliveryGraph:
    """Get or create the global delivery pipeline instance (thread-safe)."""
    global _delivery_pipeline

    if _delivery_pipeline is None:
        with _delivery_pipeline_lock:
            if _delivery_pipeline is None:
                _delivery_pipeline = create_delivery_graph()

    return _delivery_pipeline
