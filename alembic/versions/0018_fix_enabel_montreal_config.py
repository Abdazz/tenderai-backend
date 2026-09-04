"""fix_enabel_montreal_config

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-04

Chantier 4 audit constats #10 and #15 — pure DB config changes, no code.

#10: Enabel's patterns had no pdf_selector, so all 3 cards on a listing
page shared the same "url" (the listing page itself) and extract_item_links'
global seen_urls dedup ate 2 of the 3 as false "duplicates". Each card
carries its own distinct "Cahier des charges" PDF link in the HTML
(verified live: a[href$='.pdf']), just never extracted.

#15: Ville de Montréal's max_pages=10 against a real 93-page listing
(927 notices). fetch_playwright.py's pagination loop already stops early
once a page returns 0 new links (line ~187), so raising the ceiling well
above the real page count is safe and cheap — it never actually walks
past the last real page.

Idempotent — safe to re-run.
"""
import json

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

_ENABEL_NAME = "Enabel - Marchés publics Burkina Faso"
_ENABEL_OLD_PATTERNS = {
    "entity": "Enabel",
    "location": "Burkina Faso",
    "max_pages": 3,
    "card_selector": "div.card--news.card--tenders",
    "pagination_url": "https://www.enabel.be/fr/marches-publics/page/{page}/?in_country=1726&is_status=0",
    "title_selector": "p.h5 span",
    "deadline_selector": "p",
    "deadline_text_prefix": "Date de clôture",
}
_ENABEL_NEW_PATTERNS = {**_ENABEL_OLD_PATTERNS, "pdf_selector": "a[href$='.pdf']"}

_MONTREAL_NAME = "Ville de Montréal - Appels d'offres"
_MONTREAL_OLD_PATTERNS = {
    "max_pages": 10,
    "block_media": True,
    "extra_wait_ms": 2000,
    "wait_for_selector": "body",
    "item_link_selector": 'a[href*="/avis-dappels-doffres/"]',
    "pagination_url_template": "https://montreal.ca/avis-dappel-doffres?types=Appel+d'offres&categories=Services+professionnels&page={page_num}",
}
_MONTREAL_NEW_PATTERNS = {**_MONTREAL_OLD_PATTERNS, "max_pages": 100}


def _update(bind, name, patterns):
    bind.execute(
        sa.text(
            "UPDATE sources SET patterns = CAST(:patterns AS jsonb), updated_at = NOW() "
            "WHERE name = :name"
        ),
        {"patterns": json.dumps(patterns), "name": name},
    )


def upgrade() -> None:
    bind = op.get_bind()
    _update(bind, _ENABEL_NAME, _ENABEL_NEW_PATTERNS)
    _update(bind, _MONTREAL_NAME, _MONTREAL_NEW_PATTERNS)


def downgrade() -> None:
    bind = op.get_bind()
    _update(bind, _ENABEL_NAME, _ENABEL_OLD_PATTERNS)
    _update(bind, _MONTREAL_NAME, _MONTREAL_OLD_PATTERNS)
