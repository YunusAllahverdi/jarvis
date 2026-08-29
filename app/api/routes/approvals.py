"""Onay bekleyen araç çağrılarının listelenmesi ve sonuçlandırılması.

Akış iki adımlıdır: ajan onay gerektiren bir çağrıya geldiğinde durur ve
bir kayıt açar; kullanıcı buradaki uçlarla o kaydı onaylar ya da reddeder.
Onaylanan çağrı, ajanın kullandığı yürütme sınırının aynısından geçer.

NOT: Bu uçlarda kimlik doğrulama yoktur, çünkü uygulamada henüz bir kimlik
katmanı yok. Sunucu yalnızca 127.0.0.1'i dinlediği sürece bu kabul
edilebilir; dışarı açılmadan önce kimlik doğrulama eklenmelidir.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.security.approvals import (
    ApprovalAlreadyDecidedError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalRequest,
)
from app.tools.base import PermissionLevel

router = APIRouter(tags=["approvals"])


class ApprovalView(BaseModel):
    """Kullanıcıya gösterilen onay isteği.

    Argümanlar bilerek yer alır: kullanıcı neyi onayladığını görmeden
    onaylayamaz.
    """

    approval_id: str
    tool_name: str
    arguments: dict[str, Any]
    permission: PermissionLevel
    reason: str | None
    created_at: datetime
    expires_at: datetime

    @classmethod
    def from_record(cls, record: ApprovalRequest) -> "ApprovalView":
        return cls(
            approval_id=record.approval_id,
            tool_name=record.tool_name,
            arguments=dict(record.arguments),
            permission=record.permission,
            reason=record.reason,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )


class PendingApprovalsResponse(BaseModel):
    """Bekleyen onay isteklerinin listesi."""

    pending: list[ApprovalView] = Field(default_factory=list)


class ApprovalDecisionRequest(BaseModel):
    """Bir onay isteğine verilen karar.

    Gövdede yalnızca karar taşınır. Araç adı ve argümanlar istemciden
    ALINMAZ; onaylanan ile çalıştırılanın ayrışmaması için kayıttan okunur.
    """

    decision: Literal["approve", "reject"]


class ApprovalDecisionResponse(BaseModel):
    """Kararın sonucu ve onaylandıysa aracın çıktısı."""

    approval_id: str
    status: Literal["approved", "rejected"]
    tool_name: str
    success: bool | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


def _approval_service(request: Request) -> Any:
    service = getattr(request.app.state, "approval_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "approvals_unavailable", "message": "Onay servisi kurulu değil."},
        )
    return service


@router.get(
    "/approvals",
    response_model=PendingApprovalsResponse,
    status_code=status.HTTP_200_OK,
)
async def list_pending(request: Request, session_id: str | None = None) -> PendingApprovalsResponse:
    """Bekleyen onay isteklerini döndürür."""

    service = _approval_service(request)
    records = service.pending(session_id=session_id)
    return PendingApprovalsResponse(pending=[ApprovalView.from_record(r) for r in records])


@router.post(
    "/approvals/{approval_id}",
    response_model=ApprovalDecisionResponse,
    status_code=status.HTTP_200_OK,
)
async def decide(
    approval_id: str,
    body: ApprovalDecisionRequest,
    request: Request,
) -> ApprovalDecisionResponse:
    """Bir onay isteğini sonuçlandırır; onaylanırsa çağrıyı çalıştırır."""

    service = _approval_service(request)

    if body.decision == "reject":
        record = _decide(service.reject, approval_id)
        return ApprovalDecisionResponse(
            approval_id=approval_id,
            status="rejected",
            tool_name=record.tool_name,
        )

    executor = getattr(request.app.state, "approval_executor", None)
    if executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "approvals_unavailable",
                "message": "Onaylı çalıştırma için yürütme sınırı kurulu değil.",
            },
        )

    # Çağrı kayıttan gelir. Onay burada tüketilir: bu satırdan sonra aynı
    # kimlik bir daha çalışmaz, çalıştırma başarısız olsa bile.
    call = _decide(service.approve, approval_id)

    result = await executor.execute(call, approved=True)
    return ApprovalDecisionResponse(
        approval_id=approval_id,
        status="approved",
        tool_name=result.tool_name,
        success=result.success,
        result=result.data,
        error_code=result.error_code,
        error_message=result.error_message,
    )


def _decide(action: Any, approval_id: str) -> Any:
    """Onay servisinin hatalarını HTTP durumlarına çevirir."""

    try:
        return action(approval_id)
    except ApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "approval_not_found", "message": str(exc)},
        ) from exc
    except ApprovalExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"code": "approval_expired", "message": str(exc)},
        ) from exc
    except ApprovalAlreadyDecidedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "approval_already_decided", "message": str(exc)},
        ) from exc
