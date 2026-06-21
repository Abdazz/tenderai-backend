"""fix_recipients_schema

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-21

The recipients table was originally created (migration 0000) with only
5 columns: id, email, name, is_active, created_at.
The ORM model grew to include group, enabled, preferences, last_sent_at,
bounce_count, updated_at — but no migration ever added them to production.

This migration adds all missing columns and handles the is_active → enabled
rename. Fully idempotent: every operation checks existence first.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    insp = Inspector.from_engine(conn)
    try:
        return any(c["name"] == column for c in insp.get_columns(table))
    except sa.exc.NoSuchTableError:
        return False


def _index_exists(conn, index_name: str) -> bool:
    insp = Inspector.from_engine(conn)
    for table_name in insp.get_table_names():
        for idx in insp.get_indexes(table_name):
            if idx["name"] == index_name:
                return True
    return False


def upgrade() -> None:
    bind = op.get_bind()

    # 1. group VARCHAR(50) NOT NULL DEFAULT 'default'
    if not _column_exists(bind, "recipients", "group"):
        op.add_column(
            "recipients",
            sa.Column(
                "group",
                sa.String(50),
                nullable=False,
                server_default="default",
            ),
        )
    if not _index_exists(bind, "ix_recipients_group"):
        op.create_index("ix_recipients_group", "recipients", ["group"])

    # 2. enabled BOOLEAN NOT NULL DEFAULT TRUE
    #    Migrate value from is_active if that column still exists.
    if not _column_exists(bind, "recipients", "enabled"):
        op.add_column(
            "recipients",
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
        if _column_exists(bind, "recipients", "is_active"):
            op.execute("UPDATE recipients SET enabled = is_active")
    if not _index_exists(bind, "ix_recipients_enabled"):
        op.create_index("ix_recipients_enabled", "recipients", ["enabled"])

    # 3. preferences JSON (nullable)
    if not _column_exists(bind, "recipients", "preferences"):
        op.add_column(
            "recipients",
            sa.Column("preferences", sa.JSON(), nullable=True),
        )

    # 4. last_sent_at TIMESTAMP (nullable)
    if not _column_exists(bind, "recipients", "last_sent_at"):
        op.add_column(
            "recipients",
            sa.Column("last_sent_at", sa.DateTime(), nullable=True),
        )

    # 5. bounce_count INTEGER NOT NULL DEFAULT 0
    if not _column_exists(bind, "recipients", "bounce_count"):
        op.add_column(
            "recipients",
            sa.Column(
                "bounce_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    # 6. updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    if not _column_exists(bind, "recipients", "updated_at"):
        op.add_column(
            "recipients",
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    # 7. Unique index on email (may be missing on old prod tables)
    if not _index_exists(bind, "ix_recipients_email"):
        op.create_index(
            "ix_recipients_email", "recipients", ["email"], unique=True
        )


def downgrade() -> None:
    bind = op.get_bind()
    for idx in ("ix_recipients_group", "ix_recipients_enabled", "ix_recipients_email"):
        if _index_exists(bind, idx):
            op.drop_index(idx, table_name="recipients")
    for col in ("group", "enabled", "preferences", "last_sent_at", "bounce_count", "updated_at"):
        if _column_exists(bind, "recipients", col):
            op.drop_column("recipients", col)
