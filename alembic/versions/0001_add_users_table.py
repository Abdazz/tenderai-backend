"""add_users_table

Revision ID: 0001
Revises: 
Create Date: 2026-05-19
"""
import os
import uuid

import sqlalchemy as sa
from alembic import op
from passlib.context import CryptContext

revision = "0001"
down_revision = "0000"
branch_labels = None
depends_on = None

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(10), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("password_reset_required", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    # Seed initial admin from env vars
    admin_username = os.environ.get("TENDERAI_ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("TENDERAI_ADMIN_PASSWORD", "")
    admin_email = os.environ.get("TENDERAI_ADMIN_EMAIL", f"{admin_username}@tenderai.bf")

    if admin_password:
        op.execute(
            sa.text(
                "INSERT INTO users (id, username, email, hashed_password, role, "
                "is_active, password_reset_required) VALUES "
                "(:id, :username, :email, :hashed_password, 'admin', true, false)"
            ).bindparams(
                id=str(uuid.uuid4()),
                username=admin_username,
                email=admin_email,
                hashed_password=_pwd_context.hash(admin_password),
            )
        )


def downgrade() -> None:
    op.drop_index("ix_users_email", "users")
    op.drop_index("ix_users_username", "users")
    op.drop_table("users")
