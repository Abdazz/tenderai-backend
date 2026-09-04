"""fix_uemoa_pagination

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-04

Chantier 4 audit constat #6: UEMOA's patterns had max_pages=1 and no
pagination_url, so the generic pagination loop in fetch_html_tender.py
never triggered — only ~10 of the site's 194 listed notices were ever
fetched (page 0 / list_url only).

The site paginates via a 0-indexed "?page=N" query param (page=0..19,
verified live: 20 pages, 194 notices total). The generic loop defaults to
1-indexed page numbers starting at 2 (matches Enabel's "/page/2/"), so this
also sets pagination_start=1 (added alongside this migration) to land on
the correct page=1..19 range rather than skipping page=1.

Idempotent — safe to re-run.
"""
import json

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

_SOURCE_NAME = "UEMOA - Appels d'offres"

_OLD_PATTERNS = {
    "ssl_verify": False,
    "card_selector": "div.swiper-slide div.news-box",
    "title_selector": "div.new-txt p",
    "deadline_selector": "time",
    "deadline_attribute": "datetime",
    "pdf_selector": "a[href*='opportunite_affaire']",
    "entity": "UEMOA",
    "location": "Zone UEMOA",
    "max_pages": 1,
}

_NEW_PATTERNS = {
    **_OLD_PATTERNS,
    "max_pages": 19,
    "pagination_start": 1,
    "pagination_url": "https://www.uemoa.int/appel-d-offre?page={page}",
}


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE sources SET patterns = CAST(:patterns AS jsonb), updated_at = NOW() "
            "WHERE name = :name"
        ),
        {"patterns": json.dumps(_NEW_PATTERNS), "name": _SOURCE_NAME},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE sources SET patterns = CAST(:patterns AS jsonb), updated_at = NOW() "
            "WHERE name = :name"
        ),
        {"patterns": json.dumps(_OLD_PATTERNS), "name": _SOURCE_NAME},
    )
