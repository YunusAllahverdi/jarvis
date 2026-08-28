"""Agent katmanı — çok adımlı planlarda adımlar arası veri akışı.

Kapsam:
 1. Başvuru tespiti ve düz argümanların korunması
 2. Yol (path) yürütme: sözlük anahtarı ve liste indeksi
 3. Geriye başvuru zorunluluğu
 4. Başarısız adıma başvuru reddedilir
 5. Bulunamayan yol reddedilir
 6. Derinlik sınırları
 7. Kod çalıştırma yok — yalnızca veri
 8. Runner: gerçek çok adımlı akış (ilk adımın sonucu ikinciye geçer)
 9. Runner: çözülemeyen başvuruda adım çalıştırılmaz
10. Çözülemeyen başvuru diğer adımları çökertmez
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.agent.models import AgentAction, AgentDecision, AgentStatus, Intent
from app.agent.references import (
    ERROR_UNRESOLVED_REFERENCE,
    MAX_PATH_DEPTH,
    ReferenceError,
    is_reference,
    resolve_arguments,
)
from app.agent.runner import AgentRunner
from app.tools.base import PermissionLevel, Tool, ToolInput
from app.tools.defaults import build_default_tool_registry
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from pydantic import Field


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _resolve(arguments: dict[str, Any], previous: list[dict | None]) -> dict[str, Any]:
    return resolve_arguments(arguments, previous_results=previous)


# ---------------------------------------------------------------------------
# 1-2. Temel çözümleme
# ---------------------------------------------------------------------------


class TestReferenceResolution:
    def test_plain_arguments_pass_through_unchanged(self) -> None:
        assert _resolve({"expression": "2+2", "limit": 5}, []) == {"expression": "2+2", "limit": 5}

    def test_is_reference_detects_only_the_exact_shape(self) -> None:
        assert is_reference({"$from": {"step": 0, "path": "x"}}) is True
        assert is_reference({"$from": {}, "other": 1}) is False
        assert is_reference({"from": {"step": 0}}) is False
        assert is_reference("$from") is False

    def test_resolves_a_top_level_dict_key(self) -> None:
        previous = [{"trait_count": 7}]

        assert _resolve({"limit": {"$from": {"step": 0, "path": "trait_count"}}}, previous) == {
            "limit": 7
        }

    def test_resolves_through_a_list_index(self) -> None:
        previous = [{"memories": [{"content": "python"}, {"content": "rust"}]}]

        resolved = _resolve({"query": {"$from": {"step": 0, "path": "memories.1.content"}}}, previous)

        assert resolved == {"query": "rust"}

    def test_empty_path_returns_the_whole_result(self) -> None:
        previous = [{"a": 1}]

        assert _resolve({"payload": {"$from": {"step": 0, "path": ""}}}, previous) == {
            "payload": {"a": 1}
        }

    def test_resolves_inside_nested_structures(self) -> None:
        previous = [{"count": 3}]

        resolved = _resolve(
            {"filters": {"nested": [{"$from": {"step": 0, "path": "count"}}]}}, previous
        )

        assert resolved == {"filters": {"nested": [3]}}

    def test_original_arguments_are_not_mutated(self) -> None:
        arguments = {"limit": {"$from": {"step": 0, "path": "count"}}}
        original = {"limit": {"$from": {"step": 0, "path": "count"}}}

        _resolve(arguments, [{"count": 1}])

        assert arguments == original


# ---------------------------------------------------------------------------
# 3-6. Sınırlar
# ---------------------------------------------------------------------------


class TestReferenceBoundaries:
    def test_forward_reference_is_rejected(self) -> None:
        """Henüz çalışmamış bir adıma başvurulamaz."""
        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": 2, "path": "a"}}}, [{"a": 1}])

    def test_negative_step_is_rejected(self) -> None:
        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": -1, "path": "a"}}}, [{"a": 1}])

    def test_non_integer_step_is_rejected(self) -> None:
        for step in ("0", 1.5, None, True):
            with pytest.raises(ReferenceError):
                _resolve({"x": {"$from": {"step": step, "path": "a"}}}, [{"a": 1}])

    def test_reference_to_a_failed_step_is_rejected(self) -> None:
        """Başarısız adımın çıktısı yerine varsayılan uydurulmamalı."""
        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": 0, "path": "a"}}}, [None])

    def test_missing_path_is_rejected(self) -> None:
        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": 0, "path": "nope"}}}, [{"a": 1}])

    def test_out_of_range_list_index_is_rejected(self) -> None:
        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": 0, "path": "items.5"}}}, [{"items": [1]}])

    def test_non_numeric_list_index_is_rejected(self) -> None:
        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": 0, "path": "items.first"}}}, [{"items": [1]}])

    def test_walking_into_a_scalar_is_rejected(self) -> None:
        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": 0, "path": "a.b"}}}, [{"a": 5}])

    def test_unexpected_reference_field_is_rejected(self) -> None:
        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": 0, "path": "a", "eval": "1+1"}}}, [{"a": 1}])

    def test_path_depth_is_bounded(self) -> None:
        deep_path = ".".join(["a"] * (MAX_PATH_DEPTH + 1))

        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": 0, "path": deep_path}}}, [{"a": 1}])

    def test_argument_depth_is_bounded(self) -> None:
        nested: Any = {"$from": {"step": 0, "path": "a"}}
        for _ in range(10):
            nested = {"level": nested}

        with pytest.raises(ReferenceError):
            _resolve(nested, [{"a": 1}])

    def test_reference_spec_must_be_an_object(self) -> None:
        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": "step 0"}}, [{"a": 1}])


# ---------------------------------------------------------------------------
# 7. Kod çalıştırma yok
# ---------------------------------------------------------------------------


class TestNoCodeExecution:
    def test_reference_module_uses_no_dynamic_evaluation(self) -> None:
        import inspect

        from app.agent import references as references_module

        source = inspect.getsource(references_module)

        for forbidden in ("eval(", "exec(", "__import__", "compile(", "getattr("):
            assert forbidden not in source

    def test_path_cannot_reach_python_attributes(self) -> None:
        """Yol yalnızca veri içinde yürür; nesne özniteliklerine erişemez."""
        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": 0, "path": "__class__"}}}, [{"a": 1}])

    def test_non_json_safe_values_are_rejected(self) -> None:
        class _Opaque:
            pass

        with pytest.raises(ReferenceError):
            _resolve({"x": {"$from": {"step": 0, "path": "obj"}}}, [{"obj": _Opaque()}])


# ---------------------------------------------------------------------------
# 8-10. Runner ile gerçek çok adımlı akış
# ---------------------------------------------------------------------------


class _EchoCountInput(ToolInput):
    """Sayı üreten test tool'unun input'u."""

    value: int = Field(ge=0, le=1000)


class _ProducerTool(Tool[ToolInput]):
    """Sabit, iç içe bir sonuç üreten test tool'u."""

    name = "producer"
    description = "Test amaçlı sabit veri üretir."
    permission = PermissionLevel.READ
    input_model = ToolInput

    async def execute(self, tool_input: ToolInput) -> dict[str, Any]:
        return {"items": [{"label": "birinci"}, {"label": "ikinci"}], "total": 42}


class _ConsumerTool(Tool[_EchoCountInput]):
    """Aldığı değeri geri döndüren test tool'u."""

    name = "consumer"
    description = "Test amaçlı aldığı değeri döndürür."
    permission = PermissionLevel.READ
    input_model = _EchoCountInput

    async def execute(self, tool_input: _EchoCountInput) -> dict[str, Any]:
        return {"received": tool_input.value}


def _registry() -> ToolRegistry:
    registry = build_default_tool_registry()
    registry.register(_ProducerTool())
    registry.register(_ConsumerTool())
    return registry


def _runner(registry: ToolRegistry | None = None) -> AgentRunner:
    active = registry or _registry()
    return AgentRunner(
        tool_executor=ToolExecutor(active, allowed_permissions={PermissionLevel.READ})
    )


def _plan(*actions: AgentAction) -> AgentDecision:
    return AgentDecision(
        intent=Intent.INFORMATION_REQUEST,
        actions=list(actions),
        reason="test planı",
        policy="test",
    )


def _action(tool: str, arguments: dict[str, Any]) -> AgentAction:
    return AgentAction(tool_name=tool, arguments=arguments, purpose="test adımı")


class TestMultiStepDataFlow:
    def test_second_step_receives_the_first_steps_result(self) -> None:
        """Bu milestone'un asıl kazanımı: gerçek adımlar arası veri akışı."""
        plan = _plan(
            _action("producer", {}),
            _action("consumer", {"value": {"$from": {"step": 0, "path": "total"}}}),
        )

        result = _run(_runner().execute(plan))

        assert result.status is AgentStatus.COMPLETED
        assert result.outcomes[1].data == {"received": 42}

    def test_reference_can_walk_into_a_list(self) -> None:
        plan = _plan(
            _action("producer", {}),
            _action("memory_search", {"query": {"$from": {"step": 0, "path": "items.1.label"}}}),
        )
        registry = _registry()

        result = _run(_runner(registry).execute(plan))

        # memory_search kayıtlı değil → bilinmeyen tool, ama başvuru çözüldü.
        assert result.outcomes[1].error_code == "unknown_tool"

    def test_unresolved_reference_skips_only_that_step(self) -> None:
        plan = _plan(
            _action("producer", {}),
            _action("consumer", {"value": {"$from": {"step": 0, "path": "yok"}}}),
            _action("producer", {}),
        )

        result = _run(_runner().execute(plan))

        assert result.outcomes[0].success is True
        assert result.outcomes[1].success is False
        assert result.outcomes[1].error_code == ERROR_UNRESOLVED_REFERENCE
        assert result.outcomes[1].data is None
        assert result.outcomes[2].success is True
        assert result.status is AgentStatus.PARTIAL

    def test_dependent_step_is_not_executed_when_the_source_fails(self) -> None:
        """Kaynak adım başarısızsa bağımlı adım yanlış argümanla ÇALIŞTIRILMAMALI."""
        plan = _plan(
            _action("consumer", {"value": 99999}),  # şema ihlali → başarısız
            _action("consumer", {"value": {"$from": {"step": 0, "path": "received"}}}),
        )

        result = _run(_runner().execute(plan))

        assert result.outcomes[0].error_code == "invalid_arguments"
        assert result.outcomes[1].error_code == ERROR_UNRESOLVED_REFERENCE
        assert result.status is AgentStatus.FAILED

    def test_plain_multi_step_plan_still_works(self) -> None:
        """Başvuru içermeyen çok adımlı planlar eskisi gibi çalışmalı."""
        plan = _plan(_action("producer", {}), _action("get_time", {}))

        result = _run(_runner().execute(plan))

        assert result.status is AgentStatus.COMPLETED
        assert len(result.outcomes) == 2

    def test_confirmation_still_blocks_a_referencing_plan(self) -> None:
        plan = _plan(
            _action("producer", {}),
            AgentAction(
                tool_name="consumer",
                arguments={"value": {"$from": {"step": 0, "path": "total"}}},
                purpose="test",
                requires_confirmation=True,
            ),
        )

        result = _run(_runner().execute(plan))

        assert result.status is AgentStatus.PENDING_CONFIRMATION
        assert all(o.skipped for o in result.outcomes)
