"""add_companies

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-23

Adds the Company tenant axis on top of the existing Country abstraction.
Seeds YULCOM Technologies as the first company (tenant zero). Idempotent —
safe to re-run.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    insp = Inspector.from_engine(conn)
    return table_name in insp.get_table_names()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    insp = Inspector.from_engine(conn)
    try:
        return any(c["name"] == column_name for c in insp.get_columns(table_name))
    except sa.exc.NoSuchTableError:
        return False


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create companies table (idempotent: may already exist from create_all)
    if not _table_exists(bind, "companies"):
        op.create_table(
            "companies",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(64), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("logo_url", sa.String(500), nullable=True),
            sa.Column("subject_prefix", sa.String(100), nullable=True),
            sa.Column("signature", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("slug", name="uq_companies_slug"),
        )

    # 2. Seed YULCOM Technologies as the first company (idempotent)
    existing = bind.execute(
        sa.text("SELECT id FROM companies WHERE slug = 'yulcom'")
    ).fetchone()
    if existing is None:
        op.execute(
            "INSERT INTO companies (name, slug, active, created_at, updated_at) "
            "VALUES ('YULCOM Technologies', 'yulcom', true, NOW(), NOW())"
        )

    # 3. Create company_country_subscriptions table (idempotent)
    if not _table_exists(bind, "company_country_subscriptions"):
        op.create_table(
            "company_country_subscriptions",
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("country_id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("company_id", "country_id"),
            sa.ForeignKeyConstraint(
                ["company_id"], ["companies.id"], name="fk_ccs_company_id"
            ),
            sa.ForeignKeyConstraint(
                ["country_id"], ["countries.id"], name="fk_ccs_country_id"
            ),
        )

    # 4. Subscribe YULCOM to every currently-active country (idempotent)
    op.execute("""
        INSERT INTO company_country_subscriptions (company_id, country_id, enabled, created_at)
        SELECT
            (SELECT id FROM companies WHERE slug = 'yulcom'),
            c.id,
            true,
            NOW()
        FROM countries c
        WHERE c.active = true
        AND NOT EXISTS (
            SELECT 1 FROM company_country_subscriptions ccs
            WHERE ccs.company_id = (SELECT id FROM companies WHERE slug = 'yulcom')
            AND ccs.country_id = c.id
        )
    """)


def downgrade() -> None:
    op.drop_table("company_country_subscriptions")
    op.drop_table("companies")
