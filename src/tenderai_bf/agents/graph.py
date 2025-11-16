"""LangGraph pipeline orchestration for TenderAI BF."""

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from ..config import settings
from ..db import get_db_context
from ..logging import get_logger, log_run_start, log_run_complete, log_run_error
from ..models import Run
from ..schemas import PipelineState, RunStatistics

# Import node functions
from .nodes.load_sources import load_sources_node
from .nodes.fetch_listings import fetch_listings_node
from .nodes.extract_item_links import extract_item_links_node
from .nodes.fetch_items import fetch_items_node
from .nodes.parse_extract import parse_extract_node
from .nodes.classify import classify_node
from .nodes.deduplicate import deduplicate_node
from .nodes.summarize import summarize_node
from .nodes.compose_report import compose_report_node
from .nodes.email_report import email_report_node

logger = get_logger(__name__)


class TenderAIState(BaseModel):
    """Typed state for the TenderAI pipeline."""
    
    # Run metadata
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Pipeline data
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    discovered_links: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)  # Can be URL strings or quotidien dicts
    items_raw: List[Dict[str, Any]] = Field(default_factory=list)
    items_parsed: List[Dict[str, Any]] = Field(default_factory=list)
    relevant_items: List[Dict[str, Any]] = Field(default_factory=list)
    unique_items: List[Dict[str, Any]] = Field(default_factory=list)
    summaries: Dict[str, str] = Field(default_factory=dict)
    
    # Outputs
    report_bytes: Optional[bytes] = None
    report_url: Optional[str] = None
    email_status: Dict[str, Any] = Field(default_factory=dict)
    
    # Statistics and metrics
    stats: RunStatistics = Field(default_factory=RunStatistics)
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Control flow
    should_continue: bool = True
    error_occurred: bool = False
    send_email: bool = True  # Whether to send email report at the end
    
    class Config:
        arbitrary_types_allowed = True
    
    def add_error(self, step: str, error: str, **kwargs) -> None:
        """Add an error to the state."""
        self.errors.append({
            'step': step,
            'error': error,
            'timestamp': datetime.utcnow().isoformat(),
            **kwargs
        })
        self.error_occurred = True
        logger.error(f"Pipeline error in {step}", error=error, run_id=self.run_id, **kwargs)
    
    def update_stats(self, **kwargs) -> None:
        """Update run statistics."""
        for key, value in kwargs.items():
            if hasattr(self.stats, key):
                setattr(self.stats, key, value)


def error_handler(state: TenderAIState) -> TenderAIState:
    """Handle pipeline errors and cleanup."""
    
    logger.error(
        "Pipeline error handler triggered",
        run_id=state.run_id,
        errors_count=len(state.errors),
        last_error=state.errors[-1] if state.errors else None
    )
    
    # Update run record in database
    try:
        with get_db_context() as session:
            run = session.query(Run).filter(Run.id == state.run_id).first()
            if run:
                run.status = "failed"
                run.finished_at = datetime.utcnow()
                run.error_message = state.errors[-1]['error'] if state.errors else "Unknown error"
                run.counts_json = state.stats.dict()
                session.commit()
    except Exception as e:
        logger.error("Failed to update run record", error=str(e), run_id=state.run_id)
    
    # Log final error
    if state.errors:
        log_run_error(
            state.run_id,
            Exception(state.errors[-1]['error']),
            errors_count=len(state.errors),
            duration=(datetime.utcnow() - state.started_at).total_seconds()
        )
    
    return state


def router(state: TenderAIState) -> str:
    """Route to next node or handle completion/errors."""
    
    if state.error_occurred:
        return "error_handler"
    
    if not state.should_continue:
        return END
    
    # Normal flow: pipeline completed successfully
    return END


class TenderAIGraph:
    """LangGraph pipeline for TenderAI BF."""
    
    def __init__(self):
        """Initialize the pipeline graph."""
        self.graph = self._build_graph()
        self.app = self.graph.compile()
        logger.info("TenderAI pipeline graph initialized")
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state graph."""
        
        # Create state graph
        workflow = StateGraph(TenderAIState)
        
        # Add nodes
        workflow.add_node("load_sources", load_sources_node)
        workflow.add_node("fetch_listings", fetch_listings_node)
        workflow.add_node("extract_item_links", extract_item_links_node)
        workflow.add_node("fetch_items", fetch_items_node)
        workflow.add_node("parse_extract", parse_extract_node)
        workflow.add_node("classify", classify_node)
        workflow.add_node("deduplicate", deduplicate_node)
        workflow.add_node("summarize", summarize_node)
        workflow.add_node("compose_report", compose_report_node)
        workflow.add_node("email_report", email_report_node)
        workflow.add_node("error_handler", error_handler)
        
        # Set entry point
        workflow.set_entry_point("load_sources")
        
        # Add edges (sequential flow)
        workflow.add_edge("load_sources", "fetch_listings")
        workflow.add_edge("fetch_listings", "extract_item_links")
        workflow.add_edge("extract_item_links", "fetch_items")
        workflow.add_edge("fetch_items", "parse_extract")
        workflow.add_edge("parse_extract", "classify")
        workflow.add_edge("classify", "deduplicate")
        workflow.add_edge("deduplicate", "summarize")
        workflow.add_edge("summarize", "compose_report")
        workflow.add_edge("compose_report", "email_report")
        
        # Add conditional edges for error handling
        workflow.add_conditional_edges(
            "email_report",
            router,
            {
                "error_handler": "error_handler",
                END: END
            }
        )
        
        workflow.add_edge("error_handler", END)
        
        return workflow
    
    def run(self, 
            triggered_by: str = "scheduler",
            triggered_by_user: Optional[str] = None,
            sources_override: Optional[List[Dict]] = None,
            send_email: bool = True) -> TenderAIState:
        """Execute the complete pipeline."""
        
        # Initialize state
        state = TenderAIState()
        run_id = state.run_id
        
        # Log run start
        log_run_start(
            run_id,
            triggered_by=triggered_by,
            triggered_by_user=triggered_by_user,
            sources_count=len(sources_override) if sources_override else len(settings.get_active_sources())
        )
        
        # Log LLM configuration at pipeline start
        llm_provider = settings.llm.provider
        llm_model = None
        log_params = {
            "run_id": run_id,
            "llm_provider": llm_provider,
            "temperature": settings.llm.temperature,
            "max_tokens": settings.llm.max_tokens
        }
        
        if llm_provider == "groq":
            llm_model = settings.llm.groq_model
        elif llm_provider == "openai":
            llm_model = settings.llm.openai_model
        elif llm_provider == "ollama":
            llm_model = settings.llm.ollama_model
            log_params["ollama_base_url"] = getattr(settings.llm, 'ollama_base_url', 'http://localhost:11434')
        
        log_params["llm_model"] = llm_model
        logger.info("Pipeline starting with LLM configuration", **log_params)
        
        # Create run record in database
        try:
            with get_db_context() as session:
                run = Run(
                    id=run_id,
                    status="running",
                    started_at=state.started_at,
                    triggered_by=triggered_by,
                    triggered_by_user=triggered_by_user
                )
                session.add(run)
                session.commit()
        except Exception as e:
            logger.error("Failed to create run record", error=str(e), run_id=run_id)
        
        # Override sources if provided
        if sources_override:
            state.sources = sources_override
        
        # Set send_email flag
        state.send_email = send_email
        
        try:
            # Execute pipeline (pass state as dict for LangGraph)
            start_time = time.time()
            final_state = self.app.invoke(state.dict())
            duration = time.time() - start_time
            
            # Update statistics (final_state is a dict, not an object)
            if "stats" in final_state and final_state["stats"]:
                # final_state["stats"] is a dict, not an object
                if isinstance(final_state["stats"], dict):
                    final_state["stats"]["total_time_seconds"] = duration
                else:
                    final_state["stats"].total_time_seconds = duration
            
            # Update run record
            with get_db_context() as session:
                run = session.query(Run).filter(Run.id == run_id).first()
                if run:
                    run.status = "completed" if not final_state.get("error_occurred", False) else "failed"
                    run.finished_at = datetime.utcnow()
                    if "stats" in final_state and final_state["stats"]:
                        # Convert stats to dict if it's an object
                        if isinstance(final_state["stats"], dict):
                            run.counts_json = final_state["stats"]
                        else:
                            run.counts_json = final_state["stats"].dict()
                    run.report_url = final_state.get("report_url")
                    if final_state.get("errors"):
                        run.error_message = final_state["errors"][-1]['error']
                    session.commit()
            
            # Log completion
            if not final_state.get("error_occurred", False):
                if isinstance(final_state.get("stats"), dict):
                    stats_dict = final_state["stats"]
                else:
                    stats_dict = final_state["stats"].dict() if "stats" in final_state and final_state["stats"] else {}
                log_run_complete(
                    run_id,
                    duration,
                    stats_dict
                )
            
            return final_state
            
        except Exception as e:
            # Handle unexpected errors
            logger.error("Pipeline execution failed", error=str(e), run_id=run_id, exc_info=True)
            
            # Update run record
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
            
            # Log error
            log_run_error(run_id, e)
            
            # Return state with error as dict
            state.add_error("pipeline", str(e))
            state.error_occurred = True
            return state.dict()
    
    def run_step(self, step_name: str, state: TenderAIState) -> TenderAIState:
        """Execute a single step of the pipeline for testing/debugging."""
        
        if step_name not in self.graph.nodes:
            raise ValueError(f"Unknown step: {step_name}")
        
        # Get the node function
        node_func = self.graph.nodes[step_name]
        
        try:
            # Execute the step
            result = node_func(state)
            logger.info(f"Step {step_name} completed successfully", run_id=state.run_id)
            return result
        except Exception as e:
            logger.error(f"Step {step_name} failed", error=str(e), run_id=state.run_id, exc_info=True)
            state.add_error(step_name, str(e))
            return state
    
    def get_pipeline_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a pipeline run."""
        
        try:
            with get_db_context() as session:
                run = session.query(Run).filter(Run.id == run_id).first()
                if run:
                    return {
                        'id': run.id,
                        'status': run.status,
                        'started_at': run.started_at.isoformat(),
                        'finished_at': run.finished_at.isoformat() if run.finished_at else None,
                        'duration_seconds': run.duration_seconds,
                        'triggered_by': run.triggered_by,
                        'triggered_by_user': run.triggered_by_user,
                        'counts': run.counts_json or {},
                        'error_message': run.error_message,
                        'report_url': run.report_url
                    }
                return None
        except Exception as e:
            logger.error("Failed to get pipeline status", error=str(e), run_id=run_id)
            return None
    
    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent pipeline runs."""
        
        try:
            with get_db_context() as session:
                runs = session.query(Run).order_by(Run.started_at.desc()).limit(limit).all()
                return [
                    {
                        'id': run.id,
                        'status': run.status,
                        'started_at': run.started_at.isoformat(),
                        'finished_at': run.finished_at.isoformat() if run.finished_at else None,
                        'duration_seconds': run.duration_seconds,
                        'triggered_by': run.triggered_by,
                        'triggered_by_user': run.triggered_by_user,
                        'counts': run.counts_json or {},
                        'error_message': run.error_message[:100] + '...' if run.error_message and len(run.error_message) > 100 else run.error_message,
                        'report_url': run.report_url
                    }
                    for run in runs
                ]
        except Exception as e:
            logger.error("Failed to get recent runs", error=str(e))
            return []


def create_pipeline_graph() -> TenderAIGraph:
    """Create and return a new pipeline graph instance."""
    return TenderAIGraph()


# Global pipeline instance
_pipeline: Optional[TenderAIGraph] = None


def get_pipeline() -> TenderAIGraph:
    """Get or create the global pipeline instance."""
    global _pipeline
    
    if _pipeline is None:
        _pipeline = create_pipeline_graph()
    
    return _pipeline