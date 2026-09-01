"""FastAPI dependencies and utilities."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..logging import get_logger

logger = get_logger(__name__)

# OAuth2 scheme for authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/admin/login", auto_error=False)

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
SECRET_KEY = settings.monitoring.jwt_secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Database session dependency (re-export from db module)
# get_db is already imported from ..db above


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> dict | None:
    """Get current authenticated user from JWT token.

    Returns None if no token or invalid token (for optional auth).
    """

    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")

        if username is None:
            return None

        return {
            "username": username,
            "email": payload.get("email"),
            "role": payload.get("role", "company_viewer"),
            "country_id": payload.get("country_id"),
            "company_id": payload.get("company_id"),
            "password_reset_required": payload.get("password_reset_required", False),
        }

    except JWTError as e:
        logger.error("Invalid JWT token", error=str(e))
        return None


async def require_auth(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Require authentication (raises 401 if not authenticated)."""

    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return current_user


async def require_admin(current_user: Annotated[dict, Depends(require_auth)]) -> dict:
    """Require company_admin role. Raises 403 if authenticated but not company_admin."""
    if current_user.get("role") != "company_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company admin access required",
        )
    return current_user


async def require_super_admin(
    current_user: Annotated[dict, Depends(require_auth)],
) -> dict:
    """Require super_admin role. Raises 403 if not super_admin."""
    if current_user.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super-admin access required",
        )
    return current_user


async def require_company_scope(
    current_user: Annotated[dict, Depends(require_auth)],
    company_id: int | None = None,
) -> dict:
    """Enforce company scoping: super_admin may access any company_id (including
    None); company_admin/company_viewer may only access their own company_id.
    Raises 403 (not 404) on a mismatch, so a non-super_admin caller cannot
    distinguish "wrong company" from "company doesn't exist" via status code.
    """
    if current_user.get("role") == "super_admin":
        return current_user
    if current_user.get("company_id") != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this company",
        )
    return current_user


def resolve_delivery_company_id(
    user: dict | None, requested_company_id: int | None, db: Session
) -> int | None:
    """Resolve which company_id a manual harvest-trigger endpoint should
    deliver to.

    - Anonymous caller (user is None): no company can be resolved — caller
      must handle None by skipping delivery.
    - company_admin/company_viewer: always their own company_id. Callers
      must reject a mismatched requested_company_id with 403 *before*
      calling this (see the two router call sites below) — this function
      does not re-check that, it only resolves the effective value once
      authorization has already passed.
    - super_admin with an explicit requested_company_id: uses it as given.
    - super_admin with no explicit selection: falls back to the YULCOM
      company, preserving today's default behavior for the existing
      "Lancer maintenant" button until the frontend (Section 4) adds a
      real company picker that sends an explicit company_id.

    Returns None if no company can be resolved at all (e.g. anonymous
    caller, or the YULCOM row is missing) — callers must handle None by
    skipping delivery and logging, not raising.
    """
    if user is None:
        return None
    if user.get("role") != "super_admin":
        return user.get("company_id")
    if requested_company_id is not None:
        return requested_company_id

    from ..models import Company

    yulcom = db.query(Company).filter(Company.slug == "yulcom").first()
    return yulcom.id if yulcom else None


def create_access_token(data: dict, expires_delta: int | None = None) -> str:
    """Create JWT access token."""

    from datetime import datetime, timedelta

    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + timedelta(minutes=expires_delta)
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash password."""
    return pwd_context.hash(password)


# Type aliases for dependencies
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[dict | None, Depends(get_current_user)]
AuthenticatedUser = Annotated[dict, Depends(require_auth)]
AdminUser = Annotated[dict, Depends(require_admin)]
SuperAdminUser = Annotated[dict, Depends(require_super_admin)]
CompanyScopedUser = Annotated[dict, Depends(require_company_scope)]
