"""Yönetim uçları — /api/admin/llm.

Kapsam:
 1. Yapılandırma okunabilir
 2. Güncelleme kaydedilir ve döndürülür
 3. API anahtarı YANITTA HİÇ görünmez
 4. Güncelleme canlı sağlayıcıyı hemen değiştirir
 5. Yerel adreste anahtarsız erişim serbesttir
 6. Yerel olmayan adreste anahtarsız erişim REDDEDİLİR
 7. Anahtar tanımlıysa doğru başlıkla erişilir
 8. Yanlış anahtar reddedilir
 9. Eksik başlık reddedilir
10. Adres değişikliği denetim kaydına girer
11. Depo kurulu değilse açıkça bildirilir
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.admin import ADMIN_TOKEN_HEADER, router as admin_router
from app.config.settings import Settings
from app.security.audit import InMemoryAuditLog
from app.services.llm_config import LLMConfigStore, SwitchableProvider

_KEY = "sk-cok-gizli-anahtar"
_TOKEN = "yonetim-anahtari-123"


class _FakeProvider:
    def __init__(self, name: str = "ilk") -> None:
        self.name = name

    async def generate(self, messages):  # type: ignore[no-untyped-def]
        return self.name

    async def generate_with_tools(self, messages, tools):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


def _build(
    tmp_path: Path,
    *,
    host: str = "127.0.0.1",
    admin_token: str = "",
    with_store: bool = True,
):
    settings = Settings(
        app_name="T",
        app_version="t",
        environment="test",
        ollama_model="x",
        host=host,
        admin_token=admin_token,
    )
    store = LLMConfigStore(str(tmp_path / "jarvis.db")) if with_store else None
    switchable = SwitchableProvider(_FakeProvider())
    audit = InMemoryAuditLog()

    app = FastAPI()
    app.include_router(admin_router, prefix="/api")
    app.state.settings = settings
    app.state.llm_config_store = store
    app.state.llm_provider = switchable
    app.state.audit_log = audit

    return TestClient(app), store, switchable, audit


_UPDATE = {
    "kind": "openai_compatible",
    "base_url": "https://saglayici.example/v1",
    "model": "bir-model",
    "api_key": _KEY,
}


# ---------------------------------------------------------------------------
# 1-4. Okuma, yazma, gizlilik, canlı geçiş
# ---------------------------------------------------------------------------

def test_config_can_be_read(tmp_path: Path) -> None:
    """Geçerli yapılandırma okunabilmeli."""
    client, _, _, _ = _build(tmp_path)

    body = client.get("/api/admin/llm").json()

    assert body["kind"] == "ollama"
    assert body["has_api_key"] is False


def test_update_is_saved_and_returned(tmp_path: Path) -> None:
    """Güncelleme kaydedilmeli ve sonucu dönmeli."""
    client, store, _, _ = _build(tmp_path)

    body = client.put("/api/admin/llm", json=_UPDATE).json()

    assert body["kind"] == "openai_compatible"
    assert body["model"] == "bir-model"
    assert body["has_api_key"] is True
    assert store.get().base_url == "https://saglayici.example/v1"


def test_the_key_never_appears_in_a_response(tmp_path: Path) -> None:
    """Anahtar hiçbir yanıtta geri dönmemeli."""
    client, _, _, _ = _build(tmp_path)

    put_body = client.put("/api/admin/llm", json=_UPDATE).text
    get_body = client.get("/api/admin/llm").text

    assert _KEY not in put_body
    assert _KEY not in get_body


def test_update_switches_the_live_provider(tmp_path: Path) -> None:
    """Değişiklik hemen devreye girmeli; yeniden başlatma gerekmemeli."""
    client, _, switchable, _ = _build(tmp_path)
    before = switchable.delegate

    client.put("/api/admin/llm", json=_UPDATE)

    assert switchable.delegate is not before


# ---------------------------------------------------------------------------
# 5-9. Erişim kuralları
# ---------------------------------------------------------------------------

def test_local_host_without_a_token_is_allowed(tmp_path: Path) -> None:
    """Yerel adreste anahtar zorunlu olmamalı."""
    client, _, _, _ = _build(tmp_path, host="127.0.0.1")

    assert client.get("/api/admin/llm").status_code == 200


def test_non_local_host_without_a_token_is_refused(tmp_path: Path) -> None:
    """Dışarı açık sunucuda anahtarsız yönetim reddedilmeli.

    Bu uçlar API anahtarı kabul ediyor ve LLM adresini değiştirebiliyor;
    kimlik doğrulaması olmadan ağa açılmaları kabul edilemez.
    """
    client, _, _, _ = _build(tmp_path, host="0.0.0.0")

    response = client.get("/api/admin/llm")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "admin_requires_token"


def test_a_token_unlocks_a_non_local_host(tmp_path: Path) -> None:
    """Anahtar tanımlıysa dışarı açık sunucuda da çalışmalı."""
    client, _, _, _ = _build(tmp_path, host="0.0.0.0", admin_token=_TOKEN)

    response = client.get("/api/admin/llm", headers={ADMIN_TOKEN_HEADER: _TOKEN})

    assert response.status_code == 200


@pytest.mark.parametrize("headers", [{}, {ADMIN_TOKEN_HEADER: "yanlis"}])
def test_a_wrong_or_missing_token_is_refused(tmp_path: Path, headers: dict) -> None:
    """Anahtar tanımlıyken her istek onu taşımalı."""
    client, _, _, _ = _build(tmp_path, admin_token=_TOKEN)

    response = client.get("/api/admin/llm", headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "admin_token_invalid"


# ---------------------------------------------------------------------------
# 10-11. İz ve eksik kurulum
# ---------------------------------------------------------------------------

def test_changing_the_address_is_audited(tmp_path: Path) -> None:
    """Konuşmaların nereye gittiğini değiştiren işlem iz bırakmalı."""
    client, _, _, audit = _build(tmp_path)

    client.put("/api/admin/llm", json=_UPDATE)

    events = [e for e in audit.recent() if e.tool_name == "admin.llm_config"]
    assert len(events) == 1
    assert events[0].arguments["base_url"] == "https://saglayici.example/v1"
    assert events[0].arguments["previous_base_url"] == "http://127.0.0.1:11434"


def test_a_missing_store_is_reported(tmp_path: Path) -> None:
    """Yapılandırma deposu yoksa sessiz kalınmamalı."""
    client, _, _, _ = _build(tmp_path, with_store=False)

    response = client.get("/api/admin/llm")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "admin_unavailable"
