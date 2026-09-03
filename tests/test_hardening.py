"""Architecture Hardening adımına ait testler.

Kapsar:
1. ConversationStore Protocol soyutlaması
2. PromptProvider soyutlaması + prompt önbellekleme
3. Konuşma bağlamı (context) mesaj sınırı
4. Ollama AsyncClient lifecycle
5. Memory modülü arayüz içe aktarmaları
6. Settings — conversation_context_limit alanı
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

from app.adapters.llm.base import LLMUnavailableError
from app.config.settings import Settings
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.main import create_app
from app.memory import (
    Entity,
    EpisodicMemoryStore,
    Event,
    Fact,
    Goal,
    MemoryEntry,
    Preference,
    Relationship,
    SemanticMemoryStore,
    Temporality,
    WorkingMemoryStore,
    WorldStateEntry,
)
from app.services.conversation import (
    Conversation,
    ConversationStore,
    InMemoryConversationStore,
)
from app.services.orchestrator import ChatOrchestrator
from app.services.prompts import PromptProvider, SystemPromptLoader
from app.tools.base import PermissionLevel
from app.tools.defaults import build_default_tool_registry
from app.tools.executor import ToolExecutor

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Yardımcı sahte nesneler
# ---------------------------------------------------------------------------

class _SimpleFakeProvider:
    """Testlerde LLM sunucusu olmadan çalışmak için en sade fake."""

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        return "ok"

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        return LLMResponse(content=f"echo:{len(messages)}")


class _CapturingFakeProvider:
    """LLM'e gönderilen mesajları kaydeden fake provider."""

    def __init__(self) -> None:
        self.received_messages: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        r = await self.generate_with_tools(messages, tools=())
        return r.content

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.received_messages.append(list(messages))
        return LLMResponse(content=f"reply:{len(messages)}")


class _FixedPromptProvider:
    """Her zaman aynı sabit promptu döndüren fake PromptProvider."""

    def __init__(self, prompt: str) -> None:
        self._prompt = prompt

    def load(self) -> str:
        return self._prompt


def _make_test_settings(**kwargs: Any) -> Settings:
    defaults = dict(app_name="Test", app_version="t", environment="test", ollama_model="x")
    defaults.update(kwargs)
    return Settings(**defaults)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. ConversationStore Protocol soyutlaması
# ---------------------------------------------------------------------------

def test_in_memory_store_satisfies_conversation_store_protocol() -> None:
    """InMemoryConversationStore, ConversationStore Protocol'ünü karşılamalı."""
    store = InMemoryConversationStore()
    assert isinstance(store, ConversationStore)


def test_conversation_store_protocol_rejects_non_compliant_object() -> None:
    """Protocol'ü karşılamayan bir nesne isinstance testinden geçmemeli."""

    class _Missing:
        def get_or_create(self, session_id=None):  # type: ignore[override]
            ...
        # append_messages eksik

    assert not isinstance(_Missing(), ConversationStore)


def test_orchestrator_accepts_custom_store_implementation() -> None:
    """ChatOrchestrator, somut InMemoryConversationStore yerine Protocol ile çalışmalı."""

    class _CustomStore:
        """Protocol'ü manuel olarak implemente eden özel bir store."""

        def __init__(self) -> None:
            self._data: dict[str, Conversation] = {}

        def get_or_create(self, session_id: str | None = None) -> Conversation:
            sid = session_id or "default"
            if sid not in self._data:
                self._data[sid] = Conversation(session_id=sid)
            return self._data[sid].model_copy(deep=True)

        def append_messages(self, session_id: str, messages) -> None:
            if session_id not in self._data:
                self._data[session_id] = Conversation(session_id=session_id)
            self._data[session_id].messages.extend(messages)

    provider = _SimpleFakeProvider()
    store = _CustomStore()
    registry = build_default_tool_registry()
    orchestrator = ChatOrchestrator(
        provider=provider,
        conversation_store=store,
        prompt_loader=_FixedPromptProvider("sys"),
        tool_registry=registry,
        tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
    )
    result = _run(orchestrator.respond("merhaba"))
    assert result.response
    assert result.session_id


def test_create_app_accepts_custom_conversation_store() -> None:
    """create_app(), ConversationStore Protocol'ünü karşılayan herhangi bir nesneyi kabul etmeli."""
    store = InMemoryConversationStore()
    settings = _make_test_settings()
    app = create_app(settings=settings, provider=_SimpleFakeProvider(), conversation_store=store)
    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"message": "test"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. PromptProvider soyutlaması + önbellek
# ---------------------------------------------------------------------------

def test_system_prompt_loader_satisfies_prompt_provider_protocol() -> None:
    """SystemPromptLoader, PromptProvider Protocol'ünü karşılamalı."""
    loader = SystemPromptLoader()
    assert isinstance(loader, PromptProvider)


def test_prompt_loader_caches_result_and_reads_file_once(tmp_path) -> None:
    """İkinci load() çağrısı dosyadan değil önbellekten okumalı."""
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("initial prompt", encoding="utf-8")

    loader = SystemPromptLoader(str(prompt_file))
    first = loader.load()
    assert first == "initial prompt"

    # Dosya değiştirilse bile önbellek süresi dolana kadar eski değer dönmeli.
    prompt_file.write_text("updated prompt", encoding="utf-8")
    second = loader.load()
    assert second == "initial prompt"  # önbellekten geliyor


def test_prompt_loader_cache_invalidation(tmp_path) -> None:
    """invalidate_cache() sonrasında dosya yeniden okunmalı."""
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("v1", encoding="utf-8")

    loader = SystemPromptLoader(str(prompt_file))
    assert loader.load() == "v1"

    prompt_file.write_text("v2", encoding="utf-8")
    loader.invalidate_cache()
    assert loader.load() == "v2"


def test_orchestrator_accepts_custom_prompt_provider() -> None:
    """ChatOrchestrator, somut SystemPromptLoader yerine PromptProvider Protocol ile çalışmalı."""
    provider = _CapturingFakeProvider()
    registry = build_default_tool_registry()
    orchestrator = ChatOrchestrator(
        provider=provider,
        conversation_store=InMemoryConversationStore(),
        prompt_loader=_FixedPromptProvider("custom system"),
        tool_registry=registry,
        tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
    )
    result = _run(orchestrator.respond("test"))
    assert result.response
    system_msg = provider.received_messages[0][0]
    assert system_msg.role == "system"
    # Sağlayıcının metni system prompt'un BAŞINDA yer alır. Eşitlik yerine
    # "başlıyor" sınanır çünkü orchestrator kendi kalıcı talimatlarını
    # (tool sonuçlarının veri olduğu uyarısı) buna ekler.
    assert system_msg.content.startswith("custom system")


# ---------------------------------------------------------------------------
# 3. Konuşma bağlamı mesaj sınırı
# ---------------------------------------------------------------------------

def test_context_limit_trims_history_sent_to_llm() -> None:
    """Limit=2 olduğunda LLM'e en fazla 2 geçmiş mesaj gönderilmeli (system hariç)."""
    provider = _CapturingFakeProvider()
    store = InMemoryConversationStore()
    registry = build_default_tool_registry()
    orchestrator = ChatOrchestrator(
        provider=provider,
        conversation_store=store,
        prompt_loader=_FixedPromptProvider("sys"),
        tool_registry=registry,
        tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
        context_message_limit=2,
    )

    # 4 mesaj gönder — her biri bir öncekinin cevabını içerir.
    session_id = None
    for i in range(4):
        result = _run(orchestrator.respond(f"mesaj-{i}", session_id))
        session_id = result.session_id

    # Son LLM çağrısında gönderilen mesajlar: system + en fazla 2 geçmiş + 1 yeni user
    last_call = provider.received_messages[-1]
    # system mesajını say
    system_messages = [m for m in last_call if m.role == "system"]
    non_system = [m for m in last_call if m.role != "system"]
    assert len(system_messages) == 1
    # Geçmiş + mevcut user mesajı: limit=2 demek önceki 2 mesaj + yeni user = 3
    assert len(non_system) <= 3


def test_context_limit_zero_means_no_limit() -> None:
    """Limit=0 olduğunda geçmişin tamamı gönderilmeli."""
    provider = _CapturingFakeProvider()
    store = InMemoryConversationStore()
    registry = build_default_tool_registry()
    orchestrator = ChatOrchestrator(
        provider=provider,
        conversation_store=store,
        prompt_loader=_FixedPromptProvider("sys"),
        tool_registry=registry,
        tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
        context_message_limit=0,  # sınırsız
    )

    session_id = None
    for i in range(5):
        result = _run(orchestrator.respond(f"msg-{i}", session_id))
        session_id = result.session_id

    # Son çağrıda sistem + tüm geçmiş + yeni user olmalı (> 3 mesaj)
    last_call = provider.received_messages[-1]
    non_system = [m for m in last_call if m.role != "system"]
    assert len(non_system) > 3


def test_context_limit_does_not_delete_stored_history() -> None:
    """Limit kırpma yalnızca LLM bağlamını etkiler; depodaki geçmişi silmemeli."""
    store = InMemoryConversationStore()
    registry = build_default_tool_registry()
    orchestrator = ChatOrchestrator(
        provider=_SimpleFakeProvider(),
        conversation_store=store,
        prompt_loader=_FixedPromptProvider("sys"),
        tool_registry=registry,
        tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
        context_message_limit=1,  # sadece 1 mesaj bağlama gönder
    )

    session_id = None
    for i in range(4):
        result = _run(orchestrator.respond(f"msg-{i}", session_id))
        session_id = result.session_id

    # Depodaki gerçek geçmiş kırpılmamış olmalı
    conversation = store.get_or_create(session_id)
    # 4 user + 4 assistant = 8 mesaj beklenir (tool yoksa)
    assert len(conversation.messages) == 8


def test_settings_exposes_conversation_context_limit() -> None:
    """Settings, conversation_context_limit alanını desteklemeli."""
    s = Settings(
        app_name="T",
        app_version="t",
        environment="test",
        conversation_context_limit=10,
    )
    assert s.conversation_context_limit == 10


def test_settings_context_limit_default_is_positive() -> None:
    """Varsayılan değer 0'dan büyük olmalı (pratik bir sınır)."""
    s = Settings(app_name="T", app_version="t", environment="test")
    assert s.conversation_context_limit > 0


def test_create_app_passes_context_limit_from_settings() -> None:
    """create_app(), settings.conversation_context_limit değerini orchestrator'a geçirmeli."""
    provider = _CapturingFakeProvider()
    settings = _make_test_settings(conversation_context_limit=1)
    app = create_app(settings=settings, provider=provider)
    with TestClient(app) as client:
        # İki istek gönder; ikincisinde bağlam limiti devreye girmeli.
        r1 = client.post("/api/chat", json={"message": "birinci"})
        sid = r1.json()["session_id"]
        client.post("/api/chat", json={"message": "ikinci", "session_id": sid})

    # İkinci çağrıda system + en fazla 1 geçmiş + user = 3 mesaj
    last = provider.received_messages[-1]
    assert len(last) <= 3


# ---------------------------------------------------------------------------
# 4. Ollama AsyncClient lifecycle
# ---------------------------------------------------------------------------

def test_ollama_provider_creates_persistent_client() -> None:
    """OllamaProvider, her istek için yeni client yerine tek bir client kullanmalı."""
    from app.adapters.llm.ollama import OllamaProvider

    p = OllamaProvider(base_url="http://127.0.0.1:11434", model="test", timeout_seconds=5.0)
    # İlk erişim: client var olmalı
    assert p._client is not None
    client_id = id(p._client)
    # İkinci erişim: aynı client nesnesi
    assert id(p._client) == client_id
    # Temizlik
    _run(p.aclose())


def test_ollama_provider_aclose_does_not_raise() -> None:
    """aclose() başarıyla tamamlanmalı, hata fırlatmamalı."""
    from app.adapters.llm.ollama import OllamaProvider

    p = OllamaProvider(base_url="http://127.0.0.1:11434", model="test", timeout_seconds=5.0)
    _run(p.aclose())  # hata fırlatmamalı


def test_app_lifespan_closes_ollama_provider() -> None:
    """Uygulama kapatıldığında OllamaProvider.aclose() çağrılmalı."""
    from app.adapters.llm.ollama import OllamaProvider

    closed: list[bool] = []

    class _TrackingProvider(OllamaProvider):
        async def aclose(self) -> None:
            closed.append(True)
            await super().aclose()

    provider = _TrackingProvider(
        base_url="http://127.0.0.1:11434", model="test", timeout_seconds=5.0
    )
    settings = _make_test_settings()
    app = create_app(settings=settings, provider=provider)

    with TestClient(app):
        pass  # lifespan başlar ve biter

    assert closed == [True], "lifespan çıkışında aclose() çağrılmalıydı"


# ---------------------------------------------------------------------------
# 5. Memory modülü arayüz içe aktarmaları
# ---------------------------------------------------------------------------

def test_memory_base_models_are_importable() -> None:
    """Tüm temel bellek modelleri paketten içe aktarılabilmeli."""
    assert MemoryEntry is not None
    assert Fact is not None
    assert Entity is not None
    assert Relationship is not None
    assert Event is not None
    assert Preference is not None
    assert Goal is not None
    assert WorldStateEntry is not None
    assert Temporality is not None


def test_memory_protocol_interfaces_are_importable() -> None:
    """Tüm bellek Protocol sözleşmeleri paketten içe aktarılabilmeli."""
    assert WorkingMemoryStore is not None
    assert EpisodicMemoryStore is not None
    assert SemanticMemoryStore is not None


def test_temporality_enum_has_required_values() -> None:
    """Temporality enum, geçmiş/şimdi/gelecek/bilinmiyor değerlerine sahip olmalı."""
    assert Temporality.PAST == "past"
    assert Temporality.PRESENT == "present"
    assert Temporality.FUTURE == "future"
    assert Temporality.UNKNOWN == "unknown"


def test_fact_model_can_be_instantiated() -> None:
    """Fact modeli gerekli alanlarla oluşturulabilmeli."""
    fact = Fact(subject="kullanıcı", predicate="adı", object_value="Ahmet")
    assert fact.subject == "kullanıcı"
    assert fact.confidence == 1.0
    assert fact.id  # UUID atanmış olmalı


def test_event_model_supports_temporality() -> None:
    """Event modeli temporality bilgisini taşıyabilmeli."""
    past = Event(title="Geçen hafta toplantı", temporality=Temporality.PAST)
    future = Event(title="Yarın randevu", temporality=Temporality.FUTURE)
    assert past.temporality == Temporality.PAST
    assert future.temporality == Temporality.FUTURE


def test_goal_model_tracks_completion() -> None:
    """Goal modeli tamamlanma durumunu izleyebilmeli."""
    goal = Goal(title="Kitap oku", owner_id="user-1")
    assert goal.is_completed is False
    completed = goal.model_copy(update={"is_completed": True})
    assert completed.is_completed is True


def test_world_state_entry_has_domain_and_key() -> None:
    """WorldStateEntry, domain ve key alanlarına sahip olmalı."""
    entry = WorldStateEntry(domain="home_assistant", key="living_room_light", value="on")
    assert entry.domain == "home_assistant"
    assert entry.key == "living_room_light"
    assert entry.value == "on"
