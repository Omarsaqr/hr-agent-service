import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.core.company_time import COMPANY_TIMEZONE, today_in_company_timezone
from app.core.iqama_alerts import IqamaAlertLog
from app.deps import get_hris_port
from app.jobs.iqama_expiry import run_iqama_expiry_check

logger = logging.getLogger("app.jobs")


def start_scheduler(settings: Settings, alert_log: IqamaAlertLog) -> AsyncIOScheduler:
    """Wires run_iqama_expiry_check to a daily cron trigger. Only called
    from main.py's lifespan when iqama_scheduler_enabled is set -- an
    AsyncIOScheduler needs a running event loop to start against, so
    this can't happen at import time.
    """
    scheduler = AsyncIOScheduler()

    async def _run_check() -> None:
        now = datetime.now(UTC)
        hris = get_hris_port(settings)
        alerts = await run_iqama_expiry_check(
            hris=hris, alert_log=alert_log, as_of=today_in_company_timezone(now), now=now
        )
        if alerts:
            logger.warning("iqama expiry check raised %d alert(s)", len(alerts))

    # timezone=COMPANY_TIMEZONE, explicit: APScheduler's cron trigger
    # defaults to whatever timezone the process happens to run in, and
    # "6am" should mean 6am in Riyadh regardless of which region this is
    # deployed to.
    scheduler.add_job(
        _run_check, "cron", hour=6, minute=0, timezone=COMPANY_TIMEZONE, id="iqama_expiry_check"
    )
    scheduler.start()
    return scheduler
