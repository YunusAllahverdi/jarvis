"""Council — deterministik tetikleme kapısı.

Kapsam:
 1. Kapalıyken asla açılmaz
 2. Yetersiz üye sayısında açılmaz
 3. Açık kullanıcı isteği kapıyı açar
 4. Yapılandırılmış intent kapıyı açar
 5. Eşleşme yoksa açılmaz (şüphede kapalı)
 6. Kapı deterministiktir ve LLM çağırmaz
"""

from __future__ import annotations

import inspect

import pytest

from app.council import gate as gate_module
from app.council.gate import CouncilGate
from app.council.models import CouncilTrigger


def _gate(**overrides: object) -> CouncilGate:
    defaults: dict[str, object] = dict(
        enabled=True, member_count=3, min_candidates=2, trigger_intents=()
    )
    defaults.update(overrides)
    return CouncilGate(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1-2. Kapatan koşullar
# ---------------------------------------------------------------------------


class TestGateClosedConditions:
    def test_disabled_gate_never_opens(self) -> None:
        decision = _gate(enabled=False).evaluate(user_message="council kullan lütfen")

        assert decision.run is False
        assert "kapalı" in decision.reason
        assert decision.trigger is None

    def test_insufficient_members_closes_the_gate(self) -> None:
        decision = _gate(member_count=1, min_candidates=2).evaluate(
            user_message="council kullan"
        )

        assert decision.run is False
        assert "minimum aday" in decision.reason

    def test_no_trigger_means_no_council(self) -> None:
        """Şüphede kalındığında Council çalışmamalı — pahalıdır."""
        decision = _gate().evaluate(user_message="merhaba nasılsın")

        assert decision.run is False
        assert decision.trigger is None


# ---------------------------------------------------------------------------
# 3-4. Açan koşullar
# ---------------------------------------------------------------------------


class TestGateOpenConditions:
    @pytest.mark.parametrize(
        "message",
        [
            "bunu council ile cevapla",
            "farklı modellere sor bakalım",
            "birden fazla model ne diyor?",
            "ikinci bir görüş alabilir miyim",
            "ask multiple models about this",
            "I want a second opinion",
            "compare and synthesize the options",
        ],
    )
    def test_explicit_user_request_opens_the_gate(self, message: str) -> None:
        decision = _gate().evaluate(user_message=message)

        assert decision.run is True
        assert decision.trigger is CouncilTrigger.EXPLICIT_REQUEST

    def test_explicit_cue_is_case_insensitive(self) -> None:
        assert _gate().evaluate(user_message="COUNCIL kullan").run is True

    def test_configured_intent_opens_the_gate(self) -> None:
        decision = _gate(trigger_intents=("information_request",)).evaluate(
            user_message="karşılaştır", intent="information_request"
        )

        assert decision.run is True
        assert decision.trigger is CouncilTrigger.INTENT

    def test_unconfigured_intent_does_not_open_the_gate(self) -> None:
        decision = _gate(trigger_intents=("information_request",)).evaluate(
            user_message="saat kaç", intent="get_time"
        )

        assert decision.run is False

    def test_no_trigger_intents_means_only_explicit_requests(self) -> None:
        decision = _gate().evaluate(user_message="bir şey sor", intent="information_request")

        assert decision.run is False


# ---------------------------------------------------------------------------
# 5-6. Determinizm
# ---------------------------------------------------------------------------


class TestGateProperties:
    def test_same_input_always_yields_the_same_decision(self) -> None:
        gate = _gate()

        first = gate.evaluate(user_message="council kullan")
        second = gate.evaluate(user_message="council kullan")

        assert first.model_dump() == second.model_dump()

    def test_gate_calls_no_llm_and_has_no_io(self) -> None:
        source = inspect.getsource(gate_module)

        assert "LLMProvider" not in source
        assert "generate" not in source
        assert "httpx" not in source
        assert "async def" not in source

    def test_gate_never_raises_on_odd_input(self) -> None:
        gate = _gate()

        for message in ("", "   ", "?" * 5000):
            assert gate.evaluate(user_message=message).run is False

    def test_evaluate_has_no_side_effects(self) -> None:
        gate = _gate()

        gate.evaluate(user_message="council kullan")
        second = gate.evaluate(user_message="merhaba")

        assert second.run is False
