"""Agent katmanı — sınırlandırılmış bağlam inşası.

Kapsam:
 1. Bağlam yalnızca bütçe kadar veri taşır (tüm veritabanı yüklenmez)
 2. Bağlı olmayan kaynaklar `degraded_sources` ile raporlanır, hata değil
 3. Patlayan bir kaynak bağlam inşasını çökertmez
 4. Memory / Experience / User Model AYRI bölümler olarak kalır
 5. Tool keşfi: yalnızca güvenli tanımlar taşınır, Tool nesnesi taşınmaz
 6. Onay gereksinimi oturumun izin kümesinden hesaplanır
 7. Oturum içi deneyimler önceliklidir
 8. Bağlam inşası salt-okunurdur (hiçbir kaydı değiştirmez)
 9. Yalnızca PUBLIC arayüzler kullanılır — özel alanlara erişim yok
10. Gerçek depolarla uçtan uca çalışır
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

from app.agent import context as context_module
from app.agent.context import (
    SOURCE_CONVERSATION,
    SOURCE_EXPERIENCE,
    SOURCE_MEMORY,
    SOURCE_USER_MODEL,
    AgentContext,
    ContextBudget,
    ContextBuilder,
)
from app.learning.sqlite_trait_store import SQLiteUserTraitStore
from app.learning.trait import TraitSource, TraitType, UserTrait
from app.memory.experience import Experience
from app.memory.record import MemoryRecord, MemoryType
from app.memory.sqlite_experience_store import SQLiteExperienceStore
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services.conversation import InMemoryConversationStore
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.user_model_service import UserModelService
from app.tools.base import PermissionLevel
from app.tools.defaults import build_default_tool_registry, register_context_tools
from app.core.chat import ChatMessage

_NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)
_READ_ONLY = {PermissionLevel.READ}


def _exp(*, day: int = 26, session_id: str = "sess-1", message: str = "python") -> Experience:
    return Experience(
        session_id=session_id,
        occurred_at=datetime(2026, 8, day, 20, 0, tzinfo=UTC),
        user_message=message,
        assistant_response="cevap",
    )


def _trait(key: str = "topic:python") -> UserTrait:
    return UserTrait(
        trait_type=TraitType.INTEREST,
        key=key,
        value="python",
        evidence_count=4,
        confidence=0.5,
        source=TraitSource.EXPERIENCE,
        first_observed_at=_NOW,
        last_observed_at=_NOW,
    )


def _builder(**overrides: object) -> ContextBuilder:
    defaults: dict[str, object] = dict(
        tool_registry=build_default_tool_registry(), allowed_permissions=_READ_ONLY
    )
    defaults.update(overrides)
    return ContextBuilder(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Bütçe sınırları
# ---------------------------------------------------------------------------


class TestBudgetIsEnforced:
    def test_memories_are_capped_by_budget(self, tmp_path: Path) -> None:
        store = SQLiteMemoryStore(str(tmp_path / "memory.db"))
        for index in range(20):
            store.add(MemoryRecord(content=f"python kaydı {index}"))
        builder = _builder(
            memory_retrieval=MemoryRetrievalService(store=store),
            budget=ContextBudget(max_memories=3),
        )

        context = builder.build("python", now=_NOW)

        assert len(context.memories) <= 3

    def test_experiences_are_capped_by_budget(self, tmp_path: Path) -> None:
        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        for day in range(10, 25):
            store.add(_exp(day=day))
        builder = _builder(experience_store=store, budget=ContextBudget(max_experiences=2))

        context = builder.build("merhaba", now=_NOW)

        assert len(context.experiences) == 2

    def test_traits_are_capped_by_budget(self, tmp_path: Path) -> None:
        trait_store = SQLiteUserTraitStore(str(tmp_path / "memory.db"))
        for index in range(10):
            trait_store.upsert(_trait(key=f"topic:t{index}"))
        builder = _builder(
            user_model=UserModelService(trait_store=trait_store),
            budget=ContextBudget(max_traits=4),
        )

        context = builder.build("merhaba", now=_NOW)

        assert len(context.traits) == 4

    def test_recent_messages_are_capped_by_budget(self) -> None:
        conversation_store = InMemoryConversationStore()
        conversation_store.append_messages(
            "sess-1", [ChatMessage(role="user", content=f"mesaj {i}") for i in range(20)]
        )
        builder = _builder(
            conversation_store=conversation_store, budget=ContextBudget(max_recent_messages=5)
        )

        context = builder.build("merhaba", session_id="sess-1", now=_NOW)

        assert len(context.recent_messages) == 5
        assert context.recent_messages[-1].content == "mesaj 19"

    def test_zero_budget_loads_nothing(self, tmp_path: Path) -> None:
        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        store.add(_exp())
        builder = _builder(experience_store=store, budget=ContextBudget(max_experiences=0))

        assert builder.build("merhaba", now=_NOW).experiences == []


# ---------------------------------------------------------------------------
# 2-3. Eksik ve patlayan kaynaklar
# ---------------------------------------------------------------------------


class TestDegradedSources:
    def test_missing_sources_are_reported_not_raised(self) -> None:
        context = _builder().build("merhaba", now=_NOW)

        assert set(context.degraded_sources) == {
            SOURCE_CONVERSATION,
            SOURCE_MEMORY,
            SOURCE_EXPERIENCE,
            SOURCE_USER_MODEL,
        }
        assert context.memories == []
        assert context.experiences == []
        assert context.traits == []

    def test_failing_memory_source_degrades_gracefully(self) -> None:
        class _RaisingRetrieval:
            def retrieve(self, query, **kwargs):  # noqa: ANN001, ANN003
                raise RuntimeError("memory backend down")

        context = _builder(memory_retrieval=_RaisingRetrieval()).build("merhaba", now=_NOW)

        assert context.memories == []
        assert SOURCE_MEMORY in context.degraded_sources

    def test_failing_experience_source_degrades_gracefully(self) -> None:
        class _RaisingExperienceStore:
            def add(self, experience):  # noqa: ANN001, ANN201
                return experience

            def get(self, experience_id):  # noqa: ANN001, ANN201
                return None

            def list_by_session(self, session_id, *, limit=50):  # noqa: ANN001
                raise RuntimeError("experience backend down")

            def list_recent(self, *, limit=50, before=None):  # noqa: ANN001
                raise RuntimeError("experience backend down")

        context = _builder(experience_store=_RaisingExperienceStore()).build(
            "merhaba", session_id="sess-1", now=_NOW
        )

        assert context.experiences == []
        assert SOURCE_EXPERIENCE in context.degraded_sources

    def test_failing_user_model_degrades_gracefully(self) -> None:
        class _RaisingUserModel:
            def list_traits(self, **kwargs):  # noqa: ANN003, ANN201
                raise RuntimeError("user model down")

        context = _builder(user_model=_RaisingUserModel()).build("merhaba", now=_NOW)

        assert context.traits == []
        assert SOURCE_USER_MODEL in context.degraded_sources

    def test_failing_conversation_store_degrades_gracefully(self) -> None:
        class _RaisingConversationStore:
            def get_or_create(self, session_id=None):  # noqa: ANN001, ANN201
                raise RuntimeError("conversation store down")

            def append_messages(self, session_id, messages):  # noqa: ANN001
                return None

        context = _builder(conversation_store=_RaisingConversationStore()).build(
            "merhaba", session_id="sess-1", now=_NOW
        )

        assert context.recent_messages == []
        assert SOURCE_CONVERSATION in context.degraded_sources

    def test_every_source_failing_still_returns_a_usable_context(self) -> None:
        class _Boom:
            def __getattr__(self, name):  # noqa: ANN001, ANN204
                def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                    raise RuntimeError("down")

                return _raise

        context = _builder(
            conversation_store=_Boom(), memory_retrieval=_Boom(), user_model=_Boom()
        ).build("merhaba", session_id="s", now=_NOW)

        assert isinstance(context, AgentContext)
        assert context.user_message == "merhaba"
        assert context.available_tools  # tool keşfi etkilenmedi


# ---------------------------------------------------------------------------
# 4. Kavramlar ayrı kalır
# ---------------------------------------------------------------------------


class TestConceptsStaySeparate:
    def test_memory_experience_and_traits_are_distinct_sections(self, tmp_path: Path) -> None:
        db = str(tmp_path / "memory.db")
        memory_store = SQLiteMemoryStore(db)
        memory_store.add(MemoryRecord(memory_type=MemoryType.FACT, content="python biliyor"))
        experience_store = SQLiteExperienceStore(db)
        experience_store.add(_exp())
        trait_store = SQLiteUserTraitStore(db)
        trait_store.upsert(_trait())

        context = _builder(
            memory_retrieval=MemoryRetrievalService(store=memory_store),
            experience_store=experience_store,
            user_model=UserModelService(trait_store=trait_store),
        ).build("python", now=_NOW)

        assert len(context.memories) == 1
        assert len(context.experiences) == 1
        assert len(context.traits) == 1
        assert isinstance(context.memories[0], MemoryRecord)
        assert isinstance(context.experiences[0], Experience)
        assert isinstance(context.traits[0], UserTrait)
        assert context.degraded_sources == [SOURCE_CONVERSATION]


# ---------------------------------------------------------------------------
# 5-6. Tool keşfi ve onay hesabı
# ---------------------------------------------------------------------------


class TestToolDiscovery:
    def test_registered_tools_are_discoverable(self) -> None:
        context = _builder().build("merhaba", now=_NOW)

        names = {tool.name for tool in context.available_tools}
        assert {"get_time", "get_date", "calculator", "system_status"} <= names
        assert context.has_tool("calculator") is True
        assert context.has_tool("nonexistent_tool") is False

    def test_tool_objects_are_never_placed_in_context(self) -> None:
        """Bağlama yalnızca güvenli tanım girer, çalıştırılabilir nesne değil."""
        context = _builder().build("merhaba", now=_NOW)

        for tool in context.available_tools:
            assert not hasattr(tool, "execute")

    def test_permission_outside_the_allowed_set_requires_confirmation(self) -> None:
        """READ etkin değilse READ tool'ları onay gerektirir hale gelmeli."""
        builder = _builder(allowed_permissions=set())

        context = builder.build("merhaba", now=_NOW)

        assert all(tool.requires_confirmation for tool in context.available_tools)

    def test_allowed_permission_does_not_require_confirmation(self) -> None:
        context = _builder().build("merhaba", now=_NOW)

        assert all(not tool.requires_confirmation for tool in context.available_tools)

    def test_context_tools_appear_once_registered(self, tmp_path: Path) -> None:
        db = str(tmp_path / "memory.db")
        registry = build_default_tool_registry()
        registered = register_context_tools(
            registry,
            memory_retrieval=MemoryRetrievalService(store=SQLiteMemoryStore(db)),
            user_model=UserModelService(trait_store=SQLiteUserTraitStore(db)),
        )

        context = _builder(tool_registry=registry).build("merhaba", now=_NOW)

        assert registered == ["memory_search", "user_profile"]
        assert context.has_tool("memory_search") is True
        assert context.has_tool("user_profile") is True

    def test_failing_registry_yields_no_tools_instead_of_raising(self) -> None:
        class _RaisingRegistry:
            def list_tools(self):  # noqa: ANN201
                raise RuntimeError("registry down")

        context = _builder(tool_registry=_RaisingRegistry()).build("merhaba", now=_NOW)

        assert context.available_tools == []


# ---------------------------------------------------------------------------
# 7. Oturum önceliği
# ---------------------------------------------------------------------------


class TestSessionScopedExperiences:
    def test_session_experiences_are_preferred(self, tmp_path: Path) -> None:
        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        store.add(_exp(day=20, session_id="other", message="başka oturum"))
        store.add(_exp(day=21, session_id="sess-1", message="bu oturum"))

        context = _builder(experience_store=store).build(
            "merhaba", session_id="sess-1", now=_NOW
        )

        assert [e.user_message for e in context.experiences] == ["bu oturum"]

    def test_falls_back_to_recent_when_session_has_no_experiences(self, tmp_path: Path) -> None:
        store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        store.add(_exp(day=20, session_id="other", message="başka oturum"))

        context = _builder(experience_store=store).build(
            "merhaba", session_id="empty-session", now=_NOW
        )

        assert [e.user_message for e in context.experiences] == ["başka oturum"]


# ---------------------------------------------------------------------------
# 8-9. Salt-okunurluk ve mimari izolasyon
# ---------------------------------------------------------------------------


class TestReadOnlyAndIsolation:
    def test_building_context_never_writes(self, tmp_path: Path) -> None:
        db = str(tmp_path / "memory.db")
        memory_store = SQLiteMemoryStore(db)
        memory_store.add(MemoryRecord(content="python"))
        experience_store = SQLiteExperienceStore(db)
        experience_store.add(_exp())
        trait_store = SQLiteUserTraitStore(db)
        trait_store.upsert(_trait())
        builder = _builder(
            memory_retrieval=MemoryRetrievalService(store=memory_store),
            experience_store=experience_store,
            user_model=UserModelService(trait_store=trait_store),
        )

        before = (memory_store.count(), experience_store.count(), trait_store.count())
        for _ in range(5):
            builder.build("python", now=_NOW)
        after = (memory_store.count(), experience_store.count(), trait_store.count())

        assert before == after

    def test_context_module_does_not_touch_concrete_stores(self) -> None:
        source = inspect.getsource(context_module)

        assert "SQLiteMemoryStore" not in source
        assert "SQLiteExperienceStore" not in source
        assert "SQLiteUserTraitStore" not in source
        # Somut depo modülleri hiç import edilmemeli.
        assert "sqlite_store" not in source
        assert "sqlite_experience_store" not in source
        assert "sqlite_trait_store" not in source
        assert "import sqlite3" not in source

    def test_context_module_accesses_no_private_attributes(self) -> None:
        """Agent, diğer katmanların iç yapısına uzanmamalı."""
        source = inspect.getsource(context_module)

        for forbidden in ("._store", "._db_path", "._conn", "._trait_store", "._extractor"):
            assert forbidden not in source

    def test_context_module_calls_no_llm(self) -> None:
        source = inspect.getsource(context_module)

        assert "LLMProvider" not in source
        assert "generate" not in source
