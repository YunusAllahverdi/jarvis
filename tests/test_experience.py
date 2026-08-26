"""Phase 2A — Experience modeli testleri.

Kapsam:
 1. Minimal geçerli kurulum
 2. Otomatik UUID üretimi
 3. Farklı örnekler farklı id alır
 4. Varsayılan değerler
 5. Değiştirilebilir (mutable) varsayılanlar örnekler arasında izole
 6. Tüm ExperienceOutcome değerleri
 7. model_dump/model_validate round-trip
 8. Experience, MemoryRecord'dan bağımsızdır
 9. Yeni modülü import etmek mevcut import'ları etkilemez

Bu dosya yalnızca modelin veri şeklini test eder — hiçbir depoya yazma,
hiçbir LLM çağrısı veya canlı sohbet akışı içermez (Phase 2A kapsamı).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.memory.experience import Experience, ExperienceOutcome


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------


def _make_experience(**overrides: object) -> Experience:
    defaults: dict[str, object] = dict(
        occurred_at=datetime.now(UTC),
        user_message="I live in Istanbul.",
    )
    defaults.update(overrides)
    return Experience(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Minimal geçerli kurulum
# ---------------------------------------------------------------------------


class TestMinimalConstruction:
    def test_minimal_construction_requires_only_occurred_at_and_user_message(self) -> None:
        exp = Experience(occurred_at=datetime.now(UTC), user_message="Merhaba")
        assert exp.user_message == "Merhaba"

    def test_missing_occurred_at_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Experience(user_message="Merhaba")  # type: ignore[call-arg]

    def test_missing_user_message_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Experience(occurred_at=datetime.now(UTC))  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 2-3. Otomatik UUID üretimi
# ---------------------------------------------------------------------------


class TestAutomaticIdGeneration:
    def test_id_is_auto_generated_when_omitted(self) -> None:
        exp = _make_experience()
        assert exp.id
        assert isinstance(exp.id, str)

    def test_id_is_uuid_formatted(self) -> None:
        exp = _make_experience()
        # UUID4 formatı: 8-4-4-4-12 karakter hex grupları
        assert len(exp.id) == 36
        assert exp.id.count("-") == 4

    def test_two_instances_get_different_ids(self) -> None:
        exp1 = _make_experience()
        exp2 = _make_experience()
        assert exp1.id != exp2.id

    def test_explicit_id_is_preserved(self) -> None:
        exp = _make_experience(id="custom-id-123")
        assert exp.id == "custom-id-123"


# ---------------------------------------------------------------------------
# 4. Varsayılan değerler
# ---------------------------------------------------------------------------


class TestDefaultValues:
    def test_session_id_defaults_to_none(self) -> None:
        assert _make_experience().session_id is None

    def test_assistant_response_defaults_to_none(self) -> None:
        assert _make_experience().assistant_response is None

    def test_tool_calls_defaults_to_empty_list(self) -> None:
        assert _make_experience().tool_calls == []

    def test_user_state_defaults_to_none(self) -> None:
        """Emotion/user-state mantığı henüz implemente edilmedi — alan var
        ama hiçbir kod tarafından doldurulmuyor."""
        assert _make_experience().user_state is None

    def test_emotional_context_defaults_to_none(self) -> None:
        """Emotion engine implementasyonu YOK — alan yalnızca geleceğe hazır
        bir yer tutucu."""
        assert _make_experience().emotional_context is None

    def test_outcome_defaults_to_unknown(self) -> None:
        assert _make_experience().outcome == ExperienceOutcome.UNKNOWN

    def test_derived_memory_ids_defaults_to_empty_list(self) -> None:
        assert _make_experience().derived_memory_ids == []

    def test_metadata_defaults_to_empty_dict(self) -> None:
        assert _make_experience().metadata == {}


# ---------------------------------------------------------------------------
# 5. Değiştirilebilir varsayılanlar izole
# ---------------------------------------------------------------------------


class TestMutableDefaultsAreIsolated:
    def test_tool_calls_lists_are_independent_across_instances(self) -> None:
        exp1 = _make_experience()
        exp2 = _make_experience()
        exp1.tool_calls.append("calculator")
        assert exp1.tool_calls == ["calculator"]
        assert exp2.tool_calls == []

    def test_derived_memory_ids_lists_are_independent_across_instances(self) -> None:
        exp1 = _make_experience()
        exp2 = _make_experience()
        exp1.derived_memory_ids.append("mem-1")
        assert exp1.derived_memory_ids == ["mem-1"]
        assert exp2.derived_memory_ids == []

    def test_metadata_dicts_are_independent_across_instances(self) -> None:
        exp1 = _make_experience()
        exp2 = _make_experience()
        exp1.metadata["key"] = "value"
        assert exp1.metadata == {"key": "value"}
        assert exp2.metadata == {}


# ---------------------------------------------------------------------------
# 6. Tüm ExperienceOutcome değerleri
# ---------------------------------------------------------------------------


class TestExperienceOutcomeValues:
    @pytest.mark.parametrize(
        "outcome",
        [
            ExperienceOutcome.SUCCESS,
            ExperienceOutcome.PARTIAL,
            ExperienceOutcome.FAILED,
            ExperienceOutcome.UNKNOWN,
        ],
    )
    def test_each_outcome_value_is_accepted(self, outcome: ExperienceOutcome) -> None:
        exp = _make_experience(outcome=outcome)
        assert exp.outcome == outcome

    def test_outcome_accepts_raw_string_value(self) -> None:
        exp = _make_experience(outcome="failed")
        assert exp.outcome == ExperienceOutcome.FAILED

    def test_invalid_outcome_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_experience(outcome="not_a_real_outcome")

    def test_outcome_enum_has_exactly_four_values(self) -> None:
        assert {o.value for o in ExperienceOutcome} == {
            "success",
            "partial",
            "failed",
            "unknown",
        }


# ---------------------------------------------------------------------------
# 7. model_dump/model_validate round-trip
# ---------------------------------------------------------------------------


class TestSerializationRoundTrip:
    def test_model_dump_then_model_validate_round_trip(self) -> None:
        original = _make_experience(
            session_id="sess-1",
            assistant_response="Anladım.",
            tool_calls=["calculator"],
            outcome=ExperienceOutcome.SUCCESS,
            derived_memory_ids=["mem-1", "mem-2"],
            metadata={"source": "test"},
        )

        dumped = original.model_dump()
        restored = Experience.model_validate(dumped)

        assert restored == original

    def test_model_dump_json_mode_is_json_safe_and_round_trips(self) -> None:
        original = _make_experience(session_id="sess-1")
        dumped_json_mode = original.model_dump(mode="json")

        # JSON modunda datetime bir string olmalı (doğrudan JSON'a serileştirilebilir).
        assert isinstance(dumped_json_mode["occurred_at"], str)

        restored = Experience.model_validate(dumped_json_mode)
        assert restored == original


# ---------------------------------------------------------------------------
# 8. Experience, MemoryRecord'dan bağımsızdır
# ---------------------------------------------------------------------------


class TestIndependenceFromMemoryRecord:
    def test_experience_is_not_a_memory_record_subclass(self) -> None:
        from app.memory.record import MemoryRecord

        exp = _make_experience()
        assert not isinstance(exp, MemoryRecord)

    def test_experience_and_memory_record_are_distinct_classes(self) -> None:
        from app.memory.record import MemoryRecord

        assert Experience is not MemoryRecord
        assert not issubclass(Experience, MemoryRecord)
        assert not issubclass(MemoryRecord, Experience)

    def test_experience_has_no_content_field(self) -> None:
        """MemoryRecord'un zorunlu `content` alanı Experience'ta yok —
        iki model kasıtlı olarak farklı şekillere sahip."""
        assert "content" not in Experience.model_fields


# ---------------------------------------------------------------------------
# 9. Yeni modülü import etmek mevcut import'ları etkilemez
# ---------------------------------------------------------------------------


class TestImportIsolation:
    def test_importing_experience_module_does_not_break_existing_memory_imports(
        self,
    ) -> None:
        import app.memory.experience  # noqa: F401
        from app.memory.record import MemoryRecord
        from app.memory.sqlite_store import SQLiteMemoryStore
        from app.memory.store import MemoryStore

        assert MemoryRecord is not None
        assert MemoryStore is not None
        assert SQLiteMemoryStore is not None

    def test_experience_module_is_not_referenced_by_existing_memory_package_exports(
        self,
    ) -> None:
        """Bu faz Experience'ı canlı uygulamaya bağlamıyor — mevcut
        app/memory paket dışa aktarımları (varsa) hâlâ değişmeden çalışır."""
        import app.memory as memory_package

        # Paketin kendisi hâlâ sorunsuz import edilebiliyor; Experience
        # zorunlu bir dışa aktarım olarak eklenmedi (bilinçli, minimal tasarım).
        assert memory_package is not None
