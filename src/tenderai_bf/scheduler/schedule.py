"""APScheduler-based scheduling for TenderAI BF — one job per active country."""

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ..agents import get_delivery_pipeline, get_pipeline
from ..config import settings
from ..db import get_session_factory
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


def reschedule_company_delivery_job(
    company_id: int, company_slug: str, scheduler_cfg: dict
) -> None:
    """Remove and optionally re-add the APScheduler job for a company's delivery.

    Called by the settings API when a company's scheduler section is updated.
    No-op if the scheduler hasn't been started yet. Mirrors reschedule_country_job.
    """
    scheduler = get_scheduler_instance()
    if scheduler is None:
        return

    job_id = f"delivery_{company_slug}"
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
        scheduled_company_delivery_run,
        args=[company_id],
        trigger=trigger,
        id=job_id,
        name=f"Delivery {company_slug}",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=scheduler_cfg.get("max_concurrent_runs", 1),
    )
    logger.info(
        "Company delivery job rescheduled",
        company_slug=company_slug,
        cron=scheduler_cfg["cron_schedule"],
    )


def scheduled_company_delivery_run(company_id: int) -> None:
    """Execute delivery for every enabled (company, country) subscription."""

    from ..models import CompanyCountrySubscription

    logger.info("Starting scheduled company delivery run", company_id=company_id)

    SessionLocal = get_session_factory()  # noqa: N806 — SQLAlchemy idiom for a session factory
    db_session = SessionLocal()
    try:
        subscriptions = (
            db_session.query(CompanyCountrySubscription)
            .filter(
                CompanyCountrySubscription.company_id == company_id,
                CompanyCountrySubscription.enabled == True,  # noqa: E712
            )
            .all()
        )
    finally:
        db_session.close()

    pipeline = get_delivery_pipeline()
    for sub in subscriptions:
        try:
            result = pipeline.run(
                company_id=company_id, country_id=sub.country_id, triggered_by="scheduler"
            )
            if result.error_occurred:
                logger.error(
                    "Scheduled company delivery run failed",
                    company_id=company_id,
                    country_id=sub.country_id,
                    errors_count=len(result.errors),
                    run_id=result.run_id,
                )
            elif result.warnings:
                logger.warning(
                    "Scheduled company delivery run completed with warnings",
                    company_id=company_id,
                    country_id=sub.country_id,
                    run_id=result.run_id,
                    warnings_count=len(result.warnings),
                )
            else:
                logger.info(
                    "Scheduled company delivery run completed",
                    company_id=company_id,
                    country_id=sub.country_id,
                    run_id=result.run_id,
                )
        except Exception as e:
            logger.error(
                "Scheduled company delivery run exception",
                company_id=company_id,
                country_id=sub.country_id,
                error=str(e),
                exc_info=True,
            )


def start_scheduler() -> None:
    """Start the APScheduler daemon with one job per active country."""
    global _scheduler_instance

    logger.info("Starting TenderAI BF scheduler")

    # Load active countries
    from ..company_store import CompanyStore
    from ..country_store import CountryStore
    from ..models import Company, Country

    SessionLocal = get_session_factory()  # noqa: N806 — SQLAlchemy idiom for a session factory
    db_session = SessionLocal()
    try:
        countries = db_session.query(Country).filter(Country.active == True).all()  # noqa: E712 — SQLAlchemy column comparison, not a Python bool check
        country_configs = {
            c.id: (c, CountryStore.get_all_with_fallback(db_session, c.id))
            for c in countries
        }
        companies = db_session.query(Company).filter(Company.active == True).all()  # noqa: E712
        company_configs = {
            c.id: (c, CompanyStore.get_all_with_fallback(db_session, c.id))
            for c in companies
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

    for company_id, (company, config) in company_configs.items():
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
                "Company delivery scheduler disabled, skipping", company_slug=company.slug
            )
            continue

        trigger = _make_trigger(cron, tz_str)
        scheduler.add_job(
            scheduled_company_delivery_run,
            args=[company_id],
            trigger=trigger,
            id=f"delivery_{company.slug}",
            name=f"Delivery {company.name}",
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=max_inst,
        )
        logger.info(
            "Delivery scheduler job added",
            company_slug=company.slug,
            cron_schedule=cron,
            timezone=tz_str,
        )

        if run_on_startup:
            logger.info("Running delivery on startup", company_slug=company.slug)
            scheduled_company_delivery_run(company_id)

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
