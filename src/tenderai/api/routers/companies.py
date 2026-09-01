"""CRUD endpoints for companies, their country subscriptions, and per-company settings."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy.exc import IntegrityError

from ...company_store import MUTABLE_SECTIONS, CompanyStore
from ...logging import get_logger
from ...models import Company, CompanyCountrySubscription, Country
from ..dependencies import CompanyScopedUser, DatabaseSession, SuperAdminUser
from ..schemas.companies import (
    CompanyCountrySubscriptionCreate,
    CompanyCountrySubscriptionRead,
    CompanyCreate,
    CompanyRead,
    CompanyUpdate,
)
from ..schemas.settings import SECTION_SCHEMAS

logger = get_logger(__name__)

router = APIRouter()


def _get_company_or_404(company_id: int, db: DatabaseSession) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


@router.get("", response_model=list[CompanyRead])
async def list_companies(db: DatabaseSession, user: SuperAdminUser):
    return db.query(Company).order_by(Company.name).all()


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(
    body: CompanyCreate, db: DatabaseSession, user: SuperAdminUser
):
    company = Company(
        name=body.name,
        slug=body.slug,
        logo_url=body.logo_url,
        subject_prefix=body.subject_prefix,
        signature=body.signature,
    )
    db.add(company)
    try:
        db.flush()
        db.commit()
        db.refresh(company)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Company with slug '{body.slug}' already exists",
        ) from e
    CompanyStore.seed_from_global(db, company.id)
    return company


@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(company_id: int, db: DatabaseSession, user: CompanyScopedUser):
    return _get_company_or_404(company_id, db)


@router.put("/{company_id}", response_model=CompanyRead)
async def update_company(
    company_id: int, body: CompanyUpdate, db: DatabaseSession, user: SuperAdminUser
):
    company = _get_company_or_404(company_id, db)
    if body.name is not None:
        company.name = body.name
    if body.active is not None:
        company.active = body.active
    if body.logo_url is not None:
        company.logo_url = body.logo_url
    if body.subject_prefix is not None:
        company.subject_prefix = body.subject_prefix
    if body.signature is not None:
        company.signature = body.signature
    db.commit()
    db.refresh(company)
    return company


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company_id: int, db: DatabaseSession, user: SuperAdminUser):
    company = _get_company_or_404(company_id, db)
    company.active = False
    db.commit()


@router.get(
    "/{company_id}/countries", response_model=list[CompanyCountrySubscriptionRead]
)
async def list_company_countries(
    company_id: int, db: DatabaseSession, user: CompanyScopedUser
):
    _get_company_or_404(company_id, db)
    return (
        db.query(CompanyCountrySubscription)
        .filter(CompanyCountrySubscription.company_id == company_id)
        .all()
    )


@router.post(
    "/{company_id}/countries",
    response_model=CompanyCountrySubscriptionRead,
    status_code=status.HTTP_201_CREATED,
)
async def subscribe_company_country(
    company_id: int,
    body: CompanyCountrySubscriptionCreate,
    db: DatabaseSession,
    user: SuperAdminUser,
):
    _get_company_or_404(company_id, db)
    country = db.query(Country).filter(Country.id == body.country_id).first()
    if not country:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Country not found")

    existing = (
        db.query(CompanyCountrySubscription)
        .filter(
            CompanyCountrySubscription.company_id == company_id,
            CompanyCountrySubscription.country_id == body.country_id,
        )
        .first()
    )
    if existing:
        existing.enabled = True
        db.commit()
        db.refresh(existing)
        return existing

    sub = CompanyCountrySubscription(
        company_id=company_id, country_id=body.country_id, enabled=True
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.delete(
    "/{company_id}/countries/{country_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unsubscribe_company_country(
    company_id: int, country_id: int, db: DatabaseSession, user: SuperAdminUser
):
    sub = (
        db.query(CompanyCountrySubscription)
        .filter(
            CompanyCountrySubscription.company_id == company_id,
            CompanyCountrySubscription.country_id == country_id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    sub.enabled = False
    db.commit()


@router.get("/{company_id}/settings")
async def get_all_company_settings(
    company_id: int, db: DatabaseSession, user: CompanyScopedUser
):
    _get_company_or_404(company_id, db)
    return CompanyStore.get_all_with_fallback(db, company_id)


@router.get("/{company_id}/settings/{section}")
async def get_company_settings_section(
    company_id: int, section: str, db: DatabaseSession, user: CompanyScopedUser
):
    if section not in MUTABLE_SECTIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"Unknown section: {section}"
        )
    _get_company_or_404(company_id, db)
    data = CompanyStore.get_section(db, company_id, section)
    if data is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Section '{section}' not found for this company",
        )
    return data


@router.put("/{company_id}/settings/{section}")
async def update_company_settings_section(
    company_id: int,
    section: str,
    body: dict,
    db: DatabaseSession,
    user: CompanyScopedUser,
):
    if section not in MUTABLE_SECTIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"Unknown section: {section}"
        )
    if user.get("role") not in ("super_admin", "company_admin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Company admin role required"
        )
    company = _get_company_or_404(company_id, db)
    schema_cls = SECTION_SCHEMAS.get(section)
    if schema_cls:
        try:
            schema_cls(**body)
        except Exception as e:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
            ) from e
    CompanyStore.put_section(db, company_id, section, body, updated_by=user["username"])
    if section == "scheduler":
        from ...scheduler.schedule import reschedule_company_delivery_job

        try:
            reschedule_company_delivery_job(company_id, company.slug, body)
        except Exception as e:
            logger.warning(
                "Failed to reschedule company delivery job after settings update",
                company_id=company_id,
                error=str(e),
            )
    return body


@router.post("/{company_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_company_delivery(
    company_id: int,
    db: DatabaseSession,
    user: CompanyScopedUser,
    background_tasks: BackgroundTasks,
):
    if user.get("role") not in ("super_admin", "company_admin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Company admin role required"
        )
    company = _get_company_or_404(company_id, db)

    subscriptions = (
        db.query(CompanyCountrySubscription)
        .filter(
            CompanyCountrySubscription.company_id == company_id,
            CompanyCountrySubscription.enabled == True,  # noqa: E712
        )
        .all()
    )
    country_ids = [sub.country_id for sub in subscriptions]
    triggered_by_user = user["username"]

    def _run():
        from ...agents import get_delivery_pipeline

        for country_id in country_ids:
            get_delivery_pipeline().run(
                company_id=company_id,
                country_id=country_id,
                triggered_by="api",
                triggered_by_user=triggered_by_user,
            )

    background_tasks.add_task(_run)
    return {
        "status": "accepted",
        "company_id": company_id,
        "company_name": company.name,
    }
