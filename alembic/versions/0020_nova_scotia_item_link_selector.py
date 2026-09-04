"""nova_scotia_item_link_selector

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-04

Chantier 4 audit constat #16: Nova Scotia had no item_link_selector, so
fetch_playwright.py fell back to its "text blob" mode (whole-page inner_text
sent to an LLM) instead of structured link extraction.

Verified live against the real production config (block_media, the exact
wait_for_selector already configured, locale, UA): the listing renders a
nested <table> per row, with the detail link at td.id-col a[href^="/tenders/"]
(e.g. <td class="id-col"><a href="/tenders/HRM-2026-0348">HRM-2026-0348</a></td>).

Scope note, not fixed here: this listing has ~29,752 total results at only
~6 visible per page with no infinite scroll — full pagination would mean
thousands of sequential Playwright page loads per run, which isn't safe
against a source the audit already flagged as anti-bot-sensitive under
sustained load (constat #18). No pagination_url_template/pagination_selector
is set, so this only covers what's visible on load — a separate, larger
decision than constat #16 itself asked for.

Idempotent — safe to re-run.
"""
import json

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_NOVA_SCOTIA_NAME = "Nova Scotia - Procurement Portal"
_OLD_PATTERNS = {
    "block_media": True,
    "extra_wait_ms": 3000,
    "wait_timeout_ms": 20000,
    "scroll_to_bottom": True,
    "wait_for_selector": "table tbody tr, .no-results-message, [class*=tender-row]",
}
_NEW_PATTERNS = {
    **_OLD_PATTERNS,
    "item_link_selector": "td.id-col a[href^='/tenders/']",
}


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE sources SET patterns = CAST(:patterns AS jsonb), updated_at = NOW() "
            "WHERE name = :name"
        ),
        {"patterns": json.dumps(_NEW_PATTERNS), "name": _NOVA_SCOTIA_NAME},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE sources SET patterns = CAST(:patterns AS jsonb), updated_at = NOW() "
            "WHERE name = :name"
        ),
        {"patterns": json.dumps(_OLD_PATTERNS), "name": _NOVA_SCOTIA_NAME},
    )
