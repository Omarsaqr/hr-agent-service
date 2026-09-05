from fastapi import FastAPI

from app.config import Settings
from app.core.logging import configure_logging, install_request_logging


def create_app() -> FastAPI:
    settings = Settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="HR Agent Service")
    install_request_logging(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
