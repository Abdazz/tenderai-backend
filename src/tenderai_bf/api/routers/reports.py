"""Reports management endpoints."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from ...config import settings
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
            created_at=run.finished_at.isoformat() if run.finished_at else None,
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
        created_at=run.finished_at.isoformat() if run.finished_at else None,
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
        
        # Download from storage
        report_data = storage_client.get_object(object_key)
        
        if not report_data:
            raise Exception(f"Failed to retrieve report from storage: {object_key}")
        
        # Generate filename based on project name
        project_slug = settings.app_name.replace(" ", "_")
        filename = f"{project_slug}_{run_id[:8]}.docx"
        
        # Return as streaming response
        return Response(
            content=report_data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
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
    
    from ...models import Run, Notice
    from ...storage import get_storage_client
    from datetime import datetime
    
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
        # Get notices for this run
        notices = db.query(Notice).filter(Notice.run_id == run_id).all()
        
        # Get stats from counts_json
        stats = run.counts_json if run.counts_json else {}
        
        # Generate report with correct data structure
        from ...report import build_report
        report_data = {
            'run_id': str(run.id),
            'generated_at': datetime.utcnow(),
            'statistics': stats,
            'notices': [
                {
                    'id': notice.id,
                    'source_name': notice.source_name if hasattr(notice, 'source_name') else 'Unknown',
                    'entity': notice.entity,
                    'reference': notice.reference,
                    'title': notice.title,
                    'description': notice.description,
                    'url': notice.url,
                    'published_at': notice.published_at.isoformat() if notice.published_at else None,
                    'relevance_score': getattr(notice, 'relevance_score', 0)
                }
                for notice in notices
            ],
            'sources': [],
            'errors': []
        }
        
        report_bytes = build_report(report_data)
        
        if not report_bytes:
            raise Exception("Report generation failed - no bytes returned")
        
        # Upload to storage
        storage_client = get_storage_client()
        report_url = storage_client.store_report(
            report_data=report_bytes,
            run_id=str(run.id),
            timestamp=datetime.utcnow()
        )
        
        if not report_url:
            raise Exception("Failed to store report in MinIO")
        
        # Update run
        run.report_url = report_url
        db.commit()
        
        logger.info(
            "Report regenerated successfully",
            run_id=run_id,
            report_url=report_url
        )
        
        return {
            "status": "regenerated",
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