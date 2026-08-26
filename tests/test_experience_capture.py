"""Phase 2C — ChatOrchestrator'ın canlı bir turdan Experience yakalaması testleri.

Kapsam:
 1. Başarılı, tool call'sız bir tur doğru bir Experience yakalar
 2. Çok turlu tool call'lar sıralı isimlerle korunur
 3. occurred_at, çağrı zaman penceresi içinde
 4. user_state/emotional_context her zaman None
 5. outcome her zaman UNKNOWN
 6. derived_memory_ids her zaman []
 7. Builder hatası normal ChatResult'ı bozmaz
 8. Başarısız/patlayan bir provider turu Experience oluşturmaz/güncellemez
 9. ChatOrchestrator kurucu imzası değişmedi
10. Yeni bir orchestrator _last_experience=None ile başlar
11. Art arda başarılı turlar _last_experience'ı en son turla değiştirir
12. provider/tool çalıştırma çağrı sayıları değişmedi
13. Mevcut import-time davranışı güvenli kalır

Bu dosya yalnızca yakalama entegrasyonunu test eder — hiçbir Experience
kalıcı hale getirilmez, hiçbir öğrenme/emotion mantığı içermez (Phase 2C
kapsamı). Gerçek bir Ollama sunucusu gerektirmez.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from app.core.chat import ChatMessage, LLMResponse, ToolCall, ToolDefinition
from app.memory.experience import Experience, ExperienceOutcome
from app.services.conversation import InMemoryConversationStore
from app.services.orchestrator import ChatOrchestrator
from app.tools.base import PermissionLevel
from app.tools.defaults import build_default_tool_registry
from app.tools.executor import ToolExecutor


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class _FixedPromptProvider:
    def __init__(self, prompt: str) -> None:
        self._prompt = prompt

    def load(self) -> str:
        return self._prompt


class _EchoProvider:
    """generate_with_tools için sabit bir metin cevabı döndüren, çağrıları kaydeden sahte sağlayıcı."""

    def __init__(self, reply: str = "Jarvis: ok") -> None:
        self._reply = reply
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        response = await self.generate_with_tools(messages, tools=())
        return response.content

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append(list(messages))
        return LLMResponse(content=self._reply)


class _MultiRoundToolCallingProvider:
    """Sırasıyla get_time, sonra calculator çağırıp en sonda metin döndüren sahte sağlayıcı."""

    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        response = await self.generate_with_tools(messages, tools=())
        return response.content

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            return LLMResponse(tool_calls=[ToolCall(name="get_time", arguments={})])
        if len(self.calls) == 2:
            return LLMResponse(
                tool_calls=[ToolCall(name="calculator", arguments={"expression": "2 + 3"})]
            )
        return LLMResponse(content="Saat ve sonuç: 5.")


class _AlwaysToolCallingProvider:
    """Hiçbir zaman final metin döndürmeyen, her turda tool call isteyen sahte sağlayıcı
    — max_tool_rounds sınırını aşan bir hata (LLMResponseError) tetiklemek için."""

    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        response = await self.generate_with_tools(messages, tools=())
        return response.content

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append(list(messages))
        return LLMResponse(tool_calls=[ToolCall(name="calculator", arguments={"expression": "1 + 1"})])


class _ImmediatelyFailingProvider:
    """generate_with_tools çağrıldığında hemen istisna fırlatan sahte sağlayıcı."""

    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        raise RuntimeError("provider boom")

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append(list(messages))
        raise RuntimeError("provider boom")


def _make_orchestrator(*, provider) -> ChatOrchestrator:  # type: ignore[no-untyped-def]
    registry = build_default_tool_registry()
    return ChatOrchestrator(
        provider=provider,
        conversation_store=InMemoryConversationStore(),
        prompt_loader=_FixedPromptProvider("Sen Jarvis'sin."),
        tool_registry=registry,
        tool_executor=ToolExecutor(registry, allowed_permissions={PermissionLevel.READ}),
    )


# ---------------------------------------------------------------------------
# 1. Başarılı, tool call'sız bir tur
# ---------------------------------------------------------------------------


class TestSuccessfulTurnWithoutToolCalls:
    def test_captures_correct_experience(self) -> None:
        provider = _EchoProvider("Merhaba! Nasıl yardımcı olabilirim?")
        orchestrator = _make_orchestrator(provider=provider)

        result = _run(orchestrator.respond("Merhaba Jarvis", "sess-1"))

        exp = orchestrator._last_experience
        assert isinstance(exp, Experience)
        assert exp.session_id == "sess-1"
        assert exp.user_message == "Merhaba Jarvis"
        assert exp.assistant_response == "Merhaba! Nasıl yardımcı olabilirim?"
        assert exp.tool_calls == []
        assert result.response == "Merhaba! Nasıl yardımcı olabilirim?"


# ---------------------------------------------------------------------------
# 2. Çok turlu tool call'lar sıralı korunur
# ---------------------------------------------------------------------------


class TestMultiRoundToolCalls:
    def test_tool_call_names_preserved_in_order_across_rounds(self) -> None:
        provider = _MultiRoundToolCallingProvider()
        orchestrator = _make_orchestrator(provider=provider)

        _run(orchestrator.respond("Saat kaç ve 2+3 kaç eder?", "sess-1"))

        exp = orchestrator._last_experience
        assert exp is not None
        assert exp.tool_calls == ["get_time", "calculator"]


# ---------------------------------------------------------------------------
# 3. occurred_at zaman penceresi içinde
# ---------------------------------------------------------------------------


class TestOccurredAtWindow:
    def test_occurred_at_is_within_call_time_window(self) -> None:
        provider = _EchoProvider("ok")
        orchestrator = _make_orchestrator(provider=provider)

        before = datetime.now(UTC)
        _run(orchestrator.respond("test", "sess-1"))
        after = datetime.now(UTC)

        exp = orchestrator._last_experience
        assert exp is not None
        assert before <= exp.occurred_at <= after


# ---------------------------------------------------------------------------
# 4-6. Emotion/learning ile ilgili alanlar her zaman sabit
# ---------------------------------------------------------------------------


class TestFieldsThatNeverGetPopulated:
    def test_user_state_and_emotional_context_are_always_none(self) -> None:
        provider = _EchoProvider("ok")
        orchestrator = _make_orchestrator(provider=provider)

        _run(orchestrator.respond("test", "sess-1"))

        exp = orchestrator._last_experience
        assert exp is not None
        assert exp.user_state is None
        assert exp.emotional_context is None

    def test_outcome_is_always_unknown(self) -> None:
        provider = _EchoProvider("ok")
        orchestrator = _make_orchestrator(provider=provider)

        _run(orchestrator.respond("test", "sess-1"))

        exp = orchestrator._last_experience
        assert exp is not None
        assert exp.outcome is ExperienceOutcome.UNKNOWN

    def test_derived_memory_ids_is_always_empty(self) -> None:
        provider = _EchoProvider("ok")
        orchestrator = _make_orchestrator(provider=provider)

        _run(orchestrator.respond("test", "sess-1"))

        exp = orchestrator._last_experience
        assert exp is not None
        assert exp.derived_memory_ids == []


# ---------------------------------------------------------------------------
# 7. Builder hatası normal ChatResult'ı bozmaz
# ---------------------------------------------------------------------------


class TestBuilderFailureIsolated:
    def test_build_experience_from_turn_raising_does_not_break_chat_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.services.orchestrator as orchestrator_module

        def _raising_builder(**kwargs: object) -> Experience:
            raise RuntimeError("builder boom")

        monkeypatch.setattr(orchestrator_module, "build_experience_from_turn", _raising_builder)

        provider = _EchoProvider("Yine de çalışıyor.")
        orchestrator = _make_orchestrator(provider=provider)

        result = _run(orchestrator.respond("test", "sess-1"))

        assert result.response == "Yine de çalışıyor."
        assert orchestrator._last_experience is None  # hiç güncellenmedi

    def test_builder_failure_does_not_overwrite_previous_experience(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.services.orchestrator as orchestrator_module

        provider = _EchoProvider("ok")
        orchestrator = _make_orchestrator(provider=provider)

        # İlk tur normal şekilde başarıyla bir Experience yakalar.
        _run(orchestrator.respond("ilk mesaj", "sess-1"))
        first_experience = orchestrator._last_experience
        assert first_experience is not None

        # İkinci turda builder patlatılır.
        def _raising_builder(**kwargs: object) -> Experience:
            raise RuntimeError("builder boom")

        monkeypatch.setattr(orchestrator_module, "build_experience_from_turn", _raising_builder)
        result = _run(orchestrator.respond("ikinci mesaj", "sess-1"))

        assert result.response == "ok"
        # Önceki geçerli Experience korunmuş olmalı — None'a düşmemeli.
        assert orchestrator._last_experience is first_experience


# ---------------------------------------------------------------------------
# 8. Başarısız/patlayan bir provider turu Experience oluşturmaz
# ---------------------------------------------------------------------------


class TestFailedTurnDoesNotCaptureExperience:
    def test_provider_exception_leaves_last_experience_untouched(self) -> None:
        provider = _ImmediatelyFailingProvider()
        orchestrator = _make_orchestrator(provider=provider)

        with pytest.raises(RuntimeError, match="provider boom"):
            _run(orchestrator.respond("test", "sess-1"))

        assert orchestrator._last_experience is None

    def test_max_tool_rounds_exceeded_leaves_last_experience_untouched(self) -> None:
        from app.adapters.llm.base import LLMResponseError

        provider = _AlwaysToolCallingProvider()
        orchestrator = _make_orchestrator(provider=provider)

        with pytest.raises(LLMResponseError):
            _run(orchestrator.respond("test", "sess-1"))

        assert orchestrator._last_experience is None

    def test_previous_experience_survives_a_later_failed_turn(self) -> None:
        provider = _EchoProvider("ok")
        orchestrator = _make_orchestrator(provider=provider)
        _run(orchestrator.respond("ilk mesaj", "sess-1"))
        first_experience = orchestrator._last_experience
        assert first_experience is not None

        failing_provider = _ImmediatelyFailingProvider()
        orchestrator._provider = failing_provider  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError):
            _run(orchestrator.respond("ikinci mesaj", "sess-1"))

        assert orchestrator._last_experience is first_experience


# ---------------------------------------------------------------------------
# 9. Kurucu imzası değişmedi
# ---------------------------------------------------------------------------


class TestConstructorSignatureUnchanged:
    def test_constructor_parameters_are_unchanged(self) -> None:
        """Kurucu yalnızca bilinçli olarak eklenen opsiyonel bağımlılıklarla
        genişlemiş olmalı: `experience_store` (Phase 2D-Integration) ve
        `agent_service` (LLM karar katmanı milestone'u).

        Her ikisi de mevcut `memory_service`/`memory_retrieval` deseniyle
        aynı biçimde, varsayılanı None olarak eklenmiştir — verilmediğinde bu
        dosyadaki tüm yakalama davranışı aynen korunur.
        """
        sig = inspect.signature(ChatOrchestrator.__init__)
        param_names = set(sig.parameters.keys()) - {"self"}
        assert param_names == {
            "provider",
            "conversation_store",
            "prompt_loader",
            "tool_registry",
            "tool_executor",
            "memory_service",
            "memory_retrieval",
            "experience_store",
            "agent_service",
            "max_tool_rounds",
            "context_message_limit",
            "memory_context_limit",
        }
        assert sig.parameters["experience_store"].default is None


# ---------------------------------------------------------------------------
# 10-11. _last_experience başlangıç/güncelleme davranışı
# ---------------------------------------------------------------------------


class TestLastExperienceLifecycle:
    def test_fresh_orchestrator_starts_with_no_experience(self) -> None:
        orchestrator = _make_orchestrator(provider=_EchoProvider("ok"))
        assert orchestrator._last_experience is None

    def test_successive_successful_turns_replace_last_experience(self) -> None:
        provider = _EchoProvider("ok")
        orchestrator = _make_orchestrator(provider=provider)

        _run(orchestrator.respond("birinci", "sess-1"))
        first_experience = orchestrator._last_experience
        assert first_experience is not None
        assert first_experience.user_message == "birinci"

        _run(orchestrator.respond("ikinci", "sess-1"))
        second_experience = orchestrator._last_experience
        assert second_experience is not None
        assert second_experience.user_message == "ikinci"

        # En son turu yansıtıyor — biriken bir liste değil.
        assert second_experience.id != first_experience.id
        assert orchestrator._last_experience is not first_experience


# ---------------------------------------------------------------------------
# 12. provider/tool çalıştırma çağrı sayıları değişmedi
# ---------------------------------------------------------------------------


class TestProviderAndToolCallCountsUnchanged:
    def test_simple_turn_still_makes_exactly_one_provider_call(self) -> None:
        provider = _EchoProvider("ok")
        orchestrator = _make_orchestrator(provider=provider)

        _run(orchestrator.respond("test", "sess-1"))

        assert len(provider.calls) == 1

    def test_multi_round_tool_turn_still_makes_exactly_three_provider_calls(self) -> None:
        provider = _MultiRoundToolCallingProvider()
        orchestrator = _make_orchestrator(provider=provider)

        _run(orchestrator.respond("test", "sess-1"))

        assert len(provider.calls) == 3


# ---------------------------------------------------------------------------
# 13. Import-time davranışı güvenli kalır
# ---------------------------------------------------------------------------


class TestImportTimeSafety:
    def test_reimporting_orchestrator_module_succeeds_without_side_effects(self) -> None:
        import app.services.orchestrator as orchestrator_module

        # Yeniden yüklemek hata fırlatmamalı; Experience/experience_builder
        # modülleri saf olduğundan hiçbir I/O tetiklenmemeli.
        reloaded = importlib.reload(orchestrator_module)
        assert reloaded.ChatOrchestrator is not None
        # Bu dosyadaki hiçbir senaryo gerçek bir SQLiteMemoryStore kurmuyor
        # (yalnızca in-memory Experience yakalama) — importun kendisi hiçbir
        # dosya sistemi I/O'su tetiklemez; bu, Experience/experience_builder
        # modüllerinin saf (yalnızca model/fonksiyon tanımı) olmasının
        # doğrudan sonucudur.
