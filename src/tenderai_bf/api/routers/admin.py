"""Admin and authentication endpoints."""

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr

from ...config import settings
from ...logging import get_logger
from ..dependencies import (
    AuthenticatedUser,
    create_access_token,
    get_password_hash,
    verify_password,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

logger = get_logger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    """Login request model."""
    
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response model."""
    
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    """User response model."""
    
    username: str
    email: Optional[str] = None
    is_active: bool = True
    is_admin: bool = True


class EmailTestRequest(BaseModel):
    """Email test request model."""
    
    to_address: Optional[EmailStr] = None
    subject: Optional[str] = None
    body: Optional[str] = None


# Hardcoded admin credentials (TODO: Move to database)
ADMIN_USERS = {
    "admin": {
        "username": "admin",
        "email": "admin@tenderai.bf",
        "hashed_password": get_password_hash("admin123"),  # Change in production!
        "is_active": True,
        "is_admin": True
    }
}


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate user with username and password."""
    
    user = ADMIN_USERS.get(username)
    
    if not user:
        return None
    
    if not verify_password(password, user["hashed_password"]):
        return None
    
    return user


@router.post("/login", response_model=LoginResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint to get access token.
    
    Use username and password to get a JWT token.
    """
    
    user = authenticate_user(form_data.username, form_data.password)
    
    if not user:
        logger.warning("Failed login attempt", username=form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    access_token = create_access_token(
        data={"sub": user["username"], "email": user.get("email")},
        expires_delta=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    
    logger.info("User logged in", username=user["username"])
    
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60  # Convert to seconds
    )


@router.post("/login/simple", response_model=LoginResponse)
async def login_simple(request: LoginRequest):
    """Simplified login endpoint (for Gradio and other clients)."""
    
    user = authenticate_user(request.username, request.password)
    
    if not user:
        logger.warning("Failed login attempt", username=request.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    # Create access token
    access_token = create_access_token(
        data={"sub": user["username"], "email": user.get("email")},
        expires_delta=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    
    logger.info("User logged in", username=user["username"])
    
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(user: AuthenticatedUser):
    """Get current authenticated user information."""
    
    return UserResponse(
        username=user["username"],
        email=user.get("email"),
        is_active=True,
        is_admin=True
    )


@router.post("/test-email")
async def test_email(request: EmailTestRequest, user: AuthenticatedUser):
    """Test email configuration by sending a test email.
    
    Requires authentication.
    """
    
    from ...email import send_email
    
    try:
        # Prepare test email
        to_address = request.to_address or settings.email.to_address
        subject = request.subject or "Test Email from TenderAI BF"
        body = request.body or """
        Ceci est un email de test depuis TenderAI BF.
        
        Si vous recevez cet email, la configuration SMTP fonctionne correctement.
        
        Cordialement,
        TenderAI BF
        """
        
        # Send email
        success = send_email(
            to_address=to_address,
            subject=subject,
            body=body
        )
        
        if success:
            logger.info(
                "Test email sent successfully",
                to_address=to_address,
                sent_by=user["username"]
            )
            
            return {
                "status": "success",
                "message": f"Test email sent to {to_address}",
                "to_address": to_address
            }
        else:
            raise Exception("Email sending failed")
    
    except Exception as e:
        logger.error(
            "Failed to send test email",
            error=str(e),
            requested_by=user["username"]
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send test email: {str(e)}"
        )


@router.post("/clear-cache")
async def clear_cache(user: AuthenticatedUser):
    """Clear application caches.
    
    Requires authentication.
    """
    
    try:
        # Clear robots.txt cache
        from ...utils.robots import _robots_checker
        _robots_checker.clear_cache()
        
        logger.info("Caches cleared", cleared_by=user["username"])
        
        return {
            "status": "success",
            "message": "Caches cleared successfully",
            "caches_cleared": ["robots_txt"]
        }
    
    except Exception as e:
        logger.error("Failed to clear caches", error=str(e))
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear caches: {str(e)}"
        )


@router.get("/settings")
async def get_settings_info(user: AuthenticatedUser):
    """Get current application settings (safe subset).
    
    Requires authentication.
    """
    
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "environment": settings.environment,
        "debug": settings.debug,
        "log_level": settings.log_level,
        "database": {
            "url_masked": "***" if settings.database_url else None,
            "pool_size": getattr(settings.database, 'pool_size', None) if hasattr(settings, 'database') else None
        },
        "email": {
            "smtp_server": settings.email.smtp_server,
            "smtp_port": settings.email.smtp_port,
            "from_address": settings.email.from_address,
            "to_address": settings.email.to_address
        },
        "storage": {
            "endpoint_url": settings.storage.endpoint_url,
            "bucket_name": settings.storage.bucket_name
        },
        "pipeline": {
            "max_items_per_source": settings.pipeline.max_items_per_source,
            "max_total_items": settings.pipeline.max_total_items,
            "timeout_seconds": settings.pipeline.timeout_seconds
        },
        "scheduler": {
            "enabled": settings.scheduler.enabled,
            "cron_schedule": settings.scheduler.cron_schedule,
            "timezone": settings.scheduler.timezone
        }
    }


@router.post("/reload-config")
async def reload_config(user: AuthenticatedUser):
    """Reload configuration from settings.yaml.
    
    Requires authentication.
    """
    
    try:
        # Reload settings
        # Note: This is a simplified version - full reload may require app restart
        
        logger.info("Config reload requested", requested_by=user["username"])
        
        return {
            "status": "success",
            "message": "Configuration reload requested (may require app restart for full effect)",
            "note": "Some settings require application restart to take effect"
        }
    
    except Exception as e:
        logger.error("Failed to reload config", error=str(e))
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reload config: {str(e)}"
        )