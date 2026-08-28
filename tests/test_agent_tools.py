"""Agent katmanı — bağlam tool'ları (memory_search, user_profile).

Kapsam:
 1. Tool kaydı: servis verilmeyen tool kaydedilmez
 2. Varsayılan registry değişmedi (sohbetin tool yüzeyi korunur)
 3. memory_search public getirme servisini kullanır
 4. user_profile public kullanıcı modeli servisini kullanır
 5. Input doğrulaması mevcut Tool sözleşmesiyle yapılır
 6. Çıktılar JSON serileştirilebilir (tool-result mesajına çevrilebilir)
 7. Tool'lar salt okunurdur
 8. Tool'lar somut depolara değil servislere bağlıdır
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.learning.sqlite_trait_store import SQLiteUserTraitStore
from app.learning.trait import TraitSource, TraitType, UserTrait
from app.memory.record import MemoryRecord, MemoryType
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.user_model_service import UserModelService
from app.tools.base import PermissionLevel, ToolInputValidationError
from app.tools.builtin import context_tools as context_tools_module
from app.tools.builtin.context_tools import MemorySearchTool, UserProfileTool
from app.tools.defaults import build_default_tool_registry, register_context_tools
from app.tools.executor import ToolExecutor
from app.core.chat import ToolCall

_NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


@pytest.fixture()
def memory_retrieval(tmp_path: Path) -> MemoryRetrievalService:
    store = SQLiteMemoryStore(str(tmp_path / "memory.db"))
    store.add(MemoryRecord(memory_type=MemoryType.FACT, content="Kullanıcı python kullanıyor."))
    store.add(MemoryRecord(memory_type=MemoryType.FACT, content="Kullanıcı İstanbul'da yaşıyor."))
    return MemoryRetrievalService(store=store)


@pytest.fixture()
def user_model(tmp_path: Path) -> UserModelService:
    store = SQLiteUserTraitStore(str(tmp_path / "memory.db"))
    store.upsert(
        UserTrait(
            trait_type=TraitType.INTEREST,
            key="topic:python",
            value="python",
            evidence_count=4,
            confidence=0.5,
            source=TraitSource.EXPERIENCE,
            first_observed_at=_NOW,
            last_observed_at=_NOW,
        )
    )
    return UserModelService(trait_store=store)


# ---------------------------------------------------------------------------
# 1-2. Kayıt davranışı
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registers_only_the_tools_whose_service_is_available(
        self, memory_retrieval: MemoryRetrievalService
    ) -> None:
        registry = build_default_tool_registry()

        registered = register_context_tools(registry, memory_retrieval=memory_retrieval)

        assert registered == ["memory_search"]
        assert registry.get("memory_search") is not None
        assert registry.get("user_profile") is None

    def test_registers_nothing_without_services(self) -> None:
        registry = build_default_tool_registry()

        assert register_context_tools(registry) == []

    def test_registers_both_when_both_services_exist(
        self, memory_retrieval: MemoryRetrievalService, user_model: UserModelService
    ) -> None:
        registry = build_default_tool_registry()

        registered = register_context_tools(
            registry, memory_retrieval=memory_retrieval, user_model=user_model
        )

        assert registered == ["memory_search", "user_profile"]

    def test_default_registry_is_unchanged(self) -> None:
        """Sohbetin LLM'e sunduğu tool yüzeyi bu milestone'da DEĞİŞMEMELİ."""
        names = {tool.name for tool in build_default_tool_registry().list_tools()}

        assert names == {"get_time", "get_date", "calculator", "system_status"}

    def test_context_tools_are_read_only(self) -> None:
        assert MemorySearchTool.permission is PermissionLevel.READ
        assert UserProfileTool.permission is PermissionLevel.READ


# ---------------------------------------------------------------------------
# 3. memory_search
# ---------------------------------------------------------------------------


class TestMemorySearchTool:
    def test_returns_matching_memories(self, memory_retrieval: MemoryRetrievalService) -> None:
        tool = MemorySearchTool(retrieval=memory_retrieval)

        result = _run(tool.execute(tool.validate_input({"query": "python"})))

        assert result["query"] == "python"
        assert result["count"] >= 1
        assert any("python" in m["content"].lower() for m in result["memories"])

    def test_respects_the_limit(self, memory_retrieval: MemoryRetrievalService) -> None:
        tool = MemorySearchTool(retrieval=memory_retrieval)

        result = _run(tool.execute(tool.validate_input({"query": "kullanıcı", "limit": 1})))

        assert result["count"] <= 1

    def test_no_match_returns_an_empty_but_valid_result(
        self, memory_retrieval: MemoryRetrievalService
    ) -> None:
        tool = MemorySearchTool(retrieval=memory_retrieval)

        result = _run(tool.execute(tool.validate_input({"query": "kuantumfizikçisi"})))

        assert result["count"] == 0
        assert result["memories"] == []

    def test_rejects_invalid_input(self, memory_retrieval: MemoryRetrievalService) -> None:
        tool = MemorySearchTool(retrieval=memory_retrieval)

        with pytest.raises(ToolInputValidationError):
            tool.validate_input({"query": ""})
        with pytest.raises(ToolInputValidationError):
            tool.validate_input({"query": "x", "limit": 999})
        with pytest.raises(ToolInputValidationError):
            tool.validate_input({"query": "x", "unexpected": 1})


# ---------------------------------------------------------------------------
# 4. user_profile
# ---------------------------------------------------------------------------


class TestUserProfileTool:
    def test_returns_learned_traits(self, user_model: UserModelService) -> None:
        tool = UserProfileTool(user_model=user_model)

        result = _run(tool.execute(tool.validate_input({})))

        assert result["trait_count"] == 1
        assert result["traits"][0]["key"] == "topic:python"
        assert result["traits"][0]["confidence"] == 0.5
        assert "interaction" in result

    def test_min_confidence_filters(self, user_model: UserModelService) -> None:
        tool = UserProfileTool(user_model=user_model)

        result = _run(tool.execute(tool.validate_input({"min_confidence": 0.9})))

        assert result["trait_count"] == 0
        assert result["traits"] == []

    def test_rejects_out_of_range_confidence(self, user_model: UserModelService) -> None:
        tool = UserProfileTool(user_model=user_model)

        with pytest.raises(ToolInputValidationError):
            tool.validate_input({"min_confidence": 2.0})


# ---------------------------------------------------------------------------
# 5-8. Sözleşme uyumu ve izolasyon
# ---------------------------------------------------------------------------


class TestContractCompliance:
    def test_results_survive_the_existing_tool_result_serialisation(
        self, memory_retrieval: MemoryRetrievalService, user_model: UserModelService
    ) -> None:
        """Çıktılar mevcut ToolExecutionResult.as_chat_message() ile taşınabilmeli."""
        registry = build_default_tool_registry()
        register_context_tools(
            registry, memory_retrieval=memory_retrieval, user_model=user_model
        )
        executor = ToolExecutor(registry, allowed_permissions={PermissionLevel.READ})

        for call in (
            ToolCall(name="memory_search", arguments={"query": "python"}),
            ToolCall(name="user_profile", arguments={}),
        ):
            result = _run(executor.execute(call))
            assert result.success is True
            message = result.as_chat_message()
            assert json.loads(message.content)["ok"] is True

    def test_tools_expose_valid_definitions(
        self, memory_retrieval: MemoryRetrievalService, user_model: UserModelService
    ) -> None:
        for tool in (
            MemorySearchTool(retrieval=memory_retrieval),
            UserProfileTool(user_model=user_model),
        ):
            definition = tool.definition
            assert definition.name == tool.name
            assert definition.description
            assert definition.input_schema["type"] == "object"

    def test_tools_do_not_write(
        self, tmp_path: Path, memory_retrieval: MemoryRetrievalService
    ) -> None:
        store = memory_retrieval._store  # type: ignore[attr-defined]
        tool = MemorySearchTool(retrieval=memory_retrieval)
        before = store.count()

        for _ in range(3):
            _run(tool.execute(tool.validate_input({"query": "python"})))

        assert store.count() == before

    def test_tools_depend_on_services_not_concrete_stores(self) -> None:
        source = inspect.getsource(context_tools_module)

        assert "SQLiteMemoryStore" not in source
        assert "SQLiteUserTraitStore" not in source
        assert "import sqlite3" not in source
        assert "._store" not in source
        assert "._trait_store" not in source
