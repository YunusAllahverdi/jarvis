"""Kabuğun bekleyen UI aksiyonlarını aldığı uç.

    GET /api/ui/actions?session_id=...  → bekleyen aksiyonları döndürür ve TÜKETİR

Tek uç ve GET olması bilinçlidir. Sunucu istemciyi itemez (WebSocket ya da
SSE yoktur), bu yüzden kabuk her sohbet turundan sonra bir kez yoklar. Sürekli
yoklama YAPILMAZ: aksiyonlar yalnızca ajan bir tur çalıştırdığında oluşur,
dolayısıyla yoklanacak an bellidir ve arka planda saniyede bir sormak boşuna
istek üretirdi.

GET'in yan etkisi (tüketim) HTTP açısından alışılmadıktır ve bilerek
seçilmiştir: alternatif, istemcinin okuduğunu ayrıca bildirmesi olurdu ve
istemci o ikinci isteği yapmadan kapanırsa panel sonsuza dek yeniden açılırdı.
"""

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.ui.actions import UIAction, UIActionBus

router = APIRouter(tags=["ui"], prefix="/ui")


class UIActionsResponse(BaseModel):
    """Bekleyen aksiyonlar. Okunduktan sonra kuyrukta kalmazlar."""

    actions: list[UIAction] = Field(default_factory=list)
    count: int = 0


def _bus(request: Request) -> UIActionBus:
    bus = getattr(request.app.state, "ui_action_bus", None)
    if bus is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ui_actions_unavailable",
                "message": "UI aksiyon kanalı bu uygulama örneğinde bağlı değil.",
            },
        )
    return bus


@router.get("/actions", response_model=UIActionsResponse)
async def consume_actions(
    request: Request,
    session_id: str | None = Query(default=None, max_length=128),
) -> UIActionsResponse:
    """Bekleyen panel açma isteklerini döndürür ve kuyruğu boşaltır."""
    actions = _bus(request).consume(session_id=session_id)
    return UIActionsResponse(actions=actions, count=len(actions))
