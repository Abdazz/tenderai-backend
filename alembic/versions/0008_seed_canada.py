"""seed_canada

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-21

Seeds Canada (CA) as a country and inserts all validated local sources.
Idempotent: skips rows that already exist.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_CA_SOURCES = [
    {
        "name": "Achats Canada",
        "base_url": "https://achatscanada.canada.ca",
        "list_url": (
            "https://achatscanada.canada.ca/fr/occasions-de-marche"
            "?search_filter=&status%5B87%5D=87&category%5B154%5D=154"
            "&Appliquer_les_filtres=Appliquer+les+filtres"
            "&record_per_page=100&current_tab=t&words="
        ),
        "parser_type": "playwright",
        "rate_limit": "10/m",
        "enabled": True,
        "patterns": json.dumps({
            "item_link_selector": "a[href*=\"/appels-d-offres/\"]",
            "pagination_selector": "a[rel=\"next\"]",
            "max_pages": 10,
            "wait_for_selector": "body",
            "wait_timeout_ms": 20000,
            "extra_wait_ms": 5000,
            "block_media": True,
            "fetch_detail_with_playwright": True,
        }),
    },
    {
        "name": "Ville de Montréal - Appels d'offres",
        "base_url": "https://montreal.ca",
        "list_url": (
            "https://montreal.ca/avis-dappel-doffres"
            "?types=Appel+d%27offres&categories=Services+professionnels"
        ),
        "parser_type": "playwright",
        "rate_limit": "10/m",
        "enabled": True,
        "patterns": json.dumps({
            "item_link_selector": "a[href*=\"/avis-dappels-doffres/\"]",
            "pagination_url_template": (
                "https://montreal.ca/avis-dappel-doffres"
                "?types=Appel+d'offres&categories=Services+professionnels&page={page_num}"
            ),
            "max_pages": 10,
            "wait_for_selector": "body",
            "extra_wait_ms": 2000,
            "block_media": True,
        }),
    },
    {
        "name": "Le Devoir - Avis publics",
        "base_url": "https://www.ledevoir.com",
        "list_url": "https://www.ledevoir.com/services-et-annonces/avis-publics",
        "parser_type": "ledevoir",
        "rate_limit": "10/m",
        "enabled": True,
        "patterns": json.dumps({"max_days": 7}),
    },
    {
        "name": "Nova Scotia - Procurement Portal",
        "base_url": "https://procurement-portal.novascotia.ca",
        "list_url": "https://procurement-portal.novascotia.ca/tenders",
        "parser_type": "playwright",
        "rate_limit": "10/m",
        "enabled": True,
        "patterns": json.dumps({
            "wait_for_selector": "table tbody tr, .no-results-message, [class*=tender-row]",
            "wait_timeout_ms": 20000,
            "extra_wait_ms": 3000,
            "scroll_to_bottom": True,
            "block_media": True,
        }),
    },
    {
        "name": "UNDP - Procurement Notices",
        "base_url": "https://procurement-notices.undp.org",
        "list_url": "https://procurement-notices.undp.org/index.cfm",
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": True,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "Bonfire Hub Canada - Appels d'offres",
        "base_url": "https://bonfirehub.ca",
        "list_url": "https://cmn-mcn.bonfirehub.ca/portal/?tab=openOpportunities",
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": False,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "Public Procurement Belgium",
        "base_url": "https://www.publicprocurement.be",
        "list_url": "https://www.publicprocurement.be/fr/announcement-search?cpv=72000000",
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": False,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "The Commonwealth - Tenders",
        "base_url": "https://tenders.thecommonwealth.org",
        "list_url": "https://tenders.thecommonwealth.org/aspx/Tenders/Appraisal",
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": True,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "Guinea Tenders",
        "base_url": "https://www.guineatenders.com",
        "list_url": (
            "https://www.guineatenders.com"
            "/it-services-consulting-software-development-internet-and-support-tenders-9.php"
        ),
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": False,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "UNDP Africa - Procurement",
        "base_url": "https://www.undp.org",
        "list_url": "https://www.undp.org/africa/procurement",
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": False,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "World Bank - Procurement Notices",
        "base_url": "https://wbgeprocure-rfxnow.worldbank.org",
        "list_url": (
            "https://wbgeprocure-rfxnow.worldbank.org"
            "/rfxnow/public/advertisement/index.html"
        ),
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": False,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "NATO NSPA - eProcurement",
        "base_url": "https://eportal.nspa.nato.int",
        "list_url": (
            "https://eportal.nspa.nato.int"
            "/eProcurement5G/Opportunities/OpportunitiesList?PreFilter=FBO"
        ),
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": False,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "Palladium Group - Tenders",
        "base_url": "https://thepalladiumgroup.com",
        "list_url": "https://thepalladiumgroup.com/tenders",
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": True,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "BAD - Banque Africaine de Développement",
        "base_url": "https://www.afdb.org",
        "list_url": "https://www.afdb.org/en/projects-and-operations/procurement",
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": False,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "OMD / WCO - Appels à la concurrence",
        "base_url": "https://www.wcoomd.org",
        "list_url": "https://www.wcoomd.org/en/about-us/calls_for_tenders.aspx",
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": False,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
    {
        "name": "AFD - DGMarket Tenders",
        "base_url": "https://afd.dgmarket.com",
        "list_url": "https://afd.dgmarket.com/tenders/brandedNoticeList.do",
        "parser_type": "tavily_extract",
        "rate_limit": "10/m",
        "enabled": False,
        "patterns": json.dumps({"extract_depth": "advanced", "include_raw_content": True}),
    },
]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Insert Canada — idempotent
    existing = bind.execute(
        sa.text("SELECT id FROM countries WHERE code = 'CA'")
    ).fetchone()
    if existing is None:
        bind.execute(
            sa.text(
                "INSERT INTO countries (name, code, locale, active, created_at, updated_at) "
                "VALUES ('Canada', 'CA', 'fr', true, NOW(), NOW())"
            )
        )

    ca_id = bind.execute(
        sa.text("SELECT id FROM countries WHERE code = 'CA'")
    ).scalar()

    # 2. Seed country_settings from global app_settings — idempotent
    cs_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM country_settings WHERE country_id = :cid"
        ),
        {"cid": ca_id},
    ).scalar()
    if cs_count == 0:
        bind.execute(
            sa.text("""
                INSERT INTO country_settings (country_id, section, data, updated_at, updated_by)
                SELECT :cid, section, data, NOW(), 'migration_0008'
                FROM app_settings
            """),
            {"cid": ca_id},
        )

    # 3. Insert sources — idempotent (skip if name already exists for CA)
    for src in _CA_SOURCES:
        exists = bind.execute(
            sa.text(
                "SELECT id FROM sources WHERE name = :name AND country_id = :cid"
            ),
            {"name": src["name"], "cid": ca_id},
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
            {**src, "country_id": ca_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    ca = bind.execute(
        sa.text("SELECT id FROM countries WHERE code = 'CA'")
    ).fetchone()
    if ca is None:
        return
    ca_id = ca[0]
    names = [s["name"] for s in _CA_SOURCES]
    bind.execute(
        sa.text(
            "DELETE FROM sources WHERE name = ANY(:names) AND country_id = :cid"
        ),
        {"names": names, "cid": ca_id},
    )
    bind.execute(
        sa.text("DELETE FROM country_settings WHERE country_id = :cid"),
        {"cid": ca_id},
    )
    bind.execute(
        sa.text("DELETE FROM countries WHERE code = 'CA'")
    )
