"""FastAPI dependencies and utilities."""

from typing import Annotated, Optional

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
SECRET_KEY = settings.jwt_secret_key if hasattr(settings, 'jwt_secret_key') else "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Database session dependency (re-export from db module)
# get_db is already imported from ..db above


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> Optional[dict]:
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
        
        return {"username": username, "email": payload.get("email")}
    
    except JWTError as e:
        logger.warning("Invalid JWT token", error=str(e))
        return None


async def require_auth(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
    """Require authentication (raises 401 if not authenticated)."""
    
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return current_user


def create_access_token(data: dict, expires_delta: Optional[int] = None) -> str:
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
CurrentUser = Annotated[Optional[dict], Depends(get_current_user)]
AuthenticatedUser = Annotated[dict, Depends(require_auth)]