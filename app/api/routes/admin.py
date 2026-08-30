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

import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.security.audit import AuditAction, AuditEvent, AuditOutcome, safe_record
from app.services.llm_config import LLMConfig, LLMProviderKind

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
