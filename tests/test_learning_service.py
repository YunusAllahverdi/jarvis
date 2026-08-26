"""Learning katmanı — trait türetme ve LearningService testleri.

Kapsam:
 1. Tekrar eden tool kullanımı RECURRING_NEED üretir (eşiğin altı üretmez)
 2. Tekrar eden konular INTEREST üretir (eşiğin altı üretmez)
 3. Aktiflik ritmi ve oturum derinliği PATTERN üretir
 4. PREFERENCE/GOAL bellek kayıtları ilgili trait'lere dönüşür
 5. FACT kayıtları yalnızca topic_key taşıyorsa ATTRIBUTE olur
 6. Aynı topic_key'e düşen kayıtlar tek trait'te birleşir
 7. Trait anahtarları deterministiktir (aynı içerik → aynı anahtar)
 8. run_pass gerçek depolarla uçtan uca çalışır
 9. run_pass IDEMPOTENT'tir — tekrar çalıştırmak kanıtı şişirmez
10. Yeni kanıt geldiğinde kanıt/güven ARTAR
11. Kaynak depolar eksikse geçiş hatasız tamamlanır
12. Depo hatası istisna fırlatmaz, failed=True döner
13. LearningService somut SQLite sınıflarına atıf yapmaz
14. Öğrenme sohbet akışının dışındadır (orchestrator'a bağlı değildir)
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.learning.analyzer import analyze_experiences
from app.learning.sqlite_trait_store import SQLiteUserTraitStore
from app.learning.trait import TraitSource, TraitType, confidence_from_evidence
from app.memory.experience import Experience
from app.memory.record import MemoryRecord, MemoryType
from app.memory.sqlite_experience_store import SQLiteExperienceStore
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services import learning_service as learning_service_module
from app.services.learning_service import (
    LearningService,
    derive_traits_from_analysis,
    derive_traits_from_memories,
)

_NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _exp(
    *,
    user_message: str = "test",
    session_id: str | None = "sess-1",
    hour: int = 20,
    day: int = 26,
    tool_calls: list[str] | None = None,
) -> Experience:
    return Experience(
        session_id=session_id,
        occurred_at=datetime(2026, 8, day, hour, 0, tzinfo=UTC),
        user_message=user_message,
        assistant_response="cevap",
        tool_calls=tool_calls or [],
    )


def _derive(experiences: list[Experience]) -> dict[tuple[TraitType, str], object]:
    analysis = analyze_experiences(experiences)
    return {(t.trait_type, t.key): t for t in derive_traits_from_analysis(analysis, now=_NOW)}


# ---------------------------------------------------------------------------
# 1. Tekrar eden tool kullanımı
# ---------------------------------------------------------------------------


class TestRecurringNeedDerivation:
    def test_repeated_tool_use_becomes_a_recurring_need(self) -> None:
        traits = _derive([
            _exp(tool_calls=["get_time"]),
            _exp(tool_calls=["get_time"]),
            _exp(tool_calls=["get_time"]),
        ])

        trait = traits[(TraitType.RECURRING_NEED, "tool:get_time")]
        assert trait.value == "get_time"  # type: ignore[attr-defined]
        assert trait.evidence_count == 3  # type: ignore[attr-defined]
        assert trait.confidence == confidence_from_evidence(3)  # type: ignore[attr-defined]
        assert trait.source is TraitSource.EXPERIENCE  # type: ignore[attr-defined]

    def test_single_use_is_below_the_threshold(self) -> None:
        """Tek bir kullanımdan kalıcı bir ihtiyaç çıkarılmamalı."""
        traits = _derive([_exp(tool_calls=["get_time"])])

        assert (TraitType.RECURRING_NEED, "tool:get_time") not in traits

    def test_each_tool_gets_its_own_trait(self) -> None:
        traits = _derive([
            _exp(tool_calls=["get_time", "calculator"]),
            _exp(tool_calls=["get_time", "calculator"]),
        ])

        assert (TraitType.RECURRING_NEED, "tool:get_time") in traits
        assert (TraitType.RECURRING_NEED, "tool:calculator") in traits


# ---------------------------------------------------------------------------
# 2. Tekrar eden konular
# ---------------------------------------------------------------------------


class TestInterestDerivation:
    def test_recurring_topic_becomes_an_interest(self) -> None:
        traits = _derive([
            _exp(user_message="python öğreniyorum"),
            _exp(user_message="python performansı"),
            _exp(user_message="python testleri"),
        ])

        trait = traits[(TraitType.INTEREST, "topic:python")]
        assert trait.value == "python"  # type: ignore[attr-defined]
        assert trait.evidence_count == 3  # type: ignore[attr-defined]

    def test_topic_below_document_frequency_threshold_is_ignored(self) -> None:
        traits = _derive([
            _exp(user_message="python öğreniyorum"),
            _exp(user_message="python performansı"),
        ])

        assert (TraitType.INTEREST, "topic:python") not in traits

    def test_stopword_heavy_conversation_produces_no_interests(self) -> None:
        traits = _derive([
            _exp(user_message="merhaba nasılsın"),
            _exp(user_message="merhaba nasılsın"),
            _exp(user_message="merhaba nasılsın"),
        ])

        assert not [key for key in traits if key[0] is TraitType.INTEREST]


# ---------------------------------------------------------------------------
# 3. Davranış kalıpları
# ---------------------------------------------------------------------------


class TestPatternDerivation:
    def test_dominant_activity_period_becomes_a_pattern(self) -> None:
        traits = _derive([_exp(hour=20, day=d) for d in range(20, 26)])

        trait = traits[(TraitType.PATTERN, "active_period")]
        assert trait.value == "evening"  # type: ignore[attr-defined]

    def test_too_few_experiences_produce_no_rhythm_pattern(self) -> None:
        traits = _derive([_exp(hour=20), _exp(hour=20)])

        assert (TraitType.PATTERN, "active_period") not in traits

    def test_scattered_activity_produces_no_dominant_period(self) -> None:
        """Hiçbir bölüm baskın değilse kalıp uydurulmamalı."""
        traits = _derive([
            _exp(hour=2),
            _exp(hour=3),
            _exp(hour=8),
            _exp(hour=9),
            _exp(hour=14),
            _exp(hour=15),
            _exp(hour=20),
            _exp(hour=21),
        ])

        assert (TraitType.PATTERN, "active_period") not in traits

    def test_session_depth_is_derived_from_multiple_sessions(self) -> None:
        traits = _derive([
            _exp(session_id="a"),
            _exp(session_id="a"),
            _exp(session_id="a"),
            _exp(session_id="b"),
            _exp(session_id="b"),
            _exp(session_id="b"),
            _exp(session_id="c"),
            _exp(session_id="c"),
            _exp(session_id="c"),
        ])

        trait = traits[(TraitType.PATTERN, "session_depth")]
        assert trait.value == "medium"  # type: ignore[attr-defined]
        assert trait.evidence_count == 3  # type: ignore[attr-defined]

    def test_too_few_sessions_produce_no_depth_pattern(self) -> None:
        traits = _derive([_exp(session_id="a"), _exp(session_id="b")])

        assert (TraitType.PATTERN, "session_depth") not in traits


# ---------------------------------------------------------------------------
# 4-7. Bellek kaynaklı trait'ler
# ---------------------------------------------------------------------------


class TestMemoryDerivation:
    def test_preference_record_becomes_a_preference_trait(self) -> None:
        traits = derive_traits_from_memories(
            [
                MemoryRecord(
                    memory_type=MemoryType.PREFERENCE,
                    content="Kullanıcı kısa cevapları tercih ediyor.",
                    metadata={"topic_key": "answer_style"},
                )
            ],
            now=_NOW,
        )

        assert len(traits) == 1
        assert traits[0].trait_type is TraitType.PREFERENCE
        assert traits[0].key == "memory:answer_style"
        assert traits[0].value == "Kullanıcı kısa cevapları tercih ediyor."
        assert traits[0].source is TraitSource.MEMORY

    def test_goal_record_becomes_a_goal_trait(self) -> None:
        traits = derive_traits_from_memories(
            [MemoryRecord(memory_type=MemoryType.GOAL, content="Jarvis'i bitirmek.")],
            now=_NOW,
        )

        assert traits[0].trait_type is TraitType.GOAL

    def test_fact_without_topic_key_is_not_an_attribute(self) -> None:
        """Her serbest gerçek kalıcı bir kullanıcı özelliği değildir."""
        traits = derive_traits_from_memories(
            [MemoryRecord(memory_type=MemoryType.FACT, content="Hava bugün güzel.")],
            now=_NOW,
        )

        assert traits == []

    def test_fact_with_topic_key_becomes_an_attribute(self) -> None:
        traits = derive_traits_from_memories(
            [
                MemoryRecord(
                    memory_type=MemoryType.FACT,
                    content="Kullanıcı İstanbul'da yaşıyor.",
                    metadata={"topic_key": "user_residence"},
                )
            ],
            now=_NOW,
        )

        assert traits[0].trait_type is TraitType.ATTRIBUTE
        assert traits[0].key == "memory:user_residence"

    def test_unmapped_memory_types_are_ignored(self) -> None:
        traits = derive_traits_from_memories(
            [
                MemoryRecord(memory_type=MemoryType.EVENT, content="Toplantı yapıldı."),
                MemoryRecord(memory_type=MemoryType.OTHER, content="Bir şey."),
            ],
            now=_NOW,
        )

        assert traits == []

    def test_records_sharing_a_topic_key_merge_into_one_trait(self) -> None:
        older = MemoryRecord(
            memory_type=MemoryType.PREFERENCE,
            content="Kullanıcı uzun cevap istiyor.",
            metadata={"topic_key": "answer_style"},
            valid_at=_NOW - timedelta(days=5),
        )
        newer = MemoryRecord(
            memory_type=MemoryType.PREFERENCE,
            content="Kullanıcı kısa cevap istiyor.",
            metadata={"topic_key": "answer_style"},
            valid_at=_NOW,
        )

        traits = derive_traits_from_memories([older, newer], now=_NOW)

        assert len(traits) == 1
        assert traits[0].evidence_count == 2
        assert traits[0].value == "Kullanıcı kısa cevap istiyor."  # en yeni kazanır
        assert traits[0].first_observed_at == older.valid_at
        assert traits[0].last_observed_at == newer.valid_at
        assert traits[0].metadata["memory_ids"] == sorted([older.id, newer.id])

    def test_key_is_deterministic_for_records_without_topic_key(self) -> None:
        """Aynı içerik her geçişte aynı anahtarı üretmeli (idempotentlik şartı)."""
        first = derive_traits_from_memories(
            [MemoryRecord(memory_type=MemoryType.GOAL, content="Aynı hedef.")], now=_NOW
        )
        second = derive_traits_from_memories(
            [MemoryRecord(memory_type=MemoryType.GOAL, content="Aynı hedef.")], now=_NOW
        )

        assert first[0].key == second[0].key
        assert first[0].id != second[0].id  # kimlik yeni, anahtar aynı
        assert first[0].key.startswith("memory:sha256:")

    def test_different_content_yields_different_keys(self) -> None:
        traits = derive_traits_from_memories(
            [
                MemoryRecord(memory_type=MemoryType.GOAL, content="Birinci hedef."),
                MemoryRecord(memory_type=MemoryType.GOAL, content="İkinci hedef."),
            ],
            now=_NOW,
        )

        assert len({t.key for t in traits}) == 2


# ---------------------------------------------------------------------------
# 8-11. LearningService uçtan uca
# ---------------------------------------------------------------------------


def _make_service(tmp_path: Path) -> tuple[LearningService, SQLiteUserTraitStore, SQLiteExperienceStore, SQLiteMemoryStore]:
    db_path = str(tmp_path / "memory.db")
    trait_store = SQLiteUserTraitStore(db_path)
    experience_store = SQLiteExperienceStore(db_path)
    memory_store = SQLiteMemoryStore(db_path)
    service = LearningService(
        trait_store=trait_store,
        memory_store=memory_store,
        experience_store=experience_store,
    )
    return service, trait_store, experience_store, memory_store


class TestLearningPass:
    def test_end_to_end_pass_persists_derived_traits(self, tmp_path: Path) -> None:
        service, trait_store, experience_store, memory_store = _make_service(tmp_path)
        for day in range(20, 26):
            experience_store.add(
                _exp(user_message="python projesi", hour=20, day=day, tool_calls=["get_time"])
            )
        memory_store.add(
            MemoryRecord(
                memory_type=MemoryType.PREFERENCE,
                content="Kullanıcı kısa cevap istiyor.",
                metadata={"topic_key": "answer_style"},
            )
        )

        result = service.run_pass(now=_NOW)

        assert result.ok
        assert result.experiences_analyzed == 6
        assert result.memories_analyzed == 1
        assert result.traits_created == result.traits_derived
        assert result.traits_updated == 0

        assert trait_store.find_active(TraitType.RECURRING_NEED, "tool:get_time") is not None
        assert trait_store.find_active(TraitType.INTEREST, "topic:python") is not None
        assert trait_store.find_active(TraitType.PATTERN, "active_period") is not None
        assert trait_store.find_active(TraitType.PREFERENCE, "memory:answer_style") is not None

    def test_pass_is_idempotent(self, tmp_path: Path) -> None:
        """Aynı geçişi iki kez çalıştırmak kanıt sayılarını ŞİŞİRMEMELİ."""
        service, trait_store, experience_store, _ = _make_service(tmp_path)
        for day in range(20, 26):
            experience_store.add(_exp(user_message="python", day=day, tool_calls=["get_time"]))

        first = service.run_pass(now=_NOW)
        after_first = trait_store.count()
        tool_trait_first = trait_store.find_active(TraitType.RECURRING_NEED, "tool:get_time")

        second = service.run_pass(now=_NOW)
        tool_trait_second = trait_store.find_active(TraitType.RECURRING_NEED, "tool:get_time")

        assert second.traits_derived == first.traits_derived
        assert second.traits_created == 0
        assert second.traits_updated == first.traits_created
        assert trait_store.count() == after_first  # yeni satır yok
        assert tool_trait_second is not None and tool_trait_first is not None
        assert tool_trait_second.evidence_count == tool_trait_first.evidence_count
        assert tool_trait_second.id == tool_trait_first.id

    def test_new_evidence_increases_confidence(self, tmp_path: Path) -> None:
        service, trait_store, experience_store, _ = _make_service(tmp_path)
        for day in range(20, 23):
            experience_store.add(_exp(day=day, tool_calls=["get_time"]))
        service.run_pass(now=_NOW)
        before = trait_store.find_active(TraitType.RECURRING_NEED, "tool:get_time")

        for day in range(23, 26):
            experience_store.add(_exp(day=day, tool_calls=["get_time"]))
        service.run_pass(now=_NOW)
        after = trait_store.find_active(TraitType.RECURRING_NEED, "tool:get_time")

        assert before is not None and after is not None
        assert after.evidence_count == 6
        assert after.confidence > before.confidence
        assert after.id == before.id  # aynı trait güçlendi, yenisi doğmadı

    def test_pass_without_sources_succeeds_with_empty_result(self, tmp_path: Path) -> None:
        trait_store = SQLiteUserTraitStore(str(tmp_path / "memory.db"))
        service = LearningService(trait_store=trait_store)

        result = service.run_pass(now=_NOW)

        assert result.ok
        assert result.experiences_analyzed == 0
        assert result.memories_analyzed == 0
        assert result.traits_derived == 0

    def test_pass_with_only_experience_store_skips_memory_traits(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "memory.db")
        trait_store = SQLiteUserTraitStore(db_path)
        experience_store = SQLiteExperienceStore(db_path)
        for day in range(20, 26):
            experience_store.add(_exp(day=day, tool_calls=["get_time"]))
        service = LearningService(trait_store=trait_store, experience_store=experience_store)

        result = service.run_pass(now=_NOW)

        assert result.ok
        assert result.memories_analyzed == 0
        assert trait_store.find_active(TraitType.RECURRING_NEED, "tool:get_time") is not None

    def test_experience_window_bounds_the_analysis(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "memory.db")
        trait_store = SQLiteUserTraitStore(db_path)
        experience_store = SQLiteExperienceStore(db_path)
        for day in range(10, 26):
            experience_store.add(_exp(day=day))
        service = LearningService(
            trait_store=trait_store, experience_store=experience_store, experience_window=5
        )

        result = service.run_pass(now=_NOW)

        assert result.experiences_analyzed == 5


# ---------------------------------------------------------------------------
# 12. Hata izolasyonu
# ---------------------------------------------------------------------------


class TestErrorIsolation:
    def test_store_failure_returns_failed_result_instead_of_raising(self) -> None:
        class _FailingTraitStore:
            def upsert(self, trait):  # noqa: ANN001, ANN201
                raise RuntimeError("trait store unavailable")

            def invalidate(self, trait_id, *, at=None) -> bool:  # noqa: ANN001
                return False

            def get(self, trait_id):  # noqa: ANN001, ANN201
                return None

            def find_active(self, trait_type, key):  # noqa: ANN001, ANN201
                return None

            def list_active(self, **kwargs):  # noqa: ANN003, ANN201
                return []

        class _ExperienceSource:
            def add(self, experience):  # noqa: ANN001, ANN201
                return experience

            def get(self, experience_id):  # noqa: ANN001, ANN201
                return None

            def list_by_session(self, session_id, *, limit=50):  # noqa: ANN001
                return []

            def list_recent(self, *, limit=50, before=None):  # noqa: ANN001
                return [_exp(day=d, tool_calls=["get_time"]) for d in range(20, 26)]

        service = LearningService(
            trait_store=_FailingTraitStore(),  # type: ignore[arg-type]
            experience_store=_ExperienceSource(),  # type: ignore[arg-type]
        )

        result = service.run_pass(now=_NOW)

        assert result.failed is True
        assert result.ok is False

    def test_experience_source_failure_returns_failed_result(self) -> None:
        class _RaisingExperienceStore:
            def add(self, experience):  # noqa: ANN001, ANN201
                return experience

            def get(self, experience_id):  # noqa: ANN001, ANN201
                return None

            def list_by_session(self, session_id, *, limit=50):  # noqa: ANN001
                return []

            def list_recent(self, *, limit=50, before=None):  # noqa: ANN001
                raise RuntimeError("experience store unavailable")

        class _NoopTraitStore:
            def upsert(self, trait):  # noqa: ANN001, ANN201
                return trait

            def invalidate(self, trait_id, *, at=None) -> bool:  # noqa: ANN001
                return False

            def get(self, trait_id):  # noqa: ANN001, ANN201
                return None

            def find_active(self, trait_type, key):  # noqa: ANN001, ANN201
                return None

            def list_active(self, **kwargs):  # noqa: ANN003, ANN201
                return []

        service = LearningService(
            trait_store=_NoopTraitStore(),  # type: ignore[arg-type]
            experience_store=_RaisingExperienceStore(),  # type: ignore[arg-type]
        )

        assert service.run_pass(now=_NOW).failed is True


# ---------------------------------------------------------------------------
# 13-14. Mimari izolasyon
# ---------------------------------------------------------------------------


class TestArchitecturalIsolation:
    def test_learning_service_does_not_reference_concrete_stores(self) -> None:
        source = inspect.getsource(learning_service_module)

        assert "SQLiteUserTraitStore" not in source
        assert "SQLiteMemoryStore" not in source
        assert "SQLiteExperienceStore" not in source
        # Somut depo modülleri hiç import edilmemeli (mevcut orchestrator
        # izolasyon testleriyle aynı kaynak-tarama yaklaşımı).
        assert "sqlite_trait_store" not in source
        assert "sqlite_store" not in source
        assert "sqlite_experience_store" not in source

    def test_learning_is_outside_the_chat_path(self) -> None:
        """ChatOrchestrator öğrenme katmanını hiç bilmemeli — bir öğrenme
        geçişi bir sohbet cevabını hiçbir koşulda geciktirememeli."""
        import app.services.orchestrator as orchestrator_module

        source = inspect.getsource(orchestrator_module)
        assert "LearningService" not in source
        assert "learning" not in source.lower()
        assert "UserTrait" not in source

    def test_learning_service_calls_no_llm(self) -> None:
        source = inspect.getsource(learning_service_module)

        assert "LLMProvider" not in source
        assert "generate" not in source
