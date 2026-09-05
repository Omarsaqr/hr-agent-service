import sqlite3

from app.config import Settings
from app.core.iqama_alerts import IqamaAlertLog
from app.core.scheduler import start_scheduler


def make_settings() -> Settings:
    return Settings(_env_file=None, environment="test", preview_token_secret="test-secret")


async def test_start_scheduler_registers_the_iqama_job_in_riyadh_time() -> None:
    alert_log = IqamaAlertLog(sqlite3.connect(":memory:"))
    scheduler = start_scheduler(make_settings(), alert_log)
    try:
        job = scheduler.get_job("iqama_expiry_check")
        assert job is not None
        assert str(job.trigger.timezone) == "Asia/Riyadh"
    finally:
        scheduler.shutdown(wait=False)
