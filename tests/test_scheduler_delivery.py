import os
from unittest.mock import MagicMock, patch

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")


@patch("tenderai_bf.scheduler.schedule.get_scheduler_instance")
def test_reschedule_company_delivery_job_no_op_when_scheduler_not_started(
    mock_get_sched,
):
    from tenderai_bf.scheduler.schedule import reschedule_company_delivery_job

    mock_get_sched.return_value = None
    # Must not raise even though the scheduler hasn't started.
    reschedule_company_delivery_job(
        1, "yulcom", {"enabled": True, "cron_schedule": "0 8 * * *"}
    )


@patch("tenderai_bf.scheduler.schedule.get_delivery_pipeline")
def test_scheduled_company_delivery_run_iterates_enabled_subscriptions(
    mock_get_pipeline,
):
    from tenderai_bf.scheduler.schedule import scheduled_company_delivery_run

    mock_pipeline = MagicMock()
    mock_result = MagicMock(error_occurred=False, warnings=[])
    mock_pipeline.run.return_value = mock_result
    mock_get_pipeline.return_value = mock_pipeline

    with patch("tenderai_bf.scheduler.schedule.get_session_factory") as mock_sf:
        mock_session = MagicMock()
        mock_sf.return_value.return_value = mock_session
        mock_sub_1 = MagicMock(country_id=1, enabled=True)
        mock_sub_2 = MagicMock(country_id=2, enabled=True)
        mock_session.query.return_value.filter.return_value.all.return_value = [
            mock_sub_1,
            mock_sub_2,
        ]

        scheduled_company_delivery_run(company_id=1)

    assert mock_pipeline.run.call_count == 2
    called_country_ids = {
        c.kwargs["country_id"] for c in mock_pipeline.run.call_args_list
    }
    assert called_country_ids == {1, 2}
