"""seed_bf_sources

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-02

Seeds the known Burkina Faso sources into the database so the /sources UI
is populated even before the pipeline runs in production mode.
Idempotent: skips any source whose name already exists for BF.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_BF_SOURCES = [
    {
        "name": "DGCMEF RAG - PDF Quotidien avec RAG",
        "base_url": "https://www.dgcmef.gov.bf",
        "list_url": "https://www.dgcmef.gov.bf/fr/appels-d-offre",
        "parser_type": "pdf_rag",
        "rate_limit": "5/m",
        "enabled": True,
    },
    {
        "name": "Joffres.net - Page de Recherche",
        "base_url": "https://www.joffres.net",
        "list_url": (
            "https://joffres.net/recherche?domaine=Informatique+%26+D%C3%A9veloppement"
            "&localisation=&societe=&secteur=&prevision=0%2F1000000000"
            "&date_publication=&date_expiration=&statut="
        ),
        "parser_type": "html-listing",
        "rate_limit": "10/m",
        "enabled": True,
    },
    {
        "name": "UNGM - UN Global Marketplace (Burkina Faso)",
        "base_url": "https://www.ungm.org",
        "list_url": "https://www.ungm.org/Public/Notice/Search",
        "parser_type": "ungm",
        "rate_limit": "5/m",
        "enabled": True,
    },
]


def upgrade() -> None:
    bind = op.get_bind()

    bf = bind.execute(
        sa.text("SELECT id FROM countries WHERE code = 'BF'")
    ).fetchone()
    if bf is None:
        return  # countries not seeded yet — pipeline will handle it

    bf_id = bf[0]

    for src in _BF_SOURCES:
        exists = bind.execute(
            sa.text("SELECT id FROM sources WHERE name = :name AND country_id = :cid"),
            {"name": src["name"], "cid": bf_id},
        ).fetchone()
        if exists:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO sources "
                "(name, base_url, list_url, parser_type, rate_limit, enabled, country_id, "
                " created_at, updated_at) "
                "VALUES (:name, :base_url, :list_url, :parser_type, :rate_limit, :enabled, "
                "        :country_id, NOW(), NOW())"
            ),
            {**src, "country_id": bf_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bf = bind.execute(
        sa.text("SELECT id FROM countries WHERE code = 'BF'")
    ).fetchone()
    if bf is None:
        return
    names = [s["name"] for s in _BF_SOURCES]
    bind.execute(
        sa.text(
            "DELETE FROM sources WHERE name = ANY(:names) AND country_id = :cid"
        ),
        {"names": names, "cid": bf[0]},
    )
