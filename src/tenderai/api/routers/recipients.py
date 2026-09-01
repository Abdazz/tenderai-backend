"""Recipients management endpoints."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

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
    company_id: int | None = None,
):
    from ...models import Recipient

    query = db.query(Recipient)
    if user.get("role") != "super_admin":
        query = query.filter(Recipient.company_id == user.get("company_id"))
    elif company_id is not None:
        query = query.filter(Recipient.company_id == company_id)
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
    if user.get("role") != "super_admin" and row.company_id != user.get("company_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this company",
        )
    return RecipientSchema.from_orm(row)


@router.post("", response_model=RecipientSchema, status_code=status.HTTP_201_CREATED)
async def create_recipient(
    request: RecipientCreate, db: DatabaseSession, user: AuthenticatedUser
):
    from ...models import Recipient

    # Non-super_admin cannot create a recipient for a company other than their own
    if (
        user.get("role") != "super_admin"
        and request.company_id is not None
        and request.company_id != user.get("company_id")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create a recipient for another company",
        )

    from ..dependencies import resolve_delivery_company_id

    target_company_id = resolve_delivery_company_id(user, request.company_id, db)

    query = db.query(Recipient).filter(
        Recipient.email == request.email, Recipient.company_id == target_company_id
    )
    if request.country_id is not None:
        query = query.filter(Recipient.country_id == request.country_id)
    if query.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Recipient with email '{request.email}' already exists for this country",
        )

    row = Recipient(
        email=request.email,
        name=request.name,
        group=request.group,
        enabled=request.enabled,
        preferences=request.preferences,
        country_id=request.country_id,
        company_id=target_company_id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Recipient with email '{request.email}' already exists for this country",
        ) from e
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

    if user.get("role") == "company_viewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company viewer role cannot modify recipients",
        )

    row = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipient {recipient_id} not found",
        )
    if user.get("role") != "super_admin" and row.company_id != user.get("company_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this company",
        )

    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(row, field, value)

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Recipient with email '{row.email}' already exists for this country",
        ) from e
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

    if user.get("role") == "company_viewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company viewer role cannot delete recipients",
        )

    row = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipient {recipient_id} not found",
        )
    if user.get("role") != "super_admin" and row.company_id != user.get("company_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this company",
        )

    db.delete(row)
    db.commit()

    logger.info(
        "Recipient deleted", recipient_id=recipient_id, deleted_by=user.get("username")
    )
    return None
