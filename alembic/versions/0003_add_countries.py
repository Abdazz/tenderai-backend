"""add_countries

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision = "0003"
down_revision = "0002"
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

    # 1. Create countries table (idempotent: may already exist from create_all)
    if not _table_exists(bind, "countries"):
        op.create_table(
            "countries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("code", sa.String(10), nullable=False),
            sa.Column("locale", sa.String(10), nullable=False, server_default="fr"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("code", name="uq_countries_code"),
        )

    # 2. Seed Burkina Faso as the default country (idempotent)
    existing = bind.execute(
        sa.text("SELECT id FROM countries WHERE code = 'BF'")
    ).fetchone()
    if existing is None:
        op.execute(
            "INSERT INTO countries (name, code, locale, active, created_at, updated_at) "
            "VALUES ('Burkina Faso', 'BF', 'fr', true, NOW(), NOW())"
        )

    # 3. sources.country_id — nullable first for backfill, then NOT NULL
    # Skip if table doesn't exist yet; create_all() will include the column from the model.
    if _table_exists(bind, "sources") and not _column_exists(bind, "sources", "country_id"):
        op.add_column("sources", sa.Column("country_id", sa.Integer(), nullable=True))
        op.execute("UPDATE sources SET country_id = (SELECT id FROM countries WHERE code = 'BF')")
        op.execute("ALTER TABLE sources ALTER COLUMN country_id SET NOT NULL")
        op.create_foreign_key(
            "fk_sources_country_id", "sources", "countries", ["country_id"], ["id"]
        )

    # 4. runs.country_id — nullable (older runs may not have a country)
    if _table_exists(bind, "runs") and not _column_exists(bind, "runs", "country_id"):
        op.add_column("runs", sa.Column("country_id", sa.Integer(), nullable=True))
        op.execute("UPDATE runs SET country_id = (SELECT id FROM countries WHERE code = 'BF')")
        op.create_foreign_key(
            "fk_runs_country_id", "runs", "countries", ["country_id"], ["id"]
        )

    # 5. recipients.country_id — nullable
    if _table_exists(bind, "recipients") and not _column_exists(bind, "recipients", "country_id"):
        op.add_column("recipients", sa.Column("country_id", sa.Integer(), nullable=True))
        op.execute(
            "UPDATE recipients SET country_id = (SELECT id FROM countries WHERE code = 'BF')"
        )
        op.create_foreign_key(
            "fk_recipients_country_id", "recipients", "countries", ["country_id"], ["id"]
        )

    # 6. Create country_settings table (idempotent: may already exist from create_all)
    if not _table_exists(bind, "country_settings"):
        op.create_table(
            "country_settings",
            sa.Column("country_id", sa.Integer(), nullable=False),
            sa.Column("section", sa.String(64), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("updated_by", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("country_id", "section"),
            sa.ForeignKeyConstraint(
                ["country_id"],
                ["countries.id"],
                name="fk_country_settings_country_id",
            ),
        )

    # 7. Seed country_settings for BF from app_settings (idempotent)
    cs_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM country_settings WHERE country_id = "
            "(SELECT id FROM countries WHERE code = 'BF')"
        )
    ).scalar()
    if cs_count == 0:
        op.execute("""
            INSERT INTO country_settings (country_id, section, data, updated_at, updated_by)
            SELECT
                (SELECT id FROM countries WHERE code = 'BF'),
                section,
                data,
                NOW(),
                'migration_0003'
            FROM app_settings
        """)


def downgrade() -> None:
    op.drop_table("country_settings")
    op.drop_constraint("fk_recipients_country_id", "recipients", type_="foreignkey")
    op.drop_column("recipients", "country_id")
    op.drop_constraint("fk_runs_country_id", "runs", type_="foreignkey")
    op.drop_column("runs", "country_id")
    op.drop_constraint("fk_sources_country_id", "sources", type_="foreignkey")
    op.drop_column("sources", "country_id")
    op.drop_table("countries")
