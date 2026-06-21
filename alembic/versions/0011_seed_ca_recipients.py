"""seed_ca_recipients

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-21

Seeds Canada recipients into the recipients table.
Idempotent: skips any email that already exists.
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_CA_RECIPIENTS = [
    {"email": "info@yulcom.ca",    "name": "Yulcom Info",     "group": "to"},
    {"email": "clouis@yulcom.ca",  "name": "Louis C.",        "group": "cc"},
    {"email": "jerome@yulcom.ca",  "name": "PDG",             "group": "cc"},
]


def upgrade() -> None:
    bind = op.get_bind()

    ca = bind.execute(sa.text("SELECT id FROM countries WHERE code = 'CA'")).fetchone()
    if ca is None:
        return

    ca_id = ca[0]

    for r in _CA_RECIPIENTS:
        exists = bind.execute(
            sa.text("SELECT id FROM recipients WHERE email = :email"),
            {"email": r["email"]},
        ).fetchone()
        if exists:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO recipients (email, name, \"group\", enabled, bounce_count, country_id, created_at, updated_at) "
                "VALUES (:email, :name, :group, true, 0, :country_id, NOW(), NOW())"
            ),
            {**r, "country_id": ca_id},
        )


def downgrade() -> None:
    emails = [r["email"] for r in _CA_RECIPIENTS]
    op.execute(
        sa.text("DELETE FROM recipients WHERE email = ANY(:emails)"),
        {"emails": emails},
    )
