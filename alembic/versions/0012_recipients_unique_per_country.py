"""recipients_unique_per_country

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-21

Changes the unique constraint on recipients from (email) to (email, country_id)
so the same email can be a recipient for multiple countries.
Also inserts jerome@yulcom.ca for Canada (already exists for BF).
Idempotent.
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _index_exists(bind, index_name: str) -> bool:
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :name"
        ),
        {"name": index_name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()

    # Drop old unique constraint on email alone
    if _index_exists(bind, "ix_recipients_email"):
        op.drop_index("ix_recipients_email", table_name="recipients")

    # Create new unique constraint on (email, country_id)
    if not _index_exists(bind, "uq_recipients_email_country"):
        op.create_index(
            "uq_recipients_email_country",
            "recipients",
            ["email", "country_id"],
            unique=True,
        )

    # Insert jerome@yulcom.ca for Canada (skipped in 0011 due to old unique constraint)
    ca = bind.execute(sa.text("SELECT id FROM countries WHERE code = 'CA'")).fetchone()
    if ca is None:
        return

    ca_id = ca[0]

    exists = bind.execute(
        sa.text(
            "SELECT id FROM recipients WHERE email = :email AND country_id = :country_id"
        ),
        {"email": "jerome@yulcom.ca", "country_id": ca_id},
    ).fetchone()

    if not exists:
        bind.execute(
            sa.text(
                "INSERT INTO recipients (email, name, \"group\", enabled, bounce_count, country_id, created_at, updated_at) "
                "VALUES (:email, :name, :group, true, 0, :country_id, NOW(), NOW())"
            ),
            {"email": "jerome@yulcom.ca", "name": "PDG", "group": "cc", "country_id": ca_id},
        )


def downgrade() -> None:
    bind = op.get_bind()

    # Remove jerome@yulcom.ca CA entry
    ca = bind.execute(sa.text("SELECT id FROM countries WHERE code = 'CA'")).fetchone()
    if ca:
        bind.execute(
            sa.text(
                "DELETE FROM recipients WHERE email = 'jerome@yulcom.ca' AND country_id = :country_id"
            ),
            {"country_id": ca[0]},
        )

    if _index_exists(bind, "uq_recipients_email_country"):
        op.drop_index("uq_recipients_email_country", table_name="recipients")

    if not _index_exists(bind, "ix_recipients_email"):
        op.create_index("ix_recipients_email", "recipients", ["email"], unique=True)
