"""FINAL BASIC MEMORY VALIDATION — uçtan uca bilişsel bellek yaşam döngüsü.

Bu dosya, mevcut hiçbir bileşeni değiştirmez veya genişletmez. Yalnızca
tüm zincirin (MemoryExtractor → MemoryWriteService → SQLiteMemoryStore →
MemoryRetrievalService → ChatOrchestrator context injection) gerçek
SQLite + FTS5 üzerinden, ayrı "uygulama örnekleri" arasında uçtan uca
çalıştığını kanıtlar.

Ana senaryo:
    SESSION 1 (yazma):
        "My YKS goal is 100 TYT and 60 AYT."
            → MemoryExtractor → MemoryWriteService → SQLiteMemoryStore (dosya)

    SESSION 2 (TAMAMEN AYRI bir uygulama örneği, AYNI veritabanı dosyası):
        "YKS goal"
            → MemoryRetrievalService → SQLiteMemoryStore/FTS5
            → MemoryRecord → bellek bağlamı biçimlendirme → LLM context

Kapsam:
 1. Bellek, ayrı uygulama/oturum örnekleri arasında (aynı SQLite dosyası
    üzerinden) hayatta kalır.
 2. Yeni bir oturum, önceki bir oturumda oluşturulan belleği getirebilir.
 3. İlgili bellek LLM bağlamına ulaşır.
 4. İlgisiz bellekler yanlışlıkla enjekte edilmez.
 5. Boş getirme sonucu boş bir bellek bloğu eklemez.
 6. Bellek getirme hatası sohbeti bozmaz.
 7. Bellek yazma hatası sohbeti bozmaz.
 8. Mevcut konuşma geçmişi bozulmadan kalır.
 9. Mevcut tool-calling davranışı bozulmadan kalır.
10. Mevcut context limit davranışı bozulmadan kalır.
11. `app.main`'i import etmek yan etkisiz kalır.
12. Gerçek kullanıcı bellek dizini (`%LOCALAPPDATA%\\Jarvis\\`) dokunulmadan kalır
    (bu dosyadaki her test tmp_path tabanlı izole bir veritabanı kullanır;
    gerçek dizine dokunmama koşulu, tam test suite'i çalıştırıldıktan sonra
    dosya sisteminde ayrıca doğrulanır).

Not: Gerçek bir Ollama sunucusu gerektirmez; tüm LLM sağlayıcıları sahtedir.
Her test kendi izole tmp_path veritabanını kullanır — test sırası önemsizdir.
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
from app.core.chat import ChatMessage, LLMResponse, ToolCall, ToolDefinition
from app.main import create_app
from app.memory.extractor import MemoryExtractor
from app.memory.record import MemoryRecord
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.memory_service import MemoryWriteService

# ---------------------------------------------------------------------------
# Senaryo sabitleri
# ---------------------------------------------------------------------------

_GOAL_MESSAGE = "My YKS goal is 100 TYT and 60 AYT."
_GOAL_MEMORY_CONTENT = "User's YKS goal is 100 TYT and 60 AYT."
_UNRELATED_MESSAGE = "I also like pizza on weekends."
_UNRELATED_MEMORY_CONTENT = "User likes pizza on weekends."


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path, **kwargs: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        app_name="Jarvis E2E Test",
        app_version="test-1",
        environment="test",
        ollama_model="not-used-by-fake",
        memory_db_path=str(tmp_path / "default_memory.db"),
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _json_response(memories: list[dict[str, Any]]) -> str:
    return json.dumps({"memories": memories})


class _FakeChatProvider:
    """/api/chat isteklerini sabit bir metinle cevaplayan, çağrıları kaydeden sahte sağlayıcı."""

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


class _CalculatorToolCallingProvider:
    """test_chat.py'deki desenle aynı: önce tool call ister, sonra final cevap döner."""

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
            return LLMResponse(
                tool_calls=[ToolCall(name="calculator", arguments={"expression": "2 + 3"})]
            )
        return LLMResponse(content="2 + 3 sonucu 5.")


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


class _FailingWriteStore:
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


def _goal_write_service(store: SQLiteMemoryStore) -> MemoryWriteService:
    return MemoryWriteService(
        extractor=MemoryExtractor(
            provider=_FakeMemoryLLMProvider(
                _json_response(
                    [
                        {
                            "memory_type": "goal",
                            "content": _GOAL_MEMORY_CONTENT,
                            "temporality": "future",
                            "status": "planned",
                            "importance": 0.9,
                        }
                    ]
                )
            )
        ),
        store=store,
    )


# ---------------------------------------------------------------------------
# Ana senaryo: SESSION 1 (yazma) → SESSION 2 (ayrı örnek, getirme)
# ---------------------------------------------------------------------------


class TestBasicCognitiveMemoryLifecycle:
    def test_full_write_then_retrieve_lifecycle_across_separate_sessions(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "shared_memory.db"

        # ------------------------------------------------------------
        # SESSION 1 — bir "uygulama örneği": kullanıcı hedefini söylüyor
        # ------------------------------------------------------------
        session1_store = SQLiteMemoryStore(str(db_path))
        session1_settings = _make_settings(tmp_path, memory_db_path=str(db_path))
        session1_chat_provider = _FakeChatProvider("Not aldım, başarılar!")
        session1_app = create_app(
            settings=session1_settings,
            provider=session1_chat_provider,
            memory_service=_goal_write_service(session1_store),
        )

        with TestClient(session1_app) as client:
            response = client.post("/api/chat", json={"message": _GOAL_MESSAGE})

        assert response.status_code == 200
        assert response.json()["response"] == "Not aldım, başarılar!"
        assert session1_store.count() == 1
        assert session1_store.list_active()[0].content == _GOAL_MEMORY_CONTENT

        # ------------------------------------------------------------
        # SESSION 2 — TAMAMEN AYRI bir "uygulama örneği": kullanıcı soruyor
        # ------------------------------------------------------------
        session2_store = SQLiteMemoryStore(str(db_path))
        assert session2_store is not session1_store  # gerçekten ayrı bir Python örneği

        session2_settings = _make_settings(tmp_path, memory_db_path=str(db_path))
        session2_chat_provider = _FakeChatProvider("Hedefin 100 TYT, 60 AYT idi.")
        session2_app = create_app(
            settings=session2_settings,
            provider=session2_chat_provider,
            memory_retrieval=MemoryRetrievalService(store=session2_store),
        )

        with TestClient(session2_app) as client:
            response = client.post("/api/chat", json={"message": "YKS goal"})

        assert response.status_code == 200
        assert response.json()["response"] == "Hedefin 100 TYT, 60 AYT idi."

        # 1 & 2: önceki (farklı) örnek tarafından yazılan bellek, yeni
        # oturumda gerçekten bulunabildi.
        assert session2_store.count() == 1

        # 3: ilgili bellek gerçekten LLM bağlamına ulaştı.
        sent_messages = session2_chat_provider.calls[0]
        system_messages = [m for m in sent_messages if m.role == "system"]
        assert len(system_messages) == 2
        memory_block = system_messages[1]
        assert "<relevant_memory>" in memory_block.content
        assert _GOAL_MEMORY_CONTENT in memory_block.content

    def test_unrelated_memory_is_not_incorrectly_injected(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared_memory.db"
        store = SQLiteMemoryStore(str(db_path))
        settings = _make_settings(tmp_path, memory_db_path=str(db_path))

        pizza_write_service = MemoryWriteService(
            extractor=MemoryExtractor(
                provider=_FakeMemoryLLMProvider(
                    _json_response(
                        [
                            {
                                "memory_type": "fact",
                                "content": _UNRELATED_MEMORY_CONTENT,
                                "temporality": "present",
                                "status": "active",
                            }
                        ]
                    )
                )
            ),
            store=store,
        )

        app_goal = create_app(
            settings=settings, provider=_FakeChatProvider("ok"), memory_service=_goal_write_service(store)
        )
        with TestClient(app_goal) as client:
            client.post("/api/chat", json={"message": _GOAL_MESSAGE})

        app_pizza = create_app(
            settings=settings, provider=_FakeChatProvider("ok"), memory_service=pizza_write_service
        )
        with TestClient(app_pizza) as client:
            client.post("/api/chat", json={"message": _UNRELATED_MESSAGE})

        assert store.count() == 2

        retrieval_store = SQLiteMemoryStore(str(db_path))
        chat_provider = _FakeChatProvider("Hedefin 100 TYT, 60 AYT idi.")
        app_retrieve = create_app(
            settings=settings,
            provider=chat_provider,
            memory_retrieval=MemoryRetrievalService(store=retrieval_store),
        )

        with TestClient(app_retrieve) as client:
            response = client.post("/api/chat", json={"message": "YKS goal"})

        assert response.status_code == 200
        memory_block = [m for m in chat_provider.calls[0] if m.role == "system"][1].content
        assert _GOAL_MEMORY_CONTENT in memory_block
        assert _UNRELATED_MEMORY_CONTENT not in memory_block

    def test_empty_retrieval_adds_no_memory_block(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared_memory.db"
        store = SQLiteMemoryStore(str(db_path))
        settings = _make_settings(tmp_path, memory_db_path=str(db_path))

        app_write = create_app(
            settings=settings, provider=_FakeChatProvider("ok"), memory_service=_goal_write_service(store)
        )
        with TestClient(app_write) as client:
            client.post("/api/chat", json={"message": _GOAL_MESSAGE})

        retrieval_store = SQLiteMemoryStore(str(db_path))
        chat_provider = _FakeChatProvider("Bilmiyorum.")
        app_retrieve = create_app(
            settings=settings,
            provider=chat_provider,
            memory_retrieval=MemoryRetrievalService(store=retrieval_store),
        )

        with TestClient(app_retrieve) as client:
            response = client.post(
                "/api/chat", json={"message": "quantum physics research funding"}
            )

        assert response.status_code == 200
        sent = chat_provider.calls[0]
        system_messages = [m for m in sent if m.role == "system"]
        assert len(system_messages) == 1  # bellek bloğu eklenmedi
        assert not any("<relevant_memory>" in m.content for m in sent)

    def test_retrieval_failure_does_not_break_chat(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        chat_provider = _FakeChatProvider("Sorun yok.")
        app = create_app(
            settings=settings,
            provider=chat_provider,
            memory_retrieval=MemoryRetrievalService(store=_FailingSearchStore()),
        )

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "Merhaba"})

        assert response.status_code == 200
        assert response.json()["response"] == "Sorun yok."

    def test_write_failure_does_not_break_chat(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        chat_provider = _FakeChatProvider("Yine de çalışıyor.")
        write_service = MemoryWriteService(
            extractor=MemoryExtractor(
                provider=_FakeMemoryLLMProvider(
                    _json_response(
                        [{"memory_type": "fact", "content": "irrelevant", "temporality": "present", "status": "active"}]
                    )
                )
            ),
            store=_FailingWriteStore(),
        )
        app = create_app(settings=settings, provider=chat_provider, memory_service=write_service)

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "Merhaba"})

        assert response.status_code == 200
        assert response.json()["response"] == "Yine de çalışıyor."

    def test_conversation_history_remains_intact_with_memory_enabled(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        store = SQLiteMemoryStore(str(db_path))
        write_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(_json_response([]))),
            store=store,
        )
        settings = _make_settings(tmp_path, memory_db_path=str(db_path))
        chat_provider = _FakeChatProvider("Merhaba!")
        app = create_app(
            settings=settings,
            provider=chat_provider,
            memory_service=write_service,
            memory_retrieval=MemoryRetrievalService(store=store),
        )

        with TestClient(app) as client:
            first = client.post("/api/chat", json={"message": "Merhaba"})
            session_id = first.json()["session_id"]
            second = client.post(
                "/api/chat", json={"message": "Nasılsın?", "session_id": session_id}
            )

        assert first.status_code == 200
        assert second.status_code == 200
        second_call_messages = chat_provider.calls[1]
        history_texts = [m.content for m in second_call_messages if m.role in ("user", "assistant")]
        assert "Merhaba" in history_texts
        assert "Merhaba!" in history_texts
        assert "Nasılsın?" in history_texts

    def test_tool_calling_still_works_with_memory_enabled(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        store = SQLiteMemoryStore(str(db_path))
        write_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(_json_response([]))),
            store=store,
        )
        provider = _CalculatorToolCallingProvider()
        settings = _make_settings(tmp_path, memory_db_path=str(db_path))
        app = create_app(
            settings=settings,
            provider=provider,
            memory_service=write_service,
            memory_retrieval=MemoryRetrievalService(store=store),
        )

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "2 + 3 kaç eder?"})

        assert response.status_code == 200
        assert response.json()["response"] == "2 + 3 sonucu 5."
        assert len(provider.calls) == 2

    def test_context_message_limit_still_respected_with_memory_enabled(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        store = SQLiteMemoryStore(str(db_path))
        write_service = MemoryWriteService(
            extractor=MemoryExtractor(provider=_FakeMemoryLLMProvider(_json_response([]))),
            store=store,
        )
        chat_provider = _FakeChatProvider("ok")
        settings = _make_settings(tmp_path, memory_db_path=str(db_path), conversation_context_limit=2)
        app = create_app(
            settings=settings,
            provider=chat_provider,
            memory_service=write_service,
            memory_retrieval=MemoryRetrievalService(store=store),
        )

        session_id: str | None = None
        with TestClient(app) as client:
            for i in range(4):
                payload: dict[str, Any] = {"message": f"mesaj-{i}"}
                if session_id:
                    payload["session_id"] = session_id
                resp = client.post("/api/chat", json=payload)
                session_id = resp.json()["session_id"]

        last_call = chat_provider.calls[-1]
        non_system = [m for m in last_call if m.role != "system"]
        # limit=2: en fazla 2 geçmiş mesaj + 1 yeni user mesajı
        assert len(non_system) <= 3

    def test_importing_app_main_remains_side_effect_free(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "import_check.db"
        monkeypatch.setenv("JARVIS_MEMORY_DB_PATH", str(db_path))
        monkeypatch.setenv("JARVIS_ENVIRONMENT", "test")
        get_settings.cache_clear()

        import app.main as main_module

        try:
            importlib.reload(main_module)

            assert not db_path.exists(), "app.main import etmek kalıcı veritabanını oluşturmamalı"

            with TestClient(main_module.app):
                assert db_path.exists(), "uygulama gerçekten başlatıldığında veritabanı oluşmalı"
        finally:
            get_settings.cache_clear()
            importlib.reload(main_module)
