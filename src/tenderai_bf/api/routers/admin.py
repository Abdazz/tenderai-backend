"""Admin and authentication endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
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
    email: Optional[str] = None
    role: str
    is_active: bool
    password_reset_required: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class EmailTestRequest(BaseModel):
    to_address: Optional[EmailStr] = None
    subject: Optional[str] = None
    body: Optional[str] = None


def _authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Look up active user in DB and verify password. Returns User or None."""
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
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
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
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
        return {"status": "success", "message": f"Test email sent to {to_address}", "to_address": to_address}
    except Exception as e:
        logger.error("Failed to send test email", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to send test email: {str(e)}")


@router.post("/clear-cache")
async def clear_cache(user: AuthenticatedUser):
    """Clear application caches. Requires authentication."""
    try:
        from ...utils.robots import _robots_checker
        _robots_checker.clear_cache()
        logger.info("Caches cleared", cleared_by=user["username"])
        return {"status": "success", "message": "Caches cleared successfully", "caches_cleared": ["robots_txt"]}
    except Exception as e:
        logger.error("Failed to clear caches", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to clear caches: {str(e)}")


@router.get("/settings")
async def get_settings_info(user: AuthenticatedUser):
    """Get current application settings (safe subset). Requires authentication."""
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "environment": settings.environment,
        "debug": settings.debug,
        "log_level": settings.log_level,
        "database": {
            "url_masked": "***" if settings.database_url else None,
        },
        "email": {
            "smtp_server": settings.email.smtp_server,
            "smtp_port": settings.email.smtp_port,
            "from_address": settings.email.from_address,
            "to_address": settings.email.to_address,
        },
        "storage": {
            "endpoint_url": settings.storage.endpoint_url,
            "bucket_name": settings.storage.bucket_name,
        },
        "pipeline": {
            "max_items_per_source": settings.pipeline.max_items_per_source,
            "max_total_items": settings.pipeline.max_total_items,
            "timeout_seconds": settings.pipeline.timeout_seconds,
        },
        "scheduler": {
            "enabled": settings.scheduler.enabled,
            "cron_schedule": settings.scheduler.cron_schedule,
            "timezone": settings.scheduler.timezone,
        },
    }


@router.post("/reload-config")
async def reload_config(user: AuthenticatedUser):
    """Reload configuration. Requires authentication."""
    logger.info("Config reload requested", requested_by=user["username"])
    return {
        "status": "success",
        "message": "Configuration reload requested (may require app restart for full effect)",
        "note": "Some settings require application restart to take effect",
    }
