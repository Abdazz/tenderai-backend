"""Pipeline runs management endpoints."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field

from ...logging import get_logger
from ..dependencies import AuthenticatedUser, CurrentUser, DatabaseSession

logger = get_logger(__name__)

router = APIRouter()


class RunTriggerRequest(BaseModel):
    """Request model for triggering a pipeline run."""
    
    triggered_by: str = Field(default="api", description="Who/what triggered the run")
    triggered_by_user: Optional[str] = Field(default=None, description="Username if triggered by user")
    sources: Optional[List[str]] = Field(default=None, description="Specific sources to run (None = all)")
    send_email: bool = Field(default=True, description="Send email report after completion")
    dry_run: bool = Field(default=False, description="Dry run mode (no database writes)")


class RunStatusResponse(BaseModel):
    """Response model for run status."""
    
    run_id: str
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    triggered_by: str
    triggered_by_user: Optional[str]
    error_occurred: bool
    errors_count: int
    stats: Optional[dict]
    report_url: Optional[str]


class RunListResponse(BaseModel):
    """Response model for runs list."""
    
    runs: List[RunStatusResponse]
    total: int
    page: int
    page_size: int


class RunStatsResponse(BaseModel):
    """Response model for run statistics."""
    
    total_runs: int
    successful_runs: int
    failed_runs: int
    running: int
    average_duration_seconds: Optional[float]
    last_run: Optional[RunStatusResponse]


@router.post("/trigger", response_model=RunStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_run(
    request: RunTriggerRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser
):
    """Trigger a new pipeline run.
    
    The run will be executed in the background.
    Returns immediately with run_id for tracking.
    """
    
    from ...agents import get_pipeline
    
    logger.info(
        "Pipeline run triggered via API",
        triggered_by=request.triggered_by,
        user=request.triggered_by_user or current_user.get("username") if current_user else None,
        sources=request.sources,
        dry_run=request.dry_run
    )
    
    # Get pipeline
    pipeline = get_pipeline()
    
    # Generate run ID
    import uuid
    run_id = str(uuid.uuid4())
    
    # Determine who triggered
    triggered_by_user = request.triggered_by_user
    if current_user and not triggered_by_user:
        triggered_by_user = current_user.get("username", "api_user")
    
    # Execute in background
    def run_pipeline():
        try:
            # Prepare sources override if specified
            sources_override = None
            if request.sources:
                # TODO: Load full source data from DB based on names/IDs
                sources_override = request.sources
            
            result = pipeline.run(
                triggered_by=request.triggered_by,
                triggered_by_user=triggered_by_user,
                sources_override=sources_override,
                send_email=request.send_email
            )
            
            # result is a dict from LangGraph
            result_run_id = result.get("run_id") if isinstance(result, dict) else result.run_id
            error_occurred = result.get("error_occurred", False) if isinstance(result, dict) else result.error_occurred
            stats = result.get("stats") if isinstance(result, dict) else result.stats
            unique_items = stats.unique_items if stats and hasattr(stats, 'unique_items') else 0
            
            logger.info(
                "Pipeline run completed",
                run_id=result_run_id,
                status="success" if not error_occurred else "failed",
                items=unique_items
            )
            
        except Exception as e:
            logger.error(
                "Pipeline run failed",
                run_id=run_id,
                error=str(e),
                exc_info=e
            )
    
    background_tasks.add_task(run_pipeline)
    
    return RunStatusResponse(
        run_id=run_id,
        status="running",
        started_at=datetime.utcnow(),
        completed_at=None,
        duration_seconds=None,
        triggered_by=request.triggered_by,
        triggered_by_user=triggered_by_user,
        error_occurred=False,
        errors_count=0,
        stats=None,
        report_url=None
    )


@router.get("/{run_id}/status", response_model=RunStatusResponse)
async def get_run_status(run_id: str, db: DatabaseSession):
    """Get status of a specific run."""
    
    from ...models import Run
    
    # Query run from database
    run = db.query(Run).filter(Run.id == run_id).first()
    
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found"
        )
    
    # Calculate duration
    duration = None
    if run.started_at and run.finished_at:
        duration = (run.finished_at - run.started_at).total_seconds()
    
    # Get stats from counts_json instead of metadata
    stats = run.counts_json if run.counts_json else None
    
    return RunStatusResponse(
        run_id=str(run.id),
        status=run.status,
        started_at=run.started_at,
        completed_at=run.finished_at,
        duration_seconds=duration,
        triggered_by=run.triggered_by or "unknown",
        triggered_by_user=run.triggered_by_user,
        error_occurred=run.status == "failed",
        errors_count=0,  # TODO: Add error tracking to Run model
        stats=stats,
        report_url=run.report_url
    )


@router.get("", response_model=RunListResponse)
async def list_runs(
    db: DatabaseSession,
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None
):
    """List all pipeline runs with pagination."""
    
    from ...models import Run
    
    # Build query
    query = db.query(Run)
    
    if status_filter:
        query = query.filter(Run.status == status_filter)
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    offset = (page - 1) * page_size
    runs = query.order_by(Run.started_at.desc()).offset(offset).limit(page_size).all()
    
    # Convert to response models
    run_responses = []
    for run in runs:
        duration = None
        if run.started_at and run.finished_at:
            duration = (run.finished_at - run.started_at).total_seconds()
        
        stats = run.counts_json if run.counts_json else None
        
        run_responses.append(RunStatusResponse(
            run_id=str(run.id),
            status=run.status,
            started_at=run.started_at,
            completed_at=run.finished_at,
            duration_seconds=duration,
            triggered_by=run.triggered_by or "unknown",
            triggered_by_user=run.triggered_by_user,
            error_occurred=run.status == "failed",
            errors_count=0,  # TODO: Add error tracking
            stats=stats,
            report_url=run.report_url
        ))
    
    return RunListResponse(
        runs=run_responses,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/stats", response_model=RunStatsResponse)
async def get_run_statistics(db: DatabaseSession):
    """Get overall run statistics."""
    
    from ...models import Run
    from sqlalchemy import func
    
    # Total runs
    total_runs = db.query(Run).count()
    
    # Successful runs
    successful_runs = db.query(Run).filter(Run.status == "completed").count()
    
    # Failed runs
    failed_runs = db.query(Run).filter(Run.status == "failed").count()
    
    # Currently running
    running = db.query(Run).filter(Run.status == "running").count()
    
    # Average duration
    avg_duration = db.query(
        func.avg(
            func.extract('epoch', Run.finished_at - Run.started_at)
        )
    ).filter(
        Run.finished_at.isnot(None),
        Run.started_at.isnot(None)
    ).scalar()
    
    # Last run
    last_run = db.query(Run).order_by(Run.started_at.desc()).first()
    
    last_run_response = None
    if last_run:
        duration = None
        if last_run.started_at and last_run.finished_at:
            duration = (last_run.finished_at - last_run.started_at).total_seconds()
        
        stats = last_run.counts_json if last_run.counts_json else None
        
        last_run_response = RunStatusResponse(
            run_id=str(last_run.id),
            status=last_run.status,
            started_at=last_run.started_at,
            completed_at=last_run.finished_at,
            duration_seconds=duration,
            triggered_by=last_run.triggered_by or "unknown",
            triggered_by_user=last_run.triggered_by_user,
            error_occurred=last_run.status == "failed",
            errors_count=0,  # TODO: Add error tracking
            stats=stats,
            report_url=last_run.report_url
        )
    
    return RunStatsResponse(
        total_runs=total_runs,
        successful_runs=successful_runs,
        failed_runs=failed_runs,
        running=running,
        average_duration_seconds=float(avg_duration) if avg_duration else None,
        last_run=last_run_response
    )


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: str, db: DatabaseSession, user: AuthenticatedUser):
    """Delete a specific run (admin only)."""
    
    from ...models import Run
    
    run = db.query(Run).filter(Run.id == run_id).first()
    
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found"
        )
    
    db.delete(run)
    db.commit()
    
    logger.info("Run deleted", run_id=run_id, deleted_by=user.get("username"))
    
    return None