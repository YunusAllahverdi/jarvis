"""Jarvis FastAPI uygulamasının başlangıç noktası."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.api.routes.health import router as health_router
from app.config.settings import Settings, get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


class ServiceInfo(BaseModel):
    """Kök endpoint için temel servis bilgisi."""

    name: str
    version: str
    environment: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Bağımlılıkları enjekte edilebilir bir FastAPI uygulaması oluşturur."""

    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "application_started",
            extra={
                "event": "application_started",
                "environment": active_settings.environment,
                "version": active_settings.app_version,
            },
        )
        yield
        logger.info("application_stopped", extra={"event": "application_stopped"})

    app = FastAPI(
        title=active_settings.app_name,
        version=active_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.include_router(health_router, prefix="/api/v1")

    @app.get("/", response_model=ServiceInfo, tags=["system"])
    async def root() -> ServiceInfo:
        return ServiceInfo(
            name=active_settings.app_name,
            version=active_settings.app_version,
            environment=active_settings.environment,
        )

    return app


app = create_app()


def run() -> None:
    """Yerel geliştirme sunucusunu başlatır."""

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
