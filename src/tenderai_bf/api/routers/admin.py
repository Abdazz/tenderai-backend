"""Admin and authentication endpoints."""

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ...config import settings
from ...db import get_db
from ...logging import get_logger
from ...models import User
from ..dependencies import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    AuthenticatedUser,
    DatabaseSession,
    create_access_token,
    get_password_hash,
    verify_password,
)

logger = get_logger(__name__)
router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    password_reset_required: bool


class UserResponse(BaseModel):
    username: str
    email: str | None = None
    role: str
    is_active: bool
    password_reset_required: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class EmailTestRequest(BaseModel):
    to_address: EmailStr | None = None
    subject: str | None = None
    body: str | None = None


def _authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Look up active user in DB and verify password. Returns User or None."""
    user = (
        db.query(User).filter(User.username == username, User.is_active == True).first()
    )
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def _build_token(user: User) -> LoginResponse:
    token = create_access_token(
        data={
            "sub": user.username,
            "email": user.email,
            "role": user.role,
            "password_reset_required": user.password_reset_required,
        }
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        role=user.role,
        password_reset_required=user.password_reset_required,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Login endpoint (OAuth2 form). Returns JWT token."""
    user = _authenticate_user(db, form_data.username, form_data.password)
    if not user:
        logger.error("Failed login attempt", username=form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user.last_login_at = datetime.utcnow()
    db.commit()
    logger.info("User logged in", username=user.username)
    return _build_token(user)


@router.post("/login/simple", response_model=LoginResponse)
async def login_simple(request: LoginRequest, db: DatabaseSession):
    """Simplified login endpoint (JSON body)."""
    user = _authenticate_user(db, request.username, request.password)
    if not user:
        logger.error("Failed login attempt", username=request.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    user.last_login_at = datetime.utcnow()
    db.commit()
    logger.info("User logged in", username=user.username)
    return _build_token(user)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(user: AuthenticatedUser):
    """Get current authenticated user information."""
    return UserResponse(
        username=user["username"],
        email=user.get("email"),
        role=user.get("role", "viewer"),
        is_active=True,
        password_reset_required=user.get("password_reset_required", False),
    )


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: AuthenticatedUser,
    db: DatabaseSession,
):
    """Change the authenticated user's own password."""
    user = db.query(User).filter(User.username == current_user["username"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(request.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=400, detail="Password must be at least 8 characters"
        )
    user.hashed_password = get_password_hash(request.new_password)
    user.password_reset_required = False
    db.commit()
    logger.info("Password changed", username=user.username)
    return {"status": "success", "message": "Password changed successfully"}


@router.post("/test-email")
async def test_email(request: EmailTestRequest, user: AuthenticatedUser):
    """Test email configuration. Requires authentication."""
    from ...email import send_email

    try:
        to_address = request.to_address or settings.email.to_address
        subject = request.subject or "Test Email from TenderAI BF"
        body = request.body or (
            "Ceci est un email de test depuis TenderAI BF.\n\n"
            "Si vous recevez cet email, la configuration SMTP fonctionne correctement.\n\n"
            "Cordialement,\nTenderAI BF"
        )
        success = send_email(to_address=to_address, subject=subject, body=body)
        if not success:
            raise Exception("Email sending failed")
        logger.info("Test email sent", to_address=to_address, sent_by=user["username"])
        return {
            "status": "success",
            "message": f"Test email sent to {to_address}",
            "to_address": to_address,
        }
    except Exception as e:
        logger.error("Failed to send test email", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to send test email: {e!s}"
        )


@router.post("/clear-cache")
async def clear_cache(user: AuthenticatedUser):
    """Clear application caches. Requires authentication."""
    try:
        from ...utils.robots import _robots_checker

        _robots_checker.clear_cache()
        logger.info("Caches cleared", cleared_by=user["username"])
        return {
            "status": "success",
            "message": "Caches cleared successfully",
            "caches_cleared": ["robots_txt"],
        }
    except Exception as e:
        logger.error("Failed to clear caches", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to clear caches: {e!s}")


@router.get("/settings")
async def get_all_settings(user: AuthenticatedUser, db: DatabaseSession):
    """Get all mutable settings sections from DB + read-only env-var sections."""
    from ...settings_store import SettingsStore

    mutable = SettingsStore.get_all(db)
    readonly = {
        "database": {"url": "***"},
        "minio": {
            "endpoint": settings.minio.endpoint,
            "bucket_name": settings.minio.bucket_name,
            "credentials": "***",
        },
        "smtp": {
            "host": settings.smtp.host,
            "port": settings.smtp.port,
            "credentials": "***",
        },
        "security": {
            "admin_username": settings.security.admin_username,
            "jwt_secret": "***",
            "admin_password": "***",
        },
    }
    return {"sections": mutable, "readonly": readonly}


@router.get("/settings/{section}")
async def get_section_settings(
    section: str, user: AuthenticatedUser, db: DatabaseSession
):
    """Get a single mutable settings section from DB."""
    from ...settings_store import MUTABLE_SECTIONS, SettingsStore

    if section not in MUTABLE_SECTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown section '{section}'")
    data = SettingsStore.get_section(db, section)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Section '{section}' not found in DB — run /seed first",
        )
    return data


@router.put("/settings/{section}")
async def update_section_settings(
    section: str,
    user: AuthenticatedUser,
    db: DatabaseSession,
    payload: dict = Body(...),
):
    """Validate and persist a settings section, then reload in-memory config."""
    from ...api.schemas.settings import SECTION_SCHEMAS
    from ...config import reload_settings_from_db
    from ...settings_store import MUTABLE_SECTIONS, SettingsStore

    if section not in MUTABLE_SECTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown section '{section}'")

    schema_cls = SECTION_SCHEMAS[section]
    try:
        validated = schema_cls(**payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    SettingsStore.put_section(
        db, section, validated.model_dump(), updated_by=user["username"]
    )
    reload_settings_from_db(db)

    if section == "scheduler":
        _reschedule_if_running(
            settings.scheduler.cron_schedule, settings.scheduler.timezone
        )

    logger.info("Settings updated", section=section, updated_by=user["username"])
    return {"status": "ok", "section": section}


@router.post("/settings/seed")
async def seed_settings(user: AuthenticatedUser, db: DatabaseSession):
    """Seed DB with current in-memory settings (idempotent)."""
    from ...config import reload_settings_from_db
    from ...settings_store import SettingsStore

    seeded = SettingsStore.seed_from_settings(db)
    reload_settings_from_db(db)
    logger.info("Settings seeded", sections=seeded, requested_by=user["username"])
    return {"status": "ok", "seeded": seeded}


def _reschedule_if_running(cron_schedule: str, timezone: str) -> None:
    """Signal the in-process APScheduler to use the new cron, if it's running."""
    try:
        from ...scheduler.schedule import _scheduler_instance

        if _scheduler_instance and _scheduler_instance.running:
            import pytz
            from apscheduler.triggers.cron import CronTrigger

            parts = cron_schedule.split()
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                timezone=pytz.timezone(timezone),
            )
            _scheduler_instance.reschedule_job("daily_pipeline", trigger=trigger)
            logger.info("Scheduler rescheduled", cron=cron_schedule, tz=timezone)
    except Exception as e:
        logger.warning("Could not reschedule in-process scheduler", error=str(e))
