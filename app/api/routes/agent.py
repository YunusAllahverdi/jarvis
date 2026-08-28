"""Agent karar katmanı için minimal, yapılandırılmış API.

Bu uçlar bilinçli olarak KÜÇÜK tutulmuştur: iç implementasyonu (politika
kuralları, bağlam kaynakları, tool nesneleri) dışarı açmazlar, yalnızca
yapılandırılmış karar/sonuç modellerini döndürürler.

    POST /api/agent/decide   → kararı üretir, HİÇBİR eylemi yürütmez
    POST /api/agent/run      → kararı üretir ve yürütür
    GET  /api/agent/tools    → agent'ın kullanabileceği tool'lar

`decide` ile `run` ayrı uçlardır: bir istemci önce ne olacağını görüp
(özellikle `requires_confirmation` durumunda) kullanıcıya sorabilir, sonra
yürütmeyi tetikleyebilir. Onay akışının mimari temeli budur.

Agent bağlı değilse uçlar 503 ve makine tarafından okunabilir bir `code`
döndürür — mevcut chat ve user-model uçlarıyla aynı hata biçimi.
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from app.agent.models import AgentDecision, AgentResult, ToolDescriptor
from app.services.agent_service import AgentService

router = APIRouter(tags=["agent"], prefix="/agent")

_UNAVAILABLE_DETAIL = {
    "code": "agent_unavailable",
    "message": (
        "Agent katmanı bu uygulama örneğinde bağlı değil. Karar katmanı "
        "yalnızca gerçek (enjekte edilmemiş) sağlayıcı ile uygulama "
        "başlatıldığında kurulur."
    ),
}


class AgentRequest(BaseModel):
    """Bir agent karar/yürütme isteği."""

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


class ToolListResponse(BaseModel):
    """`GET /api/agent/tools` yanıtı."""

    tools: list[ToolDescriptor]
    count: int


def _require_agent(request: Request) -> AgentService:
    """Bağlı AgentService'i döndürür; yoksa 503 fırlatır."""
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE_DETAIL,
        )
    return service


@router.post("/decide", response_model=AgentDecision, status_code=status.HTTP_200_OK)
async def decide(request_body: AgentRequest, request: Request) -> AgentDecision:
    """Ne yapılması gerektiğine karar verir; hiçbir eylemi yürütmez.

    Yan etkisizdir — planı önizlemek veya onay istemek için kullanılabilir.
    """
    return await _require_agent(request).decide(
        request_body.message, session_id=request_body.session_id
    )


@router.post("/run", response_model=AgentResult, status_code=status.HTTP_200_OK)
async def run(request_body: AgentRequest, request: Request) -> AgentResult:
    """Karar verir ve kararı yürütür.

    Onay gerektiren bir planda hiçbir eylem çalıştırılmaz; sonuç
    `pending_confirmation` durumuyla döner.
    """
    return await _require_agent(request).run(
        request_body.message, session_id=request_body.session_id
    )


@router.get("/tools", response_model=ToolListResponse, status_code=status.HTTP_200_OK)
async def list_tools(request: Request) -> ToolListResponse:
    """Agent'ın bu oturumda kullanabileceği tool'ları döndürür.

    Her tool'un izin seviyesi ve onay gerektirip gerektirmediği de yer alır.
    """
    context = _require_agent(request).build_context("")
    return ToolListResponse(tools=context.available_tools, count=len(context.available_tools))
