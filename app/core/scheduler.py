import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.core.iqama_alerts import IqamaAlertLog
from app.deps import get_hris_port
from app.jobs.iqama_expiry import run_iqama_expiry_check

logger = logging.getLogger("app.jobs")

# Explicit, not the server's local time: APScheduler's cron trigger
# defaults to whatever timezone the process happens to run in, and
# "6am" should mean 6am in Riyadh regardless of which region this is
# deployed to.
_COMPANY_TIMEZONE = ZoneInfo("Asia/Riyadh")


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
            hris=hris, alert_log=alert_log, as_of=now.date(), now=now
        )
        if alerts:
            logger.warning("iqama expiry check raised %d alert(s)", len(alerts))

    scheduler.add_job(
        _run_check, "cron", hour=6, minute=0, timezone=_COMPANY_TIMEZONE, id="iqama_expiry_check"
    )
    scheduler.start()
    return scheduler
