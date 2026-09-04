"""source_disabled_reason

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-04

Chantier 4 audit constat #14: 9 sources were inserted as a batch and never
run, with no record of *why* each was left disabled — future sessions had
no way to tell "deliberately off" from "forgotten." Adds disabled_reason
and backfills the audit's own per-source verdict for all 9, then
reactivates the 4 with no known technical blocker (NATO NSPA, AFD-DGMarket)
or where the blocker (Akamai/Cloudflare 403) is worth re-testing once
Tavily is live (UNDP Africa, BAD/AfDB) rather than staying silently off.

The other 5 stay disabled with their reason recorded:
  Guinea Tenders — paywall
  Public Procurement Belgium — out of geographic scope (BF/CA project)
  OMD/WCO — portal had zero active tenders at audit time, re-check periodically
  Bonfire Hub Canada — list_url covers only one organism despite its generic
    name, needs re-scoping; browser verification wasn't available at audit time
  World Bank — 100% client-rendered SPA, browser verification wasn't
    available at audit time

Idempotent — safe to re-run.
"""
import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

_STILL_DISABLED = {
    "Guinea Tenders": "Paywall — accès payant, source non exploitable sans abonnement.",
    "Public Procurement Belgium": (
        "Hors périmètre géographique (Belgique, hors BF/CA)."
    ),
    "OMD / WCO - Appels à la concurrence": (
        "Portail sans avis actif au jour de l'audit (2026-09-01) — aucun "
        "blocage technique connu, à réévaluer périodiquement."
    ),
    "Bonfire Hub Canada - Appels d'offres": (
        "list_url ne couvre qu'un seul organisme malgré le nom générique de "
        "la source — vérification navigateur non disponible lors de "
        "l'audit, à re-scoper avant réactivation."
    ),
    "World Bank - Procurement Notices": (
        "SPA à rendu 100% côté client — non vérifiable par curl, "
        "vérification navigateur non disponible lors de l'audit."
    ),
}

_REACTIVATED = [
    "NATO NSPA - eProcurement",
    "AFD - DGMarket Tenders",
    "UNDP Africa - Procurement",
    "BAD - Banque Africaine de Développement",
]


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("sources", sa.Column("disabled_reason", sa.Text(), nullable=True))

    for name, reason in _STILL_DISABLED.items():
        bind.execute(
            sa.text(
                "UPDATE sources SET disabled_reason = :reason, updated_at = NOW() "
                "WHERE name = :name AND enabled = false"
            ),
            {"reason": reason, "name": name},
        )

    for name in _REACTIVATED:
        bind.execute(
            sa.text(
                "UPDATE sources SET enabled = true, disabled_reason = NULL, "
                "updated_at = NOW() WHERE name = :name"
            ),
            {"name": name},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for name in _REACTIVATED:
        bind.execute(
            sa.text(
                "UPDATE sources SET enabled = false, updated_at = NOW() "
                "WHERE name = :name"
            ),
            {"name": name},
        )
    op.drop_column("sources", "disabled_reason")
