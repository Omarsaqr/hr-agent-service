from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.core import db
from app.core.iqama_alerts import IqamaAlertLog
from app.core.logging import configure_logging, install_request_logging
from app.core.scheduler import start_scheduler


def create_app() -> FastAPI:
    settings = Settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = None
        if settings.iqama_scheduler_enabled:
            alert_log = IqamaAlertLog(db.connect())
            scheduler = start_scheduler(settings, alert_log)
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="HR Agent Service", lifespan=lifespan)
    install_request_logging(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
