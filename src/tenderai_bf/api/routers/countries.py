"""CRUD endpoints for countries and per-country settings."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy.exc import IntegrityError

from ...country_store import MUTABLE_SECTIONS, CountryStore
from ...logging import get_logger
from ...models import Country
from ..dependencies import AuthenticatedUser, DatabaseSession, SuperAdminUser
from ..schemas.countries import CountryCreate, CountryRead, CountryUpdate
from ..schemas.settings import SECTION_SCHEMAS

logger = get_logger(__name__)

router = APIRouter()


def _get_country_or_404(country_id: int, db: DatabaseSession) -> Country:
    country = db.query(Country).filter(Country.id == country_id).first()
    if not country:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Country not found")
    return country


@router.get("", response_model=list[CountryRead])
async def list_countries(db: DatabaseSession, user: AuthenticatedUser):
    return db.query(Country).order_by(Country.name).all()


@router.post("", response_model=CountryRead, status_code=status.HTTP_201_CREATED)
async def create_country(
    body: CountryCreate, db: DatabaseSession, user: SuperAdminUser
):
    country = Country(name=body.name, code=body.code.upper(), locale=body.locale)
    db.add(country)
    try:
        db.flush()
        db.commit()
        db.refresh(country)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Country with code '{body.code.upper()}' already exists",
        ) from e
    CountryStore.seed_from_global(db, country.id)
    return country


@router.get("/{country_id}", response_model=CountryRead)
async def get_country(country_id: int, db: DatabaseSession, user: AuthenticatedUser):
    return _get_country_or_404(country_id, db)


@router.put("/{country_id}", response_model=CountryRead)
async def update_country(
    country_id: int, body: CountryUpdate, db: DatabaseSession, user: SuperAdminUser
):
    country = _get_country_or_404(country_id, db)
    if body.name is not None:
        country.name = body.name
    if body.locale is not None:
        country.locale = body.locale
    if body.active is not None:
        country.active = body.active
    db.commit()
    db.refresh(country)
    return country


@router.delete("/{country_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_country(country_id: int, db: DatabaseSession, user: SuperAdminUser):
    country = _get_country_or_404(country_id, db)
    country.active = False
    db.commit()


@router.get("/{country_id}/settings")
async def get_all_settings(
    country_id: int, db: DatabaseSession, user: AuthenticatedUser
):
    _get_country_or_404(country_id, db)
    return CountryStore.get_all_with_fallback(db, country_id)


@router.get("/{country_id}/settings/{section}")
async def get_section(
    country_id: int, section: str, db: DatabaseSession, user: AuthenticatedUser
):
    if section not in MUTABLE_SECTIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"Unknown section: {section}"
        )
    _get_country_or_404(country_id, db)
    data = CountryStore.get_section(db, country_id, section)
    if data is None:
        from ...models import AppSettings

        row = db.query(AppSettings).filter(AppSettings.section == section).first()
        data = row.data if row else {}
    return data


@router.put("/{country_id}/settings/{section}")
async def update_section(
    country_id: int,
    section: str,
    body: dict,
    db: DatabaseSession,
    user: AuthenticatedUser,
):
    if section not in MUTABLE_SECTIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"Unknown section: {section}"
        )
    # Only company_admin or super_admin may write settings
    if user.get("role") not in ("super_admin", "company_admin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Admin role required to update settings"
        )
    # Non-super_admin can only update their own country's settings
    if user.get("role") != "super_admin" and user.get("country_id") != country_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Access denied for this country"
        )
    country = _get_country_or_404(country_id, db)
    schema_cls = SECTION_SCHEMAS.get(section)
    if schema_cls:
        try:
            schema_cls(**body)
        except Exception as e:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
            ) from e
    CountryStore.put_section(db, country_id, section, body, updated_by=user["username"])
    if section == "scheduler":
        from ...scheduler.schedule import reschedule_country_job

        try:
            reschedule_country_job(country_id, country.code, body)
        except Exception as e:
            logger.warning(
                "Failed to reschedule country job after settings update",
                country_id=country_id,
                error=str(e),
            )
    return body


@router.post("/{country_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_run(
    country_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    background_tasks: BackgroundTasks,
):
    # Only company_admin or super_admin may trigger pipeline runs
    if user.get("role") not in ("super_admin", "company_admin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Admin role required to trigger runs"
        )
    # Non-super_admin can only trigger runs for their own country
    if user.get("role") != "super_admin" and user.get("country_id") != country_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Access denied for this country"
        )
    _get_country_or_404(country_id, db)
    from ...agents import get_delivery_pipeline, get_pipeline

    def _run():
        get_pipeline().run(
            country_id=country_id,
            triggered_by="api",
            triggered_by_user=user["username"],
        )
        # Stopgap until the Auth/API plan adds company selection to this
        # endpoint: deliver to YULCOM (company zero) so this manual trigger
        # keeps sending email as it did before the pipeline split.
        from ...db import get_db_context
        from ...models import Company

        with get_db_context() as _db:
            yulcom = _db.query(Company).filter(Company.slug == "yulcom").first()
            yulcom_id = yulcom.id if yulcom else None
        if yulcom_id is not None:
            get_delivery_pipeline().run(
                company_id=yulcom_id,
                country_id=country_id,
                triggered_by="api",
                triggered_by_user=user["username"],
            )
        else:
            logger.error(
                "YULCOM company not found — skipping delivery after manual harvest trigger",
                country_id=country_id,
            )

    background_tasks.add_task(_run)
    return {"status": "accepted", "country_id": country_id}
