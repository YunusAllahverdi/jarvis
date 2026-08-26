"""Agent katmanı — servis cephesi, API ve uygulama bağlama (wiring).

Kapsam:
 1. AgentService zinciri uçtan uca çalıştırır
 2. Politika hatası kontrollü geri çekilmeye düşer (fallback)
 3. Bağlam hatası kontrollü geri çekilmeye düşer
 4. Runner hatası yapılandırılmış FAILED sonucu üretir
 5. decide() yürütmez, run() yürütür
 6. POST /api/agent/decide ve /run yapılandırılmış yanıt döner
 7. GET /api/agent/tools tool keşfi sağlar
 8. Agent bağlı değilken uçlar 503 + `code` döner
 9. Geçersiz istekler 422 döner
10. Varsayılan sağlayıcı ile lifespan agent'ı otomatik kurar
11. Enjekte edilen sağlayıcı veritabanı oluşturmaz
12. `app.main` importu yan etki üretmez
13. Sohbet akışı DEĞİŞMEDİ (agent chat yolunda değil)
14. Agent hatası sohbeti bozamaz
15. Uçtan uca: gerçek depolarla çok adımlı hatırlama planı
16. Yürütme veritabanını bozmaz
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.context import ContextBuilder
from app.agent.models import AgentStatus, Intent
from app.agent.policy import RuleBasedDecisionPolicy
from app.agent.runner import AgentRunner
from app.config.settings import Settings, get_settings
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.learning.sqlite_trait_store import SQLiteUserTraitStore
from app.learning.trait import TraitSource, TraitType, UserTrait
from app.main import create_app
from app.memory.record import MemoryRecord, MemoryType
from app.memory.sqlite_experience_store import SQLiteExperienceStore
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services.agent_service import AgentService
from app.services.conversation import InMemoryConversationStore
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.user_model_service import UserModelService
from app.tools.base import PermissionLevel
from app.tools.defaults import build_default_tool_registry, register_context_tools
from app.tools.executor import ToolExecutor

_NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class _FakeChatProvider:
    def __init__(self, reply: str = "Jarvis: ok") -> None:
        self._reply = reply
        self.calls: list[list[ChatMessage]] = []
        self.tool_definitions: list[list[ToolDefinition]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        response = await self.generate_with_tools(messages, tools=())
        return response.content

    async def generate_with_tools(
        self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]
    ) -> LLMResponse:
        self.calls.append(list(messages))
        self.tool_definitions.append(list(tools))
        return LLMResponse(content=self._reply)


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


def _build_agent(
    *,
    memory_retrieval: MemoryRetrievalService | None = None,
    user_model: UserModelService | None = None,
    experience_store: Any | None = None,
    allowed: set[PermissionLevel] | None = None,
) -> AgentService:
    permissions = allowed if allowed is not None else {PermissionLevel.READ}
    registry = build_default_tool_registry()
    register_context_tools(registry, memory_retrieval=memory_retrieval, user_model=user_model)
    return AgentService(
        context_builder=ContextBuilder(
            tool_registry=registry,
            allowed_permissions=permissions,
            conversation_store=InMemoryConversationStore(),
            memory_retrieval=memory_retrieval,
            experience_store=experience_store,
            user_model=user_model,
        ),
        policy=RuleBasedDecisionPolicy(),
        runner=AgentRunner(
            tool_executor=ToolExecutor(registry, allowed_permissions=permissions)
        ),
    )


# ---------------------------------------------------------------------------
# 1-5. AgentService
# ---------------------------------------------------------------------------


class TestAgentService:
    def test_run_executes_the_whole_chain(self) -> None:
        result = _run(_build_agent().run("25 * 17"))

        assert result.decision.intent is Intent.CALCULATE
        assert result.status is AgentStatus.COMPLETED
        assert result.outcomes[0].data["result"] == 425

    def test_decide_does_not_execute(self) -> None:
        decision = _run(_build_agent().decide("25 * 17"))

        assert decision.intent is Intent.CALCULATE
        assert decision.actions[0].tool_name == "calculator"
        # Karar nesnesinde hiçbir yürütme sonucu yoktur.
        assert not hasattr(decision, "outcomes")

    def test_conversation_message_produces_no_action(self) -> None:
        result = _run(_build_agent().run("bana bir şiir yaz"))

        assert result.decision.intent is Intent.CONVERSATION
        assert result.status is AgentStatus.NO_ACTION
        assert result.ok is True

    def test_policy_failure_falls_back_instead_of_raising(self) -> None:
        class _RaisingPolicy:
            name = "raising"

            async def decide(self, context):  # noqa: ANN001, ANN201
                raise RuntimeError("policy boom")

        service = _build_agent()
        service._policy = _RaisingPolicy()  # type: ignore[assignment]

        decision = _run(service.decide("25 * 17"))
        result = _run(service.run("25 * 17"))

        assert decision.intent is Intent.UNKNOWN
        assert result.decision.intent is Intent.UNKNOWN
        assert result.status is AgentStatus.FAILED

    def test_context_failure_falls_back_instead_of_raising(self) -> None:
        class _RaisingBuilder:
            def build(self, message, *, session_id=None, now=None):  # noqa: ANN001
                raise RuntimeError("context boom")

        service = _build_agent()
        service._context_builder = _RaisingBuilder()  # type: ignore[assignment]

        assert _run(service.decide("25 * 17")).intent is Intent.UNKNOWN
        assert _run(service.run("25 * 17")).status is AgentStatus.FAILED

    def test_runner_failure_returns_structured_failure(self) -> None:
        class _RaisingRunner:
            async def execute(self, decision):  # noqa: ANN001, ANN201
                raise RuntimeError("runner boom")

        service = _build_agent()
        service._runner = _RaisingRunner()  # type: ignore[assignment]

        result = _run(service.run("25 * 17"))

        assert result.status is AgentStatus.FAILED
        # Karar korunur — neyin denendiği görünür kalır.
        assert result.decision.intent is Intent.CALCULATE

    def test_confirmation_required_plan_is_not_executed(self) -> None:
        result = _run(_build_agent(allowed=set()).run("25 * 17"))

        assert result.status is AgentStatus.PENDING_CONFIRMATION
        assert all(o.skipped for o in result.outcomes)


# ---------------------------------------------------------------------------
# 6-9. API
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    db = str(tmp_path / "memory.db")
    memory_store = SQLiteMemoryStore(db)
    memory_store.add(
        MemoryRecord(memory_type=MemoryType.FACT, content="Kullanıcı python kullanıyor.")
    )
    trait_store = SQLiteUserTraitStore(db)
    trait_store.upsert(
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
    agent = _build_agent(
        memory_retrieval=MemoryRetrievalService(store=memory_store),
        user_model=UserModelService(trait_store=trait_store),
        experience_store=SQLiteExperienceStore(db),
    )
    return create_app(
        settings=_make_settings(tmp_path), provider=_FakeChatProvider(), agent_service=agent
    )


class TestAgentEndpoints:
    def test_decide_endpoint_returns_a_structured_decision(self, agent_app) -> None:  # type: ignore[no-untyped-def]
        with TestClient(agent_app) as client:
            response = client.post("/api/agent/decide", json={"message": "25 * 17"})

        assert response.status_code == 200
        body = response.json()
        assert body["intent"] == "calculate"
        assert body["policy"] == "rule_based"
        assert body["requires_confirmation"] is False
        assert body["actions"][0]["tool_name"] == "calculator"
        assert body["reason"]

    def test_run_endpoint_executes_and_returns_outcomes(self, agent_app) -> None:  # type: ignore[no-untyped-def]
        with TestClient(agent_app) as client:
            response = client.post("/api/agent/run", json={"message": "25 * 17"})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["outcomes"][0]["success"] is True
        assert body["outcomes"][0]["data"]["result"] == 425

    def test_run_endpoint_handles_a_multi_step_recall(self, agent_app) -> None:  # type: ignore[no-untyped-def]
        with TestClient(agent_app) as client:
            response = client.post(
                "/api/agent/run", json={"message": "hakkımda ne biliyorsun?"}
            )

        body = response.json()
        assert body["decision"]["intent"] == "recall"
        assert [a["tool_name"] for a in body["decision"]["actions"]] == [
            "memory_search",
            "user_profile",
        ]
        assert body["status"] == "completed"
        assert len(body["outcomes"]) == 2

    def test_tools_endpoint_lists_available_tools(self, agent_app) -> None:  # type: ignore[no-untyped-def]
        with TestClient(agent_app) as client:
            response = client.get("/api/agent/tools")

        assert response.status_code == 200
        body = response.json()
        names = {tool["name"] for tool in body["tools"]}
        assert {"calculator", "memory_search", "user_profile"} <= names
        assert body["count"] == len(body["tools"])
        assert all(tool["permission"] == "READ" for tool in body["tools"])

    def test_conversation_message_returns_no_action(self, agent_app) -> None:  # type: ignore[no-untyped-def]
        with TestClient(agent_app) as client:
            response = client.post("/api/agent/run", json={"message": "bana şiir yaz"})

        body = response.json()
        assert body["decision"]["intent"] == "conversation"
        assert body["status"] == "no_action"
        assert body["outcomes"] == []

    def test_endpoints_return_503_when_the_agent_is_not_wired(self, tmp_path: Path) -> None:
        app = create_app(settings=_make_settings(tmp_path), provider=_FakeChatProvider())

        with TestClient(app) as client:
            for response in (
                client.post("/api/agent/decide", json={"message": "x"}),
                client.post("/api/agent/run", json={"message": "x"}),
                client.get("/api/agent/tools"),
            ):
                assert response.status_code == 503
                assert response.json()["detail"]["code"] == "agent_unavailable"

    def test_invalid_requests_are_rejected(self, agent_app) -> None:  # type: ignore[no-untyped-def]
        with TestClient(agent_app) as client:
            assert client.post("/api/agent/run", json={"message": "   "}).status_code == 422
            assert client.post("/api/agent/run", json={}).status_code == 422
            assert (
                client.post(
                    "/api/agent/run", json={"message": "x", "session_id": "  "}
                ).status_code
                == 422
            )


# ---------------------------------------------------------------------------
# 10-12. Uygulama bağlama
# ---------------------------------------------------------------------------


class TestApplicationWiring:
    def test_create_app_alone_does_not_build_the_agent(self, tmp_path: Path) -> None:
        app = create_app(settings=_make_settings(tmp_path))

        assert app.state.agent_service is None

    def test_default_provider_auto_wires_the_agent_on_startup(self, tmp_path: Path) -> None:
        app = create_app(settings=_make_settings(tmp_path))

        with TestClient(app):
            assert isinstance(app.state.agent_service, AgentService)

    def test_auto_wired_agent_receives_the_context_sources(self, tmp_path: Path) -> None:
        app = create_app(settings=_make_settings(tmp_path))

        with TestClient(app):
            builder = app.state.agent_service._context_builder
            assert builder._memory_retrieval is app.state.memory_retrieval
            assert builder._experience_store is app.state.experience_store
            assert builder._user_model is app.state.user_model_service

    def test_auto_wired_agent_has_the_context_tools(self, tmp_path: Path) -> None:
        app = create_app(settings=_make_settings(tmp_path))

        with TestClient(app) as client:
            names = {tool["name"] for tool in client.get("/api/agent/tools").json()["tools"]}

        assert {"memory_search", "user_profile"} <= names

    def test_explicit_agent_prevents_auto_wiring(self, tmp_path: Path) -> None:
        custom = _build_agent()
        app = create_app(settings=_make_settings(tmp_path), agent_service=custom)

        assert app.state.agent_service is custom
        with TestClient(app):
            assert app.state.agent_service is custom

    def test_injected_provider_creates_no_database(self, tmp_path: Path) -> None:
        db_path = tmp_path / "should_not_exist.db"
        app = create_app(
            settings=_make_settings(tmp_path, memory_db_path=str(db_path)),
            provider=_FakeChatProvider(),
        )

        with TestClient(app):
            assert app.state.agent_service is None

        assert not db_path.exists()

    def test_importing_app_main_creates_no_database(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "import_side_effect.db"
        monkeypatch.setenv("JARVIS_MEMORY_DB_PATH", str(db_path))
        monkeypatch.setenv("JARVIS_ENVIRONMENT", "test")
        get_settings.cache_clear()

        import app.main as main_module

        try:
            importlib.reload(main_module)

            assert not db_path.exists()
            assert main_module.app.state.agent_service is None

            with TestClient(main_module.app):
                assert isinstance(main_module.app.state.agent_service, AgentService)
        finally:
            get_settings.cache_clear()
            importlib.reload(main_module)


# ---------------------------------------------------------------------------
# 13-14. Sohbet akışı korunur
# ---------------------------------------------------------------------------


class TestChatRemainsUnaffected:
    def test_orchestrator_has_no_reference_to_the_agent(self) -> None:
        import app.services.orchestrator as orchestrator_module

        source = inspect.getsource(orchestrator_module)

        assert "AgentService" not in source
        assert "agent" not in source.lower()
        assert "DecisionPolicy" not in source

    def test_chat_tool_surface_is_unchanged_by_the_agent(self, tmp_path: Path) -> None:
        """Agent'ın tool'ları LLM'in sohbette gördüğü yüzeye SIZMAMALI."""
        provider = _FakeChatProvider()
        app = create_app(
            settings=_make_settings(tmp_path), provider=provider, agent_service=_build_agent(
                memory_retrieval=MemoryRetrievalService(
                    store=SQLiteMemoryStore(str(tmp_path / "memory.db"))
                )
            )
        )

        with TestClient(app) as client:
            assert client.post("/api/chat", json={"message": "merhaba"}).status_code == 200

        offered = {definition.name for definition in provider.tool_definitions[0]}
        assert offered == {"get_time", "get_date", "calculator", "system_status"}
        assert "memory_search" not in offered

    def test_chat_works_while_the_agent_is_broken(self, tmp_path: Path) -> None:
        class _BrokenAgent:
            async def decide(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
                raise RuntimeError("agent down")

            async def run(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
                raise RuntimeError("agent down")

            def build_context(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
                raise RuntimeError("agent down")

        app = create_app(
            settings=_make_settings(tmp_path),
            provider=_FakeChatProvider("Jarvis: hâlâ ayakta."),
            agent_service=_BrokenAgent(),  # type: ignore[arg-type]
        )

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "merhaba"})

        assert response.status_code == 200
        assert response.json()["response"] == "Jarvis: hâlâ ayakta."

    def test_existing_endpoints_still_work(self, agent_app) -> None:  # type: ignore[no-untyped-def]
        with TestClient(agent_app) as client:
            assert client.get("/api/v1/health").status_code == 200
            assert client.get("/").status_code == 200
            assert client.post("/api/chat", json={"message": "merhaba"}).status_code == 200


# ---------------------------------------------------------------------------
# 15-16. Uçtan uca ve veri bütünlüğü
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_recall_plan_reads_real_memory_and_user_model(self, tmp_path: Path) -> None:
        db = str(tmp_path / "memory.db")
        memory_store = SQLiteMemoryStore(db)
        memory_store.add(
            MemoryRecord(memory_type=MemoryType.FACT, content="Kullanıcı python öğreniyor.")
        )
        trait_store = SQLiteUserTraitStore(db)
        trait_store.upsert(
            UserTrait(
                trait_type=TraitType.INTEREST,
                key="topic:python",
                value="python",
                evidence_count=6,
                confidence=0.6,
                source=TraitSource.EXPERIENCE,
                first_observed_at=_NOW,
                last_observed_at=_NOW,
            )
        )
        agent = _build_agent(
            memory_retrieval=MemoryRetrievalService(store=memory_store),
            user_model=UserModelService(trait_store=trait_store),
        )

        result = _run(agent.run("python hakkında ne biliyorsun?"))

        assert result.status is AgentStatus.COMPLETED
        memory_outcome, profile_outcome = result.outcomes
        assert memory_outcome.data["count"] >= 1
        assert "python" in memory_outcome.data["memories"][0]["content"].lower()
        assert profile_outcome.data["traits"][0]["key"] == "topic:python"

    def test_running_the_agent_does_not_modify_stored_data(self, tmp_path: Path) -> None:
        db = str(tmp_path / "memory.db")
        memory_store = SQLiteMemoryStore(db)
        memory_store.add(MemoryRecord(content="python"))
        trait_store = SQLiteUserTraitStore(db)
        experience_store = SQLiteExperienceStore(db)
        agent = _build_agent(
            memory_retrieval=MemoryRetrievalService(store=memory_store),
            user_model=UserModelService(trait_store=trait_store),
            experience_store=experience_store,
        )
        before = (memory_store.count(), trait_store.count(), experience_store.count())

        for message in ("25 * 17", "ne biliyorsun?", "saat kaç", "şiir yaz"):
            _run(agent.run(message))

        assert (memory_store.count(), trait_store.count(), experience_store.count()) == before
        assert [p.name for p in tmp_path.glob("*.db")] == ["memory.db"]
