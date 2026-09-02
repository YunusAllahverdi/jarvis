"""Kodlama döngüsü için minimal, yapılandırılmış API.

    POST /api/coding/run  → isteği uçtan uca yürütür ve sonucu döndürür

Tek bir uç olması bilinçlidir. Karar katmanında `decide`/`run` ayrımı vardı
çünkü orada plan tek atımlıktı ve önizlenebilirdi; burada plan turlar
boyunca DEĞİŞİR, dolayısıyla "önce göster, sonra çalıştır" diye bir an
yoktur. Güvenlik sınırı önizlemeyle değil, onay akışıyla korunur: onay
gerektiren bir adıma gelindiğinde döngü durur ve kullanıcının
yanıtlayacağı kayıtlar `pending_approval_ids` içinde döner.

Servis bağlı değilse uç 503 ve makine tarafından okunabilir bir `code`
döndürür — mevcut chat, agent ve user-model uçlarıyla aynı hata biçimi.
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from app.coding.models import CodingResult
from app.services.coding_service import CodingService

router = APIRouter(tags=["coding"], prefix="/coding")

_UNAVAILABLE_DETAIL = {
    "code": "coding_unavailable",
    "message": (
        "Kodlama döngüsü bu uygulama örneğinde bağlı değil. Döngü yalnızca "
        "bir çalışma kökü tanımlıysa, yazma yetkisi verilmişse ve "
        "JARVIS_CODING_LOOP_ENABLED açıksa kurulur."
    ),
}


class CodingRequest(BaseModel):
    """Bir kodlama isteği."""

    message: str = Field(max_length=10_000)
    session_id: str | None = Field(default=None, max_length=128)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message boş olamaz")
        return normalized

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("session_id boş olamaz")
        return normalized


def _require_service(request: Request) -> CodingService:
    """Bağlı CodingService'i döndürür; yoksa 503 fırlatır."""
    service = getattr(request.app.state, "coding_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE_DETAIL,
        )
    return service


@router.post("/run", response_model=CodingResult, status_code=status.HTTP_200_OK)
async def run(request_body: CodingRequest, request: Request) -> CodingResult:
    """İsteği anlar, planlar, uygular, doğrular ve gerekirse düzeltir.

    Onay gerektiren bir adıma gelindiğinde döngü durur; o adım ve sonrası
    çalıştırılmaz ve sonuç `pending_approval` durumuyla döner.
    """
    return await _require_service(request).run(
        request_body.message, session_id=request_body.session_id
    )
