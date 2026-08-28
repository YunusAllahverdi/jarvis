"""Agent katmanı — yürütme sınırı ve hata izolasyonu.

Kapsam:
 1. Başarılı tek adım yürütmesi
 2. Çok adımlı plan sırayla yürütülür
 3. Bilinmeyen tool planı çökertmez
 4. Patlayan tool planı çökertmez ve diğer adımları etkilemez
 5. Geçersiz argümanlar yapılandırılmış hataya çevrilir
 6. İzin reddi yapılandırılmış hataya çevrilir
 7. Onay gerektiren planda HİÇBİR eylem çalışmaz
 8. Eylemsiz karar NO_ACTION üretir
 9. Runner ayrı bir tool mekanizması icat etmez (ToolExecutor kullanılır)
10. Yürütme uygulama durumunu bozmaz
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path

from app.agent import runner as runner_module
from app.agent.models import AgentAction, AgentDecision, AgentStatus, Intent
from app.agent.runner import AgentRunner
from app.memory.experience import Experience
from app.memory.record import MemoryRecord
from app.memory.sqlite_experience_store import SQLiteExperienceStore
from app.memory.sqlite_store import SQLiteMemoryStore
from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput
from app.tools.defaults import build_default_tool_registry
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

_NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)


class _ExplodingInput(ToolInput):
    pass


class _ExplodingTool(Tool[_ExplodingInput]):
    """Her çağrıda beklenmedik bir istisna fırlatan tool."""

    name = "exploding_tool"
    description = "Test amaçlı her zaman patlayan tool."
    permission = PermissionLevel.READ
    input_model = _ExplodingInput

    async def execute(self, tool_input: _ExplodingInput) -> dict[str, object]:
        raise RuntimeError("tool boom")


class _ControlledFailureTool(Tool[_ExplodingInput]):
    """Kontrollü bir ToolExecutionError fırlatan tool."""

    name = "controlled_failure"
    description = "Test amaçlı kontrollü hata fırlatan tool."
    permission = PermissionLevel.READ
    input_model = _ExplodingInput

    async def execute(self, tool_input: _ExplodingInput) -> dict[str, object]:
        raise ToolExecutionError("kontrollü hata")


class _WriteTool(Tool[_ExplodingInput]):
    """WRITE izinli, bu oturumda etkin olmayan tool."""

    name = "write_tool"
    description = "Test amaçlı WRITE izinli tool."
    permission = PermissionLevel.WRITE
    input_model = _ExplodingInput

    async def execute(self, tool_input: _ExplodingInput) -> dict[str, object]:
        return {"written": True}


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _runner(registry: ToolRegistry | None = None) -> AgentRunner:
    active = registry if registry is not None else build_default_tool_registry()
    return AgentRunner(
        tool_executor=ToolExecutor(active, allowed_permissions={PermissionLevel.READ})
    )


def _decision(*actions: AgentAction, **overrides: object) -> AgentDecision:
    defaults: dict[str, object] = dict(
        intent=Intent.CALCULATE,
        actions=list(actions),
        reason="test kararı",
        policy="test",
    )
    defaults.update(overrides)
    return AgentDecision(**defaults)  # type: ignore[arg-type]


def _action(tool_name: str, arguments: dict | None = None, **overrides: object) -> AgentAction:
    defaults: dict[str, object] = dict(
        tool_name=tool_name, arguments=arguments or {}, purpose="test adımı"
    )
    defaults.update(overrides)
    return AgentAction(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1-2. Başarılı yürütme
# ---------------------------------------------------------------------------


class TestSuccessfulExecution:
    def test_single_action_executes_and_returns_data(self) -> None:
        result = _run(
            _runner().execute(_decision(_action("calculator", {"expression": "25 * 17"})))
        )

        assert result.status is AgentStatus.COMPLETED
        assert result.ok is True
        assert len(result.outcomes) == 1
        assert result.outcomes[0].success is True
        assert result.outcomes[0].data == {"expression": "25 * 17", "result": 425}

    def test_multi_step_plan_executes_in_order(self) -> None:
        result = _run(
            _runner().execute(
                _decision(
                    _action("calculator", {"expression": "1+1"}),
                    _action("get_time"),
                )
            )
        )

        assert result.status is AgentStatus.COMPLETED
        assert [o.tool_name for o in result.outcomes] == ["calculator", "get_time"]
        assert all(o.success for o in result.outcomes)

    def test_outcome_count_matches_action_count(self) -> None:
        result = _run(
            _runner().execute(
                _decision(*[_action("get_time") for _ in range(4)])
            )
        )

        assert len(result.outcomes) == 4


# ---------------------------------------------------------------------------
# 3-6. Hata izolasyonu
# ---------------------------------------------------------------------------


class TestFailureIsolation:
    def test_unknown_tool_does_not_crash_the_plan(self) -> None:
        result = _run(_runner().execute(_decision(_action("nonexistent_tool"))))

        assert result.status is AgentStatus.FAILED
        assert result.outcomes[0].success is False
        assert result.outcomes[0].error_code == "unknown_tool"

    def test_exploding_tool_does_not_crash_the_plan(self) -> None:
        registry = build_default_tool_registry()
        registry.register(_ExplodingTool())

        result = _run(_runner(registry).execute(_decision(_action("exploding_tool"))))

        assert result.status is AgentStatus.FAILED
        assert result.outcomes[0].error_code == "tool_execution_failed"

    def test_controlled_tool_error_is_structured(self) -> None:
        registry = build_default_tool_registry()
        registry.register(_ControlledFailureTool())

        result = _run(_runner(registry).execute(_decision(_action("controlled_failure"))))

        assert result.outcomes[0].success is False
        assert "kontrollü hata" in (result.outcomes[0].error_message or "")

    def test_invalid_arguments_become_a_structured_error(self) -> None:
        result = _run(_runner().execute(_decision(_action("calculator", {"wrong": "arg"}))))

        assert result.outcomes[0].success is False
        assert result.outcomes[0].error_code == "invalid_arguments"

    def test_permission_denied_becomes_a_structured_error(self) -> None:
        registry = build_default_tool_registry()
        registry.register(_WriteTool())

        result = _run(_runner(registry).execute(_decision(_action("write_tool"))))

        assert result.outcomes[0].success is False
        assert result.outcomes[0].error_code == "permission_denied"

    def test_one_failing_step_does_not_stop_the_others(self) -> None:
        registry = build_default_tool_registry()
        registry.register(_ExplodingTool())

        result = _run(
            _runner(registry).execute(
                _decision(
                    _action("exploding_tool"),
                    _action("calculator", {"expression": "2+2"}),
                    _action("get_time"),
                )
            )
        )

        assert result.status is AgentStatus.PARTIAL
        assert [o.success for o in result.outcomes] == [False, True, True]

    def test_runner_never_raises_even_if_the_executor_misbehaves(self) -> None:
        """ToolExecutor sözleşmeyi ihlal edip patlasa bile plan çökmemeli."""

        class _RaisingExecutor:
            async def execute(self, call):  # noqa: ANN001, ANN201
                raise RuntimeError("executor contract violated")

        runner = AgentRunner(tool_executor=_RaisingExecutor())  # type: ignore[arg-type]

        result = _run(runner.execute(_decision(_action("calculator", {"expression": "1+1"}))))

        assert result.status is AgentStatus.FAILED
        assert result.outcomes[0].error_code == "action_execution_failed"


# ---------------------------------------------------------------------------
# 7. Onay sınırı
# ---------------------------------------------------------------------------


class TestConfirmationBoundary:
    def test_plan_requiring_confirmation_executes_nothing(self) -> None:
        result = _run(
            _runner().execute(
                _decision(_action("calculator", {"expression": "2+2"}, requires_confirmation=True))
            )
        )

        assert result.status is AgentStatus.PENDING_CONFIRMATION
        assert result.outcomes[0].skipped is True
        assert result.outcomes[0].success is False
        assert result.outcomes[0].data is None

    def test_partial_confirmation_blocks_the_whole_plan(self) -> None:
        """Bir adım onay istiyorsa yarım yürütülmüş bir plan oluşmamalı."""
        result = _run(
            _runner().execute(
                _decision(
                    _action("calculator", {"expression": "2+2"}),
                    _action("get_time", requires_confirmation=True),
                )
            )
        )

        assert result.status is AgentStatus.PENDING_CONFIRMATION
        assert all(o.skipped for o in result.outcomes)
        assert all(o.data is None for o in result.outcomes)

    def test_confirmation_result_still_reports_the_full_plan(self) -> None:
        decision = _decision(
            _action("calculator", {"expression": "2+2"}, requires_confirmation=True),
            _action("get_time", requires_confirmation=True),
        )

        result = _run(_runner().execute(decision))

        assert [o.tool_name for o in result.outcomes] == ["calculator", "get_time"]
        assert result.decision.requires_confirmation is True


# ---------------------------------------------------------------------------
# 8-10. Diğer davranışlar
# ---------------------------------------------------------------------------


class TestOtherBehaviour:
    def test_decision_without_actions_is_no_action(self) -> None:
        decision = _decision(intent=Intent.CONVERSATION)

        result = _run(_runner().execute(decision))

        assert result.status is AgentStatus.NO_ACTION
        assert result.outcomes == []
        assert result.ok is True

    def test_runner_reuses_the_existing_tool_executor_boundary(self) -> None:
        """Agent ikinci bir tool çalıştırma mekanizması icat etmemeli."""
        source = inspect.getsource(runner_module)

        assert "ToolExecutor" in source
        assert "validate_input" not in source
        assert "permission" not in source.lower().replace("permissionlevel", "")

    def test_execution_does_not_corrupt_application_state(self, tmp_path: Path) -> None:
        """Tool çalıştırmak Memory/Experience kayıtlarına dokunmamalı."""
        db = str(tmp_path / "memory.db")
        memory_store = SQLiteMemoryStore(db)
        memory_store.add(MemoryRecord(content="python"))
        experience_store = SQLiteExperienceStore(db)
        experience_store.add(
            Experience(
                session_id="s", occurred_at=_NOW, user_message="x", assistant_response="y"
            )
        )
        registry = build_default_tool_registry()
        registry.register(_ExplodingTool())
        before = (memory_store.count(), experience_store.count())

        _run(
            _runner(registry).execute(
                _decision(_action("exploding_tool"), _action("calculator", {"expression": "1+1"}))
            )
        )

        assert (memory_store.count(), experience_store.count()) == before
