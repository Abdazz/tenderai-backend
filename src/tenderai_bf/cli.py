"""Command-line interface for TenderAI BF."""

import json
import os
import sys
import uuid
from pathlib import Path

import click

from .agents import get_pipeline
from .config import settings
from .db import check_database_health, get_database_info, get_engine, init_database
from .email import test_email_configuration
from .logging import get_logger
from .storage import get_storage_client

logger = get_logger(__name__)


@click.group()
@click.version_option(version=settings.app_version)
def main():
    """TenderAI BF - Multi-agent RFP harvester for Burkina Faso."""
    pass


@main.command()
@click.option("--triggered-by", default="manual", help="Who triggered this run")
@click.option("--user", default=None, help="User who triggered this run")
@click.option(
    "--country-id", default=1, type=int, help="Country ID to run pipeline for"
)
@click.option(
    "--country-code",
    default=None,
    help="ISO-2 country code (CA, BF, CI, SN…) — overrides --country-id",
)
@click.option(
    "--test",
    "test_mode",
    is_flag=True,
    default=False,
    help="Test mode: send the report only to the admin email (TENDERAI_ADMIN_EMAIL), not all recipients",
)
def run_once(triggered_by: str, user: str | None, country_id: int, country_code: str | None, test_mode: bool):
    """Execute the pipeline once and generate a report."""

    click.echo("🚀 Starting TenderAI BF pipeline..." + (" [MODE TEST]" if test_mode else ""))

    try:
        # Resolve country code → country ID when --country-code is provided
        if country_code:
            from sqlalchemy import text as _text
            _engine = get_engine()
            with _engine.connect() as _conn:
                _row = _conn.execute(
                    _text("SELECT id, name FROM countries WHERE UPPER(code) = UPPER(:code)"),
                    {"code": country_code},
                ).fetchone()
            if not _row:
                click.echo(f"❌ Unknown country code '{country_code}'. Check the countries table.")
                sys.exit(1)
            country_id = _row[0]
            click.echo(f"   Country: {_row[1]} (code={country_code.upper()}, id={country_id})")

        # Get pipeline
        pipeline = get_pipeline()

        # Execute pipeline (returns a TenderAIState)
        result = pipeline.run(
            country_id=country_id,
            triggered_by=triggered_by,
            triggered_by_user=user,
            test_mode=test_mode,
        )

        errors = result.errors
        warnings = result.warnings
        stats = result.stats.dict()
        report_url = result.report_url
        email_status = result.email_status or {}

        if result.error_occurred:
            click.echo(f"❌ Pipeline failed with {len(errors)} error(s)")
            for error in errors:
                click.echo(f"   • [{error['step']}] {error['error']}")
            sys.exit(1)

        if warnings:
            click.echo(f"⚠️  Pipeline completed with {len(warnings)} warning(s)")
            for w in warnings:
                click.echo(f"   • [{w['step']}] {w['warning']}")
        else:
            click.echo("✅ Pipeline completed successfully!")

        click.echo(f"   • Sources checked: {stats.get('sources_checked', 0)}")
        click.echo(f"   • Items found: {stats.get('items_parsed', 0)}")
        click.echo(f"   • Relevant items: {stats.get('relevant_items', 0)}")
        click.echo(f"   • Unique items: {stats.get('unique_items', 0)}")
        click.echo(f"   • Execution time: {stats.get('total_time_seconds', 0):.1f}s")

        if report_url:
            click.echo(f"   • Report URL: {report_url}")

        if email_status.get("success"):
            click.echo(
                f"   • Email sent to {email_status.get('recipients_count', 0)} recipient(s)"
            )
        elif email_status and not email_status.get("skipped"):
            click.echo("   • Email delivery failed (report still available on MinIO)")

    except KeyboardInterrupt:
        click.echo("\n⚠️ Pipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Pipeline failed: {e}")
        logger.error("CLI run-once failed", error=str(e), exc_info=True)
        sys.exit(1)


@main.command()
def run_scheduler():
    """Start the scheduler daemon."""

    click.echo("⏰ Starting TenderAI BF scheduler...")

    try:
        from .scheduler.schedule import start_scheduler

        start_scheduler()
    except KeyboardInterrupt:
        click.echo("\n⚠️ Scheduler stopped by user")
    except Exception as e:
        click.echo(f"❌ Scheduler failed: {e}")
        logger.error("CLI scheduler failed", error=str(e), exc_info=True)
        sys.exit(1)


@main.command()
def run_worker():
    """Start the worker daemon for heavy processing."""

    click.echo("⚙️ Starting TenderAI BF worker...")

    try:
        # TODO: Implement worker daemon for OCR/heavy processing
        click.echo("Worker daemon not yet implemented")
        import time

        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        click.echo("\n⚠️ Worker stopped by user")
    except Exception as e:
        click.echo(f"❌ Worker failed: {e}")
        logger.error("CLI worker failed", error=str(e), exc_info=True)
        sys.exit(1)


@main.command()
def init_db():
    """Initialize the database schema."""

    click.echo("🗄️ Initializing database...")

    try:
        init_database()
        click.echo("✅ Database initialized successfully")
    except Exception as e:
        click.echo(f"❌ Database initialization failed: {e}")
        logger.error("Database init failed", error=str(e), exc_info=True)
        sys.exit(1)


@main.command()
def health_check():
    """Check system health and connectivity."""

    click.echo("🏥 Checking system health...")

    # Check database
    if check_database_health():
        click.echo("✅ Database: Connected")
        db_info = get_database_info()
        if not db_info.get("error"):
            click.echo(f"   • Version: {db_info.get('version', 'Unknown')}")
            click.echo(f"   • Database: {db_info.get('database', 'Unknown')}")
    else:
        click.echo("❌ Database: Connection failed")

    # Check storage
    try:
        storage_client = get_storage_client()
        if storage_client.health_check():
            click.echo("✅ Storage (MinIO): Connected")
        else:
            click.echo("❌ Storage (MinIO): Health check failed")
    except Exception as e:
        click.echo(f"❌ Storage (MinIO): {e}")

    # Check email
    if test_email_configuration():
        click.echo("✅ Email (SMTP): Configuration valid")
    else:
        click.echo("❌ Email (SMTP): Configuration failed")

    click.echo("\n📊 Configuration:")
    click.echo(f"   • Environment: {settings.environment}")
    click.echo(f"   • Log level: {settings.monitoring.log_level}")
    click.echo("   • Active sources: (loaded from DB at runtime)")
    click.echo(f"   • LLM provider: {settings.llm.provider}")


@main.command()
def test_email():
    """Test email configuration by sending a test message."""

    click.echo("📧 Testing email configuration...")

    try:
        if test_email_configuration():
            click.echo("✅ Test email sent successfully")
        else:
            click.echo("❌ Test email failed")
            sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Email test failed: {e}")
        logger.error("Email test failed", error=str(e), exc_info=True)
        sys.exit(1)


@main.command()
@click.option("--run-id", help="Specific run ID to check")
def status(run_id: str | None):
    """Check pipeline status and recent runs."""

    try:
        pipeline = get_pipeline()

        if run_id:
            # Check specific run
            run_status = pipeline.get_pipeline_status(run_id)
            if run_status:
                click.echo(f"📊 Run {run_id}:")
                click.echo(f"   • Status: {run_status['status']}")
                click.echo(f"   • Started: {run_status['started_at']}")
                if run_status["finished_at"]:
                    click.echo(f"   • Finished: {run_status['finished_at']}")
                    click.echo(f"   • Duration: {run_status['duration_seconds']:.1f}s")
                click.echo(f"   • Triggered by: {run_status['triggered_by']}")
                if run_status.get("error_message"):
                    click.echo(f"   • Error: {run_status['error_message']}")
            else:
                click.echo(f"❌ Run {run_id} not found")
                sys.exit(1)
        else:
            # Show recent runs
            recent_runs = pipeline.get_recent_runs(limit=5)
            if recent_runs:
                click.echo("📊 Recent pipeline runs:")
                for run in recent_runs:
                    status_icon = (
                        "✅"
                        if run["status"] == "completed"
                        else "❌"
                        if run["status"] == "failed"
                        else "🔄"
                    )
                    click.echo(
                        f"   {status_icon} {run['id'][:8]}... ({run['status']}) - {run['started_at']}"
                    )
                    if run.get("counts"):
                        counts = run["counts"]
                        click.echo(
                            f"      Sources: {counts.get('sources_checked', 0)}, "
                            f"Relevant: {counts.get('relevant_items', 0)}, "
                            f"Duration: {counts.get('total_time_seconds', 0):.1f}s"
                        )
            else:
                click.echo("No recent runs found")

    except Exception as e:
        click.echo(f"❌ Status check failed: {e}")
        logger.error("Status check failed", error=str(e), exc_info=True)
        sys.exit(1)


@main.command()
def build_report():
    """Generate a report from the last successful run."""

    click.echo("📄 Building report from last run...")

    try:
        pipeline = get_pipeline()
        recent_runs = pipeline.get_recent_runs(limit=1)

        if not recent_runs:
            click.echo("❌ No recent runs found")
            sys.exit(1)

        last_run = recent_runs[0]
        if last_run["status"] != "completed":
            click.echo(f"❌ Last run status: {last_run['status']}")
            sys.exit(1)

        if last_run.get("report_url"):
            click.echo(f"✅ Report already exists: {last_run['report_url']}")
        else:
            click.echo("❌ No report URL found for last run")
            sys.exit(1)

    except Exception as e:
        click.echo(f"❌ Report building failed: {e}")
        logger.error("Report building failed", error=str(e), exc_info=True)
        sys.exit(1)


@main.command("create-admin")
@click.option(
    "--username",
    default=None,
    help="Admin username (default: $TENDERAI_ADMIN_USERNAME or 'admin')",
)
@click.option("--email", default=None, help="Admin email")
@click.option(
    "--password",
    default=None,
    help="Admin password (default: $TENDERAI_ADMIN_PASSWORD)",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite the password if the user already exists",
)
def create_admin(
    username: str | None, email: str | None, password: str | None, force: bool
):
    """Create (or reset) the admin user. Safe to re-run: skips if user exists unless --force."""

    from passlib.context import CryptContext
    from sqlalchemy import text

    username = username or os.environ.get("TENDERAI_ADMIN_USERNAME", "admin")
    password = password or os.environ.get("TENDERAI_ADMIN_PASSWORD", "")
    email = email or os.environ.get("TENDERAI_ADMIN_EMAIL", f"{username}@tenderai.bf")

    if not password:
        click.echo(
            "❌ No password provided. Use --password or set TENDERAI_ADMIN_PASSWORD."
        )
        sys.exit(1)

    if len(password) < 8:
        click.echo("❌ Password must be at least 8 characters.")
        sys.exit(1)

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    hashed = pwd_context.hash(password)

    try:
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id FROM users WHERE username = :username"),
                {"username": username},
            ).fetchone()

            if row:
                if not force:
                    click.echo(
                        f"ℹ️  User '{username}' already exists. Use --force to overwrite the password."
                    )
                    return
                conn.execute(
                    text(
                        "UPDATE users SET hashed_password = :pwd, is_active = true, "
                        "password_reset_required = false WHERE username = :username"
                    ),
                    {"pwd": hashed, "username": username},
                )
                conn.commit()
                click.echo(f"✅ Password updated for existing admin user '{username}'.")
            else:
                conn.execute(
                    text(
                        "INSERT INTO users (id, username, email, hashed_password, role, "
                        "is_active, password_reset_required) "
                        "VALUES (:id, :username, :email, :pwd, 'admin', true, false)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "username": username,
                        "email": email,
                        "pwd": hashed,
                    },
                )
                conn.commit()
                click.echo(f"✅ Admin user '{username}' created successfully.")

    except Exception as e:
        click.echo(f"❌ Failed to create admin user: {e}")
        logger.error("create-admin failed", error=str(e), exc_info=True)
        sys.exit(1)


@main.command("seed-sources")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Update sources that already exist in the DB",
)
def seed_sources(force: bool):
    """Seed sources from settings.yaml into the database. Safe to re-run: skips existing unless --force."""

    from urllib.parse import urlparse

    from sqlalchemy import text

    import yaml

    yaml_path = Path("settings.yaml")
    if not yaml_path.exists():
        click.echo("No settings.yaml found.")
        return
    with open(yaml_path, encoding="utf-8") as _f:
        _yaml_cfg = yaml.safe_load(_f) or {}
    sources = _yaml_cfg.get("sources", [])
    if not sources:
        click.echo("No sources found in settings.yaml (key 'sources' is empty).")
        return

    try:
        engine = get_engine()
        with engine.connect() as conn:
            created = updated = skipped = 0

            for source in sources:
                name = source.get("name", "").strip()
                list_url = source.get("list_url", "").strip()
                # settings.yaml uses 'parser', DB uses 'parser_type'
                parser_type = source.get("parser", source.get("parser_type", "html"))
                rate_limit = source.get("rate_limit", "10/m")
                enabled = source.get("enabled", True)
                # Fold parser-specific *_settings blocks (ungm_settings, etc.) into
                # patterns so they actually persist to the DB and are readable at
                # runtime via source["patterns"][...] — settings.yaml keeps them
                # as top-level sibling keys for readability.
                patterns_raw = dict(source.get("patterns") or {})
                for key, value in source.items():
                    if key.endswith("_settings"):
                        patterns_raw[key] = value
                patterns_json = json.dumps(patterns_raw) if patterns_raw else None

                if not name or not list_url:
                    click.echo(
                        f"  Skipping entry with missing name or list_url: {source}"
                    )
                    continue

                # Derive base_url from list_url origin
                parsed = urlparse(list_url)
                base_url = f"{parsed.scheme}://{parsed.netloc}"

                row = conn.execute(
                    text("SELECT id FROM sources WHERE name = :name"),
                    {"name": name},
                ).fetchone()

                if row:
                    if not force:
                        click.echo(f"  Skipping (exists): {name}")
                        skipped += 1
                        continue
                    conn.execute(
                        text(
                            "UPDATE sources SET base_url=:base_url, list_url=:list_url, "
                            "parser_type=:parser_type, rate_limit=:rate_limit, enabled=:enabled, "
                            "patterns=:patterns, updated_at=NOW() WHERE name=:name"
                        ),
                        {
                            "name": name,
                            "base_url": base_url,
                            "list_url": list_url,
                            "parser_type": parser_type,
                            "rate_limit": rate_limit,
                            "enabled": enabled,
                            "patterns": patterns_json,
                        },
                    )
                    conn.commit()
                    click.echo(f"  Updated: {name}")
                    updated += 1
                else:
                    conn.execute(
                        text(
                            "INSERT INTO sources (name, base_url, list_url, parser_type, "
                            "rate_limit, enabled, patterns, created_at, updated_at) "
                            "VALUES (:name, :base_url, :list_url, :parser_type, "
                            ":rate_limit, :enabled, :patterns, NOW(), NOW())"
                        ),
                        {
                            "name": name,
                            "base_url": base_url,
                            "list_url": list_url,
                            "parser_type": parser_type,
                            "rate_limit": rate_limit,
                            "enabled": enabled,
                            "patterns": patterns_json,
                        },
                    )
                    conn.commit()
                    click.echo(f"  Created: {name}")
                    created += 1

        click.echo(f"\nDone: {created} created, {updated} updated, {skipped} skipped.")

    except Exception as e:
        click.echo(f"❌ Failed to seed sources: {e}")
        logger.error("seed-sources failed", error=str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
