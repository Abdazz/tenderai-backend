import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")


def test_get_scheduler_instance_returns_none_before_start():
    import tenderai_bf.scheduler.schedule as sched_mod
    sched_mod._scheduler_instance = None
    from tenderai_bf.scheduler.schedule import get_scheduler_instance
    assert get_scheduler_instance() is None


def test_reschedule_country_job_does_nothing_when_scheduler_not_started():
    import tenderai_bf.scheduler.schedule as sched_mod
    sched_mod._scheduler_instance = None
    from tenderai_bf.scheduler.schedule import reschedule_country_job
    # Should not raise
    reschedule_country_job(1, "BF", {"cron_schedule": "0 7 * * *", "timezone": "UTC", "enabled": True})


def test_reschedule_country_job_replaces_existing_job():
    from tenderai_bf.scheduler.schedule import reschedule_country_job
    import tenderai_bf.scheduler.schedule as sched_mod

    mock_scheduler = MagicMock()
    mock_scheduler.get_job.return_value = MagicMock()  # job exists
    sched_mod._scheduler_instance = mock_scheduler

    reschedule_country_job(
        1, "BF",
        {"cron_schedule": "0 8 * * *", "timezone": "Africa/Abidjan", "enabled": True,
         "max_concurrent_runs": 1}
    )

    mock_scheduler.remove_job.assert_called_once_with("pipeline_BF")
    mock_scheduler.add_job.assert_called_once()
    add_call_kwargs = mock_scheduler.add_job.call_args[1]
    assert add_call_kwargs["id"] == "pipeline_BF"


def test_reschedule_country_job_disabled_removes_without_readding():
    from tenderai_bf.scheduler.schedule import reschedule_country_job
    import tenderai_bf.scheduler.schedule as sched_mod

    mock_scheduler = MagicMock()
    mock_scheduler.get_job.return_value = MagicMock()
    sched_mod._scheduler_instance = mock_scheduler

    reschedule_country_job(1, "CI", {"cron_schedule": "0 7 * * *", "timezone": "UTC", "enabled": False})

    mock_scheduler.remove_job.assert_called_once_with("pipeline_CI")
    mock_scheduler.add_job.assert_not_called()
