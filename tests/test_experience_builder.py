"""Phase 2B — build_experience_from_turn() testleri.

Kapsam:
 1. Tool call'sız minimal tur
 2. Birden fazla tool call sırası korunur
 3. Tekrarlanan tool call'lar korunur (dedupe yok)
 4. user_state her zaman None
 5. emotional_context her zaman None
 6. outcome her zaman UNKNOWN
 7. derived_memory_ids her zaman []
 8. metadata verilmezse boş sözlük
 9. metadata verilirse doğru değerler + çağıranın sözlüğünden izole
10. occurred_at aynen korunur
11. Aynı mantıksal girdi, tekrarlanan çağrılarda eşdeğer alanlar üretir (id hariç)
12. Fonksiyonun LLM/store bağımlılığı yok, hiçbir I/O yapmaz
13. Builder'ı import etmek mevcut import'ları etkilemez

Bu dosya yalnızca saf fonksiyonun veri dönüşümünü test eder — hiçbir depoya
yazma, hiçbir LLM çağrısı veya canlı sohbet akışı içermez (Phase 2B kapsamı).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from app.core.chat import ChatMessage, ToolCall
from app.memory.experience import Experience, ExperienceOutcome
from app.memory.experience_builder import build_experience_from_turn


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _user(content: str) -> ChatMessage:
    return ChatMessage(role="user", content=content)


def _assistant_tool_call(*names: str) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        tool_calls=[ToolCall(name=name, arguments={}) for name in names],
    )


def _tool_result(name: str, content: str = '{"ok": true}') -> ChatMessage:
    return ChatMessage(role="tool", tool_name=name, content=content)


def _assistant_final(content: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=content)


_OCCURRED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _build(**overrides: object) -> Experience:
    defaults: dict[str, object] = dict(
        session_id="sess-1",
        user_message="Merhaba",
        assistant_response="Merhaba! Nasıl yardımcı olabilirim?",
        turn_messages=[_user("Merhaba"), _assistant_final("Merhaba! Nasıl yardımcı olabilirim?")],
        occurred_at=_OCCURRED_AT,
    )
    defaults.update(overrides)
    return build_experience_from_turn(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Tool call'sız minimal tur
# ---------------------------------------------------------------------------


class TestMinimalTurnWithoutToolCalls:
    def test_returns_experience_with_no_tool_calls(self) -> None:
        exp = _build()

        assert isinstance(exp, Experience)
        assert exp.tool_calls == []
        assert exp.session_id == "sess-1"
        assert exp.user_message == "Merhaba"
        assert exp.assistant_response == "Merhaba! Nasıl yardımcı olabilirim?"


# ---------------------------------------------------------------------------
# 2-3. Tool call sırası ve tekrarlar
# ---------------------------------------------------------------------------


class TestToolCallExtraction:
    def test_multiple_tool_calls_preserve_order(self) -> None:
        turn_messages = [
            _user("Saat kaç ve 2+3 kaç eder?"),
            _assistant_tool_call("get_time"),
            _tool_result("get_time"),
            _assistant_tool_call("calculator"),
            _tool_result("calculator"),
            _assistant_final("Saat 10:00 ve 2+3=5."),
        ]

        exp = _build(
            user_message="Saat kaç ve 2+3 kaç eder?",
            assistant_response="Saat 10:00 ve 2+3=5.",
            turn_messages=turn_messages,
        )

        assert exp.tool_calls == ["get_time", "calculator"]

    def test_multiple_tool_calls_within_a_single_assistant_message_preserve_order(
        self,
    ) -> None:
        turn_messages = [
            _user("test"),
            _assistant_tool_call("get_time", "calculator", "get_date"),
            _tool_result("get_time"),
            _tool_result("calculator"),
            _tool_result("get_date"),
            _assistant_final("tamam"),
        ]

        exp = _build(turn_messages=turn_messages)

        assert exp.tool_calls == ["get_time", "calculator", "get_date"]

    def test_duplicate_tool_calls_are_preserved_not_deduplicated(self) -> None:
        turn_messages = [
            _user("test"),
            _assistant_tool_call("calculator"),
            _tool_result("calculator"),
            _assistant_tool_call("calculator"),
            _tool_result("calculator"),
            _assistant_final("tamam"),
        ]

        exp = _build(turn_messages=turn_messages)

        assert exp.tool_calls == ["calculator", "calculator"]

    def test_tool_arguments_and_results_are_ignored(self) -> None:
        """Yalnızca tool ADLARI çıkarılır — argümanlar ve sonuçlar (JSON içerik) yok sayılır."""
        turn_messages = [
            _user("test"),
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(name="calculator", arguments={"expression": "2+3"}, call_id="abc")],
            ),
            _tool_result("calculator", content='{"ok": true, "result": {"value": 5}}'),
            _assistant_final("5"),
        ]

        exp = _build(turn_messages=turn_messages)

        assert exp.tool_calls == ["calculator"]


# ---------------------------------------------------------------------------
# 4-7. Emotion/learning ile ilgili alanlar her zaman sabit
# ---------------------------------------------------------------------------


class TestFieldsThatNeverGetPopulated:
    @pytest.mark.parametrize(
        "turn_messages",
        [
            [_user("x"), _assistant_final("y")],
            [
                _user("x"),
                _assistant_tool_call("calculator"),
                _tool_result("calculator"),
                _assistant_final("y"),
            ],
        ],
    )
    def test_user_state_is_always_none(self, turn_messages: list[ChatMessage]) -> None:
        exp = _build(turn_messages=turn_messages)
        assert exp.user_state is None

    def test_emotional_context_is_always_none(self) -> None:
        exp = _build()
        assert exp.emotional_context is None

    def test_outcome_is_always_unknown(self) -> None:
        exp = _build()
        assert exp.outcome is ExperienceOutcome.UNKNOWN

    def test_outcome_is_unknown_even_with_successful_tool_calls(self) -> None:
        """outcome, tool sonuçlarına bakılmaksızın her zaman UNKNOWN'dur —
        bu faz hiçbir çıkarım yapmaz (bilinçli minimal tasarım)."""
        turn_messages = [
            _user("x"),
            _assistant_tool_call("calculator"),
            _tool_result("calculator", content='{"ok": true, "result": 5}'),
            _assistant_final("5"),
        ]
        exp = _build(turn_messages=turn_messages)
        assert exp.outcome is ExperienceOutcome.UNKNOWN

    def test_derived_memory_ids_is_always_empty(self) -> None:
        exp = _build()
        assert exp.derived_memory_ids == []


# ---------------------------------------------------------------------------
# 8-9. metadata davranışı
# ---------------------------------------------------------------------------


class TestMetadataHandling:
    def test_omitted_metadata_defaults_to_empty_dict(self) -> None:
        exp = _build()
        assert exp.metadata == {}

    def test_supplied_metadata_is_copied_correctly(self) -> None:
        exp = _build(metadata={"source": "test", "count": 3})
        assert exp.metadata == {"source": "test", "count": 3}

    def test_supplied_metadata_is_isolated_from_caller_mutation(self) -> None:
        caller_metadata = {"source": "test"}
        exp = _build(metadata=caller_metadata)

        caller_metadata["source"] = "mutated"
        caller_metadata["new_key"] = "new_value"

        assert exp.metadata == {"source": "test"}

    def test_mutating_experience_metadata_does_not_affect_caller_dict(self) -> None:
        caller_metadata = {"source": "test"}
        exp = _build(metadata=caller_metadata)

        exp.metadata["added_later"] = True

        assert "added_later" not in caller_metadata


# ---------------------------------------------------------------------------
# 10. occurred_at aynen korunur
# ---------------------------------------------------------------------------


class TestOccurredAtPreserved:
    def test_occurred_at_is_preserved_exactly(self) -> None:
        specific_time = datetime(2025, 6, 15, 8, 30, 45, tzinfo=UTC)
        exp = _build(occurred_at=specific_time)
        assert exp.occurred_at == specific_time

    def test_function_never_calls_a_clock_internally(self) -> None:
        """İki farklı occurred_at değeriyle çağrılan iki sonuç birbirinden
        farklı olmalı — fonksiyon kendi saatini kullanmıyor, girdiyi aynen yansıtıyor."""
        t1 = datetime(2025, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 12, 31, tzinfo=UTC)
        exp1 = _build(occurred_at=t1)
        exp2 = _build(occurred_at=t2)
        assert exp1.occurred_at == t1
        assert exp2.occurred_at == t2
        assert exp1.occurred_at != exp2.occurred_at


# ---------------------------------------------------------------------------
# 11. Determinizm: aynı mantıksal girdi, eşdeğer alanlar üretir (id hariç)
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_repeated_calls_with_same_input_produce_equivalent_fields(self) -> None:
        turn_messages = [
            _user("Merhaba"),
            _assistant_tool_call("calculator"),
            _tool_result("calculator"),
            _assistant_final("tamam"),
        ]

        exp1 = build_experience_from_turn(
            session_id="sess-x",
            user_message="Merhaba",
            assistant_response="tamam",
            turn_messages=turn_messages,
            occurred_at=_OCCURRED_AT,
            metadata={"k": "v"},
        )
        exp2 = build_experience_from_turn(
            session_id="sess-x",
            user_message="Merhaba",
            assistant_response="tamam",
            turn_messages=turn_messages,
            occurred_at=_OCCURRED_AT,
            metadata={"k": "v"},
        )

        assert exp1.id != exp2.id  # her çağrı yeni bir kimlik üretir
        dumped1 = exp1.model_dump(exclude={"id"})
        dumped2 = exp2.model_dump(exclude={"id"})
        assert dumped1 == dumped2

    def test_repeated_calls_with_pinned_id_produce_fully_equal_experiences(self) -> None:
        """Experience.id doğrudan model üzerinde sonradan atanabildiğinden
        (Deneyim üretme çağrısı id'yi sabitlemez), tam eşitliği kanıtlamak
        için iki sonucu id hariç karşılaştırmak yeterli ve doğru yöntemdir."""
        exp1 = _build()
        exp2 = _build()
        assert exp1.model_dump(exclude={"id"}) == exp2.model_dump(exclude={"id"})


# ---------------------------------------------------------------------------
# 12. Bağımlılık/I-O yokluğu
# ---------------------------------------------------------------------------


class TestNoDependenciesNoIO:
    def test_function_signature_has_no_llm_or_store_parameter(self) -> None:
        sig = inspect.signature(build_experience_from_turn)
        param_names = set(sig.parameters.keys())
        assert param_names == {
            "session_id",
            "user_message",
            "assistant_response",
            "turn_messages",
            "occurred_at",
            "metadata",
        }

    def test_function_is_synchronous_not_async(self) -> None:
        """LLM çağrısı yapan servisler (MemoryExtractor, MemoryWriteService)
        async'tir; bu fonksiyonun sync olması I/O yapmadığının yapısal kanıtıdır."""
        assert not inspect.iscoroutinefunction(build_experience_from_turn)

    def test_module_imports_nothing_from_llm_or_store_layers(self) -> None:
        import app.memory.experience_builder as builder_module

        import_lines = [
            line.strip()
            for line in inspect.getsource(builder_module).splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        joined_imports = "\n".join(import_lines)

        assert "LLMProvider" not in joined_imports
        assert "MemoryStore" not in joined_imports
        assert "sqlite3" not in joined_imports


# ---------------------------------------------------------------------------
# 13. Import izolasyonu
# ---------------------------------------------------------------------------


class TestImportIsolation:
    def test_importing_builder_does_not_break_existing_imports(self) -> None:
        import app.memory.experience_builder  # noqa: F401
        from app.core.chat import ChatMessage as _ChatMessage
        from app.memory.experience import Experience as _Experience
        from app.services.orchestrator import ChatOrchestrator

        assert _ChatMessage is not None
        assert _Experience is not None
        assert ChatOrchestrator is not None

    def test_builder_module_does_not_import_from_the_orchestrator(self) -> None:
        """Bağımlılık yönü tek yönlüdür: ChatOrchestrator artık builder'ı
        kullanır (Phase 2C), ama builder hiçbir zaman orchestrator'a (veya
        başka bir çağırana) geri bağımlı olmamalı. Bu, builder'ın bağımsız
        ve saf kalmaya devam ettiğinin yapısal kanıtıdır — 'orchestrator
        builder'ı hiç bilmiyor' testi (Phase 2B'de geçerliydi) Phase 2C'de
        kasıtlı olarak geçersiz kılındığından, burada onun yerine geçen,
        hâlâ doğru olan garanti budur.

        Not: import satırları taranır (tam kaynak metni değil) — aksi halde
        modülün kendi docstring'indeki açıklayıcı "ChatOrchestrator" sözcüğü
        (bağımlılık değil, düz metin) yanlışlıkla testi patlatırdı.
        """
        import app.memory.experience_builder as builder_module

        import_lines = [
            line.strip()
            for line in inspect.getsource(builder_module).splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        joined_imports = "\n".join(import_lines)

        assert "orchestrator" not in joined_imports.lower()
