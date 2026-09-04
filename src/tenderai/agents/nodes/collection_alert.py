"""Alert the admin when harvest collection silently produced nothing.

Chantier 4 audit constat #12: nothing ever alerted on a dead collection —
BF stayed broken 3+ weeks (crashing, then persisting 0 notices even on
non-crash days) and CA never worked, while the daily report kept sending
"successfully" with an empty report and no one noticed. This module checks
the two anomaly shapes the audit named explicitly and, if found, emails the
admin — the same recipient and SMTP setup the daily report already uses,
not new infrastructure.
"""

from ...config import settings
from ...email.smtp_client import SMTPClient
from ...logging import get_logger

logger = get_logger(__name__)


def check_and_alert(state, run_id: str) -> None:
    """Inspect a finished harvest run's state and email an alert if the
    collection died silently. Never raises — a failed alert must not affect
    the run's own recorded status."""
    try:
        anomalies = _find_anomalies(state)
        if not anomalies:
            return

        _send_alert(state, run_id, anomalies)
    except Exception as e:
        logger.error(
            "Collection alert check failed", error=str(e), run_id=run_id, exc_info=True
        )


def _find_anomalies(state) -> list[str]:
    anomalies: list[str] = []
    stats = state.stats

    if stats.unique_items > 0 and stats.notices_persisted == 0:
        anomalies.append(
            f"{stats.unique_items} avis uniques trouvés mais 0 persisté(s) en base "
            "— la persistance a échoué silencieusement pour la totalité du run."
        )

    for warning in state.warnings:
        if warning.get("step") in ("fetch_listings", "parse_extract"):
            source_name = warning.get("source_name", "source inconnue")
            reason = warning.get("warning", "raison inconnue")
            anomalies.append(f"Source « {source_name} » : {reason}")

    return anomalies


def _send_alert(state, run_id: str, anomalies: list[str]) -> None:
    to_address = settings.email.to_address
    if not to_address:
        logger.warning(
            "Collection anomaly detected but no admin email configured — "
            "cannot alert",
            run_id=run_id,
            anomalies=anomalies,
        )
        return

    country = getattr(state, "country_name", None) or f"country_id={state.country_id}"
    subject = f"[TenderAI] Collecte anormale — {country} ({run_id[:8]})"
    body_lines = [
        f"Anomalie(s) détectée(s) sur le run de collecte {run_id} ({country}) :",
        "",
    ]
    body_lines.extend(f"- {a}" for a in anomalies)
    body_lines.extend(
        [
            "",
            f"Stats du run : items_parsed={state.stats.items_parsed}, "
            f"unique_items={state.stats.unique_items}, "
            f"notices_persisted={state.stats.notices_persisted}, "
            f"sources_checked={state.stats.sources_checked}",
        ]
    )
    body_text = "\n".join(body_lines)

    client = SMTPClient()
    sent = client.send_email(
        to_addresses=to_address,
        subject=subject,
        body_text=body_text,
    )
    logger.info(
        "Collection alert email sent" if sent else "Collection alert email failed",
        run_id=run_id,
        anomalies_count=len(anomalies),
    )
