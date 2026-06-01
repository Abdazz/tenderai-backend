"""User management endpoints (admin only)."""

import os
import secrets
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from ...email import send_credentials_email
from ...logging import get_logger
from ...models import User
from ..dependencies import AdminUser, DatabaseSession, get_password_hash

logger = get_logger(__name__)
router = APIRouter()

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")


class UserCreateRequest(BaseModel):
    username: str
    email: EmailStr
    role: str  # "admin" | "viewer"


class UserUpdateRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    password_reset_required: bool

    class Config:
        from_attributes = True


@router.get("", response_model=dict)
async def list_users(current_user: AdminUser, db: DatabaseSession):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return {"users": [UserOut.model_validate(u) for u in users]}


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    request: UserCreateRequest, current_user: AdminUser, db: DatabaseSession
):
    if request.role not in ("admin", "viewer"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'viewer'")

    if db.query(User).filter(User.username == request.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")

    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(status_code=409, detail="Email already exists")

    password = secrets.token_urlsafe(12)
    user = User(
        id=str(uuid.uuid4()),
        username=request.username,
        email=request.email,
        hashed_password=get_password_hash(password),
        role=request.role,
        is_active=True,
        password_reset_required=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    send_credentials_email(
        to_address=user.email,
        username=user.username,
        password=password,
        frontend_url=FRONTEND_URL,
        is_reset=False,
    )
    logger.info(
        "User created", username=user.username, created_by=current_user["username"]
    )
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    request: UserUpdateRequest,
    current_user: AdminUser,
    db: DatabaseSession,
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.username == current_user["username"] and request.is_active is False:
        raise HTTPException(
            status_code=400, detail="You cannot deactivate your own account"
        )

    if request.role is not None:
        if request.role not in ("admin", "viewer"):
            raise HTTPException(
                status_code=400, detail="role must be 'admin' or 'viewer'"
            )
        user.role = request.role

    if request.is_active is not None:
        user.is_active = request.is_active

    db.commit()
    db.refresh(user)
    logger.info("User updated", user_id=user_id, updated_by=current_user["username"])
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: str, current_user: AdminUser, db: DatabaseSession):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.username == current_user["username"]:
        raise HTTPException(
            status_code=400, detail="You cannot delete your own account"
        )
    db.delete(user)
    db.commit()
    logger.info("User deleted", user_id=user_id, deleted_by=current_user["username"])


@router.post("/{user_id}/reset-password", response_model=UserOut)
async def reset_password(user_id: str, current_user: AdminUser, db: DatabaseSession):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    password = secrets.token_urlsafe(12)
    user.hashed_password = get_password_hash(password)
    user.password_reset_required = True
    db.commit()
    db.refresh(user)

    send_credentials_email(
        to_address=user.email,
        username=user.username,
        password=password,
        frontend_url=FRONTEND_URL,
        is_reset=True,
    )
    logger.info("Password reset", user_id=user_id, reset_by=current_user["username"])
    return UserOut.model_validate(user)
