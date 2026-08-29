"""Pipeline runs management endpoints."""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field

from ...agents import get_delivery_pipeline, get_pipeline
from ...logging import get_logger
from ..dependencies import AuthenticatedUser, CurrentUser, DatabaseSession

logger = get_logger(__name__)

router = APIRouter()


class RunTriggerRequest(BaseModel):
    """Request model for triggering a pipeline run."""

    triggered_by: str = Field(default="api", description="Who/what triggered the run")
    triggered_by_user: str | None = Field(
        default=None, description="Username if triggered by user"
    )
    sources: list[str] | None = Field(
        default=None, description="Specific sources to run (None = all)"
    )
    send_email: bool = Field(
        default=True, description="Send email report after completion"
    )
    dry_run: bool = Field(
        default=False, description="Dry run mode (no database writes)"
    )
    country_id: int = Field(default=1, description="Country ID to run pipeline for")
    company_id: int | None = Field(
        default=None,
        description="Company to deliver to (super_admin only; company_admin/"
        "company_viewer always deliver to their own company; defaults to "
        "YULCOM for super_admin if omitted)",
    )


class RunStatusResponse(BaseModel):
    """Response model for run status."""

    run_id: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None
    triggered_by: str
    triggered_by_user: str | None
    error_occurred: bool
    errors_count: int
    stats: dict | None
    report_url: str | None


class RunListResponse(BaseModel):
    """Response model for runs list."""

    runs: list[RunStatusResponse]
    total: int
    page: int
    page_size: int


class RunStatsResponse(BaseModel):
    """Response model for run statistics."""

    total_runs: int
    successful_runs: int
    failed_runs: int
    running: int
    average_duration_seconds: float | None
    last_run: RunStatusResponse | None


@router.post(
    "/trigger", response_model=RunStatusResponse, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_run(
    request: RunTriggerRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: DatabaseSession,
):
    """Trigger a new pipeline run.

    The run will be executed in the background.
    Returns immediately with run_id for tracking.
    """

    logger.info(
        "Pipeline run triggered via API",
        triggered_by=request.triggered_by,
        user=request.triggered_by_user or current_user.get("username")
        if current_user
        else None,
        sources=request.sources,
        dry_run=request.dry_run,
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

    # Non-super_admin cannot request delivery to a company other than their own
    if (
        current_user
        and current_user.get("role") != "super_admin"
        and request.company_id is not None
        and request.company_id != current_user.get("company_id")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot trigger delivery for another company",
        )

    from ..dependencies import resolve_delivery_company_id

    target_company_id = resolve_delivery_company_id(
        current_user, request.company_id, db
    )

    # Execute in background
    def run_pipeline():
        try:
            # Prepare sources override if specified
            sources_override = None
            if request.sources:
                # TODO: Load full source data from DB based on names/IDs
                sources_override = request.sources

            harvest_result = pipeline.run(
                country_id=request.country_id,
                triggered_by=request.triggered_by,
                triggered_by_user=triggered_by_user,
                sources_override=sources_override,
            )

            if harvest_result.error_occurred:
                logger.error(
                    "Pipeline run failed",
                    run_id=harvest_result.run_id,
                    errors_count=len(harvest_result.errors),
                )
                return

            result = harvest_result
            if request.send_email:
                if target_company_id is not None:
                    result = get_delivery_pipeline().run(
                        company_id=target_company_id,
                        country_id=request.country_id,
                        triggered_by=request.triggered_by,
                        triggered_by_user=triggered_by_user,
                    )
                else:
                    logger.warning(
                        "No company_id resolved for delivery after manual harvest "
                        "trigger — skipping delivery",
                        country_id=request.country_id,
                    )

            if result.error_occurred:
                run_status = "failed"
            elif result.warnings:
                run_status = "completed_with_warnings"
            else:
                run_status = "completed"

            logger.info(
                "Pipeline run completed",
                run_id=result.run_id,
                status=run_status,
                warnings_count=len(result.warnings),
            )

        except Exception as e:
            logger.error("Pipeline run failed", run_id=run_id, error=str(e), exc_info=e)

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
        report_url=None,
    )


@router.get("/{run_id}/status", response_model=RunStatusResponse)
async def get_run_status(run_id: str, db: DatabaseSession):
    """Get status of a specific run."""

    from ...models import Run

    # Query run from database
    run = db.query(Run).filter(Run.id == run_id).first()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found"
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
        report_url=run.report_url,
    )


@router.get("", response_model=RunListResponse)
async def list_runs(
    db: DatabaseSession,
    current_user: AuthenticatedUser,
    page: int = 1,
    page_size: int = 20,
    status_filter: str | None = None,
    country_id: int | None = None,
):
    """List all pipeline runs with pagination."""

    from ...models import Run

    # Build query
    query = db.query(Run)

    if current_user.get("role") != "super_admin":
        query = query.filter(
            Run.run_type == "delivery", Run.company_id == current_user.get("company_id")
        )

    if status_filter:
        query = query.filter(Run.status == status_filter)

    if country_id is not None:
        query = query.filter(Run.country_id == country_id)

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

        run_responses.append(
            RunStatusResponse(
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
                report_url=run.report_url,
            )
        )

    return RunListResponse(
        runs=run_responses, total=total, page=page, page_size=page_size
    )


@router.get("/stats", response_model=RunStatsResponse)
async def get_run_statistics(db: DatabaseSession):
    """Get overall run statistics."""

    from sqlalchemy import func

    from ...models import Run

    # Total runs
    total_runs = db.query(Run).count()

    # Successful runs
    successful_runs = db.query(Run).filter(Run.status == "completed").count()

    # Failed runs
    failed_runs = db.query(Run).filter(Run.status == "failed").count()

    # Currently running
    running = db.query(Run).filter(Run.status == "running").count()

    # Average duration
    avg_duration = (
        db.query(func.avg(func.extract("epoch", Run.finished_at - Run.started_at)))
        .filter(Run.finished_at.isnot(None), Run.started_at.isnot(None))
        .scalar()
    )

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
            report_url=last_run.report_url,
        )

    return RunStatsResponse(
        total_runs=total_runs,
        successful_runs=successful_runs,
        failed_runs=failed_runs,
        running=running,
        average_duration_seconds=float(avg_duration) if avg_duration else None,
        last_run=last_run_response,
    )


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: str, db: DatabaseSession, user: AuthenticatedUser):
    """Delete a specific run (admin only)."""

    from ...models import Run

    run = db.query(Run).filter(Run.id == run_id).first()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found"
        )

    is_own_company_admin = user.get(
        "role"
    ) == "company_admin" and run.company_id == user.get("company_id")
    if user.get("role") != "super_admin" and not is_own_company_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this run",
        )

    db.delete(run)
    db.commit()

    logger.info("Run deleted", run_id=run_id, deleted_by=user.get("username"))

    return None
