"""Agent katmanı — yapılandırılmış karar/sonuç modelleri.

Kapsam:
 1. AgentAction mevcut ToolCall sınırına dönüşür
 2. Onay bayrağı eylemlerle tutarsız kalamaz (güvenlik sınırı atlanamaz)
 3. Tek adım / çok adım temsili
 4. status_for() toplu durumu deterministik türetir
 5. AgentResult yardımcıları
 6. Tool adları mevcut desenle doğrulanır
 7. Modeller saftır (I/O yok)
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from app.agent import models as models_module
from app.agent.models import (
    ActionOutcome,
    AgentAction,
    AgentDecision,
    AgentResult,
    AgentStatus,
    Intent,
    ToolDescriptor,
    status_for,
)
from app.core.chat import ToolCall
from app.tools.base import PermissionLevel


def _action(tool_name: str = "calculator", **overrides: object) -> AgentAction:
    defaults: dict[str, object] = dict(
        tool_name=tool_name, arguments={"expression": "2+2"}, purpose="Hesapla."
    )
    defaults.update(overrides)
    return AgentAction(**defaults)  # type: ignore[arg-type]


def _decision(**overrides: object) -> AgentDecision:
    defaults: dict[str, object] = dict(
        intent=Intent.CALCULATE,
        actions=[_action()],
        reason="Aritmetik ifade tespit edildi.",
        policy="rule_based",
    )
    defaults.update(overrides)
    return AgentDecision(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Eylem → mevcut ToolCall sınırı
# ---------------------------------------------------------------------------


class TestActionToToolCall:
    def test_action_converts_to_the_existing_tool_call_model(self) -> None:
        call = _action().as_tool_call()

        assert isinstance(call, ToolCall)
        assert call.name == "calculator"
        assert call.arguments == {"expression": "2+2"}

    def test_conversion_copies_arguments(self) -> None:
        """Dönüşüm sonrası çağrıyı değiştirmek eylemi bozmamalı."""
        action = _action()
        call = action.as_tool_call()
        call.arguments["expression"] = "9*9"

        assert action.arguments == {"expression": "2+2"}

    def test_invalid_tool_name_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _action(tool_name="Invalid Name")


# ---------------------------------------------------------------------------
# 2. Onay sınırı atlanamaz
# ---------------------------------------------------------------------------


class TestConfirmationConsistency:
    def test_action_requiring_confirmation_forces_the_decision_flag(self) -> None:
        """Eylem onay istiyorsa karar bunu gizleyemez."""
        decision = _decision(
            actions=[_action(requires_confirmation=True)], requires_confirmation=False
        )

        assert decision.requires_confirmation is True

    def test_flag_stays_false_when_no_action_requires_confirmation(self) -> None:
        assert _decision().requires_confirmation is False

    def test_flag_can_be_set_without_any_action(self) -> None:
        """Eylemsiz bir kararda bayrak açıkça ayarlanabilir kalmalı."""
        decision = _decision(actions=[], requires_confirmation=True)
        assert decision.requires_confirmation is True

    def test_one_confirming_action_among_many_is_enough(self) -> None:
        decision = _decision(
            actions=[_action(), _action("get_time", arguments={}, requires_confirmation=True)]
        )
        assert decision.requires_confirmation is True


# ---------------------------------------------------------------------------
# 3. Plan temsili
# ---------------------------------------------------------------------------


class TestPlanRepresentation:
    def test_single_step_plan(self) -> None:
        decision = _decision()
        assert decision.has_actions is True
        assert decision.is_multi_step is False

    def test_multi_step_plan(self) -> None:
        decision = _decision(
            actions=[
                _action("memory_search", arguments={"query": "x"}, purpose="Belleği getir."),
                _action("user_profile", arguments={}, purpose="Profili getir."),
            ]
        )
        assert decision.is_multi_step is True
        assert [a.tool_name for a in decision.actions] == ["memory_search", "user_profile"]

    def test_conversation_decision_has_no_actions(self) -> None:
        decision = _decision(intent=Intent.CONVERSATION, actions=[])
        assert decision.has_actions is False
        assert decision.is_multi_step is False

    def test_reason_is_required_and_bounded(self) -> None:
        """Gerekçe zorunlu ve kısa olmalı — düşünce dökümü saklanmamalı."""
        with pytest.raises(ValidationError):
            _decision(reason="")
        with pytest.raises(ValidationError):
            _decision(reason="x" * 301)


# ---------------------------------------------------------------------------
# 4. Toplu durum türetimi
# ---------------------------------------------------------------------------


class TestStatusDerivation:
    def test_no_outcomes_is_no_action(self) -> None:
        assert status_for([]) is AgentStatus.NO_ACTION

    def test_all_successful_is_completed(self) -> None:
        outcomes = [
            ActionOutcome(tool_name="calculator", success=True),
            ActionOutcome(tool_name="get_time", success=True),
        ]
        assert status_for(outcomes) is AgentStatus.COMPLETED

    def test_all_failed_is_failed(self) -> None:
        outcomes = [
            ActionOutcome(tool_name="calculator", success=False),
            ActionOutcome(tool_name="get_time", success=False),
        ]
        assert status_for(outcomes) is AgentStatus.FAILED

    def test_mixed_is_partial(self) -> None:
        outcomes = [
            ActionOutcome(tool_name="calculator", success=True),
            ActionOutcome(tool_name="get_time", success=False),
        ]
        assert status_for(outcomes) is AgentStatus.PARTIAL

    def test_all_skipped_is_pending_confirmation(self) -> None:
        outcomes = [
            ActionOutcome(tool_name="calculator", skipped=True),
            ActionOutcome(tool_name="get_time", skipped=True),
        ]
        assert status_for(outcomes) is AgentStatus.PENDING_CONFIRMATION

    def test_success_alongside_a_skip_is_not_completed(self) -> None:
        """Atlanan bir adım varken plan "tamamlandı" sayılmamalı."""
        outcomes = [
            ActionOutcome(tool_name="calculator", success=True),
            ActionOutcome(tool_name="get_time", skipped=True),
        ]
        assert status_for(outcomes) is AgentStatus.PARTIAL


# ---------------------------------------------------------------------------
# 5. Sonuç yardımcıları
# ---------------------------------------------------------------------------


class TestAgentResult:
    def test_ok_is_true_for_completed_and_no_action(self) -> None:
        for status in (AgentStatus.COMPLETED, AgentStatus.NO_ACTION):
            assert AgentResult(decision=_decision(), outcomes=[], status=status).ok is True

    def test_ok_is_false_for_failure_and_pending(self) -> None:
        for status in (AgentStatus.FAILED, AgentStatus.PARTIAL, AgentStatus.PENDING_CONFIRMATION):
            assert AgentResult(decision=_decision(), outcomes=[], status=status).ok is False

    def test_successful_outcomes_filters(self) -> None:
        result = AgentResult(
            decision=_decision(),
            outcomes=[
                ActionOutcome(tool_name="calculator", success=True),
                ActionOutcome(tool_name="get_time", success=False),
            ],
            status=AgentStatus.PARTIAL,
        )
        assert [o.tool_name for o in result.successful_outcomes] == ["calculator"]


# ---------------------------------------------------------------------------
# 6-7. Tanımlayıcılar ve saflık
# ---------------------------------------------------------------------------


class TestDescriptorAndPurity:
    def test_tool_descriptor_carries_permission_and_confirmation(self) -> None:
        descriptor = ToolDescriptor(
            name="calculator",
            description="Hesaplar.",
            permission=PermissionLevel.READ,
            requires_confirmation=False,
        )
        assert descriptor.permission is PermissionLevel.READ
        assert descriptor.requires_confirmation is False

    def test_tool_descriptor_is_immutable(self) -> None:
        """Bağlama konan tanım sonradan değiştirilememeli."""
        descriptor = ToolDescriptor(
            name="calculator", description="Hesaplar.", permission=PermissionLevel.READ
        )
        with pytest.raises(ValidationError):
            descriptor.name = "other"  # type: ignore[misc]

    def test_models_module_performs_no_io(self) -> None:
        source = inspect.getsource(models_module)

        assert "sqlite" not in source.lower()
        assert "open(" not in source
        assert "LLMProvider" not in source
