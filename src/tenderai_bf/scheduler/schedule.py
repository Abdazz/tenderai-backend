"""APScheduler-based scheduling for TenderAI BF — one job per active country."""

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ..agents import get_pipeline
from ..config import settings
from ..logging import get_logger

logger = get_logger(__name__)

_scheduler_instance = None


def get_scheduler_instance():
    """Return the running scheduler, or None if not started."""
    return _scheduler_instance


def _make_trigger(cron_schedule: str, timezone_str: str) -> CronTrigger:
    tz = pytz.timezone(timezone_str)
    minute, hour, day, month, dow = cron_schedule.strip().split()
    return CronTrigger(
        minute=minute, hour=hour, day=day, month=month, day_of_week=dow, timezone=tz
    )


def reschedule_country_job(
    country_id: int, country_code: str, scheduler_cfg: dict
) -> None:
    """Remove and optionally re-add the APScheduler job for a country.

    Called by the settings API when a country's scheduler section is updated.
    No-op if the scheduler hasn't been started yet.
    """
    scheduler = get_scheduler_instance()
    if scheduler is None:
        return

    job_id = f"pipeline_{country_code}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if not scheduler_cfg.get("enabled", True):
        return

    cron = scheduler_cfg.get("cron_schedule") or settings.scheduler.cron_schedule
    trigger = _make_trigger(
        cron,
        scheduler_cfg.get("timezone", settings.scheduler.timezone),
    )
    scheduler.add_job(
        scheduled_pipeline_run,
        args=[country_id],
        trigger=trigger,
        id=job_id,
        name=f"Pipeline {country_code}",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=scheduler_cfg.get("max_concurrent_runs", 1),
    )
    logger.info(
        "Country job rescheduled",
        country_code=country_code,
        cron=scheduler_cfg["cron_schedule"],
    )


def scheduled_pipeline_run(country_id: int) -> None:
    """Execute the pipeline for one country as a scheduled job."""

    logger.info("Starting scheduled pipeline run", country_id=country_id)

    try:
        pipeline = get_pipeline()
        result = pipeline.run(country_id=country_id, triggered_by="scheduler")

        if result.error_occurred:
            logger.error(
                "Scheduled pipeline run failed",
                country_id=country_id,
                errors_count=len(result.errors),
                run_id=result.run_id,
            )
        elif result.warnings:
            logger.warning(
                "Scheduled pipeline run completed with warnings",
                country_id=country_id,
                run_id=result.run_id,
                warnings_count=len(result.warnings),
            )
        else:
            logger.info(
                "Scheduled pipeline run completed",
                country_id=country_id,
                run_id=result.run_id,
                relevant_items=result.stats.relevant_items,
                duration_seconds=result.stats.total_time_seconds,
            )
    except Exception as e:
        logger.error(
            "Scheduled pipeline run exception",
            country_id=country_id,
            error=str(e),
            exc_info=True,
        )


def start_scheduler() -> None:
    """Start the APScheduler daemon with one job per active country."""
    global _scheduler_instance

    logger.info("Starting TenderAI BF scheduler")

    # Load active countries
    from ..country_store import CountryStore
    from ..db import get_session_factory
    from ..models import Country

    SessionLocal = get_session_factory()  # noqa: N806 — SQLAlchemy idiom for a session factory
    db_session = SessionLocal()
    try:
        countries = db_session.query(Country).filter(Country.active == True).all()  # noqa: E712 — SQLAlchemy column comparison, not a Python bool check
        country_configs = {
            c.id: (c, CountryStore.get_all_with_fallback(db_session, c.id))
            for c in countries
        }
    finally:
        db_session.close()

    _default_cron = settings.scheduler.cron_schedule
    _default_tz = settings.scheduler.timezone

    timezone = pytz.timezone(_default_tz)
    scheduler = BlockingScheduler(timezone=timezone)
    _scheduler_instance = scheduler

    for country_id, (country, config) in country_configs.items():
        sched_cfg = config.get("scheduler", {})
        cron = sched_cfg.get("cron_schedule", _default_cron)
        tz_str = sched_cfg.get("timezone", _default_tz)
        enabled = sched_cfg.get("enabled", True)
        max_inst = sched_cfg.get(
            "max_concurrent_runs", settings.scheduler.max_concurrent_runs
        )
        run_on_startup = sched_cfg.get("run_on_startup", False)

        if not enabled:
            logger.info(
                "Country scheduler disabled, skipping", country_code=country.code
            )
            continue

        trigger = _make_trigger(cron, tz_str)
        scheduler.add_job(
            scheduled_pipeline_run,
            args=[country_id],
            trigger=trigger,
            id=f"pipeline_{country.code}",
            name=f"Pipeline {country.name}",
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=max_inst,
        )
        logger.info(
            "Scheduler job added",
            country_code=country.code,
            cron_schedule=cron,
            timezone=tz_str,
        )

        if run_on_startup:
            logger.info("Running pipeline on startup", country_code=country.code)
            scheduled_pipeline_run(country_id)

    logger.info("Scheduler configured", jobs_count=len(scheduler.get_jobs()))

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
