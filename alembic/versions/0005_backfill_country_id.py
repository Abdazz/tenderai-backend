"""backfill_country_id_nulls

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-02

Backfills country_id = BF for any rows in sources / runs / recipients that
were created before the column was properly seeded (e.g. when create_all()
added the column without running the backfill UPDATE in migration 0003).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    insp = Inspector.from_engine(conn)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    bf_exists = bind.execute(
        sa.text("SELECT id FROM countries WHERE code = 'BF'")
    ).fetchone()
    if bf_exists is None:
        return  # no BF country to backfill against

    for table in ("sources", "runs", "recipients"):
        if _table_exists(bind, table):
            op.execute(
                sa.text(
                    f"UPDATE {table} SET country_id = "
                    "(SELECT id FROM countries WHERE code = 'BF') "
                    "WHERE country_id IS NULL"
                )
            )


def downgrade() -> None:
    pass  # backfill is safe to keep; no meaningful rollback
