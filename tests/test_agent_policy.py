"""Agent katmanı — deterministik kural tabanlı karar politikası.

Kapsam:
 1. Tek adımlı kararlar (hesaplama, saat, tarih, sistem durumu)
 2. Çok adımlı plan temsili (hatırlama)
 3. Kural eşleşmezse normal sohbete devredilir — eylem UYDURULMAZ
 4. Aritmetik tespiti yanlış pozitiflere karşı korunur
 5. Kayıtlı olmayan bir tool için asla eylem planlanmaz
 6. Onay gereksinimi bağlamdan taşınır
 7. Karar deterministiktir (aynı bağlam → aynı karar)
 8. Politika LLM çağırmaz
 9. Gerekçe kısa ve olgusaldır (düşünce dökümü değil)
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime

import pytest

from app.agent import policy as policy_module
from app.agent.context import AgentContext, ContextBuilder
from app.agent.models import Intent
from app.agent.policy import (
    DecisionPolicy,
    RuleBasedDecisionPolicy,
    extract_arithmetic_expression,
)
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.user_model_service import UserModelService
from app.tools.base import PermissionLevel
from app.tools.defaults import build_default_tool_registry, register_context_tools

_NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class _StubRetrieval:
    def retrieve(self, query, **kwargs):  # noqa: ANN001, ANN003, ANN201
        return []


class _StubUserModel:
    def build_profile(self, **kwargs):  # noqa: ANN003, ANN201
        raise AssertionError("politika servis çağırmamalı")

    def list_traits(self, **kwargs):  # noqa: ANN003, ANN201
        return []


def _context(
    message: str,
    *,
    with_context_tools: bool = True,
    allowed: set[PermissionLevel] | None = None,
    registry=None,  # type: ignore[no-untyped-def]
) -> AgentContext:
    active_registry = registry if registry is not None else build_default_tool_registry()
    if with_context_tools and registry is None:
        register_context_tools(
            active_registry,
            memory_retrieval=_StubRetrieval(),  # type: ignore[arg-type]
            user_model=_StubUserModel(),  # type: ignore[arg-type]
        )
    builder = ContextBuilder(
        tool_registry=active_registry,
        allowed_permissions=allowed if allowed is not None else {PermissionLevel.READ},
    )
    return builder.build(message, session_id="sess-1", now=_NOW)


def _decide(message: str, **kwargs: object):  # type: ignore[no-untyped-def]
    return _run(RuleBasedDecisionPolicy().decide(_context(message, **kwargs)))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Tek adımlı kararlar
# ---------------------------------------------------------------------------


class TestSingleStepDecisions:
    def test_bare_arithmetic_becomes_a_calculator_action(self) -> None:
        decision = _decide("25 * 17")

        assert decision.intent is Intent.CALCULATE
        assert decision.is_multi_step is False
        assert decision.actions[0].tool_name == "calculator"
        assert decision.actions[0].arguments == {"expression": "25 * 17"}

    def test_arithmetic_with_a_turkish_cue(self) -> None:
        decision = _decide("25 * 17 kaç eder?")

        assert decision.intent is Intent.CALCULATE
        assert decision.actions[0].arguments["expression"] == "25 * 17"

    def test_arithmetic_with_an_english_cue(self) -> None:
        decision = _decide("What is 25 * 17?")

        assert decision.intent is Intent.CALCULATE

    def test_decimal_comma_is_normalised_for_the_tool(self) -> None:
        decision = _decide("hesapla 2,5 + 1,5")

        assert decision.actions[0].arguments["expression"] == "2.5 + 1.5"

    def test_time_question_becomes_a_get_time_action(self) -> None:
        decision = _decide("saat kaç?")

        assert decision.intent is Intent.GET_TIME
        assert decision.actions[0].tool_name == "get_time"

    def test_date_question_becomes_a_get_date_action(self) -> None:
        decision = _decide("bugünün tarihi ne?")

        assert decision.intent is Intent.GET_DATE
        assert decision.actions[0].tool_name == "get_date"

    def test_system_question_becomes_a_system_status_action(self) -> None:
        decision = _decide("sistem durumu nedir?")

        assert decision.intent is Intent.SYSTEM_STATUS
        assert decision.actions[0].tool_name == "system_status"

    def test_every_action_carries_a_purpose(self) -> None:
        decision = _decide("saat kaç?")

        assert decision.actions[0].purpose.strip()


# ---------------------------------------------------------------------------
# 2. Çok adımlı plan
# ---------------------------------------------------------------------------


class TestMultiStepPlan:
    def test_recall_question_produces_a_two_step_plan(self) -> None:
        decision = _decide("hakkımda ne biliyorsun?")

        assert decision.intent is Intent.RECALL
        assert decision.is_multi_step is True
        assert [a.tool_name for a in decision.actions] == ["memory_search", "user_profile"]

    def test_recall_passes_the_original_message_as_the_query(self) -> None:
        decision = _decide("neye odaklanıyorum son zamanlarda?")

        assert decision.actions[0].arguments["query"] == "neye odaklanıyorum son zamanlarda?"

    def test_english_recall_cue_is_recognised(self) -> None:
        decision = _decide("what do you know about me?")

        assert decision.intent is Intent.RECALL

    def test_recall_degrades_to_one_step_when_only_memory_is_available(self) -> None:
        registry = build_default_tool_registry()
        register_context_tools(registry, memory_retrieval=_StubRetrieval())  # type: ignore[arg-type]

        decision = _run(
            RuleBasedDecisionPolicy().decide(_context("ne biliyorsun?", registry=registry))
        )

        assert decision.intent is Intent.RECALL
        assert [a.tool_name for a in decision.actions] == ["memory_search"]


# ---------------------------------------------------------------------------
# 3, 5. Emin olunmayan durumda eylem uydurulmaz
# ---------------------------------------------------------------------------


class TestNoFabricatedActions:
    def test_unmatched_message_falls_back_to_conversation(self) -> None:
        decision = _decide("bana bir şiir yaz")

        assert decision.intent is Intent.CONVERSATION
        assert decision.actions == []
        assert decision.has_actions is False

    def test_greeting_falls_back_to_conversation(self) -> None:
        assert _decide("merhaba Jarvis").intent is Intent.CONVERSATION

    def test_no_action_is_planned_for_an_unregistered_tool(self) -> None:
        """Calculator kayıtlı değilse hesaplama kararı verilmemeli."""
        registry = build_default_tool_registry()
        registry.unregister("calculator")

        decision = _run(RuleBasedDecisionPolicy().decide(_context("25 * 17", registry=registry)))

        assert decision.intent is Intent.CONVERSATION

    def test_recall_without_context_tools_falls_back_to_conversation(self) -> None:
        decision = _decide("ne biliyorsun?", with_context_tools=False)

        assert decision.intent is Intent.CONVERSATION

    def test_every_planned_action_targets_an_available_tool(self) -> None:
        for message in ("25 * 17", "saat kaç", "bugünün tarihi", "sistem durumu", "ne biliyorsun"):
            context = _context(message)
            decision = _run(RuleBasedDecisionPolicy().decide(context))
            for action in decision.actions:
                assert context.has_tool(action.tool_name), message


# ---------------------------------------------------------------------------
# 4. Aritmetik tespiti yanlış pozitiflere karşı korunur
# ---------------------------------------------------------------------------


class TestArithmeticDetection:
    def test_bare_expression_is_extracted(self) -> None:
        assert extract_arithmetic_expression("12+30") == "12+30"

    def test_single_number_is_not_an_expression(self) -> None:
        assert extract_arithmetic_expression("25") is None

    def test_number_inside_a_sentence_is_not_an_expression(self) -> None:
        assert extract_arithmetic_expression("saat 5 gibi geleceğim") is None

    def test_expression_buried_in_an_unrelated_request_is_ignored(self) -> None:
        """"5-3 arası" bir aralıktır, hesaplanacak bir işlem değil."""
        assert extract_arithmetic_expression("5-3 arası bir sayı söyle bana lütfen") is None

    def test_explicit_cue_rescues_a_buried_expression(self) -> None:
        assert extract_arithmetic_expression("acaba 5 - 3 kaç eder diye merak ettim") == "5 - 3"

    def test_a_buried_expression_without_a_cue_makes_no_decision(self) -> None:
        assert _decide("5-3 arası bir sayı söyle bana lütfen").intent is Intent.CONVERSATION


# ---------------------------------------------------------------------------
# 6. Onay gereksinimi taşınır
# ---------------------------------------------------------------------------


class TestConfirmationPropagation:
    def test_action_requires_confirmation_when_permission_is_not_allowed(self) -> None:
        decision = _decide("25 * 17", allowed=set())

        assert decision.actions[0].requires_confirmation is True
        assert decision.requires_confirmation is True

    def test_action_needs_no_confirmation_when_permission_is_allowed(self) -> None:
        decision = _decide("25 * 17")

        assert decision.requires_confirmation is False

    def test_multi_step_plan_inherits_confirmation(self) -> None:
        decision = _decide("hakkımda ne biliyorsun?", allowed=set())

        assert decision.requires_confirmation is True
        assert all(a.requires_confirmation for a in decision.actions)


# ---------------------------------------------------------------------------
# 7-9. Determinizm, LLM'sizlik, gerekçe
# ---------------------------------------------------------------------------


class TestPolicyProperties:
    def test_same_context_yields_the_same_decision(self) -> None:
        context = _context("25 * 17")
        policy = RuleBasedDecisionPolicy()

        first = _run(policy.decide(context))
        second = _run(policy.decide(context))

        assert first.model_dump() == second.model_dump()

    def test_policy_satisfies_the_protocol(self) -> None:
        assert isinstance(RuleBasedDecisionPolicy(), DecisionPolicy)

    def test_policy_records_its_own_name_on_the_decision(self) -> None:
        assert _decide("saat kaç").policy == "rule_based"

    def test_policy_module_calls_no_llm(self) -> None:
        """Deterministik politika hiçbir sağlayıcıyı import etmemeli."""
        source = inspect.getsource(policy_module)

        assert "from app.adapters" not in source
        assert "OllamaProvider" not in source
        assert "generate_with_tools" not in source

    def test_policy_module_touches_no_store(self) -> None:
        source = inspect.getsource(policy_module)

        assert "from app.memory" not in source
        assert "from app.learning" not in source
        assert "import sqlite3" not in source
        assert "._store" not in source

    def test_reasons_are_short_and_factual(self) -> None:
        for message in ("25 * 17", "saat kaç", "ne biliyorsun", "merhaba"):
            decision = _decide(message)
            assert 0 < len(decision.reason) <= 300

    @pytest.mark.parametrize("message", ["", "   "])
    def test_blank_message_is_handled_as_conversation(self, message: str) -> None:
        assert _decide(message).intent is Intent.CONVERSATION
