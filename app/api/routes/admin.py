"""Sağlayıcı yapılandırmasının yönetildiği uçlar.

Bu uçlar iki nedenle diğerlerinden daha hassastır: bir API anahtarı kabul
ederler ve LLM adresini değiştirebilirler. İkincisi daha az göze çarpar ama
daha tehlikelidir — adresi değiştirebilen biri, bütün konuşmaları kendi
sunucusuna yönlendirebilir.

Uygulamada henüz bir kimlik katmanı olmadığı için burada açık bir kural
uygulanır: **sunucu `127.0.0.1` dışına bağlıysa ve bir yönetim anahtarı
tanımlanmamışsa bu uçlar çalışmaz.** Böylece "kimlik doğrulama yok" durumu
sessiz bir risk olmaktan çıkıp uygulanan bir sınıra dönüşür.

API anahtarı hiçbir yanıtta geri dönmez; yalnızca tanımlı olup olmadığı
bildirilir.
"""

import logging
import re
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.council.gate import CouncilGate
from app.security.audit import AuditAction, AuditEvent, AuditOutcome, safe_record
from app.services.council_config import MEMBER_ID_PATTERN, CouncilMemberConfig
from app.services.council_service import CouncilService
from app.services.llm_config import LLMConfig, LLMProviderKind

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

ADMIN_TOKEN_HEADER = "X-Admin-Token"


class LLMConfigUpdate(BaseModel):
    """Sağlayıcı yapılandırması güncelleme isteği."""

    kind: LLMProviderKind
    base_url: str = Field(min_length=1, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    api_key: str | None = Field(default=None, max_length=500)
    """Yeni anahtar. Gönderilmezse mevcut anahtar korunur.

    Panel anahtarı geri okuyamadığı için, her kaydetmede yeniden
    girilmesini istemek kullanıcıyı anahtarı bir yerde saklamaya zorlardı.
    """

    clear_api_key: bool = False
    """Anahtarı silmek için açıkça istenmelidir."""


def _is_local(host: str) -> bool:
    return host.strip().lower() in _LOCAL_HOSTS


def _require_admin(request: Request) -> None:
    """Yönetim uçlarına erişimi denetler.

    Yönetim anahtarı tanımlıysa her istekte istenir. Tanımlı değilse uçlar
    yalnızca sunucu yerel adrese bağlıyken çalışır.
    """
    settings = request.app.state.settings
    token = getattr(settings, "admin_token", "") or ""

    if token:
        provided = request.headers.get(ADMIN_TOKEN_HEADER, "")
        # Sabit zamanlı karşılaştırma: uzunluk ya da ilk farklı karakter
        # üzerinden anahtar tahmin edilemesin.
        if not secrets.compare_digest(provided, token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "admin_token_invalid", "message": "Yönetim anahtarı geçersiz."},
            )
        return

    if not _is_local(getattr(settings, "host", "127.0.0.1")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "admin_requires_token",
                "message": (
                    "Sunucu yerel adres dışına bağlı. Yönetim uçları için "
                    "JARVIS_ADMIN_TOKEN tanımlanmalıdır."
                ),
            },
        )


def _store(request: Request) -> Any:
    store = getattr(request.app.state, "llm_config_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "admin_unavailable", "message": "Yapılandırma deposu kurulu değil."},
        )
    return store


@router.get("/admin/llm", response_model=LLMConfig, status_code=status.HTTP_200_OK)
async def read_llm_config(request: Request) -> LLMConfig:
    """Geçerli sağlayıcı yapılandırmasını döndürür (anahtar hariç)."""

    _require_admin(request)
    return _store(request).get()


@router.put("/admin/llm", response_model=LLMConfig, status_code=status.HTTP_200_OK)
async def update_llm_config(body: LLMConfigUpdate, request: Request) -> LLMConfig:
    """Sağlayıcıyı değiştirir ve hemen devreye alır."""

    _require_admin(request)
    store = _store(request)

    previous = store.get()
    config = store.update(
        kind=body.kind,
        base_url=body.base_url,
        model=body.model,
        timeout_seconds=body.timeout_seconds,
        api_key=body.api_key,
        clear_api_key=body.clear_api_key,
    )

    # Adres değişikliği denetim kaydına girer: konuşmaların nereye gittiğini
    # değiştiren bir işlem iz bırakmalıdır.
    safe_record(
        getattr(request.app.state, "audit_log", None),
        AuditEvent(
            action=AuditAction.TOOL_CALL,
            outcome=AuditOutcome.SUCCESS,
            tool_name="admin.llm_config",
            arguments={
                "kind": str(config.kind),
                "base_url": config.base_url,
                "model": config.model,
                "previous_base_url": previous.base_url,
            },
        ),
    )

    switchable = getattr(request.app.state, "llm_provider", None)
    if switchable is not None:
        await switchable.switch(store.build_provider())

    return config


# ---------------------------------------------------------------------------
# Council üyeleri — çoklu ajan, üye başına anahtar
# ---------------------------------------------------------------------------


class CouncilMemberUpdate(BaseModel):
    """Bir Council üyesini ekleme/güncelleme isteği."""

    kind: LLMProviderKind
    base_url: str = Field(min_length=1, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    is_chairman: bool = False
    enabled: bool = True

    api_key: str | None = Field(default=None, max_length=500)
    """Yeni anahtar. Gönderilmezse mevcut anahtar korunur."""

    clear_api_key: bool = False


class CouncilMembersResponse(BaseModel):
    """Council üye listesi ve müzakerenin fiilen açık olup olmadığı."""

    members: list[CouncilMemberConfig]
    count: int

    active: bool
    """Council şu an gerçekten çalışıyor mu?

    Üye TANIMLANMIŞ olması yetmez: etkin üye sayısı `council_min_candidates`
    altındaysa müzakere kurulmaz. Bu alan olmadan kullanıcı, üyelerini
    kaydettiği hâlde neden hiçbir şeyin değişmediğini anlayamazdı.
    """

    min_candidates: int


def _council_store(request: Request) -> Any:
    store = getattr(request.app.state, "council_member_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "council_store_unavailable",
                "message": "Council üye deposu kurulu değil.",
            },
        )
    return store


def _council_response(request: Request) -> CouncilMembersResponse:
    """Üye listesini ve Council'ın fiilî durumunu birlikte döndürür."""
    store = _council_store(request)
    settings = request.app.state.settings
    members = store.list()
    enabled = [member for member in members if member.enabled]
    agent = getattr(request.app.state, "agent_service", None)
    return CouncilMembersResponse(
        members=members,
        count=len(members),
        active=(
            agent is not None
            and getattr(agent, "council_service", None) is not None
            and len(enabled) >= settings.council_min_candidates
        ),
        min_candidates=settings.council_min_candidates,
    )


async def _rebuild_council(request: Request) -> None:
    """Üye listesinden Council'ı yeniden kurar ve ajana bağlar.

    Sağlayıcı değişiminde olduğu gibi, değişikliğin etkili olması için
    uygulamayı yeniden başlatmak gerekmez. Eski üyelerin sağlayıcıları
    kapatılır: kapatılmasalardı her kaydetmede bir HTTP istemcisi daha
    birikirdi.

    Yeterli üye yoksa Council SÖKÜLÜR (None atanır) ve sistem tek-LLM
    davranışına döner — yarım bir Council'dan iyidir.
    """
    agent = getattr(request.app.state, "agent_service", None)
    if agent is None or not hasattr(agent, "set_council"):
        return

    store = _council_store(request)
    settings = request.app.state.settings

    members, chairman, providers = store.build_members(
        max_members=settings.council_max_members
    )

    if chairman is None or len(members) < settings.council_min_candidates:
        agent.set_council(None, None)
        service = None
    else:
        service = CouncilService(
            members=members,
            chairman=chairman,
            min_candidates=settings.council_min_candidates,
            review_enabled=settings.council_review_enabled,
            member_timeout_seconds=settings.council_member_timeout_seconds,
            total_timeout_seconds=settings.council_total_timeout_seconds,
            max_concurrency=settings.council_max_concurrency,
            max_candidate_chars=settings.council_max_candidate_chars,
            max_review_chars=settings.council_max_review_chars,
        )
        agent.set_council(
            service,
            CouncilGate(
                enabled=True,
                member_count=service.member_count,
                min_candidates=settings.council_min_candidates,
            ),
        )

    for previous in getattr(request.app.state, "council_providers", []) or []:
        closer = getattr(previous, "aclose", None)
        if closer is None:
            continue
        try:
            await closer()
        except Exception:  # noqa: BLE001
            logger.exception("council_provider_close_failed")

    request.app.state.council_service = service
    request.app.state.council_providers = providers if service is not None else []


@router.get(
    "/admin/council", response_model=CouncilMembersResponse, status_code=status.HTTP_200_OK
)
async def read_council_members(request: Request) -> CouncilMembersResponse:
    """Tanımlı Council üyelerini döndürür (anahtarlar hariç)."""

    _require_admin(request)
    return _council_response(request)


@router.put(
    "/admin/council/members/{member_id}",
    response_model=CouncilMembersResponse,
    status_code=status.HTTP_200_OK,
)
async def upsert_council_member(
    member_id: str, body: CouncilMemberUpdate, request: Request
) -> CouncilMembersResponse:
    """Bir Council üyesini ekler veya günceller ve Council'ı yeniden kurar."""

    _require_admin(request)
    if not re.fullmatch(MEMBER_ID_PATTERN, member_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "member_id_invalid",
                "message": "Üye kimliği küçük harf, rakam, tire ve alt çizgiden oluşmalıdır.",
            },
        )

    store = _council_store(request)
    try:
        store.upsert(
            member_id=member_id,
            kind=body.kind,
            base_url=body.base_url,
            model=body.model,
            timeout_seconds=body.timeout_seconds,
            is_chairman=body.is_chairman,
            enabled=body.enabled,
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "council_member_limit", "message": str(exc)},
        ) from exc

    # Bir üyenin adresi, konuşmaların nereye gittiğini değiştirir; tekil
    # sağlayıcı değişimiyle aynı gerekçeyle iz bırakır.
    safe_record(
        getattr(request.app.state, "audit_log", None),
        AuditEvent(
            action=AuditAction.TOOL_CALL,
            outcome=AuditOutcome.SUCCESS,
            tool_name="admin.council_member",
            arguments={
                "member_id": member_id,
                "kind": str(body.kind),
                "base_url": body.base_url,
                "model": body.model,
                "enabled": body.enabled,
            },
        ),
    )

    await _rebuild_council(request)
    return _council_response(request)


@router.delete(
    "/admin/council/members/{member_id}",
    response_model=CouncilMembersResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_council_member(member_id: str, request: Request) -> CouncilMembersResponse:
    """Bir Council üyesini siler ve Council'ı yeniden kurar."""

    _require_admin(request)
    if not _council_store(request).delete(member_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "council_member_not_found", "message": "Üye bulunamadı."},
        )

    safe_record(
        getattr(request.app.state, "audit_log", None),
        AuditEvent(
            action=AuditAction.TOOL_CALL,
            outcome=AuditOutcome.SUCCESS,
            tool_name="admin.council_member_delete",
            arguments={"member_id": member_id},
        ),
    )

    await _rebuild_council(request)
    return _council_response(request)
