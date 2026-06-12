"""seed_bf_sources_uemoa_enabel

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-12

Seeds UEMOA and Enabel sources for Burkina Faso into the database.
Idempotent: skips any source whose name already exists for BF.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_NEW_BF_SOURCES = [
    {
        "name": "UEMOA - Appels d'offres",
        "base_url": "https://www.uemoa.int",
        "list_url": "https://www.uemoa.int/appel-d-offre",
        "parser_type": "html-tender",
        "rate_limit": "5/m",
        "enabled": True,
        "patterns": json.dumps({
            "ssl_verify": False,
            "card_selector": "div.swiper-slide div.news-box",
            "title_selector": "div.new-txt p",
            "deadline_selector": "time",
            "deadline_attribute": "datetime",
            "pdf_selector": "a[href*='opportunite_affaire']",
            "entity": "UEMOA",
            "location": "Zone UEMOA",
            "max_pages": 1,
        }),
    },
    {
        "name": "Enabel - Marchés publics Burkina Faso",
        "base_url": "https://www.enabel.be",
        "list_url": "https://www.enabel.be/fr/marches-publics/?in_country=1726&is_status=0",
        "parser_type": "html-tender",
        "rate_limit": "5/m",
        "enabled": True,
        "patterns": json.dumps({
            "card_selector": "div.card--news.card--tenders",
            "title_selector": "p.h5 span",
            "deadline_selector": "p",
            "deadline_text_prefix": "Date de clôture",
            "entity": "Enabel",
            "location": "Burkina Faso",
            "max_pages": 3,
            "pagination_url": "https://www.enabel.be/fr/marches-publics/page/{page}/?in_country=1726&is_status=0",
        }),
    },
]


def upgrade() -> None:
    bind = op.get_bind()

    bf = bind.execute(
        sa.text("SELECT id FROM countries WHERE code = 'BF'")
    ).fetchone()
    if bf is None:
        return

    bf_id = bf[0]

    for src in _NEW_BF_SOURCES:
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
                " patterns, created_at, updated_at) "
                "VALUES (:name, :base_url, :list_url, :parser_type, :rate_limit, :enabled, "
                "        :country_id, CAST(:patterns AS jsonb), NOW(), NOW())"
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
    names = [s["name"] for s in _NEW_BF_SOURCES]
    bind.execute(
        sa.text(
            "DELETE FROM sources WHERE name = ANY(:names) AND country_id = :cid"
        ),
        {"names": names, "cid": bf[0]},
    )
