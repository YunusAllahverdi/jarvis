"""Council — servis, Agent ve Chat entegrasyonu.

HİÇBİR TESTTE GERÇEK AĞ ÇAĞRISI YOK.

Kapsam:
SERVICE  tam akış, minimum aday eşiği, chairman hatası, toplam timeout,
         üye yokluğu, asla istisna fırlatmaz
AGENT    kapı, kapalı/açık Council, AgentResult.council, özyineleme yok,
         ToolExecutor sınırı korunur, bounded context
CHAT     Council kapalıyken davranış aynı, başarılı Council VERİ olarak
         enjekte edilir, Chairman metni doğrudan dönmez, hata fallback,
         memory/experience kalıcılığı korunur
SYSTEM   config, provider yaşam döngüsü, import-time yan etki, secret log
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.adapters.llm.base import LLMUnavailableError
from app.agent.context import ContextBuilder
from app.agent.policy import RuleBasedDecisionPolicy
from app.agent.runner import AgentRunner
from app.config.settings import Settings, get_settings
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.council.gate import CouncilGate
from app.council.models import CouncilMember, CouncilRequest, CouncilStatus
from app.main import _build_council_service, create_app
from app.memory.extractor import MemoryExtractor
from app.memory.sqlite_experience_store import SQLiteExperienceStore
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services import council_service as council_service_module
from app.services.agent_service import AgentService
from app.services.conversation import InMemoryConversationStore
from app.services.council_service import CouncilService
from app.services.memory_service import MemoryWriteService
from app.tools.base import PermissionLevel
from app.tools.defaults import build_default_tool_registry
from app.tools.executor import ToolExecutor

_NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class _CouncilProvider:
    """Council aşamalarına göre cevap veren sahte sağlayıcı."""

    def __init__(
        self,
        *,
        answer: str = "Aday cevabı",
        review: dict | None = None,
        chairman: str = "Council sentezi",
        fail: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.answer = answer
        self.review = review or {"rankings": [], "scores": {}, "criticisms": []}
        self.chairman = chairman
        self.fail = fail
        self.delay = delay
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        system = messages[0].content
        if "chairman of an expert council" in system:
            return self.chairman
        if "evaluating anonymous candidate" in system:
            return json.dumps(self.review)
        return self.answer

    async def generate_with_tools(self, messages, tools):  # noqa: ANN001, ANN201
        raise AssertionError("Council tool-calling kullanmamalı")


class _ChatProvider:
    """Sohbet cevabı üreten, mesajları kaydeden sahte sağlayıcı."""

    def __init__(self, reply: str = "Jarvis: tamam.") -> None:
        self._reply = reply
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        response = await self.generate_with_tools(messages, tools=())
        return response.content

    async def generate_with_tools(
        self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]
    ) -> LLMResponse:
        self.calls.append(list(messages))
        return LLMResponse(content=self._reply)


def _members(*providers: _CouncilProvider) -> list[CouncilMember]:
    return [
        CouncilMember(member_id=f"member-{index}", provider=provider)
        for index, provider in enumerate(providers, start=1)
    ]


def _council(*providers: _CouncilProvider, chairman: _CouncilProvider | None = None,
             **overrides: Any) -> CouncilService:
    members = _members(*providers)
    chairman_member = (
        CouncilMember(member_id="chairman", provider=chairman)
        if chairman is not None
        else members[0]
    )
    return CouncilService(members=members, chairman=chairman_member, **overrides)


def _settings(tmp_path: Path, **kwargs: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        app_name="Jarvis Test",
        app_version="test-1",
        environment="test",
        ollama_model="not-used-by-fake",
        memory_db_path=str(tmp_path / "memory.db"),
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _agent(*, council: CouncilService | None = None, gate: CouncilGate | None = None) -> AgentService:
    registry = build_default_tool_registry()
    return AgentService(
        context_builder=ContextBuilder(
            tool_registry=registry,
            allowed_permissions={PermissionLevel.READ},
            conversation_store=InMemoryConversationStore(),
        ),
        policy=RuleBasedDecisionPolicy(),
        runner=AgentRunner(
            tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ})
        ),
        council_service=council,
        council_gate=gate,
    )


def _open_gate(member_count: int = 3) -> CouncilGate:
    return CouncilGate(enabled=True, member_count=member_count, min_candidates=2)


def _systems(sent: list[ChatMessage]) -> list[ChatMessage]:
    return [message for message in sent if message.role == "system"]


# ---------------------------------------------------------------------------
# SERVICE
# ---------------------------------------------------------------------------


class TestCouncilService:
    def test_full_deliberation_completes(self) -> None:
        service = _council(
            _CouncilProvider(answer="A", review={"rankings": ["B", "C"], "scores": {}, "criticisms": []}),
            _CouncilProvider(answer="B", review={"rankings": ["A", "C"], "scores": {}, "criticisms": []}),
            _CouncilProvider(answer="C", review={"rankings": ["A", "B"], "scores": {}, "criticisms": []}),
        )

        result = _run(service.deliberate(CouncilRequest(task="Görev")))

        assert result.status is CouncilStatus.COMPLETED
        assert result.ok is True
        assert result.final_answer == "Council sentezi"
        assert len(result.successful_candidates) == 3
        assert len(result.reviews) == 3

    def test_one_failed_member_still_completes(self) -> None:
        service = _council(
            _CouncilProvider(answer="A"),
            _CouncilProvider(fail=LLMUnavailableError("down")),
            _CouncilProvider(answer="C"),
        )

        result = _run(service.deliberate(CouncilRequest(task="Görev")))

        assert result.status is CouncilStatus.COMPLETED
        assert len(result.successful_candidates) == 2

    def test_below_minimum_candidates_is_insufficient(self) -> None:
        service = _council(
            _CouncilProvider(answer="A"),
            _CouncilProvider(fail=LLMUnavailableError("down")),
            _CouncilProvider(fail=LLMUnavailableError("down")),
            min_candidates=2,
        )

        result = _run(service.deliberate(CouncilRequest(task="Görev")))

        assert result.status is CouncilStatus.INSUFFICIENT
        assert result.final_answer is None
        assert result.failure_reason == "insufficient_candidates"

    def test_chairman_failure_returns_failed_not_a_candidate(self) -> None:
        """Chairman düşerse en yüksek skorlu aday kullanıcıya VERİLMEZ."""
        service = _council(
            _CouncilProvider(answer="A cevabı"),
            _CouncilProvider(answer="B cevabı"),
            chairman=_CouncilProvider(fail=LLMUnavailableError("chairman down")),
        )

        result = _run(service.deliberate(CouncilRequest(task="Görev")))

        assert result.status is CouncilStatus.FAILED
        assert result.final_answer is None
        assert result.failure_reason == "chairman_failed"
        assert "A cevabı" not in (result.final_answer or "")

    def test_total_timeout_is_enforced(self) -> None:
        service = _council(
            _CouncilProvider(delay=1.0),
            _CouncilProvider(delay=1.0),
            total_timeout_seconds=0.05,
            member_timeout_seconds=5.0,
        )

        result = _run(service.deliberate(CouncilRequest(task="Görev")))

        assert result.status is CouncilStatus.FAILED
        assert result.failure_reason == "total_timeout"

    def test_no_members_fails_cleanly(self) -> None:
        service = CouncilService(
            members=[],
            chairman=CouncilMember(member_id="chairman", provider=_CouncilProvider()),
        )

        result = _run(service.deliberate(CouncilRequest(task="Görev")))

        assert result.status is CouncilStatus.FAILED
        assert result.failure_reason == "no_members"

    def test_review_stage_can_be_disabled(self) -> None:
        providers = [_CouncilProvider(answer="A"), _CouncilProvider(answer="B")]
        service = _council(*providers, review_enabled=False)

        result = _run(service.deliberate(CouncilRequest(task="Görev")))

        assert result.status is CouncilStatus.COMPLETED
        assert result.reviews == []
        # Yalnızca Stage 1 + Chairman: ilk üye iki kez çağrılır (aday + chairman).
        assert len(providers[1].calls) == 1

    def test_service_never_raises(self) -> None:
        class _Exploding:
            async def generate(self, messages):  # noqa: ANN001, ANN201
                raise RuntimeError("boom")

            async def generate_with_tools(self, messages, tools):  # noqa: ANN001, ANN201
                raise RuntimeError("boom")

        service = _council(_Exploding(), _Exploding())  # type: ignore[arg-type]

        result = _run(service.deliberate(CouncilRequest(task="Görev")))

        assert result.status is CouncilStatus.INSUFFICIENT

    def test_service_never_imports_tool_or_agent_layers(self) -> None:
        source = inspect.getsource(council_service_module)

        for forbidden in (
            "from app.tools", "import app.tools",
            "from app.agent", "import app.agent",
            "from app.services.agent_service", "AgentRunner(",
        ):
            assert forbidden not in source


# ---------------------------------------------------------------------------
# AGENT
# ---------------------------------------------------------------------------


class TestAgentIntegration:
    def test_council_does_not_run_without_a_gate(self) -> None:
        """Kapısız bir Council her mesajda çalışırdı — engellenmeli."""
        result = _run(_agent(council=_council(_CouncilProvider(), _CouncilProvider())).run("merhaba"))

        assert result.council is None

    def test_council_does_not_run_when_the_gate_is_closed(self) -> None:
        agent = _agent(council=_council(_CouncilProvider(), _CouncilProvider()), gate=_open_gate())

        result = _run(agent.run("merhaba nasılsın"))

        assert result.council is None

    def test_council_runs_on_an_explicit_request(self) -> None:
        agent = _agent(
            council=_council(_CouncilProvider(answer="A"), _CouncilProvider(answer="B")),
            gate=_open_gate(),
        )

        result = _run(agent.run("bunu council ile cevapla"))

        assert result.council is not None
        assert result.council.status is CouncilStatus.COMPLETED
        assert result.council.final_answer == "Council sentezi"

    def test_council_is_absent_when_no_service_is_wired(self) -> None:
        result = _run(_agent().run("bunu council ile cevapla"))

        assert result.council is None

    def test_council_failure_leaves_the_agent_result_usable(self) -> None:
        agent = _agent(
            council=_council(
                _CouncilProvider(answer="A"),
                _CouncilProvider(answer="B"),
                chairman=_CouncilProvider(fail=LLMUnavailableError("down")),
            ),
            gate=_open_gate(),
        )

        result = _run(agent.run("council kullan"))

        assert result.council is not None
        assert result.council.status is CouncilStatus.FAILED
        assert result.decision is not None  # agent sonucu hâlâ geçerli

    def test_exploding_council_does_not_break_the_agent(self) -> None:
        class _RaisingCouncil:
            async def deliberate(self, request, *, trigger=None):  # noqa: ANN001, ANN201
                raise RuntimeError("council boom")

        agent = _agent(council=_RaisingCouncil(), gate=_open_gate())  # type: ignore[arg-type]

        result = _run(agent.run("council kullan"))

        assert result.council is None
        assert result.decision is not None

    def test_council_receives_bounded_context_not_agent_objects(self) -> None:
        provider = _CouncilProvider(answer="A")
        agent = _agent(council=_council(provider, _CouncilProvider(answer="B")), gate=_open_gate())

        _run(agent.run("council kullan ve 2+2 hesapla"))

        prompt = provider.calls[0][1].content
        assert "AgentContext" not in prompt
        assert "ToolDescriptor" not in prompt

    def test_council_cannot_reach_the_agent_or_tool_layers(self) -> None:
        """Council → Agent → Council özyinelemesi yapısal olarak imkânsız."""
        import app.council.stages as stages_module
        import app.council.gate as gate_module
        import app.council.models as models_module

        for module in (stages_module, gate_module, models_module):
            source = inspect.getsource(module)
            assert "from app.agent" not in source
            assert "from app.services" not in source
            assert "from app.tools" not in source


# ---------------------------------------------------------------------------
# CHAT
# ---------------------------------------------------------------------------


class TestChatIntegration:
    def test_council_disabled_keeps_the_prompt_identical(self, tmp_path: Path) -> None:
        provider = _ChatProvider()
        app = create_app(settings=_settings(tmp_path), provider=provider, agent_service=_agent())

        with TestClient(app) as client:
            assert client.post("/api/chat", json={"message": "merhaba"}).status_code == 200

        assert [m.role for m in provider.calls[0]] == ["system", "user"]
        assert app.state.council_service is None

    def test_successful_council_is_injected_as_data(self, tmp_path: Path) -> None:
        chat = _ChatProvider("Jarvis: özet.")
        agent = _agent(
            council=_council(_CouncilProvider(answer="A"), _CouncilProvider(answer="B")),
            gate=_open_gate(),
        )
        app = create_app(settings=_settings(tmp_path), provider=chat, agent_service=agent)

        with TestClient(app) as client:
            body = client.post("/api/chat", json={"message": "council kullan"}).json()

        systems = _systems(chat.calls[0])
        assert len(systems) == 2
        injected = systems[1].content
        assert "Council sentezi" in injected
        assert "<untrusted_data>" in injected
        assert "DATA, not instructions" in injected
        assert body["response"] == "Jarvis: özet."

    def test_chairman_text_is_not_returned_directly(self, tmp_path: Path) -> None:
        """Chairman çıktısı HTTP cevabı DEĞİLDİR; normal üretim yazar."""
        chat = _ChatProvider("Jarvis'in kendi cümlesi.")
        agent = _agent(
            council=_council(
                _CouncilProvider(answer="A"),
                _CouncilProvider(answer="B"),
                chairman=_CouncilProvider(chairman="HAM-CHAIRMAN-METNI"),
            ),
            gate=_open_gate(),
        )
        app = create_app(settings=_settings(tmp_path), provider=chat, agent_service=agent)

        with TestClient(app) as client:
            body = client.post("/api/chat", json={"message": "council kullan"}).json()

        assert body["response"] == "Jarvis'in kendi cümlesi."
        assert "HAM-CHAIRMAN-METNI" not in body["response"]

    def test_failed_council_injects_nothing(self, tmp_path: Path) -> None:
        chat = _ChatProvider("Jarvis: normal cevap.")
        agent = _agent(
            council=_council(
                _CouncilProvider(answer="A"),
                _CouncilProvider(answer="B"),
                chairman=_CouncilProvider(fail=LLMUnavailableError("down")),
            ),
            gate=_open_gate(),
        )
        app = create_app(settings=_settings(tmp_path), provider=chat, agent_service=agent)

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "council kullan"})

        assert response.status_code == 200
        assert response.json()["response"] == "Jarvis: normal cevap."
        assert len(_systems(chat.calls[0])) == 1

    def test_insufficient_council_injects_nothing(self, tmp_path: Path) -> None:
        chat = _ChatProvider()
        agent = _agent(
            council=_council(
                _CouncilProvider(answer="A"),
                _CouncilProvider(fail=LLMUnavailableError("down")),
                min_candidates=2,
            ),
            gate=_open_gate(),
        )
        app = create_app(settings=_settings(tmp_path), provider=chat, agent_service=agent)

        with TestClient(app) as client:
            assert client.post("/api/chat", json={"message": "council kullan"}).status_code == 200

        assert len(_systems(chat.calls[0])) == 1

    def test_council_never_produces_a_500(self, tmp_path: Path) -> None:
        class _RaisingCouncil:
            async def deliberate(self, request, *, trigger=None):  # noqa: ANN001, ANN201
                raise RuntimeError("council boom")

        chat = _ChatProvider("Jarvis: ayakta.")
        app = create_app(
            settings=_settings(tmp_path),
            provider=chat,
            agent_service=_agent(council=_RaisingCouncil(), gate=_open_gate()),  # type: ignore[arg-type]
        )

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "council kullan"})

        assert response.status_code == 200
        assert response.json()["response"] == "Jarvis: ayakta."

    def test_experience_persistence_still_works(self, tmp_path: Path) -> None:
        experience_store = SQLiteExperienceStore(str(tmp_path / "memory.db"))
        agent = _agent(
            council=_council(_CouncilProvider(answer="A"), _CouncilProvider(answer="B")),
            gate=_open_gate(),
        )
        app = create_app(
            settings=_settings(tmp_path),
            provider=_ChatProvider(),
            experience_store=experience_store,
            agent_service=agent,
        )

        with TestClient(app) as client:
            client.post("/api/chat", json={"message": "council kullan"})

        assert experience_store.count() == 1

    def test_memory_persistence_still_works(self, tmp_path: Path) -> None:
        class _FakeMemoryLLM:
            async def generate(self, messages):  # noqa: ANN001, ANN201
                return json.dumps(
                    {
                        "memories": [
                            {
                                "memory_type": "fact",
                                "content": "The user lives in Istanbul.",
                                "temporality": "present",
                                "status": "active",
                            }
                        ]
                    }
                )

            async def generate_with_tools(self, messages, tools):  # noqa: ANN001, ANN201
                raise AssertionError

        store = SQLiteMemoryStore(str(tmp_path / "memory.db"))
        agent = _agent(
            council=_council(_CouncilProvider(answer="A"), _CouncilProvider(answer="B")),
            gate=_open_gate(),
        )
        app = create_app(
            settings=_settings(tmp_path),
            provider=_ChatProvider(),
            memory_service=MemoryWriteService(
                extractor=MemoryExtractor(provider=_FakeMemoryLLM()), store=store
            ),
            agent_service=agent,
        )

        with TestClient(app) as client:
            client.post("/api/chat", json={"message": "council kullan, I live in Istanbul."})

        assert store.count() == 1


# ---------------------------------------------------------------------------
# SYSTEM
# ---------------------------------------------------------------------------


class TestSystemWiring:
    def test_council_is_disabled_by_default(self) -> None:
        settings = Settings(environment="test")

        assert settings.council_enabled is False
        assert settings.council_models == []

    def test_disabled_council_builds_nothing(self, tmp_path: Path) -> None:
        service, providers = _build_council_service(_settings(tmp_path))

        assert service is None
        assert providers == []

    def test_insufficient_models_build_nothing(self, tmp_path: Path) -> None:
        settings = _settings(
            tmp_path, council_enabled=True, council_models=["only-one"], council_min_candidates=2
        )

        service, providers = _build_council_service(settings)

        assert service is None
        assert providers == []

    def test_one_provider_per_model_is_created(self, tmp_path: Path) -> None:
        settings = _settings(
            tmp_path, council_enabled=True, council_models=["m-a", "m-b", "m-c"]
        )

        service, providers = _build_council_service(settings)

        assert service is not None
        assert service.member_count == 3
        assert len(providers) == 3

    def test_chairman_reuses_a_member_provider_when_models_match(self, tmp_path: Path) -> None:
        """Aynı model için ikinci bir HTTP istemcisi açılmamalı."""
        settings = _settings(
            tmp_path,
            council_enabled=True,
            council_models=["m-a", "m-b"],
            council_chairman_model="m-b",
        )

        service, providers = _build_council_service(settings)

        assert service is not None
        assert len(providers) == 2  # ek chairman istemcisi yok

    def test_distinct_chairman_model_gets_its_own_provider(self, tmp_path: Path) -> None:
        settings = _settings(
            tmp_path,
            council_enabled=True,
            council_models=["m-a", "m-b"],
            council_chairman_model="m-judge",
        )

        service, providers = _build_council_service(settings)

        assert service is not None
        assert len(providers) == 3

    def test_max_members_truncates_the_configured_list(self, tmp_path: Path) -> None:
        settings = _settings(
            tmp_path,
            council_enabled=True,
            council_models=["a", "b", "c", "d", "e"],
            council_max_members=2,
        )

        service, _ = _build_council_service(settings)

        assert service is not None
        assert service.member_count == 2

    def test_duplicate_models_are_deduplicated(self) -> None:
        settings = Settings(environment="test", council_models=["a", "a", " b ", ""])

        assert settings.council_models == ["a", "b"]

    def test_all_providers_are_closed_on_shutdown(self, tmp_path: Path) -> None:
        closed: list[str] = []

        class _Closable:
            def __init__(self, name: str) -> None:
                self.name = name

            async def generate(self, messages):  # noqa: ANN001, ANN201
                return "x"

            async def generate_with_tools(self, messages, tools):  # noqa: ANN001, ANN201
                raise AssertionError

            async def aclose(self) -> None:
                closed.append(self.name)

        chat_provider = _Closable("chat")
        app = create_app(settings=_settings(tmp_path), provider=chat_provider)
        # `app.state.council_providers`, lifespan'ın kapattığı listenin TA
        # KENDİSİDİR; buraya eklenen bir sağlayıcı da kapatılır.
        app.state.council_providers.extend([_Closable("council-1"), _Closable("council-2")])

        with TestClient(app):
            pass

        assert closed == ["chat", "council-1", "council-2"]

    def test_a_failing_close_does_not_block_the_others(self, tmp_path: Path) -> None:
        closed: list[str] = []

        class _Closable:
            def __init__(self, name: str, *, fail: bool = False) -> None:
                self.name, self.fail = name, fail

            async def generate(self, messages):  # noqa: ANN001, ANN201
                return "x"

            async def generate_with_tools(self, messages, tools):  # noqa: ANN001, ANN201
                raise AssertionError

            async def aclose(self) -> None:
                if self.fail:
                    raise RuntimeError("close boom")
                closed.append(self.name)

        app = create_app(settings=_settings(tmp_path), provider=_Closable("chat"))
        app.state.council_providers.extend(
            [_Closable("bad", fail=True), _Closable("council-2")]
        )

        with TestClient(app):
            pass

        assert closed == ["chat", "council-2"]

    def test_lifespan_closes_council_providers_built_from_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        closed: list[str] = []

        class _Recording:
            def __init__(self, **kwargs: Any) -> None:
                self.model = kwargs.get("model")

            async def generate(self, messages):  # noqa: ANN001, ANN201
                return "x"

            async def generate_with_tools(self, messages, tools):  # noqa: ANN001, ANN201
                raise AssertionError

            async def aclose(self) -> None:
                closed.append(self.model)

        import app.main as main_module

        monkeypatch.setattr(main_module, "OllamaProvider", _Recording)
        app = main_module.create_app(
            settings=_settings(
                tmp_path, council_enabled=True, council_models=["m-a", "m-b"]
            )
        )

        with TestClient(app):
            assert len(app.state.council_providers) == 2

        # Sohbet sağlayıcısı VE iki Council sağlayıcısının tamamı kapatılmalı;
        # hiçbir HTTP istemcisi sızdırılmamalı.
        assert sorted(closed) == ["m-a", "m-b", "not-used-by-fake"]

    def test_importing_app_main_has_no_side_effects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "import_side_effect.db"
        monkeypatch.setenv("JARVIS_MEMORY_DB_PATH", str(db_path))
        monkeypatch.setenv("JARVIS_ENVIRONMENT", "test")
        get_settings.cache_clear()

        import app.main as main_module

        try:
            import importlib

            importlib.reload(main_module)

            assert not db_path.exists()
            assert main_module.app.state.council_service is None
            assert main_module.app.state.council_providers == []
        finally:
            get_settings.cache_clear()
            import importlib

            importlib.reload(main_module)

    def test_no_secret_appears_in_council_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        secret = "sk-council-secret-key-9876543210"
        service = _council(
            _CouncilProvider(answer="A"),
            _CouncilProvider(fail=LLMUnavailableError("down")),
            min_candidates=2,
        )

        with caplog.at_level(logging.DEBUG):
            _run(service.deliberate(CouncilRequest(task=f"anahtarım {secret}")))

        combined = "\n".join(
            record.getMessage() + str(record.__dict__) for record in caplog.records
        )
        assert secret not in combined
