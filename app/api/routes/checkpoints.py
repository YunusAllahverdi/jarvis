"""Ajanın yaptığı değişikliklerin listelenmesi ve geri alınması.

Geri alma bir KULLANICI eylemidir, ajanın bir aracı değildir. Ajanın kendi
değişikliğini geri alabilmesi, yaptığının izini kendi silebilmesi anlamına
gelirdi; burada karar hep insanda kalır.

NOT: Onay uçlarındaki gibi, burada da kimlik doğrulama yoktur — uygulamada
henüz bir kimlik katmanı yok. Sunucu dışarı açılmadan önce eklenmelidir.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.security.checkpoints import (
    Checkpoint,
    CheckpointError,
    CheckpointNotFoundError,
    CheckpointNotRestorableError,
)

router = APIRouter(tags=["checkpoints"])


class CheckpointView(BaseModel):
    """Kullanıcıya gösterilen geri alma noktası."""

    checkpoint_id: str
    created_at: datetime
    path: str
    existed: bool
    """False ise dosya değişiklikten önce yoktu; geri alma onu siler."""

    restorable: bool
    reason: str | None

    @classmethod
    def from_record(cls, record: Checkpoint) -> "CheckpointView":
        return cls(
            checkpoint_id=record.checkpoint_id,
            created_at=record.created_at,
            path=record.path,
            existed=record.existed,
            restorable=record.restorable,
            reason=record.reason,
        )


class CheckpointListResponse(BaseModel):
    """Son geri alma noktaları."""

    checkpoints: list[CheckpointView] = Field(default_factory=list)


class RestoreResponse(BaseModel):
    """Geri alma sonucu."""

    checkpoint_id: str
    status: Literal["restored"]
    path: str
    removed: bool
    """True ise dosya silindi (değişiklikten önce yoktu)."""


def _store(request: Request) -> Any:
    store = getattr(request.app.state, "checkpoint_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "checkpoints_unavailable",
                "message": "Geri alma kaydı kurulu değil; bir çalışma kökü gerekiyor.",
            },
        )
    return store


@router.get(
    "/checkpoints",
    response_model=CheckpointListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_checkpoints(
    request: Request, session_id: str | None = None, limit: int = 20
) -> CheckpointListResponse:
    """Son değişikliklerin geri alma noktalarını döndürür."""

    records = _store(request).recent(limit=max(1, min(limit, 100)), session_id=session_id)
    return CheckpointListResponse(
        checkpoints=[CheckpointView.from_record(record) for record in records]
    )


@router.post(
    "/checkpoints/{checkpoint_id}/restore",
    response_model=RestoreResponse,
    status_code=status.HTTP_200_OK,
)
async def restore(checkpoint_id: str, request: Request) -> RestoreResponse:
    """Bir dosyayı değişiklik öncesindeki hâline döndürür."""

    store = _store(request)
    try:
        record = store.restore(checkpoint_id)
    except CheckpointNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "checkpoint_not_found", "message": str(exc)},
        ) from exc
    except CheckpointNotRestorableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "checkpoint_not_restorable", "message": str(exc)},
        ) from exc
    except CheckpointError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "checkpoint_restore_failed", "message": str(exc)},
        ) from exc

    return RestoreResponse(
        checkpoint_id=checkpoint_id,
        status="restored",
        path=record.path,
        removed=not record.existed,
    )
