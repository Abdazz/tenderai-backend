"""seed_bf_recipients

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-21

Seeds the recipients defined in settings.yaml into the recipients table
for Burkina Faso. The primary recipient (email.to_address) is already
handled by the pipeline config — only the secondary ones are seeded here.
Idempotent: skips any email that already exists.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_BF_RECIPIENTS = [
    {"email": "jerome@yulcom.ca",                    "name": "PDG",                  "group": "cc"},
    {"email": "ymorgane@yulcom.ca",                  "name": "DGA",                  "group": "cc"},
    {"email": "tdiane@yulcom.ca",                    "name": "Diane Tapsoaba",        "group": "cc"},
    {"email": "oconstantin@yulcom-technologies.com", "name": "Constantin Ouedraogo", "group": "cc"},
]


def upgrade() -> None:
    bind = op.get_bind()

    bf = bind.execute(sa.text("SELECT id FROM countries WHERE code = 'BF'")).fetchone()
    if bf is None:
        return

    bf_id = bf[0]

    for r in _BF_RECIPIENTS:
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
            {**r, "country_id": bf_id},
        )


def downgrade() -> None:
    emails = [r["email"] for r in _BF_RECIPIENTS]
    op.execute(
        sa.text("DELETE FROM recipients WHERE email = ANY(:emails)"),
        {"emails": emails},
    )
