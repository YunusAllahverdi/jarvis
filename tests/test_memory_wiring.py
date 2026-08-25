"""Phase 1B-3A — Bellek bileşenlerinin gerçek FastAPI uygulamasına bağlanması.

Kapsam:
 1. create_app() bellek yığınını (SQLiteMemoryStore + MemoryExtractor +
    MemoryWriteService) varsayılan (enjekte edilmemiş) sağlayıcı ile kurabilir
    — ANCAK bu kurulum uygulama fiilen başlatılana (lifespan startup) kadar
    gerçekleşmez; salt create_app() çağrısı veya modül import'u SQLite
    dosyasına dokunmaz.
 2. settings.memory_db_path, SQLiteMemoryStore'a doğru şekilde iletilir.
 3. MemoryWriteService doğru extractor/store referanslarını alır.
 4. ChatOrchestrator, kurulan MemoryWriteService'i (geç bağlama ile) alır.
 5. Enjekte edilen (sahte) bir provider bellek çıkarımına otomatik bağlanmaz —
    mevcut testlerin davranışı bu sayede değişmeden korunur.
 6. Bellek etkinken (memory_service açıkça enjekte edilerek) normal bir chat
    isteği çalışır ve bellek gerçekten kalıcı hale gelir.
 7. Bellek çıkarma/depolama hatası chat isteğini bozmaz.
 8. Uygulama gerçekten başlatıldığında (lifespan) SQLite veritabanı dosyası
    yapılandırılan yolda oluşturulur — ama yalnızca o zaman; create_app()'i
    çağırmak veya `app.main`'i import etmek başlı başına dosyayı oluşturmaz.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings, get_settings
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.main import create_app
from app.memory.extractor import MemoryExtractor
from app.memory.record import MemoryRecord
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services.memory_service import MemoryWriteService


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path, **kwargs: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        app_name="Jarvis Test",
        app_version="test-1",
        environment="test",
        ollama_model="not-used-by-fake",
        memory_db_path=str(tmp_path / "memory.db"),
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _json_response(memories: list[dict[str, Any]]) -> str:
    return json.dumps({"memories": memories})


class _FakeChatProvider:
    """/api/chat isteklerini sabit bir metinle cevaplayan sahte sağlayıcı."""

    def __init__(self, reply: str = "Jarvis: ok") -> None:
        self._reply = reply
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        response = await self.generate_with_tools(messages, tools=())
        return response.content

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append(list(messages))
        return LLMResponse(content=self._reply)


class _FakeMemoryLLMProvider:
    """MemoryExtractor için sabit bir JSON yanıtı döndüren sahte sağlayıcı."""

    def __init__(self, response: str) -> None:
        self._response = response

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        return self._response

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        return LLMResponse(content=self._response)


class _RaisingExtractor:
    """extract() çağrısında her zaman beklenmedik bir hata fırlatan sahte extractor."""

    async def extract(self, user_message: str, *, session_id: str | None = None):
        raise RuntimeError("extraction boom")


class _FailingStore:
    """MemoryStore Protocol'ünü karşılayan ama add() sırasında her zaman patlayan sahte store."""

    def add(self, record: MemoryRecord) -> MemoryRecord:
        raise RuntimeError("store unavailable")

    def update(self, record: MemoryRecord) -> MemoryRecord:
        raise RuntimeError("unused")

    def invalidate(self, memory_id: str, *, at=None) -> bool:
        return False

    def delete(self, memory_id: str, *, at=None) -> bool:
        return False

    def get(self, memory_id: str) -> MemoryRecord | None:
        return None

    def list_active(self, **kwargs: Any) -> list[MemoryRecord]:
        return []

    def list_by_session(self, session_id: str, *, include_invalidated: bool = False) -> list[MemoryRecord]:
        return []

    def search(self, query: str, **kwargs: Any) -> list[MemoryRecord]:
        return []


# ---------------------------------------------------------------------------
# 1-5. create_app bellek yığınını doğru şekilde kurar / gerektiğinde kurmaz
# ---------------------------------------------------------------------------


class TestCreateAppBuildsMemoryStack:
    def test_create_app_alone_does_not_build_memory_stack_yet(self, tmp_path: Path) -> None:
        """create_app() dönüşünde — lifespan başlamadan önce — bellek servisi henüz None olmalı."""
        settings = _make_settings(tmp_path)

        app = create_app(settings=settings)

        assert app.state.memory_service is None
        assert app.state.chat_orchestrator._memory_service is None

    def test_default_provider_triggers_real_memory_wiring_on_startup(self, tmp_path: Path) -> None:
        """provider enjekte edilmediğinde (gerçek üretim yolu) bellek, uygulama
        gerçekten başlatıldığında (lifespan) otomatik kurulmalı."""
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            assert isinstance(app.state.memory_service, MemoryWriteService)

    def test_memory_db_path_is_passed_to_sqlite_store(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            store = app.state.memory_service._store
            assert isinstance(store, SQLiteMemoryStore)
            assert store._db_path == settings.memory_db_path

    def test_memory_service_extractor_is_bound_to_the_active_provider(self, tmp_path: Path) -> None:
        """MemoryExtractor, orchestrator'ın kullandığı aynı LLM sağlayıcısını kullanmalı —
        ayrı bir LLM bağlantı mimarisi kurulmamalı."""
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            extractor = app.state.memory_service._extractor
            assert isinstance(extractor, MemoryExtractor)
            assert extractor._provider is app.state.chat_orchestrator._provider

    def test_orchestrator_receives_the_constructed_memory_service(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            assert app.state.chat_orchestrator._memory_service is app.state.memory_service
            assert isinstance(app.state.chat_orchestrator._memory_service, MemoryWriteService)

    def test_injected_fake_provider_does_not_auto_wire_memory(self, tmp_path: Path) -> None:
        """Testlerin enjekte ettiği sahte sağlayıcılar bellek çıkarımına otomatik bağlanmamalı.

        Bu davranış, mevcut test paketinin (test_chat.py, test_hardening.py vb.)
        hiçbir değişiklik yapılmadan geçmeye devam etmesini garanti eder.
        Uygulama gerçekten başlatılsa (lifespan) bile bu durum değişmemeli.
        """
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings, provider=_FakeChatProvider())

        assert app.state.memory_service is None
        assert app.state.chat_orchestrator._memory_service is None

        with TestClient(app):
            assert app.state.memory_service is None
            assert app.state.chat_orchestrator._memory_service is None

    def test_explicit_memory_service_override_is_used_as_is(self, tmp_path: Path) -> None:
        """Çağıran açıkça bir memory_service verirse, otomatik kurulum devre dışı kalır."""
        real_store = SQLiteMemoryStore(str(tmp_path / "custom.db"))
        custom_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(_json_response([]))),
            store=real_store,
        )
        settings = _make_settings(tmp_path)

        app = create_app(
            settings=settings,
            provider=_FakeChatProvider(),
            memory_service=custom_service,
        )

        assert app.state.memory_service is custom_service
        assert app.state.chat_orchestrator._memory_service is custom_service


# ---------------------------------------------------------------------------
# 6. Bellek etkinken normal bir chat isteği çalışır
# ---------------------------------------------------------------------------


class TestChatWorksWithMemoryEnabled:
    def test_chat_request_succeeds_and_persists_extracted_memory(self, tmp_path: Path) -> None:
        chat_provider = _FakeChatProvider("Jarvis: Merhaba!")
        memory_response = _json_response([
            {
                "memory_type": "fact",
                "content": "The user lives in Istanbul.",
                "temporality": "present",
                "status": "active",
            }
        ])
        real_store = SQLiteMemoryStore(str(tmp_path / "memory.db"))
        memory_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(memory_response)),
            store=real_store,
        )
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings, provider=chat_provider, memory_service=memory_service)

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "I live in Istanbul."})

        assert response.status_code == 200
        assert response.json()["response"] == "Jarvis: Merhaba!"
        assert real_store.count() == 1
        stored = real_store.list_active()[0]
        assert stored.content == "The user lives in Istanbul."


# ---------------------------------------------------------------------------
# 7. Bellek hatası chat isteğini bozmaz
# ---------------------------------------------------------------------------


class TestChatSurvivesMemoryFailure:
    def test_extraction_failure_does_not_break_chat_response(self, tmp_path: Path) -> None:
        chat_provider = _FakeChatProvider("Jarvis: yine de çalışıyor.")
        memory_service = MemoryWriteService(
            extractor=_RaisingExtractor(),  # type: ignore[arg-type]
            store=SQLiteMemoryStore(str(tmp_path / "memory.db")),
        )
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings, provider=chat_provider, memory_service=memory_service)

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "Merhaba"})

        assert response.status_code == 200
        assert response.json()["response"] == "Jarvis: yine de çalışıyor."

    def test_store_failure_does_not_break_chat_response(self, tmp_path: Path) -> None:
        chat_provider = _FakeChatProvider("Jarvis: hâlâ ayakta.")
        memory_response = _json_response([
            {"memory_type": "fact", "content": "User owns a cat.", "temporality": "present", "status": "active"}
        ])
        memory_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(memory_response)),
            store=_FailingStore(),
        )
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings, provider=chat_provider, memory_service=memory_service)

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "I have a cat."})

        assert response.status_code == 200
        assert response.json()["response"] == "Jarvis: hâlâ ayakta."


# ---------------------------------------------------------------------------
# 8. SQLite dosyası yalnızca gerçek başlatma (lifespan) sırasında oluşturulur
# ---------------------------------------------------------------------------


class TestSqliteFileCreatedOnStartup:
    def test_create_app_alone_does_not_create_db_file(self, tmp_path: Path) -> None:
        """Salt create_app() çağrısı — uygulama fiilen başlamadan — dosya oluşturmamalı."""
        db_path = tmp_path / "nested" / "memory.db"
        settings = _make_settings(tmp_path, memory_db_path=str(db_path))
        assert not db_path.exists()

        create_app(settings=settings)

        assert not db_path.exists(), "create_app() tek başına kalıcı veritabanını oluşturmamalı"

    def test_db_file_exists_after_application_actually_starts(self, tmp_path: Path) -> None:
        """Uygulama gerçekten başlatıldığında (lifespan startup) dosya oluşmalı."""
        db_path = tmp_path / "nested" / "memory.db"
        settings = _make_settings(tmp_path, memory_db_path=str(db_path))
        app = create_app(settings=settings)
        assert not db_path.exists()

        with TestClient(app):
            assert db_path.exists()

    def test_db_file_created_at_exact_configured_path(self, tmp_path: Path) -> None:
        db_path = tmp_path / "custom_name.db"
        settings = _make_settings(tmp_path, memory_db_path=str(db_path))
        app = create_app(settings=settings)

        with TestClient(app):
            assert db_path.is_file()

    def test_no_db_file_created_when_provider_is_injected(self, tmp_path: Path) -> None:
        """Enjekte edilen sahte provider ile bellek kurulmadığından dosya hiç oluşmamalı,
        uygulama başlatılsa bile."""
        db_path = tmp_path / "should_not_exist.db"
        settings = _make_settings(tmp_path, memory_db_path=str(db_path))
        app = create_app(settings=settings, provider=_FakeChatProvider())

        with TestClient(app):
            pass

        assert not db_path.exists()


# ---------------------------------------------------------------------------
# `app.main`'i import etmek kalıcı bellek veritabanını oluşturmamalı
# ---------------------------------------------------------------------------


class TestImportingAppMainHasNoSideEffect:
    def test_importing_app_main_module_does_not_create_memory_database(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`app.main`'i import etmek (modül seviyesindeki `app = create_app()` dahil)
        kullanıcının kalıcı bellek veritabanını asla oluşturmamalı; veritabanı
        yalnızca uygulama gerçekten başlatıldığında (lifespan) oluşmalı.

        Bu test, gerçek modül import akışını (get_settings() üzerinden) taklit
        etmek için app.main'i yeniden yükler — tam olarak `app = create_app()`
        modül seviyesi satırının çalıştığı yol.
        """
        db_path = tmp_path / "import_side_effect.db"
        monkeypatch.setenv("JARVIS_MEMORY_DB_PATH", str(db_path))
        monkeypatch.setenv("JARVIS_ENVIRONMENT", "test")
        get_settings.cache_clear()

        import app.main as main_module

        try:
            importlib.reload(main_module)

            assert not db_path.exists(), (
                "app.main import etmek (modül seviyesi `app = create_app()` dahil) "
                "kalıcı bellek veritabanını oluşturmamalı"
            )

            with TestClient(main_module.app):
                assert db_path.exists(), (
                    "uygulama gerçekten başlatıldığında (lifespan) veritabanı oluşmalı"
                )
        finally:
            get_settings.cache_clear()
            importlib.reload(main_module)
