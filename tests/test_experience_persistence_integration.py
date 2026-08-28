"""Phase 2D-Integration — Yakalanan Experience'ın canlı sohbet akışında kalıcılaştırılması.

Bu faz, Phase 2C'nin YAKALADIĞI Experience'ı Phase 2D'nin ZATEN var olan
ExperienceStore'una bağlar. Yeni bir Experience üretilmez, yeni bir kimlik
oluşturulmaz, yeni bir depolama mekanizması eklenmez.

Kapsam:
 1. experience_store=None mevcut davranışı birebir korur
 2. Başarılı bir tur tam olarak bir Experience kalıcılaştırır
 3. Kalıcılaştırılan nesne `_last_experience` ile AYNI nesnedir
 4. Kalıcılaştırılan kimlik `_last_experience.id` ile aynıdır
 5. Tool-call'lı bir tur tam olarak bir Experience kalıcılaştırır
 6. Patlayan bir sağlayıcı turu hiçbir şey kalıcılaştırmaz
 7. max_tool_rounds aşımı hiçbir şey kalıcılaştırmaz
 8. Kalıcılaştırma hatası ChatResult'ı bozmaz
 9. Kalıcılaştırma hatası `_last_experience`'ı geçersizleştirmez
10. Builder hatası ÖNCEKİ turun Experience'ını yeniden yazmaya çalışmaz
11. Sağlayıcı/tool çağrı sayıları değişmedi
12. Bellek işleme kalıcılaştırmadan ÖNCE çalışır
13. experience_store olmadan kurucu uyumluluğu korunur
14. Orchestrator kaynağı SQLiteExperienceStore'a hiç atıf yapmaz
15. assistant_response=None kalıcılaştırma hatası güvenle izole edilir
16. Gerçek SQLiteExperienceStore ile uçtan uca round-trip
17. Çok turlu tool akışı SQLite'ta tam olarak bir kayıt üretir
18. Yinelenen kimlik mevcut IntegrityError davranışını izler
19. SQLiteExperienceStore ve SQLiteMemoryStore aynı dosyada birlikte çalışır
20. İkinci bir veritabanı dosyası oluşturulmaz
21. Varsayılan sağlayıcı ile lifespan SQLiteExperienceStore'u otomatik kurar
22. app.state.experience_store başlatmadan sonra dolar
23. Açıkça verilen experience_store otomatik kurulumu engeller
24. Enjekte edilen (test) sağlayıcı veritabanı oluşturulmasını engeller
25. `app.main`'i import etmek veritabanı oluşturmaz

Gerçek bir Ollama sunucusu gerektirmez. Dosya sistemine dokunan tüm testler
geçici dizin (tmp_path) kullanır.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings, get_settings
from app.core.chat import ChatMessage, LLMResponse, ToolCall, ToolDefinition
from app.main import create_app
from app.memory.experience import Experience, ExperienceOutcome
from app.memory.experience_store import ExperienceStore
from app.memory.record import MemoryRecord
from app.memory.sqlite_experience_store import SQLiteExperienceStore
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services.conversation import InMemoryConversationStore
from app.services.orchestrator import ChatOrchestrator
from app.tools.base import PermissionLevel
from app.tools.defaults import build_default_tool_registry
from app.tools.executor import ToolExecutor


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class _FixedPromptProvider:
    def __init__(self, prompt: str = "Sen Jarvis'sin.") -> None:
        self._prompt = prompt

    def load(self) -> str:
        return self._prompt


class _EchoProvider:
    """Sabit bir metin cevabı döndüren, çağrıları kaydeden sahte sağlayıcı."""

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


class _MultiRoundToolCallingProvider:
    """Sırasıyla get_time, sonra calculator çağırıp en sonda metin döndüren sahte sağlayıcı."""

    def __init__(self) -> None:
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
        if len(self.calls) == 1:
            return LLMResponse(tool_calls=[ToolCall(name="get_time", arguments={})])
        if len(self.calls) == 2:
            return LLMResponse(
                tool_calls=[ToolCall(name="calculator", arguments={"expression": "2 + 3"})]
            )
        return LLMResponse(content="Saat ve sonuç: 5.")


class _AlwaysToolCallingProvider:
    """Hiçbir zaman final metin döndürmeyen sağlayıcı — max_tool_rounds aşımını tetikler."""

    def __init__(self) -> None:
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
        return LLMResponse(
            tool_calls=[ToolCall(name="calculator", arguments={"expression": "1 + 1"})]
        )


class _ImmediatelyFailingProvider:
    """generate_with_tools çağrıldığında hemen istisna fırlatan sahte sağlayıcı."""

    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        raise RuntimeError("provider boom")

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append(list(messages))
        raise RuntimeError("provider boom")


class _RecordingExperienceStore:
    """ExperienceStore Protocol'ünü karşılayan, eklenenleri kaydeden bellek-içi sahte depo."""

    def __init__(self) -> None:
        self.added: list[Experience] = []

    def add(self, experience: Experience) -> Experience:
        self.added.append(experience)
        return experience

    def get(self, experience_id: str) -> Experience | None:
        for experience in self.added:
            if experience.id == experience_id:
                return experience
        return None

    def list_by_session(self, session_id: str, *, limit: int = 50) -> list[Experience]:
        return [e for e in self.added if e.session_id == session_id][:limit]

    def list_recent(
        self, *, limit: int = 50, before: datetime | None = None
    ) -> list[Experience]:
        return list(reversed(self.added))[:limit]


class _FailingExperienceStore:
    """ExperienceStore Protocol'ünü karşılayan ama add() sırasında her zaman patlayan depo."""

    def __init__(self) -> None:
        self.attempts: list[Experience] = []

    def add(self, experience: Experience) -> Experience:
        self.attempts.append(experience)
        raise RuntimeError("experience store unavailable")

    def get(self, experience_id: str) -> Experience | None:
        return None

    def list_by_session(self, session_id: str, *, limit: int = 50) -> list[Experience]:
        return []

    def list_recent(
        self, *, limit: int = 50, before: datetime | None = None
    ) -> list[Experience]:
        return []


class _OrderRecordingMemoryService:
    """process_turn() çağrıldığında paylaşılan bir sıra listesine işaret bırakan sahte servis."""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.calls: list[tuple[str, str]] = []

    async def process_turn(self, user_message: str, *, session_id: str) -> None:
        self._order.append("memory")
        self.calls.append((user_message, session_id))


class _OrderRecordingExperienceStore(_RecordingExperienceStore):
    """add() çağrıldığında paylaşılan bir sıra listesine işaret bırakan sahte depo."""

    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order

    def add(self, experience: Experience) -> Experience:
        self._order.append("persist")
        return super().add(experience)


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


def _make_orchestrator(
    *,
    provider,  # type: ignore[no-untyped-def]
    experience_store: ExperienceStore | None = None,
    memory_service: Any | None = None,
) -> ChatOrchestrator:
    registry = build_default_tool_registry()
    return ChatOrchestrator(
        provider=provider,
        conversation_store=InMemoryConversationStore(),
        prompt_loader=_FixedPromptProvider(),
        tool_registry=registry,
        tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
        memory_service=memory_service,
        experience_store=experience_store,
    )


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


# ---------------------------------------------------------------------------
# 1, 13. experience_store verilmediğinde mevcut davranış korunur
# ---------------------------------------------------------------------------


class TestNoExperienceStoreKeepsExistingBehaviour:
    def test_chat_still_works_and_captures_without_a_store(self) -> None:
        provider = _EchoProvider("Merhaba!")
        orchestrator = _make_orchestrator(provider=provider)

        result = _run(orchestrator.respond("selam", "sess-1"))

        assert result.response == "Merhaba!"
        assert orchestrator._experience_store is None
        # Yakalama (Phase 2C) hiçbir depo olmadan da eskisi gibi çalışır.
        assert orchestrator._last_experience is not None
        assert orchestrator._last_experience.user_message == "selam"

    def test_constructor_without_experience_store_defaults_to_none(self) -> None:
        """Mevcut tüm çağıranlar (testler dahil) hiçbir değişiklik yapmadan çalışmaya devam eder."""
        registry = build_default_tool_registry()
        orchestrator = ChatOrchestrator(
            provider=_EchoProvider("ok"),
            conversation_store=InMemoryConversationStore(),
            prompt_loader=_FixedPromptProvider(),
            tool_registry=registry,
            tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
        )

        assert orchestrator._experience_store is None
        assert _run(orchestrator.respond("test", "sess-1")).response == "ok"

    def test_set_experience_store_binds_late(self) -> None:
        """Geç bağlama, mevcut set_memory_service/set_memory_retrieval deseniyle aynıdır."""
        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"))

        _run(orchestrator.respond("bağlanmadan önce", "sess-1"))
        assert store.added == []

        orchestrator.set_experience_store(store)
        _run(orchestrator.respond("bağlandıktan sonra", "sess-1"))

        assert len(store.added) == 1
        assert store.added[0].user_message == "bağlandıktan sonra"


# ---------------------------------------------------------------------------
# 2-4. Başarılı tur: tam olarak bir kayıt, AYNI nesne, AYNI kimlik
# ---------------------------------------------------------------------------


class TestSuccessfulTurnPersistsExactlyOnce:
    def test_persists_exactly_one_experience(self) -> None:
        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        _run(orchestrator.respond("test", "sess-1"))

        assert len(store.added) == 1

    def test_persisted_object_is_the_same_object_as_last_experience(self) -> None:
        """İkinci bir Experience inşa edilmediğinin kanıtı — nesne kimliği aynıdır."""
        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        _run(orchestrator.respond("test", "sess-1"))

        assert store.added[0] is orchestrator._last_experience

    def test_persisted_id_equals_last_experience_id(self) -> None:
        """İkinci bir kimlik üretilmediğinin kanıtı."""
        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        _run(orchestrator.respond("test", "sess-1"))

        assert orchestrator._last_experience is not None
        assert store.added[0].id == orchestrator._last_experience.id

    def test_last_experience_survives_persistence(self) -> None:
        """Kalıcılaştırma `_last_experience`'ın YERİNİ ALMAZ — ikisi birlikte var olur."""
        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        _run(orchestrator.respond("test", "sess-1"))

        assert isinstance(orchestrator._last_experience, Experience)

    def test_each_successful_turn_persists_its_own_experience(self) -> None:
        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        _run(orchestrator.respond("birinci", "sess-1"))
        _run(orchestrator.respond("ikinci", "sess-1"))

        assert [e.user_message for e in store.added] == ["birinci", "ikinci"]
        assert store.added[0].id != store.added[1].id


# ---------------------------------------------------------------------------
# 5. Tool-call'lı tur da tam olarak bir Experience kalıcılaştırır
# ---------------------------------------------------------------------------


class TestToolCallTurnPersistsExactlyOnce:
    def test_multi_round_tool_turn_persists_one_experience(self) -> None:
        store = _RecordingExperienceStore()
        provider = _MultiRoundToolCallingProvider()
        orchestrator = _make_orchestrator(provider=provider, experience_store=store)

        _run(orchestrator.respond("Saat kaç ve 2+3 kaç eder?", "sess-1"))

        assert len(store.added) == 1

    def test_persisted_experience_keeps_deterministic_tool_call_names(self) -> None:
        """Kalıcılaştırma sırasında tool call'lar YENİDEN AYRIŞTIRILMAZ — yakalanan
        Experience'ın zaten taşıdığı deterministik isimler olduğu gibi saklanır."""
        store = _RecordingExperienceStore()
        provider = _MultiRoundToolCallingProvider()
        orchestrator = _make_orchestrator(provider=provider, experience_store=store)

        _run(orchestrator.respond("Saat kaç ve 2+3 kaç eder?", "sess-1"))

        assert store.added[0].tool_calls == ["get_time", "calculator"]
        assert store.added[0] is orchestrator._last_experience


# ---------------------------------------------------------------------------
# 6-7. Başarısız turlar hiçbir şey kalıcılaştırmaz
# ---------------------------------------------------------------------------


class TestFailedTurnPersistsNothing:
    def test_provider_exception_persists_nothing(self) -> None:
        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(
            provider=_ImmediatelyFailingProvider(), experience_store=store
        )

        with pytest.raises(RuntimeError, match="provider boom"):
            _run(orchestrator.respond("test", "sess-1"))

        assert store.added == []
        assert orchestrator._last_experience is None

    def test_max_tool_rounds_exceeded_persists_nothing(self) -> None:
        from app.adapters.llm.base import LLMResponseError

        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(
            provider=_AlwaysToolCallingProvider(), experience_store=store
        )

        with pytest.raises(LLMResponseError):
            _run(orchestrator.respond("test", "sess-1"))

        assert store.added == []
        assert orchestrator._last_experience is None

    def test_empty_provider_response_persists_nothing(self) -> None:
        """Orchestrator'ın boş-cevap koruması (LLMResponseError) da hiçbir şey
        kalıcılaştırmamalı.

        Not: LLMResponse modeli boş/yalnızca-boşluk içeriği zaten kendi
        doğrulamasında reddeder (app/core/chat.py), bu yüzden orchestrator'ın
        kendi koruması ancak doğrulamayı atlayan bozuk bir sağlayıcıyla
        tetiklenebilir — burada model_construct() ile tam olarak bu durum
        taklit edilir.
        """
        from app.adapters.llm.base import LLMResponseError

        class _MalformedProvider:
            def __init__(self) -> None:
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
                return LLMResponse.model_construct(content="   ", tool_calls=[])

        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_MalformedProvider(), experience_store=store)

        with pytest.raises(LLMResponseError):
            _run(orchestrator.respond("test", "sess-1"))

        assert store.added == []
        assert orchestrator._last_experience is None

    def test_earlier_persisted_experience_is_not_rewritten_by_a_later_failed_turn(self) -> None:
        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)
        _run(orchestrator.respond("başarılı", "sess-1"))
        assert len(store.added) == 1

        orchestrator._provider = _ImmediatelyFailingProvider()  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError):
            _run(orchestrator.respond("başarısız", "sess-1"))

        assert len(store.added) == 1


# ---------------------------------------------------------------------------
# 8-9. Kalıcılaştırma hatası tamamen izole edilir
# ---------------------------------------------------------------------------


class TestPersistenceFailureIsIsolated:
    def test_store_failure_does_not_break_chat_result(self) -> None:
        store = _FailingExperienceStore()
        orchestrator = _make_orchestrator(
            provider=_EchoProvider("Yine de çalışıyor."), experience_store=store
        )

        result = _run(orchestrator.respond("test", "sess-1"))

        assert result.response == "Yine de çalışıyor."
        assert result.session_id == "sess-1"
        assert len(store.attempts) == 1

    def test_store_failure_leaves_last_experience_valid(self) -> None:
        """Kalıcılaştırma `_last_experience` güncellendikten SONRA çalıştığı için
        buradaki bir hata geçerli bellek-içi Experience'ı geçersizleştiremez."""
        store = _FailingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        _run(orchestrator.respond("test", "sess-1"))

        experience = orchestrator._last_experience
        assert isinstance(experience, Experience)
        assert experience.user_message == "test"
        assert experience.assistant_response == "ok"

    def test_store_failure_does_not_affect_subsequent_turns(self) -> None:
        store = _FailingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        first = _run(orchestrator.respond("birinci", "sess-1"))
        second = _run(orchestrator.respond("ikinci", "sess-1"))

        assert first.response == "ok"
        assert second.response == "ok"
        assert len(store.attempts) == 2

    def test_store_failure_does_not_affect_conversation_history(self) -> None:
        store = _FailingExperienceStore()
        conversation_store = InMemoryConversationStore()
        registry = build_default_tool_registry()
        orchestrator = ChatOrchestrator(
            provider=_EchoProvider("ok"),
            conversation_store=conversation_store,
            prompt_loader=_FixedPromptProvider(),
            tool_registry=registry,
            tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
            experience_store=store,
        )

        _run(orchestrator.respond("test", "sess-1"))

        conversation = conversation_store.get_or_create("sess-1")
        assert [m.role for m in conversation.messages] == ["user", "assistant"]


# ---------------------------------------------------------------------------
# 10. Builder hatası ÖNCEKİ Experience'ı yeniden yazmaya çalışmaz
# ---------------------------------------------------------------------------


class TestBuilderFailureDoesNotPersistStaleExperience:
    def test_builder_failure_persists_nothing_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.services.orchestrator as orchestrator_module

        def _raising_builder(**kwargs: object) -> Experience:
            raise RuntimeError("builder boom")

        monkeypatch.setattr(orchestrator_module, "build_experience_from_turn", _raising_builder)

        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        result = _run(orchestrator.respond("test", "sess-1"))

        assert result.response == "ok"
        assert store.added == []

    def test_builder_failure_does_not_repersist_the_previous_experience(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Kalıcılaştırma adımı `_last_experience`'ı OKUMAZ; yakalamanın dönüş
        değerini kullanır. Aksi halde builder patladığında bir önceki turun
        Experience'ı ikinci kez — yinelenen kimlikle — yazılmaya çalışılırdı."""
        import app.services.orchestrator as orchestrator_module

        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        _run(orchestrator.respond("birinci", "sess-1"))
        first_experience = orchestrator._last_experience
        assert first_experience is not None
        assert len(store.added) == 1

        def _raising_builder(**kwargs: object) -> Experience:
            raise RuntimeError("builder boom")

        monkeypatch.setattr(orchestrator_module, "build_experience_from_turn", _raising_builder)
        result = _run(orchestrator.respond("ikinci", "sess-1"))

        assert result.response == "ok"
        # Hiçbir yeni kayıt yok ve önceki kayıt yeniden yazılmaya çalışılmadı.
        assert len(store.added) == 1
        assert store.added[0] is first_experience
        # Bellek-içi önceki Experience de korunmuş olmalı (Phase 2C davranışı).
        assert orchestrator._last_experience is first_experience


# ---------------------------------------------------------------------------
# 11. Sağlayıcı/tool çağrı sayıları değişmedi
# ---------------------------------------------------------------------------


class TestProviderAndToolCallCountsUnchanged:
    def test_simple_turn_still_makes_exactly_one_provider_call(self) -> None:
        provider = _EchoProvider("ok")
        orchestrator = _make_orchestrator(
            provider=provider, experience_store=_RecordingExperienceStore()
        )

        _run(orchestrator.respond("test", "sess-1"))

        assert len(provider.calls) == 1

    def test_multi_round_tool_turn_still_makes_exactly_three_provider_calls(self) -> None:
        provider = _MultiRoundToolCallingProvider()
        orchestrator = _make_orchestrator(
            provider=provider, experience_store=_RecordingExperienceStore()
        )

        _run(orchestrator.respond("test", "sess-1"))

        assert len(provider.calls) == 3

    def test_failing_store_does_not_change_provider_call_count(self) -> None:
        provider = _EchoProvider("ok")
        orchestrator = _make_orchestrator(
            provider=provider, experience_store=_FailingExperienceStore()
        )

        _run(orchestrator.respond("test", "sess-1"))

        assert len(provider.calls) == 1


# ---------------------------------------------------------------------------
# 12. Bellek işleme kalıcılaştırmadan ÖNCE çalışır
# ---------------------------------------------------------------------------


class TestMemoryProcessingHappensBeforePersistence:
    def test_memory_runs_before_experience_persistence(self) -> None:
        order: list[str] = []
        memory_service = _OrderRecordingMemoryService(order)
        store = _OrderRecordingExperienceStore(order)
        orchestrator = _make_orchestrator(
            provider=_EchoProvider("ok"),
            experience_store=store,
            memory_service=memory_service,
        )

        _run(orchestrator.respond("test", "sess-1"))

        assert order == ["memory", "persist"]

    def test_memory_processing_still_receives_the_same_arguments(self) -> None:
        """Bellek işleme davranışı bu fazda hiç değişmedi."""
        order: list[str] = []
        memory_service = _OrderRecordingMemoryService(order)
        orchestrator = _make_orchestrator(
            provider=_EchoProvider("ok"),
            experience_store=_RecordingExperienceStore(),
            memory_service=memory_service,
        )

        _run(orchestrator.respond("bellek mesajı", "sess-1"))

        assert memory_service.calls == [("bellek mesajı", "sess-1")]

    def test_persistence_still_happens_without_a_memory_service(self) -> None:
        store = _RecordingExperienceStore()
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        _run(orchestrator.respond("test", "sess-1"))

        assert orchestrator._memory_service is None
        assert len(store.added) == 1


# ---------------------------------------------------------------------------
# 14. Orchestrator somut SQLite implementasyonuna atıf yapmaz
# ---------------------------------------------------------------------------


class TestOrchestratorDependsOnlyOnTheProtocol:
    def test_orchestrator_source_does_not_reference_sqlite_experience_store(self) -> None:
        """ChatOrchestrator yalnızca ExperienceStore Protocol'üne bağımlı olmalı;
        somut depolama implementasyonu (SQLite vb.) bu katmana hiç sızmamalı."""
        import app.services.orchestrator as orchestrator_module

        source = inspect.getsource(orchestrator_module)
        assert "SQLiteExperienceStore" not in source
        # Somut depo modülü hiç import edilmemeli (mevcut MemoryTemporalService
        # izolasyon testiyle aynı kaynak-tarama yaklaşımı).
        assert "sqlite_experience_store" not in source

    def test_orchestrator_accepts_any_protocol_compatible_store(self) -> None:
        """Sahte, tamamen bellek-içi bir depo hiçbir uyarlama olmadan çalışır."""
        store = _RecordingExperienceStore()
        assert isinstance(store, ExperienceStore)

        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)
        _run(orchestrator.respond("test", "sess-1"))

        assert len(store.added) == 1


# ---------------------------------------------------------------------------
# 15. assistant_response=None kalıcılaştırma hatası güvenle izole edilir
# ---------------------------------------------------------------------------


class TestNullAssistantResponseIsIsolated:
    def test_none_assistant_response_persistence_failure_does_not_break_chat(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Experience modeli `assistant_response: str | None` iken `experiences`
        tablosundaki sütun NOT NULL'dur.

        Üretim akışında bu uyuşmazlık TETİKLENEMEZ: respond() yalnızca boş
        olmayan bir final cevaptan sonra yakalama yapar ve
        build_experience_from_turn() parametreyi zorunlu `str` olarak alır. Bu
        test, o üretim garantisini kasıtlı olarak devre dışı bırakarak sınırın
        güvenli tarafta kaldığını belgeler: SQLite bir IntegrityError fırlatır,
        hata yutulur, sohbet cevabı bozulmaz.

        Bu yüzden ne Experience modeli ne de şema değiştirilmemiştir.
        """
        import app.services.orchestrator as orchestrator_module

        def _null_response_builder(**kwargs: object) -> Experience:
            return Experience(
                session_id=str(kwargs["session_id"]),
                occurred_at=datetime.now(UTC),
                user_message=str(kwargs["user_message"]),
                assistant_response=None,
            )

        monkeypatch.setattr(
            orchestrator_module, "build_experience_from_turn", _null_response_builder
        )

        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        orchestrator = _make_orchestrator(
            provider=_EchoProvider("Sohbet bozulmadı."), experience_store=store
        )

        result = _run(orchestrator.respond("test", "sess-1"))

        assert result.response == "Sohbet bozulmadı."
        # Kayıt yazılamadı (NOT NULL kısıtı) ama sohbet etkilenmedi.
        assert store.count() == 0
        # Bellek-içi Experience yine de geçerli kaldı.
        assert orchestrator._last_experience is not None
        assert orchestrator._last_experience.assistant_response is None

    def test_store_level_null_assistant_response_raises_integrity_error(
        self, tmp_path: Path
    ) -> None:
        """Depo seviyesinde davranış açıkça bir hata olmalı — sessizce boş metne
        dönüştürülmemeli."""
        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        experience = Experience(
            session_id="sess-1",
            occurred_at=datetime.now(UTC),
            user_message="test",
            assistant_response=None,
        )

        with pytest.raises(sqlite3.IntegrityError):
            store.add(experience)


# ---------------------------------------------------------------------------
# 16-17. Gerçek SQLiteExperienceStore ile uçtan uca
# ---------------------------------------------------------------------------


class TestRealSQLiteRoundTrip:
    def test_successful_turn_round_trips_through_real_sqlite(self, tmp_path: Path) -> None:
        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        orchestrator = _make_orchestrator(
            provider=_EchoProvider("Merhaba! Nasıl yardımcı olabilirim?"),
            experience_store=store,
        )

        _run(orchestrator.respond("Merhaba Jarvis", "sess-1"))

        assert store.count() == 1
        captured = orchestrator._last_experience
        assert captured is not None
        fetched = store.get(captured.id)
        assert fetched is not None
        assert fetched.id == captured.id
        assert fetched.session_id == "sess-1"
        assert fetched.user_message == "Merhaba Jarvis"
        assert fetched.assistant_response == "Merhaba! Nasıl yardımcı olabilirim?"
        assert fetched.tool_calls == []
        assert fetched.user_state is None
        assert fetched.emotional_context is None
        assert fetched.outcome is ExperienceOutcome.UNKNOWN
        assert fetched.derived_memory_ids == []

    def test_multi_round_tool_turn_produces_exactly_one_sqlite_row(
        self, tmp_path: Path
    ) -> None:
        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        orchestrator = _make_orchestrator(
            provider=_MultiRoundToolCallingProvider(), experience_store=store
        )

        _run(orchestrator.respond("Saat kaç ve 2+3 kaç eder?", "sess-1"))

        assert store.count() == 1
        stored = store.list_by_session("sess-1")
        assert len(stored) == 1
        assert stored[0].tool_calls == ["get_time", "calculator"]

    def test_successive_turns_accumulate_in_session_order(self, tmp_path: Path) -> None:
        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        _run(orchestrator.respond("birinci", "sess-1"))
        _run(orchestrator.respond("ikinci", "sess-1"))

        assert store.count() == 2
        stored = store.list_by_session("sess-1")
        assert [e.user_message for e in stored] == ["birinci", "ikinci"]


# ---------------------------------------------------------------------------
# 18. Yinelenen kimlik mevcut IntegrityError davranışını izler
# ---------------------------------------------------------------------------


class TestDuplicateIdBehaviour:
    def test_adding_the_same_experience_twice_raises_integrity_error(
        self, tmp_path: Path
    ) -> None:
        """Düz INSERT davranışı korunur: yinelenen kimlik bir programlama
        hatasıdır ve görünür kalmalıdır (INSERT OR IGNORE kullanılmaz)."""
        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        experience = Experience(
            session_id="sess-1",
            occurred_at=datetime.now(UTC),
            user_message="test",
            assistant_response="ok",
        )

        store.add(experience)
        with pytest.raises(sqlite3.IntegrityError):
            store.add(experience)

        assert store.count() == 1

    def test_duplicate_id_through_the_orchestrator_is_logged_not_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Yinelenen kimlik depo seviyesinde patlar, ancak orchestrator'ın güvenli
        sarmalayıcısı bunu yutar — başarılı bir sohbet cevabı asla bozulmaz."""
        import app.services.orchestrator as orchestrator_module

        fixed_experience = Experience(
            id="fixed-duplicate-id",
            session_id="sess-1",
            occurred_at=datetime.now(UTC),
            user_message="test",
            assistant_response="ok",
        )

        def _fixed_builder(**kwargs: object) -> Experience:
            return fixed_experience

        monkeypatch.setattr(orchestrator_module, "build_experience_from_turn", _fixed_builder)

        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"), experience_store=store)

        first = _run(orchestrator.respond("birinci", "sess-1"))
        second = _run(orchestrator.respond("ikinci", "sess-1"))

        assert first.response == "ok"
        assert second.response == "ok"
        # İkinci INSERT reddedildi; tek fiziksel kayıt kaldı.
        assert store.count() == 1


# ---------------------------------------------------------------------------
# 19-20. Aynı veritabanı dosyasında birlikte var olma
# ---------------------------------------------------------------------------


class TestSharedDatabaseFile:
    def test_memory_and_experience_stores_coexist_on_the_same_file(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "memory.db"
        memory_store = SQLiteMemoryStore(str(db_path))
        experience_store = SQLiteExperienceStore(str(db_path))
        memory_store.add(MemoryRecord(content="The user lives in Istanbul."))

        orchestrator = _make_orchestrator(
            provider=_EchoProvider("ok"), experience_store=experience_store
        )
        _run(orchestrator.respond("test", "sess-1"))

        # İki bağımsız şema aynı dosyada birbirini bozmadan yaşar.
        assert experience_store.count() == 1
        assert memory_store.count() == 1
        assert memory_store.list_active()[0].content == "The user lives in Istanbul."

    def test_no_second_database_file_is_created(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        SQLiteMemoryStore(str(db_path))
        experience_store = SQLiteExperienceStore(str(db_path))

        orchestrator = _make_orchestrator(
            provider=_EchoProvider("ok"), experience_store=experience_store
        )
        _run(orchestrator.respond("test", "sess-1"))

        assert [p.name for p in tmp_path.glob("*.db")] == ["memory.db"]


# ---------------------------------------------------------------------------
# 21-24. Uygulama (create_app/lifespan) seviyesinde bağlama
# ---------------------------------------------------------------------------


class TestApplicationWiring:
    def test_create_app_alone_does_not_build_the_experience_store(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)

        app = create_app(settings=settings)

        assert app.state.experience_store is None
        assert app.state.chat_orchestrator._experience_store is None

    def test_default_provider_auto_wires_sqlite_experience_store_on_startup(
        self, tmp_path: Path
    ) -> None:
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            store = app.state.experience_store
            assert isinstance(store, SQLiteExperienceStore)
            assert app.state.chat_orchestrator._experience_store is store

    def test_auto_wired_store_uses_the_configured_memory_db_path(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            store = app.state.experience_store
            assert store._db_path == settings.memory_db_path
            # Bellek deposuyla AYNI fiziksel dosya — ikinci bir veritabanı yok.
            assert store._db_path == app.state.memory_store._db_path
            assert [p.name for p in tmp_path.glob("*.db")] == ["memory.db"]

    def test_explicit_experience_store_prevents_auto_wiring(self, tmp_path: Path) -> None:
        custom_store = _RecordingExperienceStore()
        settings = _make_settings(tmp_path)

        app = create_app(settings=settings, experience_store=custom_store)

        assert app.state.experience_store is custom_store
        assert app.state.chat_orchestrator._experience_store is custom_store

        with TestClient(app):
            assert app.state.experience_store is custom_store
            assert app.state.chat_orchestrator._experience_store is custom_store

    def test_injected_provider_prevents_experience_store_creation(self, tmp_path: Path) -> None:
        """Sahte sağlayıcı enjekte eden testler, uygulamayı başlatsalar bile
        kullanıcının kalıcı veritabanına dokunmamalı."""
        db_path = tmp_path / "should_not_exist.db"
        settings = _make_settings(tmp_path, memory_db_path=str(db_path))
        app = create_app(settings=settings, provider=_FakeChatProvider())

        with TestClient(app):
            assert app.state.experience_store is None
            assert app.state.chat_orchestrator._experience_store is None

        assert not db_path.exists()

    def test_experience_wiring_is_independent_of_memory_wiring(self, tmp_path: Path) -> None:
        """Çağıran bellek yığınını elle verdiğinde Experience kalıcılaştırması
        sessizce kapanmamalı — iki sınır birbirinden bağımsızdır."""
        from app.memory.extractor import MemoryExtractor
        from app.services.memory_service import MemoryWriteService

        settings = _make_settings(tmp_path)
        custom_memory_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeChatProvider()),
            store=SQLiteMemoryStore(str(tmp_path / "custom.db")),
        )

        # provider enjekte edilmiyor (üretim yolu) — yalnızca memory_service verildi.
        app = create_app(settings=settings, memory_service=custom_memory_service)

        with TestClient(app):
            # Bellek otomatik kurulumu devre dışı ...
            assert app.state.memory_retrieval is None
            # ... ama Experience kalıcılaştırması yine de kuruldu.
            assert isinstance(app.state.experience_store, SQLiteExperienceStore)

    def test_chat_request_through_the_app_persists_one_experience(
        self, tmp_path: Path
    ) -> None:
        """Gerçek bir /api/chat isteği, enjekte edilen depoya tam olarak bir
        Experience yazar ve cevabı hiç etkilemez."""
        store = _RecordingExperienceStore()
        settings = _make_settings(tmp_path)
        app = create_app(
            settings=settings,
            provider=_FakeChatProvider("Jarvis: Merhaba!"),
            experience_store=store,
        )

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "Merhaba"})

        assert response.status_code == 200
        assert response.json()["response"] == "Jarvis: Merhaba!"
        assert len(store.added) == 1
        assert store.added[0].user_message == "Merhaba"
        assert store.added[0].session_id == response.json()["session_id"]

    def test_chat_request_survives_a_failing_experience_store(self, tmp_path: Path) -> None:
        store = _FailingExperienceStore()
        settings = _make_settings(tmp_path)
        app = create_app(
            settings=settings,
            provider=_FakeChatProvider("Jarvis: hâlâ ayakta."),
            experience_store=store,
        )

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "Merhaba"})

        assert response.status_code == 200
        assert response.json()["response"] == "Jarvis: hâlâ ayakta."
        assert len(store.attempts) == 1


# ---------------------------------------------------------------------------
# 25. Import-time güvenliği
# ---------------------------------------------------------------------------


class TestImportTimeSafety:
    def test_importing_app_main_does_not_create_the_experience_database(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`app.main`'i import etmek (modül seviyesindeki `app = create_app()` dahil)
        Experience veritabanını asla oluşturmamalı; SQLiteExperienceStore yalnızca
        uygulama fiilen başlatıldığında (lifespan) kurulur."""
        db_path = tmp_path / "import_side_effect.db"
        monkeypatch.setenv("JARVIS_MEMORY_DB_PATH", str(db_path))
        monkeypatch.setenv("JARVIS_ENVIRONMENT", "test")
        get_settings.cache_clear()

        import app.main as main_module

        try:
            importlib.reload(main_module)

            assert not db_path.exists()
            assert main_module.app.state.experience_store is None

            with TestClient(main_module.app):
                assert db_path.exists()
                assert isinstance(
                    main_module.app.state.experience_store, SQLiteExperienceStore
                )
        finally:
            get_settings.cache_clear()
            importlib.reload(main_module)

    def test_reimporting_orchestrator_module_has_no_side_effects(self) -> None:
        """Orchestrator yalnızca saf ExperienceStore Protocol modülünü import eder;
        somut SQLite implementasyonunu değil. Bu yüzden modülü yeniden yüklemek
        hiçbir dosya sistemi/SQLite etkisi doğurmaz."""
        import app.services.orchestrator as orchestrator_module

        reloaded = importlib.reload(orchestrator_module)

        assert reloaded.ChatOrchestrator is not None
        assert "sqlite_experience_store" not in inspect.getsource(reloaded)
