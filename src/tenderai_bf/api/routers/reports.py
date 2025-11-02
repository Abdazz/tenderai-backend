"""Reports management endpoints."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ...logging import get_logger
from ..dependencies import DatabaseSession

logger = get_logger(__name__)

router = APIRouter()


class ReportResponse(BaseModel):
    """Response model for a report."""
    
    run_id: str
    report_url: Optional[str]
    created_at: Optional[str]
    file_size: Optional[int]
    format: str = "docx"


class ReportListResponse(BaseModel):
    """Response model for reports list."""
    
    reports: List[ReportResponse]
    total: int


@router.get("", response_model=ReportListResponse)
async def list_reports(db: DatabaseSession, limit: int = 50):
    """List all available reports."""
    
    from ...models import Run
    
    # Query runs with reports
    runs = (
        db.query(Run)
        .filter(Run.report_url.isnot(None))
        .order_by(Run.completed_at.desc())
        .limit(limit)
        .all()
    )
    
    reports = []
    for run in runs:
        reports.append(ReportResponse(
            run_id=str(run.id),
            report_url=run.report_url,
            created_at=run.completed_at.isoformat() if run.completed_at else None,
            file_size=None,  # TODO: Get from storage
            format="docx"
        ))
    
    return ReportListResponse(
        reports=reports,
        total=len(reports)
    )


@router.get("/{run_id}", response_model=ReportResponse)
async def get_report_info(run_id: str, db: DatabaseSession):
    """Get information about a specific report."""
    
    from ...models import Run
    
    run = db.query(Run).filter(Run.id == run_id).first()
    
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found"
        )
    
    if not run.report_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No report available for run {run_id}"
        )
    
    return ReportResponse(
        run_id=str(run.id),
        report_url=run.report_url,
        created_at=run.completed_at.isoformat() if run.completed_at else None,
        file_size=None,
        format="docx"
    )


@router.get("/{run_id}/download")
async def download_report(run_id: str, db: DatabaseSession):
    """Download a report file.
    
    Returns the DOCX file as a download.
    """
    
    from ...models import Run
    from ...storage import get_storage_client
    import tempfile
    import os
    
    # Get run
    run = db.query(Run).filter(Run.id == run_id).first()
    
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found"
        )
    
    if not run.report_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No report available for run {run_id}"
        )
    
    try:
        # Get storage client
        storage_client = get_storage_client()
        
        # Extract object key from URL
        # Assuming format: http://endpoint/bucket/path/to/file
        from urllib.parse import urlparse
        parsed = urlparse(run.report_url)
        object_key = parsed.path.lstrip('/')
        
        # Remove bucket name from path if present
        bucket_name = storage_client.bucket_name
        if object_key.startswith(f"{bucket_name}/"):
            object_key = object_key[len(bucket_name) + 1:]
        
        # Download to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as tmp_file:
            tmp_path = tmp_file.name
        
        storage_client.download_file(object_key, tmp_path)
        
        # Generate filename
        filename = f"tenderai_rapport_{run_id[:8]}.docx"
        
        # Return file
        return FileResponse(
            path=tmp_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=filename,
            background=None  # Keep file until response is sent
        )
    
    except Exception as e:
        logger.error(
            "Failed to download report",
            run_id=run_id,
            error=str(e)
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download report: {str(e)}"
        )


@router.get("/{run_id}/preview")
async def preview_report(run_id: str, db: DatabaseSession):
    """Get a preview of the report content.
    
    Returns a summary of the report without downloading the full file.
    """
    
    from ...models import Run, Notice
    
    # Get run
    run = db.query(Run).filter(Run.id == run_id).first()
    
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found"
        )
    
    # Get notices for this run
    notices = db.query(Notice).filter(Notice.run_id == run_id).all()
    
    # Build preview
    stats = run.metadata.get("stats", {}) if run.metadata else {}
    
    preview = {
        "run_id": str(run.id),
        "created_at": run.completed_at.isoformat() if run.completed_at else None,
        "status": run.status,
        "stats": {
            "total_items": stats.get("items_parsed", 0),
            "relevant_items": stats.get("relevant_items", 0),
            "unique_items": stats.get("unique_items", 0),
            "sources_checked": stats.get("sources_checked", 0)
        },
        "notices_preview": [
            {
                "title": notice.title,
                "organization": notice.organization,
                "deadline": notice.deadline.isoformat() if notice.deadline else None,
                "url": notice.url,
                "is_relevant": notice.is_relevant
            }
            for notice in notices[:10]  # First 10 notices
        ],
        "total_notices": len(notices)
    }
    
    return preview


@router.post("/{run_id}/regenerate", status_code=status.HTTP_202_ACCEPTED)
async def regenerate_report(run_id: str, db: DatabaseSession):
    """Regenerate the report for a specific run.
    
    Useful if report generation failed or needs to be updated.
    """
    
    from ...models import Run
    
    # Get run
    run = db.query(Run).filter(Run.id == run_id).first()
    
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found"
        )
    
    if run.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot regenerate report for run with status '{run.status}'"
        )
    
    try:
        # Regenerate report
        from ...report import generate_docx_report
        from ...storage import get_storage_client
        
        # Get notices for this run
        from ...models import Notice
        notices = db.query(Notice).filter(Notice.run_id == run_id).all()
        
        # Generate report
        report_path = generate_docx_report(
            notices=notices,
            run_id=str(run.id),
            stats=run.metadata.get("stats") if run.metadata else {}
        )
        
        # Upload to storage
        storage_client = get_storage_client()
        object_key = f"reports/{run.id}/rapport.docx"
        report_url = storage_client.upload_file(report_path, object_key)
        
        # Update run
        run.report_url = report_url
        db.commit()
        
        logger.info(
            "Report regenerated",
            run_id=run_id,
            report_url=report_url
        )
        
        return {
            "status": "success",
            "run_id": run_id,
            "report_url": report_url,
            "message": "Report regenerated successfully"
        }
    
    except Exception as e:
        logger.error(
            "Failed to regenerate report",
            run_id=run_id,
            error=str(e)
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate report: {str(e)}"
        )