"""Uygulama sağlık kontrolleri."""

from fastapi import APIRouter, Request, status
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Sağlık kontrolü yanıt şeması."""

    status: str
    service: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check(request: Request) -> HealthResponse:
    """Uygulama sürecinin yanıt verebildiğini doğrular."""

    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
