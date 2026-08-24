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


def _constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    insp = Inspector.from_engine(conn)
    try:
        constraints = insp.get_foreign_keys(table_name)
        return any(c["name"] == constraint_name for c in constraints)
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

    # 5. Create company_settings table (idempotent)
    if not _table_exists(bind, "company_settings"):
        op.create_table(
            "company_settings",
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("section", sa.String(64), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("updated_by", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("company_id", "section"),
            sa.ForeignKeyConstraint(
                ["company_id"], ["companies.id"], name="fk_company_settings_company_id"
            ),
        )

    # 6. Seed YULCOM's classification section from AppSettings["classification"],
    #    consolidating min_relevance_score (today under AppSettings["pipeline"])
    #    into the same company-level "classification" section (idempotent).
    cs_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM company_settings WHERE company_id = "
            "(SELECT id FROM companies WHERE slug = 'yulcom') AND section = 'classification'"
        )
    ).scalar()
    if cs_count == 0:
        classification_row = bind.execute(
            sa.text("SELECT data FROM app_settings WHERE section = 'classification'")
        ).fetchone()
        pipeline_row = bind.execute(
            sa.text("SELECT data FROM app_settings WHERE section = 'pipeline'")
        ).fetchone()
        if classification_row is not None:
            import json as _json

            merged = dict(classification_row[0])
            if pipeline_row is not None and "min_relevance_score" in pipeline_row[0]:
                merged["min_relevance_score"] = pipeline_row[0]["min_relevance_score"]
            # Plain string substitution, not a bind param: the JSON payload comes
            # from our own app_settings row, not user input, so this is safe, and
            # it sidesteps dialect-specific JSON bind-param handling entirely.
            merged_json = _json.dumps(merged).replace("'", "''")
            op.execute(
                "INSERT INTO company_settings (company_id, section, data, updated_at, updated_by) "
                "VALUES ((SELECT id FROM companies WHERE slug = 'yulcom'), "
                f"'classification', '{merged_json}'::json, NOW(), 'migration_0013')"
            )

    # 7. Seed YULCOM's scheduler section from AppSettings["scheduler"] (idempotent)
    sched_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM company_settings WHERE company_id = "
            "(SELECT id FROM companies WHERE slug = 'yulcom') AND section = 'scheduler'"
        )
    ).scalar()
    if sched_count == 0:
        op.execute("""
            INSERT INTO company_settings (company_id, section, data, updated_at, updated_by)
            SELECT
                (SELECT id FROM companies WHERE slug = 'yulcom'),
                'scheduler',
                data,
                NOW(),
                'migration_0013'
            FROM app_settings
            WHERE section = 'scheduler'
        """)

    # 8. Create company_notice_status table (idempotent)
    if not _table_exists(bind, "company_notice_status"):
        op.create_table(
            "company_notice_status",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("notice_id", sa.String(36), nullable=False),
            sa.Column("is_relevant", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("relevance_score", sa.Float(), nullable=True),
            sa.Column("classification_method", sa.String(50), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "notice_id", name="uq_company_notice"),
            sa.ForeignKeyConstraint(
                ["company_id"], ["companies.id"], name="fk_cns_company_id"
            ),
            sa.ForeignKeyConstraint(
                ["notice_id"], ["notices.id"], name="fk_cns_notice_id"
            ),
        )

    # 9. Backfill from historical Notice classification, tagged to YULCOM (idempotent)
    if _table_exists(bind, "notices"):
        op.execute("""
            INSERT INTO company_notice_status
                (id, company_id, notice_id, is_relevant, relevance_score, classification_method, delivered_at, created_at)
            SELECT
                gen_random_uuid()::text,
                (SELECT id FROM companies WHERE slug = 'yulcom'),
                n.id,
                COALESCE(n.is_relevant, false),
                n.relevance_score,
                n.classification_method,
                n.created_at,
                n.created_at
            FROM notices n
            WHERE NOT EXISTS (
                SELECT 1 FROM company_notice_status cns
                WHERE cns.company_id = (SELECT id FROM companies WHERE slug = 'yulcom')
                AND cns.notice_id = n.id
            )
        """)

    # 10. runs.run_type and runs.company_id
    if _table_exists(bind, "runs"):
        if not _column_exists(bind, "runs", "run_type"):
            op.add_column(
                "runs",
                sa.Column("run_type", sa.String(20), nullable=False, server_default="harvest"),
            )
        if not _column_exists(bind, "runs", "company_id"):
            op.add_column("runs", sa.Column("company_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_runs_company_id", "runs", "companies", ["company_id"], ["id"]
            )

    # 11. recipients.company_id — backfilled to YULCOM
    if _table_exists(bind, "recipients"):
        if not _column_exists(bind, "recipients", "company_id"):
            op.add_column("recipients", sa.Column("company_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_recipients_company_id", "recipients", "companies", ["company_id"], ["id"]
            )
        op.execute(
            "UPDATE recipients SET company_id = (SELECT id FROM companies WHERE slug = 'yulcom') "
            "WHERE company_id IS NULL"
        )


def downgrade() -> None:
    op.drop_constraint("fk_recipients_company_id", "recipients", type_="foreignkey")
    op.drop_column("recipients", "company_id")
    bind = op.get_bind()
    # Drop runs.company_id and runs.run_type (idempotent)
    if _column_exists(bind, "runs", "company_id"):
        if _constraint_exists(bind, "runs", "fk_runs_company_id"):
            op.drop_constraint("fk_runs_company_id", "runs", type_="foreignkey")
        op.drop_column("runs", "company_id")
    if _column_exists(bind, "runs", "run_type"):
        op.drop_column("runs", "run_type")
    op.drop_table("company_notice_status")
    op.drop_table("company_settings")
    op.drop_table("company_country_subscriptions")
    op.drop_table("companies")
