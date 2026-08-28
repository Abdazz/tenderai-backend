"""Recipients management endpoints."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ...logging import get_logger
from ...schemas import Recipient as RecipientSchema, RecipientCreate, RecipientUpdate
from ..dependencies import AuthenticatedUser, DatabaseSession

logger = get_logger(__name__)

router = APIRouter()


class RecipientListResponse(BaseModel):
    recipients: list[RecipientSchema]
    total: int


@router.get("", response_model=RecipientListResponse)
async def list_recipients(
    db: DatabaseSession,
    user: AuthenticatedUser,
    country_id: int | None = None,
    enabled_only: bool = False,
):
    from ...models import Recipient

    query = db.query(Recipient)
    if country_id is not None:
        query = query.filter(Recipient.country_id == country_id)
    if enabled_only:
        query = query.filter(Recipient.enabled == True)  # noqa: E712 — SQLAlchemy column comparison, not a Python bool check

    rows = query.order_by(Recipient.email).all()
    return RecipientListResponse(
        recipients=[RecipientSchema.from_orm(r) for r in rows],
        total=len(rows),
    )


@router.get("/{recipient_id}", response_model=RecipientSchema)
async def get_recipient(
    recipient_id: int, db: DatabaseSession, user: AuthenticatedUser
):
    from ...models import Recipient

    row = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipient {recipient_id} not found",
        )
    return RecipientSchema.from_orm(row)


@router.post("", response_model=RecipientSchema, status_code=status.HTTP_201_CREATED)
async def create_recipient(
    request: RecipientCreate, db: DatabaseSession, user: AuthenticatedUser
):
    from ...models import Company, Recipient

    query = db.query(Recipient).filter(Recipient.email == request.email)
    if request.country_id is not None:
        query = query.filter(Recipient.country_id == request.country_id)
    if query.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Recipient with email '{request.email}' already exists for this country",
        )

    # Stopgap until the Auth/API plan adds company selection to this
    # endpoint: attach new recipients to YULCOM so they're actually picked
    # up by email_report_node's company-scoped query instead of silently
    # getting company_id=NULL and being excluded from every delivery.
    yulcom = db.query(Company).filter(Company.slug == "yulcom").first()
    yulcom_id = yulcom.id if yulcom else None

    row = Recipient(
        email=request.email,
        name=request.name,
        group=request.group,
        enabled=request.enabled,
        preferences=request.preferences,
        country_id=request.country_id,
        company_id=yulcom_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    logger.info(
        "Recipient created",
        recipient_id=row.id,
        email=row.email,
        created_by=user.get("username"),
    )
    return RecipientSchema.from_orm(row)


@router.put("/{recipient_id}", response_model=RecipientSchema)
async def update_recipient(
    recipient_id: int,
    request: RecipientUpdate,
    db: DatabaseSession,
    user: AuthenticatedUser,
):
    from ...models import Recipient

    row = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipient {recipient_id} not found",
        )

    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(row, field, value)

    db.commit()
    db.refresh(row)

    logger.info(
        "Recipient updated", recipient_id=row.id, updated_by=user.get("username")
    )
    return RecipientSchema.from_orm(row)


@router.delete("/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipient(
    recipient_id: int, db: DatabaseSession, user: AuthenticatedUser
):
    from ...models import Recipient

    row = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipient {recipient_id} not found",
        )

    db.delete(row)
    db.commit()

    logger.info(
        "Recipient deleted", recipient_id=recipient_id, deleted_by=user.get("username")
    )
    return None
