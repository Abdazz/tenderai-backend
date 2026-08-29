"""rename_admin_viewer_roles

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-29

Renames User.role values to match the company-scoped role model:
admin -> company_admin, viewer -> company_viewer. super_admin is
unchanged. Idempotent — safe to re-run (UPDATE ... WHERE role = X
is a no-op once already applied).
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'company_admin' WHERE role = 'admin'")
    op.execute("UPDATE users SET role = 'company_viewer' WHERE role = 'viewer'")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'company_admin'")
    op.execute("UPDATE users SET role = 'viewer' WHERE role = 'company_viewer'")
