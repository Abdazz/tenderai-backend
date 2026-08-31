"""recipients_unique_per_company

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-31

Rescopes the recipients uniqueness guarantee to include company_id.

Migration 0012 made email unique per (email, country_id), predating the
company_id column added in migration 0013. Two companies sharing a country
and a recipient email currently pass the application-level dedup check in
create_recipient (which already filters by company_id) but then hit this
stale DB-level index on commit, raising an unhandled IntegrityError (500)
instead of the intended 409.

Replaces uq_recipients_email_country (email, country_id) with
uq_recipients_company_email_country (company_id, email, country_id).
Idempotent — safe to re-run.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _index_exists(bind, index_name: str) -> bool:
    row = bind.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
        {"name": index_name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()

    if _index_exists(bind, "uq_recipients_email_country"):
        op.drop_index("uq_recipients_email_country", table_name="recipients")

    if not _index_exists(bind, "uq_recipients_company_email_country"):
        op.create_index(
            "uq_recipients_company_email_country",
            "recipients",
            ["company_id", "email", "country_id"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _index_exists(bind, "uq_recipients_company_email_country"):
        op.drop_index(
            "uq_recipients_company_email_country", table_name="recipients"
        )

    if not _index_exists(bind, "uq_recipients_email_country"):
        op.create_index(
            "uq_recipients_email_country",
            "recipients",
            ["email", "country_id"],
            unique=True,
        )
