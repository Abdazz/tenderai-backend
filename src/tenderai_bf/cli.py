"""Command-line interface for TenderAI BF."""

import asyncio
import sys
from typing import Optional

import click

from .agents import get_pipeline
from .config import settings
from .db import init_database, check_database_health, get_database_info
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
@click.option('--triggered-by', default='manual', help='Who triggered this run')
@click.option('--user', default=None, help='User who triggered this run')
def run_once(triggered_by: str, user: Optional[str]):
    """Execute the pipeline once and generate a report."""
    
    click.echo("🚀 Starting TenderAI BF pipeline...")
    
    try:
        # Get pipeline
        pipeline = get_pipeline()
        
        # Execute pipeline
        result = pipeline.run(
            triggered_by=triggered_by,
            triggered_by_user=user
        )
        
        # Report results
        if result.error_occurred:
            click.echo(f"❌ Pipeline failed with {len(result.errors)} error(s)")
            for error in result.errors:
                click.echo(f"   • [{error['step']}] {error['error']}")
            sys.exit(1)
        else:
            stats = result.stats
            click.echo("✅ Pipeline completed successfully!")
            click.echo(f"   • Sources checked: {stats.sources_checked}")
            click.echo(f"   • Items found: {stats.items_parsed}")
            click.echo(f"   • Relevant items: {stats.relevant_items}")
            click.echo(f"   • Unique items: {stats.unique_items}")
            click.echo(f"   • Execution time: {stats.total_time_seconds:.1f}s")
            
            if result.report_url:
                click.echo(f"   • Report URL: {result.report_url}")
            
            if result.email_status.get('success'):
                click.echo(f"   • Email sent to {result.email_status.get('recipients_count', 0)} recipient(s)")
    
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
        if not db_info.get('error'):
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
    click.echo(f"   • Active sources: {len(settings.get_active_sources())}")
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
@click.option('--run-id', help='Specific run ID to check')
def status(run_id: Optional[str]):
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
                if run_status['finished_at']:
                    click.echo(f"   • Finished: {run_status['finished_at']}")
                    click.echo(f"   • Duration: {run_status['duration_seconds']:.1f}s")
                click.echo(f"   • Triggered by: {run_status['triggered_by']}")
                if run_status.get('error_message'):
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
                    status_icon = "✅" if run['status'] == 'completed' else "❌" if run['status'] == 'failed' else "🔄"
                    click.echo(f"   {status_icon} {run['id'][:8]}... ({run['status']}) - {run['started_at']}")
                    if run.get('counts'):
                        counts = run['counts']
                        click.echo(f"      Sources: {counts.get('sources_checked', 0)}, "
                                 f"Relevant: {counts.get('relevant_items', 0)}, "
                                 f"Duration: {counts.get('total_time_seconds', 0):.1f}s")
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
        if last_run['status'] != 'completed':
            click.echo(f"❌ Last run status: {last_run['status']}")
            sys.exit(1)
        
        if last_run.get('report_url'):
            click.echo(f"✅ Report already exists: {last_run['report_url']}")
        else:
            click.echo("❌ No report URL found for last run")
            sys.exit(1)
    
    except Exception as e:
        click.echo(f"❌ Report building failed: {e}")
        logger.error("Report building failed", error=str(e), exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()