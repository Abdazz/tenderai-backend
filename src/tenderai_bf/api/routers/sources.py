"""Sources management endpoints."""

from typing import List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ...logging import get_logger
from ...schemas import Source as SourceSchema, SourceCreate, SourceUpdate
from ..dependencies import AuthenticatedUser, DatabaseSession

logger = get_logger(__name__)

router = APIRouter()


class SourceListResponse(BaseModel):
    """Response model for sources list."""
    
    sources: List[SourceSchema]
    total: int


@router.get("", response_model=SourceListResponse)
async def list_sources(db: DatabaseSession, enabled_only: bool = False):
    """List all configured sources from database."""
    
    from ...models import Source
    
    # Get sources from database
    query = db.query(Source)
    
    if enabled_only:
        query = query.filter(Source.enabled == True)
    
    db_sources = query.all()
    
    return SourceListResponse(
        sources=[SourceSchema.from_orm(source) for source in db_sources],
        total=len(db_sources)
    )


@router.get("/{source_id}", response_model=SourceSchema)
async def get_source(source_id: int, db: DatabaseSession):
    """Get a specific source by ID."""
    
    from ...models import Source
    
    source = db.query(Source).filter(Source.id == source_id).first()
    
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found"
        )
    
    return SourceSchema.from_orm(source)


@router.post("", response_model=SourceSchema, status_code=status.HTTP_201_CREATED)
async def create_source(request: SourceCreate, db: DatabaseSession, user: AuthenticatedUser):
    """Create a new source (admin only)."""
    
    from ...models import Source
    
    # Check if source with same name exists
    existing = db.query(Source).filter(Source.name == request.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Source with name '{request.name}' already exists"
        )
    
    # Create source from schema
    source = Source(
        name=request.name,
        base_url=str(request.base_url),
        list_url=str(request.list_url),
        parser_type=request.parser_type,
        rate_limit=request.rate_limit,
        enabled=request.enabled,
        patterns=request.patterns
    )
    
    db.add(source)
    db.commit()
    db.refresh(source)
    
    logger.info(
        "Source created",
        source_id=source.id,
        source_name=source.name,
        created_by=user.get("username")
    )
    
    return SourceSchema.from_orm(source)



@router.put("/{source_id}", response_model=SourceSchema)
async def update_source(
    source_id: int,
    request: SourceUpdate,
    db: DatabaseSession,
    user: AuthenticatedUser
):
    """Update an existing source (admin only)."""
    
    from ...models import Source
    
    source = db.query(Source).filter(Source.id == source_id).first()
    
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found"
        )
    
    # Map schema fields to model fields
    update_data = request.model_dump(exclude_unset=True)
    field_mapping = {
        'base_url': 'base_url',
        'list_url': 'list_url',
        'parser_type': 'parser_type',
        'patterns': 'patterns',
        'rate_limit': 'rate_limit',
        'enabled': 'enabled',
        'name': 'name'
    }
    
    for schema_field, model_field in field_mapping.items():
        if schema_field in update_data:
            value = update_data[schema_field]
            # Convert HttpUrl to string if needed
            if hasattr(value, '__str__'):
                value = str(value)
            setattr(source, model_field, value)
    
    db.commit()
    db.refresh(source)
    
    logger.info(
        "Source updated",
        source_id=source.id,
        source_name=source.name,
        updated_by=user.get("username")
    )
    
    return SourceSchema.from_orm(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: int, db: DatabaseSession, user: AuthenticatedUser):
    """Delete a source (admin only)."""
    
    from ...models import Source
    
    source = db.query(Source).filter(Source.id == source_id).first()
    
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found"
        )
    
    db.delete(source)
    db.commit()
    
    logger.info(
        "Source deleted",
        source_id=source_id,
        source_name=source.name,
        deleted_by=user.get("username")
    )
    
    return None


@router.post("/{source_id}/test")
async def test_source(source_id: int, db: DatabaseSession):
    """Test a source to verify it's accessible and parseable."""
    
    from ...models import Source
    
    source = db.query(Source).filter(Source.id == source_id).first()
    
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found"
        )
    
    # Test fetch
    try:
        from ...agents.nodes.fetch_listings import fetch_page_content
        
        content = fetch_page_content(source.list_url)
        
        if not content:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to fetch content from source"
            )
        
        return {
            "status": "success",
            "source_id": source_id,
            "source_name": source.name,
            "content_length": len(content),
            "message": f"Successfully fetched {len(content)} bytes from source"
        }
    
    except Exception as e:
        logger.error(
            "Source test failed",
            source_id=source_id,
            source_name=source.name,
            error=str(e)
        )
        
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Source test failed: {str(e)}"
        )