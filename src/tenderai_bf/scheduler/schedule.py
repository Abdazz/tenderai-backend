"""APScheduler-based scheduling for TenderAI BF."""

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ..agents import get_pipeline
from ..config import settings
from ..logging import get_logger

logger = get_logger(__name__)


def scheduled_pipeline_run():
    """Execute the pipeline as a scheduled job."""
    
    logger.info("Starting scheduled pipeline run")
    
    try:
        # Get pipeline
        pipeline = get_pipeline()
        
        # Execute pipeline
        result = pipeline.run(
            triggered_by="scheduler",
            triggered_by_user=None
        )
        
        # Log results
        if result.error_occurred:
            logger.error(
                "Scheduled pipeline run failed",
                errors_count=len(result.errors),
                run_id=result.run_id
            )
        else:
            logger.info(
                "Scheduled pipeline run completed successfully",
                run_id=result.run_id,
                relevant_items=result.stats.relevant_items,
                duration_seconds=result.stats.total_time_seconds
            )
    
    except Exception as e:
        logger.error(
            "Scheduled pipeline run exception",
            error=str(e),
            exc_info=True
        )


def start_scheduler():
    """Start the APScheduler daemon."""
    
    logger.info("Starting TenderAI BF scheduler")
    
    # Create scheduler
    timezone = pytz.timezone(settings.scheduler.timezone)
    scheduler = BlockingScheduler(timezone=timezone)
    
    # Parse cron schedule
    cron_parts = settings.scheduler.cron_schedule.split()
    if len(cron_parts) != 5:
        raise ValueError(f"Invalid cron schedule: {settings.scheduler.cron_schedule}")
    
    minute, hour, day, month, day_of_week = cron_parts
    
    # Add job
    trigger = CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=timezone
    )
    
    scheduler.add_job(
        scheduled_pipeline_run,
        trigger=trigger,
        id='daily_pipeline',
        name='Daily TenderAI BF Pipeline',
        misfire_grace_time=3600,  # 1 hour grace period
        coalesce=True,  # Combine multiple missed runs into one
        max_instances=settings.scheduler.max_concurrent_runs
    )
    
    # Log scheduler configuration
    logger.info(
        "Scheduler configured",
        cron_schedule=settings.scheduler.cron_schedule,
        timezone=settings.scheduler.timezone,
        jobs_count=len(scheduler.get_jobs())
    )
    
    # Optionally run on startup
    if settings.scheduler.run_on_startup:
        logger.info("Running pipeline on startup")
        scheduled_pipeline_run()
    
    # Start scheduler
    try:
        logger.info("Scheduler started, waiting for scheduled runs...")
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
        scheduler.shutdown()
    except Exception as e:
        logger.error("Scheduler error", error=str(e), exc_info=True)
        scheduler.shutdown()
        raise