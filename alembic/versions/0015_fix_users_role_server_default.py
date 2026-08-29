"""fix_users_role_server_default

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-29

Migration 0014 renamed existing role values (admin -> company_admin,
viewer -> company_viewer) but the users.role column's DB-level
server_default was never updated — it was still "viewer" prior to
this migration, so a raw INSERT omitting role would still land the
old, pre-rename value. This fixes the server_default to match the
new role model (the ORM-level default was already updated to
"company_viewer" alongside this).
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(15),
        server_default="company_viewer",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(15),
        server_default="viewer",
        existing_nullable=False,
    )
