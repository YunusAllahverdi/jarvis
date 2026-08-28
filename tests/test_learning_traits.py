"""Learning katmanı — UserTrait modeli ve SQLiteUserTraitStore testleri.

Kapsam:
 1. confidence_from_evidence deterministik ve doyuma ulaşan bir eğridir
 2. normalize_trait_key deterministik ve tekrarlanabilirdir
 3. UserTrait anahtar doğrulaması normalize edilmemiş anahtarları reddeder
 4. Trait round-trip (tüm alanlar korunur)
 5. upsert aynı (trait_type, key) için YENİ satır oluşturmaz, tazeler
 6. upsert id/created_at/first_observed_at'i korur
 7. Farklı trait_type aynı key ile ayrı trait'lerdir
 8. invalidate mantıksaldır — fiziksel kayıt korunur
 9. Geçersizleştirmeden sonra aynı kimlik yeniden oluşturulabilir (tarihçe birikir)
10. list_active güven sırasına göre döner ve filtreleri uygular
11. Etkin kimlik kısıtı veritabanı düzeyinde zorlanır
12. Aynı veritabanı dosyasında diğer store'larla birlikte var olur
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.learning.sqlite_trait_store import SQLiteUserTraitStore
from app.learning.trait import (
    TraitSource,
    TraitType,
    UserTrait,
    confidence_from_evidence,
    normalize_trait_key,
)
from app.learning.trait_store import UserTraitStore
from app.memory.experience import Experience
from app.memory.record import MemoryRecord
from app.memory.sqlite_experience_store import SQLiteExperienceStore
from app.memory.sqlite_store import SQLiteMemoryStore

_NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _make_trait(**overrides: object) -> UserTrait:
    defaults: dict[str, object] = dict(
        trait_type=TraitType.INTEREST,
        key="topic:python",
        value="python",
        evidence_count=3,
        confidence=confidence_from_evidence(3),
        source=TraitSource.EXPERIENCE,
        first_observed_at=_NOW,
        last_observed_at=_NOW,
    )
    defaults.update(overrides)
    return UserTrait(**defaults)  # type: ignore[arg-type]


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteUserTraitStore:
    return SQLiteUserTraitStore(str(tmp_path / "memory.db"))


# ---------------------------------------------------------------------------
# 1. Güven fonksiyonu
# ---------------------------------------------------------------------------


class TestConfidenceFromEvidence:
    def test_zero_or_negative_evidence_is_zero_confidence(self) -> None:
        assert confidence_from_evidence(0) == 0.0
        assert confidence_from_evidence(-5) == 0.0

    def test_known_reference_points(self) -> None:
        assert confidence_from_evidence(1) == 0.2
        assert confidence_from_evidence(4) == 0.5
        assert confidence_from_evidence(12) == 0.75
        assert confidence_from_evidence(36) == 0.9

    def test_is_monotonically_increasing(self) -> None:
        values = [confidence_from_evidence(n) for n in range(1, 50)]
        assert values == sorted(values)
        assert len(set(values)) == len(values)

    def test_never_reaches_certainty(self) -> None:
        """Hiçbir gözlem sayısı mutlak kesinlik üretmemeli."""
        assert confidence_from_evidence(10_000) < 1.0

    def test_is_deterministic(self) -> None:
        assert confidence_from_evidence(7) == confidence_from_evidence(7)


# ---------------------------------------------------------------------------
# 2-3. Anahtar normalizasyonu ve doğrulaması
# ---------------------------------------------------------------------------


class TestTraitKeyNormalization:
    def test_normalizes_case_and_separators(self) -> None:
        assert normalize_trait_key("Topic: Machine Learning") == "topic:_machine_learning"

    def test_is_idempotent(self) -> None:
        once = normalize_trait_key("Kullanıcı Tercihi!")
        assert normalize_trait_key(once) == once

    def test_same_input_always_yields_same_key(self) -> None:
        assert normalize_trait_key("tool:get_time") == normalize_trait_key("tool:get_time")

    def test_turkish_letters_are_preserved_not_mangled(self) -> None:
        """ASCII'ye kısıtlamak Türkçe terimleri bozar ve daha kötüsü farklı
        kelimeleri aynı anahtara çökertip ilgisiz gözlemleri birleştirirdi."""
        assert normalize_trait_key("topic:başlık") == "topic:başlık"
        assert normalize_trait_key("topic:nasılsın") == "topic:nasılsın"

    def test_distinct_turkish_words_do_not_collide(self) -> None:
        assert normalize_trait_key("topic:şık") != normalize_trait_key("topic:çık")

    def test_uppercase_is_folded_so_one_concept_is_one_row(self) -> None:
        assert normalize_trait_key("Topic:İLGİ") == normalize_trait_key("topic:ilgi")

    def test_empty_input_yields_placeholder(self) -> None:
        assert normalize_trait_key("   ") == "unknown"
        assert normalize_trait_key("!!!") == "unknown"

    def test_is_truncated_to_the_column_limit(self) -> None:
        assert len(normalize_trait_key("a" * 500)) == 120

    def test_model_rejects_unnormalized_keys(self) -> None:
        """Serbest metin anahtarlar sessizce kabul edilirse idempotentlik bozulur."""
        with pytest.raises(ValueError, match="normalize edilmemiş"):
            _make_trait(key="Topic: Python")

    def test_model_accepts_normalized_keys(self) -> None:
        assert _make_trait(key="memory:sha256:abc123").key == "memory:sha256:abc123"


# ---------------------------------------------------------------------------
# 4. Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_all_fields_survive_a_round_trip(self, store: SQLiteUserTraitStore) -> None:
        trait = _make_trait(
            trait_type=TraitType.RECURRING_NEED,
            key="tool:get_time",
            value="get_time",
            evidence_count=9,
            confidence=confidence_from_evidence(9),
            source=TraitSource.EXPERIENCE,
            metadata={"share_of_tool_calls": 0.75, "nested": {"a": 1}},
        )

        stored = store.upsert(trait)
        fetched = store.get(stored.id)

        assert fetched is not None
        assert fetched.trait_type is TraitType.RECURRING_NEED
        assert fetched.key == "tool:get_time"
        assert fetched.value == "get_time"
        assert fetched.evidence_count == 9
        assert fetched.confidence == confidence_from_evidence(9)
        assert fetched.source is TraitSource.EXPERIENCE
        assert fetched.metadata == {"share_of_tool_calls": 0.75, "nested": {"a": 1}}
        assert fetched.invalid_at is None
        assert fetched.is_active

    def test_unicode_values_are_preserved_exactly(self, store: SQLiteUserTraitStore) -> None:
        text = "Kullanıcı sade ve öz cevapları tercih ediyor — İstanbul'da yaşıyor."
        stored = store.upsert(_make_trait(trait_type=TraitType.PREFERENCE, value=text))
        fetched = store.get(stored.id)
        assert fetched is not None
        assert fetched.value == text

    def test_get_returns_none_for_unknown_id(self, store: SQLiteUserTraitStore) -> None:
        assert store.get("does-not-exist") is None

    def test_store_satisfies_the_protocol(self, store: SQLiteUserTraitStore) -> None:
        assert isinstance(store, UserTraitStore)


# ---------------------------------------------------------------------------
# 5-7. upsert semantiği
# ---------------------------------------------------------------------------


class TestUpsertSemantics:
    def test_second_upsert_updates_instead_of_inserting(
        self, store: SQLiteUserTraitStore
    ) -> None:
        store.upsert(_make_trait(evidence_count=3, confidence=confidence_from_evidence(3)))
        store.upsert(_make_trait(evidence_count=8, confidence=confidence_from_evidence(8)))

        assert store.count() == 1
        active = store.find_active(TraitType.INTEREST, "topic:python")
        assert active is not None
        assert active.evidence_count == 8
        assert active.confidence == confidence_from_evidence(8)

    def test_upsert_preserves_identity_and_first_observation(
        self, store: SQLiteUserTraitStore
    ) -> None:
        """Bir gözlemin İLK kez ne zaman görüldüğü bilgisi kaybolmamalı."""
        first = store.upsert(_make_trait(first_observed_at=_NOW, last_observed_at=_NOW))

        later = _NOW + timedelta(days=30)
        second = store.upsert(
            _make_trait(evidence_count=20, first_observed_at=later, last_observed_at=later)
        )

        assert second.id == first.id
        assert second.created_at == first.created_at
        assert second.first_observed_at == _NOW  # korunur
        assert second.last_observed_at == later  # tazelenir

    def test_upsert_refreshes_value_and_metadata(self, store: SQLiteUserTraitStore) -> None:
        store.upsert(_make_trait(value="python", metadata={"document_frequency": 3}))
        store.upsert(_make_trait(value="python3", metadata={"document_frequency": 7}))

        active = store.find_active(TraitType.INTEREST, "topic:python")
        assert active is not None
        assert active.value == "python3"
        assert active.metadata == {"document_frequency": 7}

    def test_same_key_under_different_types_are_separate_traits(
        self, store: SQLiteUserTraitStore
    ) -> None:
        store.upsert(_make_trait(trait_type=TraitType.INTEREST, key="shared_key"))
        store.upsert(_make_trait(trait_type=TraitType.PATTERN, key="shared_key"))

        assert store.count() == 2
        assert store.find_active(TraitType.INTEREST, "shared_key") is not None
        assert store.find_active(TraitType.PATTERN, "shared_key") is not None

    def test_find_active_returns_none_when_absent(self, store: SQLiteUserTraitStore) -> None:
        assert store.find_active(TraitType.GOAL, "topic:absent") is None


# ---------------------------------------------------------------------------
# 8-9. Geçersizleştirme mantıksaldır
# ---------------------------------------------------------------------------


class TestInvalidation:
    def test_invalidate_is_logical_not_physical(self, store: SQLiteUserTraitStore) -> None:
        stored = store.upsert(_make_trait())

        assert store.invalidate(stored.id) is True

        # Etkin listede yok ...
        assert store.find_active(TraitType.INTEREST, "topic:python") is None
        assert store.list_active() == []
        assert store.count() == 0
        # ... ama fiziksel kayıt duruyor.
        assert store.count(include_invalidated=True) == 1
        historical = store.get(stored.id)
        assert historical is not None
        assert historical.invalid_at is not None
        assert historical.is_active is False
        assert historical.value == "python"

    def test_invalidating_twice_returns_false(self, store: SQLiteUserTraitStore) -> None:
        stored = store.upsert(_make_trait())
        assert store.invalidate(stored.id) is True
        assert store.invalidate(stored.id) is False

    def test_invalidating_unknown_id_returns_false(self, store: SQLiteUserTraitStore) -> None:
        assert store.invalidate("does-not-exist") is False

    def test_identity_can_be_recreated_after_invalidation(
        self, store: SQLiteUserTraitStore
    ) -> None:
        """Geçersizleştirme sonrası aynı kavram yeniden öğrenilebilir; tarihçe birikir."""
        first = store.upsert(_make_trait())
        store.invalidate(first.id)

        second = store.upsert(_make_trait(evidence_count=5))

        assert second.id != first.id
        assert store.count() == 1
        assert store.count(include_invalidated=True) == 2


# ---------------------------------------------------------------------------
# 10. list_active sıralama ve filtreleme
# ---------------------------------------------------------------------------


class TestListActive:
    def test_orders_by_confidence_descending(self, store: SQLiteUserTraitStore) -> None:
        store.upsert(_make_trait(key="topic:a", evidence_count=1, confidence=0.2))
        store.upsert(_make_trait(key="topic:c", evidence_count=36, confidence=0.9))
        store.upsert(_make_trait(key="topic:b", evidence_count=4, confidence=0.5))

        assert [t.key for t in store.list_active()] == ["topic:c", "topic:b", "topic:a"]

    def test_filters_by_trait_type(self, store: SQLiteUserTraitStore) -> None:
        store.upsert(_make_trait(trait_type=TraitType.INTEREST, key="topic:x"))
        store.upsert(_make_trait(trait_type=TraitType.GOAL, key="memory:goal_1"))

        goals = store.list_active(trait_type=TraitType.GOAL)
        assert [t.key for t in goals] == ["memory:goal_1"]

    def test_filters_by_min_confidence(self, store: SQLiteUserTraitStore) -> None:
        store.upsert(_make_trait(key="topic:weak", confidence=0.2))
        store.upsert(_make_trait(key="topic:strong", confidence=0.9))

        strong = store.list_active(min_confidence=0.5)
        assert [t.key for t in strong] == ["topic:strong"]

    def test_respects_limit_and_offset(self, store: SQLiteUserTraitStore) -> None:
        for index in range(5):
            store.upsert(_make_trait(key=f"topic:t{index}", confidence=0.9 - index * 0.1))

        page = store.list_active(limit=2, offset=2)
        assert [t.key for t in page] == ["topic:t2", "topic:t3"]

    def test_excludes_invalidated_traits(self, store: SQLiteUserTraitStore) -> None:
        keep = store.upsert(_make_trait(key="topic:keep"))
        drop = store.upsert(_make_trait(key="topic:drop"))
        store.invalidate(drop.id)

        assert [t.id for t in store.list_active()] == [keep.id]

    def test_empty_store_returns_empty_list(self, store: SQLiteUserTraitStore) -> None:
        assert store.list_active() == []


# ---------------------------------------------------------------------------
# 11. Etkin kimlik kısıtı veritabanı düzeyinde
# ---------------------------------------------------------------------------


class TestActiveIdentityConstraint:
    def test_duplicate_active_identity_is_rejected_by_the_database(
        self, store: SQLiteUserTraitStore
    ) -> None:
        """upsert bu durumu zaten önler; kısıt ikinci bir savunma hattıdır —
        gelecekte doğrudan INSERT eden bir yol eklenirse veri bozulamaz."""
        store.upsert(_make_trait())
        duplicate = _make_trait()  # aynı (trait_type, key), farklı id

        with pytest.raises(sqlite3.IntegrityError):
            store._insert(duplicate)


# ---------------------------------------------------------------------------
# 12. Aynı veritabanı dosyasında birlikte var olma
# ---------------------------------------------------------------------------


class TestCoexistenceWithOtherStores:
    def test_three_stores_share_one_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        memory_store = SQLiteMemoryStore(str(db_path))
        experience_store = SQLiteExperienceStore(str(db_path))
        trait_store = SQLiteUserTraitStore(str(db_path))

        memory_store.add(MemoryRecord(content="The user lives in Istanbul."))
        experience_store.add(
            Experience(
                session_id="sess-1",
                occurred_at=_NOW,
                user_message="merhaba",
                assistant_response="selam",
            )
        )
        trait_store.upsert(_make_trait())

        assert memory_store.count() == 1
        assert experience_store.count() == 1
        assert trait_store.count() == 1
        assert [p.name for p in tmp_path.glob("*.db")] == ["memory.db"]

    def test_trait_store_can_be_created_before_the_other_stores(
        self, tmp_path: Path
    ) -> None:
        """Şema kurulum sırası sonucu değiştirmemeli (idempotent DDL)."""
        db_path = tmp_path / "memory.db"
        trait_store = SQLiteUserTraitStore(str(db_path))
        memory_store = SQLiteMemoryStore(str(db_path))

        trait_store.upsert(_make_trait())
        memory_store.add(MemoryRecord(content="x"))

        assert trait_store.count() == 1
        assert memory_store.count() == 1
