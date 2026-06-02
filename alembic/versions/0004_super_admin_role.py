"""add super_admin role and country_id to users

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widen role column from VARCHAR(10) to VARCHAR(15)
    op.alter_column(
        "users", "role",
        existing_type=sa.String(10),
        type_=sa.String(15),
        existing_nullable=False,
    )
    # Add country_id FK (nullable — super_admin has no country)
    op.add_column(
        "users",
        sa.Column("country_id", sa.Integer(), sa.ForeignKey("countries.id"), nullable=True),
    )
    op.create_index("ix_users_country_id", "users", ["country_id"])
    # Promote existing admin users to super_admin
    op.execute("UPDATE users SET role = 'super_admin' WHERE role = 'admin'")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'super_admin'")
    op.drop_index("ix_users_country_id", "users")
    op.drop_column("users", "country_id")
    op.alter_column(
        "users", "role",
        existing_type=sa.String(15),
        type_=sa.String(10),
        existing_nullable=False,
    )
