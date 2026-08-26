"""Phase 1B-3A/3D — Bellek bileşenlerinin gerçek FastAPI uygulamasına bağlanması.

Kapsam (1B-3A — yazma yığını):
 1. create_app() bellek yığınını (SQLiteMemoryStore + MemoryExtractor +
    MemoryWriteService + MemoryRetrievalService) varsayılan (enjekte
    edilmemiş) sağlayıcı ile kurabilir — ANCAK bu kurulum uygulama fiilen
    başlatılana (lifespan startup) kadar gerçekleşmez; salt create_app()
    çağrısı veya modül import'u SQLite dosyasına dokunmaz.
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

Kapsam (1B-3D — getirme yığını + paylaşılan store):
 9. MemoryWriteService ve MemoryRetrievalService AYNI SQLiteMemoryStore
    örneğini paylaşır.
10. ChatOrchestrator hem memory_service hem memory_retrieval'i alır.
11. Yalnızca memory_service (retrieval olmadan) enjekte edilirse otomatik
    kurulum tamamen devre dışı kalır (ikisi de birlikte kurulur/kurulmaz).
12. Gerçek bir /api/chat akışı bir bellek yazabilir ve sonraki bir tur bu
    belleği getirip LLM bağlamına ekleyebilir (uçtan uca, gerçek SQLite ile).
13. Bellek getirme hatası normal sohbeti bozmaz.

Kapsam (1C-3 — zamansal bellek gerçek uygulamaya bağlanır):
14. Üretim başlatması (lifespan) bir MemoryTemporalService kurar.
15. MemoryWriteService, kurulan temporal servisi alır.
16. Temporal servis ve retrieval servisi AYNI SQLiteMemoryStore örneğini
    paylaşır (write servisiyle birlikte, üçü de aynı örnek).
17. Gerçek bir /api/chat akışı: 1. tur bir bellek yazar, ÇAKIŞAN 2. tur
    öncekini geçersizleştirir (fiziksel olarak korunur), yeni kayıt etkin
    olur, 3. tur getirme ile yeni etkin gerçeği bulur.
18. Tarihsel (geçersizleştirilmiş) kayıt, açıkça istendiğinde (get(id))
    hâlâ erişilebilir kalır.
19. MemoryTemporalService hatası normal sohbeti bozmaz.
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
from app.memory.record import MemoryRecord, MemoryType
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.memory_service import MemoryWriteService
from app.services.memory_temporal import MemoryTemporalService


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


class _FailingSearchStore:
    """MemoryStore Protocol'ünü karşılayan ama search() sırasında her zaman patlayan sahte store."""

    def add(self, record: MemoryRecord) -> MemoryRecord:
        return record

    def update(self, record: MemoryRecord) -> MemoryRecord:
        return record

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
        raise RuntimeError("search backend unavailable")


# ---------------------------------------------------------------------------
# 1-5. create_app bellek yığınını doğru şekilde kurar / gerektiğinde kurmaz
# ---------------------------------------------------------------------------


class TestCreateAppBuildsMemoryStack:
    def test_create_app_alone_does_not_build_memory_stack_yet(self, tmp_path: Path) -> None:
        """create_app() dönüşünde — lifespan başlamadan önce — bellek servisleri henüz None olmalı."""
        settings = _make_settings(tmp_path)

        app = create_app(settings=settings)

        assert app.state.memory_service is None
        assert app.state.memory_retrieval is None
        assert app.state.memory_store is None
        assert app.state.chat_orchestrator._memory_service is None
        assert app.state.chat_orchestrator._memory_retrieval is None

    def test_default_provider_triggers_real_memory_wiring_on_startup(self, tmp_path: Path) -> None:
        """provider enjekte edilmediğinde (gerçek üretim yolu) bellek yazma VE
        getirme, uygulama gerçekten başlatıldığında (lifespan) otomatik kurulmalı."""
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            assert isinstance(app.state.memory_service, MemoryWriteService)
            assert isinstance(app.state.memory_retrieval, MemoryRetrievalService)

    def test_memory_db_path_is_passed_to_sqlite_store(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            store = app.state.memory_service._store
            assert isinstance(store, SQLiteMemoryStore)
            assert store._db_path == settings.memory_db_path
            assert app.state.memory_store is store

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
            assert app.state.chat_orchestrator._memory_retrieval is app.state.memory_retrieval
            assert isinstance(app.state.chat_orchestrator._memory_retrieval, MemoryRetrievalService)

    def test_injected_fake_provider_does_not_auto_wire_memory(self, tmp_path: Path) -> None:
        """Testlerin enjekte ettiği sahte sağlayıcılar bellek çıkarımına/getirmesine
        otomatik bağlanmamalı.

        Bu davranış, mevcut test paketinin (test_chat.py, test_hardening.py vb.)
        hiçbir değişiklik yapılmadan geçmeye devam etmesini garanti eder.
        Uygulama gerçekten başlatılsa (lifespan) bile bu durum değişmemeli.
        """
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings, provider=_FakeChatProvider())

        assert app.state.memory_service is None
        assert app.state.memory_retrieval is None
        assert app.state.chat_orchestrator._memory_service is None
        assert app.state.chat_orchestrator._memory_retrieval is None

        with TestClient(app):
            assert app.state.memory_service is None
            assert app.state.memory_retrieval is None
            assert app.state.chat_orchestrator._memory_service is None
            assert app.state.chat_orchestrator._memory_retrieval is None

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

    def test_explicit_memory_retrieval_override_is_used_as_is(self, tmp_path: Path) -> None:
        """Çağıran açıkça bir memory_retrieval verirse, otomatik kurulum devre dışı kalır."""
        real_store = SQLiteMemoryStore(str(tmp_path / "custom.db"))
        custom_retrieval = MemoryRetrievalService(store=real_store)
        settings = _make_settings(tmp_path)

        app = create_app(
            settings=settings,
            provider=_FakeChatProvider(),
            memory_retrieval=custom_retrieval,
        )

        assert app.state.memory_retrieval is custom_retrieval
        assert app.state.chat_orchestrator._memory_retrieval is custom_retrieval

    def test_providing_only_memory_service_disables_all_auto_wiring(self, tmp_path: Path) -> None:
        """Yalnızca memory_service verilip memory_retrieval verilmezse (provider
        varsayılan olsa bile), otomatik kurulum ikisi için de devreye girmez —
        yazma ve getirme her zaman BİRLİKTE, atomik olarak kurulur."""
        real_store = SQLiteMemoryStore(str(tmp_path / "custom.db"))
        custom_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(_json_response([]))),
            store=real_store,
        )
        settings = _make_settings(tmp_path)

        # provider enjekte edilmiyor (varsayılan/gerçek yol) — yalnızca memory_service verildi.
        app = create_app(settings=settings, memory_service=custom_service)

        with TestClient(app):
            assert app.state.memory_service is custom_service
            assert app.state.memory_retrieval is None
            assert app.state.chat_orchestrator._memory_retrieval is None


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
# 9. MemoryWriteService ve MemoryRetrievalService AYNI store'u paylaşır
# ---------------------------------------------------------------------------


class TestWriteAndRetrievalShareTheSameStore:
    def test_auto_wired_services_share_the_same_sqlite_store_instance(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            write_store = app.state.memory_service._store
            retrieval_store = app.state.memory_retrieval._store
            temporal_store = app.state.memory_temporal._store
            assert write_store is retrieval_store
            assert write_store is temporal_store
            assert write_store is app.state.memory_store
            assert isinstance(write_store, SQLiteMemoryStore)

    def test_production_startup_creates_memory_temporal_service(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        assert app.state.memory_temporal is None  # lifespan başlayana kadar

        with TestClient(app):
            assert isinstance(app.state.memory_temporal, MemoryTemporalService)

    def test_write_service_receives_the_temporal_service(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            assert app.state.memory_service._temporal_service is app.state.memory_temporal

    def test_orchestrator_does_not_reference_temporal_service(self, tmp_path: Path) -> None:
        """ChatOrchestrator yalnızca memory_service ve memory_retrieval alır;
        temporal servisi hiç bilmemeli — bu, MemoryWriteService'in içinde
        dolaylı olarak kullanılan bir uygulama detayıdır."""
        import inspect

        import app.services.orchestrator as orchestrator_module

        source = inspect.getsource(orchestrator_module)
        assert "MemoryTemporalService" not in source
        assert "memory_temporal" not in source


# ---------------------------------------------------------------------------
# 12-13. Uçtan uca: bir turda yazılan bellek sonraki turda getirilip
# LLM bağlamına eklenir; getirme hatası sohbeti bozmaz
# ---------------------------------------------------------------------------


class TestEndToEndWriteThenRetrieve:
    def test_memory_written_in_one_turn_is_retrieved_in_a_later_turn(self, tmp_path: Path) -> None:
        """Gerçek SQLiteMemoryStore ile: 1. turda yazılan bellek, 2. turda
        MemoryRetrievalService.search() (FTS5) ile bulunup LLM bağlamına
        <relevant_memory> bloğu olarak eklenmelidir."""
        chat_provider = _FakeChatProvider("Jarvis: tamam.")
        memory_response = _json_response([
            {
                "memory_type": "fact",
                "content": "The user's favorite city is Istanbul.",
                "temporality": "present",
                "status": "active",
            }
        ])
        real_store = SQLiteMemoryStore(str(tmp_path / "memory.db"))
        memory_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(memory_response)),
            store=real_store,
        )
        memory_retrieval = MemoryRetrievalService(store=real_store)
        settings = _make_settings(tmp_path)
        app = create_app(
            settings=settings,
            provider=chat_provider,
            memory_service=memory_service,
            memory_retrieval=memory_retrieval,
        )

        with TestClient(app) as client:
            first = client.post(
                "/api/chat", json={"message": "My favorite city is Istanbul."}
            )
            session_id = first.json()["session_id"]
            assert real_store.count() == 1

            # Not: SQLite FTS5'in varsayılan sorgu sözdizimi, boşlukla ayrılmış
            # kelimeleri örtük AND ile birleştirir — bu yüzden test sorgusu
            # kasıtlı olarak saklanan içerikte gerçekten geçen tek bir kelime
            # kullanır (gerçek arama davranışını taklit etmek, FTS5 sözdizimini
            # test etmek değil bu testin amacı; FTS5'in kendi davranışı zaten
            # test_memory_store.py'de ayrıca test ediliyor).
            second = client.post(
                "/api/chat",
                json={"message": "Istanbul", "session_id": session_id},
            )

        assert first.status_code == 200
        assert second.status_code == 200

        # 2. sohbet turunda LLM'e gönderilen mesajlar arasında getirilen
        # bellek bloğu bulunmalı.
        second_turn_messages = chat_provider.calls[1]
        system_messages = [m for m in second_turn_messages if m.role == "system"]
        assert len(system_messages) == 2
        memory_block = system_messages[1]
        assert "<relevant_memory>" in memory_block.content
        assert "The user's favorite city is Istanbul." in memory_block.content

    def test_retrieval_failure_does_not_break_chat_response(self, tmp_path: Path) -> None:
        chat_provider = _FakeChatProvider("Jarvis: sorun yok.")
        memory_retrieval = MemoryRetrievalService(store=_FailingSearchStore())
        settings = _make_settings(tmp_path)
        app = create_app(
            settings=settings,
            provider=chat_provider,
            memory_service=MemoryWriteService(
                extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(_json_response([]))),
                store=_FailingSearchStore(),
            ),
            memory_retrieval=memory_retrieval,
        )

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "Merhaba"})

        assert response.status_code == 200
        assert response.json()["response"] == "Jarvis: sorun yok."
        # Getirme patladığından hiçbir bellek bloğu eklenmemiş olmalı.
        sent = chat_provider.calls[0]
        assert not any("<relevant_memory>" in m.content for m in sent)


# ---------------------------------------------------------------------------
# 14-19. Zamansal bellek (MemoryTemporalService) gerçek uygulamaya bağlanır
# ---------------------------------------------------------------------------


class TestEndToEndTemporalConflictResolution:
    def test_conflicting_fact_across_three_chat_turns_is_resolved_correctly(
        self, tmp_path: Path
    ) -> None:
        """1. tur bir gerçeği yazar, ÇAKIŞAN 2. tur öncekini geçersizleştirir
        (fiziksel olarak korunur) ve yeni kaydı etkin yapar, 3. tur getirme
        ile yalnızca yeni etkin gerçeği bulur — tamamı gerçek SQLiteMemoryStore
        ve gerçek MemoryTemporalService ile, tek paylaşılan store örneği
        üzerinden."""
        db_path = tmp_path / "shared_memory.db"
        real_store = SQLiteMemoryStore(str(db_path))
        temporal_service = MemoryTemporalService(store=real_store)
        settings = _make_settings(tmp_path, memory_db_path=str(db_path))

        # --- Tur 1: Istanbul yazılır ---
        turn1_response = _json_response([
            {
                "memory_type": "fact",
                "content": "User lives in Istanbul.",
                "temporality": "present",
                "status": "active",
                "topic_key": "user_residence",
            }
        ])
        turn1_write_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(turn1_response)),
            store=real_store,
            temporal_service=temporal_service,
        )
        app1 = create_app(
            settings=settings,
            provider=_FakeChatProvider("Not aldım."),
            memory_service=turn1_write_service,
        )
        with TestClient(app1) as client:
            r1 = client.post("/api/chat", json={"message": "I live in Istanbul."})
        assert r1.status_code == 200
        assert real_store.count() == 1
        istanbul_record = real_store.list_active(memory_type=MemoryType.FACT)[0]
        assert istanbul_record.invalid_at is None

        # --- Tur 2: Ankara ile ÇAKIŞAN gerçek yazılır ---
        turn2_response = _json_response([
            {
                "memory_type": "fact",
                "content": "User lives in Ankara.",
                "temporality": "present",
                "status": "active",
                "topic_key": "user_residence",
            }
        ])
        turn2_write_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(turn2_response)),
            store=real_store,
            temporal_service=temporal_service,
        )
        app2 = create_app(
            settings=settings,
            provider=_FakeChatProvider("Güncellendi."),
            memory_service=turn2_write_service,
        )
        with TestClient(app2) as client:
            r2 = client.post("/api/chat", json={"message": "I moved to Ankara."})
        assert r2.status_code == 200

        # Eski kayıt fiziksel olarak korunuyor (silinmedi) ama artık geçersiz.
        historical = real_store.get(istanbul_record.id)
        assert historical is not None
        assert historical.content == "User lives in Istanbul."
        assert historical.invalid_at is not None

        # Yeni kayıt etkin kayıttır.
        active = real_store.list_active(memory_type=MemoryType.FACT)
        assert len(active) == 1
        assert active[0].content == "User lives in Ankara."

        # Fiziksel kayıt sayısı: iki tur = iki kayıt, hiçbiri silinmedi.
        assert real_store.count(include_deleted=True) == 2

        # --- Tur 3: Getirme, yalnızca güncel (Ankara) gerçeği bulmalı ---
        turn3_chat_provider = _FakeChatProvider("Ankara'da yaşıyorsun.")
        app3 = create_app(
            settings=settings,
            provider=turn3_chat_provider,
            memory_retrieval=MemoryRetrievalService(store=SQLiteMemoryStore(str(db_path))),
        )
        with TestClient(app3) as client:
            r3 = client.post("/api/chat", json={"message": "Where do I live?"})
        assert r3.status_code == 200

        sent = turn3_chat_provider.calls[0]
        system_messages = [m for m in sent if m.role == "system"]
        assert len(system_messages) == 2
        memory_block = system_messages[1].content
        assert "Ankara" in memory_block
        assert "Istanbul" not in memory_block  # tarihsel/geçersiz kayıt sızmamalı

    def test_temporal_service_failure_does_not_break_chat_response(
        self, tmp_path: Path
    ) -> None:
        class _RaisingTemporalService:
            def write(self, record: MemoryRecord):  # noqa: ANN201
                raise RuntimeError("temporal boom")

        response = _json_response([
            {"memory_type": "fact", "content": "User lives in Istanbul.", "temporality": "present", "status": "active"}
        ])
        chat_provider = _FakeChatProvider("Jarvis: hâlâ çalışıyor.")
        settings = _make_settings(tmp_path)
        app = create_app(
            settings=settings,
            provider=chat_provider,
            memory_service=MemoryWriteService(
                extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(response)),
                store=SQLiteMemoryStore(str(tmp_path / "memory.db")),
                temporal_service=_RaisingTemporalService(),
            ),
        )

        with TestClient(app) as client:
            chat_response = client.post("/api/chat", json={"message": "I live in Istanbul."})

        assert chat_response.status_code == 200
        assert chat_response.json()["response"] == "Jarvis: hâlâ çalışıyor."


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
