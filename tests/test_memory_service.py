"""Phase 1B-2 — MemoryWriteService ve ChatOrchestrator entegrasyon test suite.

Kapsam:
 1. Tek bellek başarıyla çıkarılır ve depolanır
 2. Birden fazla bellek depolanır
 3. Bellek yoksa hiçbir yazma olmaz
 4. Çıkarma hatası sohbeti bozmaz (servis seviyesi)
 5. Depolama hatası sohbeti bozmaz (servis seviyesi)
 6. session_id doğru şekilde yayılır
 7. Kayıtlar MemoryStore Protocol üzerinden kalıcı hale getirilir
 8. ChatOrchestrator, SQLiteMemoryStore'a değil servise bağımlıdır
 9. Bellek üretmeyen turlarda mevcut davranış değişmez
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.adapters.llm.base import LLMUnavailableError
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.memory.extractor import MemoryExtractor
from app.memory.record import MemoryRecord
from app.memory.store import MemoryStore
from app.services.memory_service import MemoryWriteResult, MemoryWriteService

import app.services.orchestrator as orchestrator_module
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


def _json_response(memories: list[dict[str, Any]]) -> str:
    return json.dumps({"memories": memories})


class _FakeLLMProvider:
    """Sabit bir JSON yanıtı döndüren sahte LLM sağlayıcısı (MemoryExtractor için)."""

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


class _FailingLLMProvider:
    """generate() çağrısında LLMUnavailableError fırlatan sahte sağlayıcı."""

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        raise LLMUnavailableError("Fake LLM unavailable")

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        raise LLMUnavailableError("Fake LLM unavailable")


class _RaisingExtractor:
    """extract() çağrısında her zaman beklenmedik bir hata fırlatan sahte extractor."""

    async def extract(self, user_message: str, *, session_id: str | None = None):
        raise RuntimeError("extractor boom")


class _InMemoryFakeStore:
    """MemoryStore Protocol'ünü karşılayan, SQLite kullanmayan basit RAM store'u.

    Amaç: MemoryWriteService ve ChatOrchestrator'ın somut SQLiteMemoryStore'a
    değil, yalnızca MemoryStore Protocol'üne bağımlı olduğunu kanıtlamak.
    """

    def __init__(self, *, fail_on_add: bool = False) -> None:
        self.records: dict[str, MemoryRecord] = {}
        self._fail_on_add = fail_on_add

    def add(self, record: MemoryRecord) -> MemoryRecord:
        if self._fail_on_add:
            raise RuntimeError("store unavailable")
        self.records[record.id] = record
        return record

    def update(self, record: MemoryRecord) -> MemoryRecord:
        self.records[record.id] = record
        return record

    def invalidate(self, memory_id: str, *, at=None) -> bool:
        return memory_id in self.records

    def delete(self, memory_id: str, *, at=None) -> bool:
        return memory_id in self.records

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self.records.get(memory_id)

    def list_active(self, **kwargs: Any) -> list[MemoryRecord]:
        return list(self.records.values())

    def list_by_session(self, session_id: str, *, include_invalidated: bool = False) -> list[MemoryRecord]:
        return [r for r in self.records.values() if r.source_session_id == session_id]

    def search(self, query: str, **kwargs: Any) -> list[MemoryRecord]:
        return []


def _make_extractor(response: str) -> MemoryExtractor:
    return MemoryExtractor(provider=_FakeLLMProvider(response))


# ---------------------------------------------------------------------------
# 1. Tek bellek başarıyla çıkarılır ve depolanır
# ---------------------------------------------------------------------------


class TestSuccessfulPersistence:
    def test_single_memory_is_extracted_and_stored(self) -> None:
        response = _json_response([
            {
                "memory_type": "fact",
                "content": "The user lives in Istanbul.",
                "temporality": "present",
                "status": "active",
            }
        ])
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_make_extractor(response), store=store)

        result = _run(service.process_turn("I live in Istanbul.", session_id="s1"))

        assert isinstance(result, MemoryWriteResult)
        assert result.ok is True
        assert result.stored_count == 1
        assert result.rejected_count == 0
        assert len(store.records) == 1
        stored = next(iter(store.records.values()))
        assert stored.content == "The user lives in Istanbul."
        assert stored.source_session_id == "s1"


# ---------------------------------------------------------------------------
# 2. Birden fazla bellek depolanır
# ---------------------------------------------------------------------------


class TestMultiplePersistence:
    def test_multiple_memories_are_all_stored(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "User lives in Ankara.", "temporality": "present", "status": "active"},
            {"memory_type": "preference", "content": "User prefers tea over coffee.", "temporality": "present", "status": "active"},
            {"memory_type": "goal", "content": "User wants to learn Spanish.", "temporality": "future", "status": "planned"},
        ])
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_make_extractor(response), store=store)

        result = _run(service.process_turn("Ankara, tea, Spanish.", session_id="s1"))

        assert result.stored_count == 3
        assert len(store.records) == 3
        contents = {r.content for r in store.records.values()}
        assert "User lives in Ankara." in contents
        assert "User prefers tea over coffee." in contents
        assert "User wants to learn Spanish." in contents


# ---------------------------------------------------------------------------
# 3. Bellek yoksa hiçbir yazma olmaz
# ---------------------------------------------------------------------------


class TestNoMemoriesNoWrites:
    def test_empty_extraction_writes_nothing(self) -> None:
        response = _json_response([])
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_make_extractor(response), store=store)

        result = _run(service.process_turn("Merhaba! Nasılsın?", session_id="s1"))

        assert result.stored_count == 0
        assert result.ok is True
        assert store.records == {}

    def test_question_produces_no_writes(self) -> None:
        response = _json_response([])
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_make_extractor(response), store=store)

        result = _run(service.process_turn("What is the capital of France?", session_id="s1"))

        assert result.stored_count == 0
        assert store.records == {}


# ---------------------------------------------------------------------------
# 4. Çıkarma hatası sohbeti bozmaz (servis seviyesi)
# ---------------------------------------------------------------------------


class TestExtractionFailureIsolated:
    def test_extractor_raising_unexpectedly_does_not_propagate(self) -> None:
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_RaisingExtractor(), store=store)  # type: ignore[arg-type]

        result = _run(service.process_turn("test", session_id="s1"))

        assert isinstance(result, MemoryWriteResult)
        assert result.extraction_failed is True
        assert result.ok is False
        assert result.stored_count == 0
        assert store.records == {}

    def test_llm_unavailable_marks_extraction_failed_without_raising(self) -> None:
        store = _InMemoryFakeStore()
        extractor = MemoryExtractor(provider=_FailingLLMProvider())
        service = MemoryWriteService(extractor=extractor, store=store)

        result = _run(service.process_turn("I live in Paris.", session_id="s1"))

        assert result.extraction_failed is True
        assert result.stored_count == 0
        assert store.records == {}


# ---------------------------------------------------------------------------
# 5. Depolama hatası sohbeti bozmaz (servis seviyesi)
# ---------------------------------------------------------------------------


class TestStoreFailureIsolated:
    def test_store_add_raising_is_isolated_and_reported(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "User uses Linux.", "temporality": "present", "status": "active"}
        ])
        store = _InMemoryFakeStore(fail_on_add=True)
        service = MemoryWriteService(extractor=_make_extractor(response), store=store)

        result = _run(service.process_turn("I use Linux.", session_id="s1"))

        assert isinstance(result, MemoryWriteResult)  # hata fırlatılmadı
        assert result.store_failed is True
        assert result.ok is False
        assert result.stored_count == 0

    def test_partial_store_failure_still_reports_successful_writes(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "First fact here.", "temporality": "present", "status": "active"},
            {"memory_type": "fact", "content": "Second fact here.", "temporality": "present", "status": "active"},
        ])
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_make_extractor(response), store=store)

        # İlk add başarılı, ikincisi hataya düşecek şekilde store'u sonradan bozuyoruz.
        original_add = store.add
        call_count = {"n": 0}

        def _flaky_add(record: MemoryRecord) -> MemoryRecord:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("second write fails")
            return original_add(record)

        store.add = _flaky_add  # type: ignore[method-assign]

        result = _run(service.process_turn("test", session_id="s1"))

        assert result.stored_count == 1
        assert result.store_failed is True
        assert len(store.records) == 1


# ---------------------------------------------------------------------------
# 6. session_id doğru şekilde yayılır
# ---------------------------------------------------------------------------


class TestSessionIdPropagation:
    def test_session_id_flows_to_stored_records(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "User works remotely.", "temporality": "present", "status": "active"}
        ])
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_make_extractor(response), store=store)

        _run(service.process_turn("I work remotely.", session_id="sess-42"))

        stored = next(iter(store.records.values()))
        assert stored.source_session_id == "sess-42"

    def test_no_session_id_leaves_field_none(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "User works remotely.", "temporality": "present", "status": "active"}
        ])
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_make_extractor(response), store=store)

        _run(service.process_turn("I work remotely."))

        stored = next(iter(store.records.values()))
        assert stored.source_session_id is None


# ---------------------------------------------------------------------------
# 7. Kayıtlar MemoryStore Protocol üzerinden kalıcı hale getirilir
# ---------------------------------------------------------------------------


class TestPersistedThroughMemoryStoreProtocol:
    def test_fake_store_satisfies_memory_store_protocol(self) -> None:
        store = _InMemoryFakeStore()
        assert isinstance(store, MemoryStore)

    def test_real_sqlite_store_receives_records_through_service(self, tmp_path) -> None:
        """Servis, gerçek SQLiteMemoryStore ile de (Protocol üzerinden) çalışmalı."""
        from app.memory.sqlite_store import SQLiteMemoryStore

        response = _json_response([
            {"memory_type": "fact", "content": "User is a backend developer.", "temporality": "present", "status": "active"}
        ])
        real_store = SQLiteMemoryStore(str(tmp_path / "memory.db"))
        service = MemoryWriteService(extractor=_make_extractor(response), store=real_store)

        result = _run(service.process_turn("I'm a backend developer.", session_id="s1"))

        assert result.stored_count == 1
        assert real_store.count() == 1


# ---------------------------------------------------------------------------
# 8-9. ChatOrchestrator entegrasyonu
# ---------------------------------------------------------------------------


class _FixedPromptProvider:
    def __init__(self, prompt: str) -> None:
        self._prompt = prompt

    def load(self) -> str:
        return self._prompt


class _EchoProvider:
    """generate_with_tools için sabit bir metin cevabı döndüren basit provider."""

    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        return self._reply

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        return LLMResponse(content=self._reply)


def _make_orchestrator(
    *,
    memory_service: MemoryWriteService | None = None,
    provider: Any = None,
) -> ChatOrchestrator:
    registry = build_default_tool_registry()
    return ChatOrchestrator(
        provider=provider or _EchoProvider("Merhaba!"),
        conversation_store=InMemoryConversationStore(),
        prompt_loader=_FixedPromptProvider("sys"),
        tool_registry=registry,
        tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
        memory_service=memory_service,
    )


class TestOrchestratorDecoupledFromSQLite:
    def test_orchestrator_module_does_not_reference_sqlite_store(self) -> None:
        """ChatOrchestrator kaynak kodu SQLiteMemoryStore'a hiç değinmemeli."""
        source = inspect.getsource(orchestrator_module)
        assert "SQLiteMemoryStore" not in source
        assert "sqlite_store" not in source
        assert "import sqlite3" not in source

    def test_orchestrator_persists_memories_via_non_sqlite_store(self) -> None:
        """Orchestrator, SQLite olmayan bir MemoryStore ile de sorunsuz çalışmalı."""
        response = _json_response([
            {"memory_type": "fact", "content": "User codes in Python.", "temporality": "present", "status": "active"}
        ])
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_make_extractor(response), store=store)
        orchestrator = _make_orchestrator(memory_service=service)

        result = _run(orchestrator.respond("I code in Python.", "sess-x"))

        assert result.response == "Merhaba!"
        assert len(store.records) == 1
        stored = next(iter(store.records.values()))
        assert stored.source_session_id == "sess-x"


class TestMemoryFailureIsolatedFromChatResponse:
    def test_extraction_failure_does_not_break_chat_response(self) -> None:
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_RaisingExtractor(), store=store)  # type: ignore[arg-type]
        orchestrator = _make_orchestrator(memory_service=service)

        result = _run(orchestrator.respond("Merhaba", "sess-y"))

        assert result.response == "Merhaba!"
        assert result.session_id == "sess-y"
        assert store.records == {}

    def test_store_failure_does_not_break_chat_response(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "User owns a cat.", "temporality": "present", "status": "active"}
        ])
        store = _InMemoryFakeStore(fail_on_add=True)
        service = MemoryWriteService(extractor=_make_extractor(response), store=store)
        orchestrator = _make_orchestrator(memory_service=service)

        result = _run(orchestrator.respond("I have a cat.", "sess-z"))

        assert result.response == "Merhaba!"
        assert store.records == {}

    def test_conversation_history_still_updated_when_memory_fails(self) -> None:
        """Bellek katmanı çökse bile konuşma geçmişi bozulmadan güncellenmeli."""
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_RaisingExtractor(), store=store)  # type: ignore[arg-type]
        conversation_store = InMemoryConversationStore()
        registry = build_default_tool_registry()
        orchestrator = ChatOrchestrator(
            provider=_EchoProvider("Merhaba!"),
            conversation_store=conversation_store,
            prompt_loader=_FixedPromptProvider("sys"),
            tool_registry=registry,
            tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
            memory_service=service,
        )

        result = _run(orchestrator.respond("Merhaba", "sess-hist"))

        conversation = conversation_store.get_or_create("sess-hist")
        assert [m.role for m in conversation.messages] == ["user", "assistant"]
        assert conversation.messages[-1].content == "Merhaba!"


class TestExistingBehaviorUnchangedWhenNoMemories:
    def test_response_identical_with_and_without_memory_service(self) -> None:
        empty_response = _json_response([])
        store = _InMemoryFakeStore()
        service = MemoryWriteService(extractor=_make_extractor(empty_response), store=store)

        with_memory = _make_orchestrator(memory_service=service)
        without_memory = _make_orchestrator(memory_service=None)

        r1 = _run(with_memory.respond("Merhaba Jarvis", "sess-a"))
        r2 = _run(without_memory.respond("Merhaba Jarvis", "sess-b"))

        assert r1.response == r2.response == "Merhaba!"
        assert store.records == {}

    def test_no_memory_service_means_no_memory_side_effects(self) -> None:
        """memory_service=None olduğunda orchestrator eskisi gibi davranmalı."""
        orchestrator = _make_orchestrator(memory_service=None)

        result = _run(orchestrator.respond("test", "sess-none"))

        assert result.response == "Merhaba!"
        assert result.session_id == "sess-none"
