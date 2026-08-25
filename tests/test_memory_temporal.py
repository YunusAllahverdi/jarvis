"""Phase 1C-2 — MemoryTemporalService test suite.

Kapsam:
 1. Çakışmayan yeni bellek etkin kalır
 2. Çakışan yeni gerçek, eski gerçeği geçersizleştirir
 3. Eski gerçek fiziksel olarak SQLite'ta kalır
 4. Yeni gerçek etkin kayıttır
 5. Geçersizleştirilmiş tarihsel kayıt, açıkça istendiğinde hâlâ getirilebilir
 6. Tercih (preference) değişimi çalışır
 7. Planlanan olay → iptal geçişi çalışır
 8. Planlanan olay → tamamlandı geçişi çalışır
 9. Zaten geçersiz bir kaydı geçersizleştirmek güvenli/idempotent'tir
10. İlgisiz bellekler asla geçersizleştirilmez
11. Bellek id'leri kararlı kalır
12. Geçersizleştirme sırasında created_at değişmez
13. invalid_at doğru şekilde ayarlanır
14. updated_at uygun şekilde değişir
15. Getirme (arama), varsayılan olarak geçersizleştirilmiş kayıtları dışlar
19. Zamansal geçersizleştirme için hiçbir fiziksel DELETE yapılmaz

Not: 16, 17, 18, 20 numaralı gereksinimler (mevcut doğal dil getirme,
uçtan uca yaşam döngüsü testleri, sohbetin bozulmaması, tam suite'in yeşil
kalması) bu dosyaya özgü değildir — tam pytest suite'i çalıştırılarak ve
tests/test_memory_service.py'deki entegrasyon testleriyle doğrulanır.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.memory.record import MemoryRecord, MemoryStatus, MemoryType, Temporality
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services.memory_temporal import MemoryTemporalService, TemporalWriteResult


# ---------------------------------------------------------------------------
# Fixture / yardımcılar
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteMemoryStore:
    """Her test için izole, geçici bir SQLiteMemoryStore döner."""
    return SQLiteMemoryStore(str(tmp_path / "temporal_test.db"))


def _fact(content: str, *, topic_key: str | None = None, **kwargs: object) -> MemoryRecord:
    metadata = {"topic_key": topic_key} if topic_key else {}
    return MemoryRecord(content=content, memory_type=MemoryType.FACT, metadata=metadata, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Çakışmayan yeni bellek etkin kalır
# ---------------------------------------------------------------------------


class TestNoConflictWrite:
    def test_new_fact_without_topic_key_remains_active(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        record = _fact("User's favorite color is blue.")

        result = service.write(record)

        assert isinstance(result, TemporalWriteResult)
        assert result.invalidated_ids == []
        assert result.replaced_conflict is False
        fetched = store.get(record.id)
        assert fetched is not None
        assert fetched.invalid_at is None

    def test_new_fact_with_unique_topic_key_remains_active(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        record = _fact("User lives in Istanbul.", topic_key="user_residence")

        result = service.write(record)

        assert result.invalidated_ids == []
        active = store.list_active(memory_type=MemoryType.FACT)
        assert len(active) == 1


# ---------------------------------------------------------------------------
# 2-5. FACT çakışması / değiştirme
# ---------------------------------------------------------------------------


class TestFactReplacement:
    def test_conflicting_fact_invalidates_old_one(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        old = _fact("User lives in Istanbul.", topic_key="user_residence")
        service.write(old)

        new = _fact("User lives in Ankara.", topic_key="user_residence")
        result = service.write(new)

        assert result.invalidated_ids == [old.id]
        assert result.replaced_conflict is True

    def test_old_fact_physically_remains_in_store(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        old = _fact("User lives in Istanbul.", topic_key="user_residence")
        service.write(old)
        service.write(_fact("User lives in Ankara.", topic_key="user_residence"))

        assert store.count(include_deleted=True) == 2
        fetched_old = store.get(old.id)
        assert fetched_old is not None
        assert fetched_old.content == "User lives in Istanbul."

    def test_new_fact_is_the_active_record(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        service.write(_fact("User lives in Istanbul.", topic_key="user_residence"))
        new = _fact("User lives in Ankara.", topic_key="user_residence")
        service.write(new)

        active = store.list_active(memory_type=MemoryType.FACT)
        assert len(active) == 1
        assert active[0].id == new.id
        assert active[0].content == "User lives in Ankara."

    def test_historical_fact_retrievable_when_explicitly_requested(
        self, store: SQLiteMemoryStore
    ) -> None:
        """Açık talep = get(id). search()/list_active() hâlâ hariç tutar (kasıtlı)."""
        service = MemoryTemporalService(store=store)
        old = _fact("User lives in Istanbul.", topic_key="user_residence")
        service.write(old)
        service.write(_fact("User lives in Ankara.", topic_key="user_residence"))

        historical = store.get(old.id)
        assert historical is not None
        assert historical.content == "User lives in Istanbul."
        assert historical.invalid_at is not None

    def test_search_excludes_invalidated_fact_by_default(
        self, store: SQLiteMemoryStore
    ) -> None:
        service = MemoryTemporalService(store=store)
        service.write(_fact("User lives in Istanbul.", topic_key="user_residence"))
        service.write(_fact("User lives in Ankara.", topic_key="user_residence"))

        assert store.search("Istanbul") == []
        results = store.search("Ankara")
        assert len(results) == 1
        assert results[0].content == "User lives in Ankara."


# ---------------------------------------------------------------------------
# 6. PREFERENCE değişimi
# ---------------------------------------------------------------------------


class TestPreferenceReplacement:
    def test_new_preference_invalidates_old_preference(
        self, store: SQLiteMemoryStore
    ) -> None:
        service = MemoryTemporalService(store=store)
        old = MemoryRecord(
            content="User prefers dark mode.",
            memory_type=MemoryType.PREFERENCE,
            metadata={"topic_key": "user_theme_preference"},
        )
        service.write(old)

        new = MemoryRecord(
            content="User prefers light mode.",
            memory_type=MemoryType.PREFERENCE,
            metadata={"topic_key": "user_theme_preference"},
        )
        result = service.write(new)

        assert result.invalidated_ids == [old.id]
        fetched_old = store.get(old.id)
        assert fetched_old is not None
        assert fetched_old.invalid_at is not None
        active = store.list_active(memory_type=MemoryType.PREFERENCE)
        assert len(active) == 1
        assert active[0].content == "User prefers light mode."
        assert store.count(include_deleted=True) == 2  # fiziksel kayıt korunuyor


# ---------------------------------------------------------------------------
# 7-8. EVENT durum geçişleri
# ---------------------------------------------------------------------------


class TestEventStatusTransitions:
    def test_planned_event_cancelled_transition(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        planned = MemoryRecord(
            content="User is planning a trip to America next month.",
            memory_type=MemoryType.EVENT,
            temporality=Temporality.FUTURE,
            status=MemoryStatus.PLANNED,
            metadata={"topic_key": "travel_plan_america"},
        )
        service.write(planned)

        cancelled = MemoryRecord(
            content="User's trip to America was cancelled.",
            memory_type=MemoryType.EVENT,
            temporality=Temporality.PAST,
            status=MemoryStatus.CANCELLED,
            metadata={"topic_key": "travel_plan_america"},
        )
        result = service.write(cancelled)

        assert result.invalidated_ids == [planned.id]
        old = store.get(planned.id)
        assert old is not None
        assert old.invalid_at is not None
        assert old.status == MemoryStatus.PLANNED  # eski kayıt kendi tarihsel hâlini korur

        active = store.list_active(memory_type=MemoryType.EVENT)
        assert len(active) == 1
        assert active[0].status == MemoryStatus.CANCELLED
        assert "cancelled" in active[0].content.lower()
        # İptal bilgisi kalıcı olarak kayıtlı (fiziksel kayıt sayısı 2).
        assert store.count(include_deleted=True) == 2

    def test_planned_event_completed_transition(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        planned = MemoryRecord(
            content="User is planning to run a marathon in June.",
            memory_type=MemoryType.EVENT,
            status=MemoryStatus.PLANNED,
            metadata={"topic_key": "marathon_june"},
        )
        service.write(planned)

        completed = MemoryRecord(
            content="User completed the June marathon.",
            memory_type=MemoryType.EVENT,
            status=MemoryStatus.COMPLETED,
            metadata={"topic_key": "marathon_june"},
        )
        result = service.write(completed)

        assert result.invalidated_ids == [planned.id]
        active = store.list_active(memory_type=MemoryType.EVENT)
        assert len(active) == 1
        assert active[0].status == MemoryStatus.COMPLETED


# ---------------------------------------------------------------------------
# 9-10. İdempotentlik ve güvenlik
# ---------------------------------------------------------------------------


class TestIdempotenceAndSafety:
    def test_invalidating_already_invalid_record_is_safe(
        self, store: SQLiteMemoryStore
    ) -> None:
        service = MemoryTemporalService(store=store)
        service.write(_fact("User lives in Istanbul.", topic_key="user_residence"))
        service.write(_fact("User lives in Ankara.", topic_key="user_residence"))

        # Üçüncü yazma: yalnızca hâlâ ETKİN olan (Ankara) kayıt geçersizleşir;
        # Istanbul zaten geçersiz olduğundan aday listesine hiç girmez
        # (list_active zaten hariç tutar) — tekrar geçersizleştirme denenmez.
        result = service.write(_fact("User lives in Izmir.", topic_key="user_residence"))

        assert len(result.invalidated_ids) == 1
        active = store.list_active(memory_type=MemoryType.FACT)
        assert len(active) == 1
        assert active[0].content == "User lives in Izmir."

    def test_direct_double_invalidate_on_store_returns_false_second_time(
        self, store: SQLiteMemoryStore
    ) -> None:
        """MemoryTemporalService'in dayandığı store.invalidate() zaten
        idempotent — ikinci çağrı False döner, hata fırlatmaz."""
        rec = store.add(_fact("standalone fact"))
        assert store.invalidate(rec.id) is True
        assert store.invalidate(rec.id) is False  # zaten geçersiz — güvenli

    def test_unrelated_memories_are_never_invalidated(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        unrelated = _fact("User likes pizza.", topic_key="user_food_preference")
        service.write(unrelated)
        service.write(_fact("User lives in Istanbul.", topic_key="user_residence"))
        service.write(_fact("User lives in Ankara.", topic_key="user_residence"))

        fetched_unrelated = store.get(unrelated.id)
        assert fetched_unrelated is not None
        assert fetched_unrelated.invalid_at is None

    def test_different_memory_type_same_topic_key_not_conflicting(
        self, store: SQLiteMemoryStore
    ) -> None:
        """Aynı topic_key farklı memory_type'larda asla çakışma sayılmamalı."""
        service = MemoryTemporalService(store=store)
        fact_rec = _fact("User lives in Istanbul.", topic_key="user_residence")
        service.write(fact_rec)

        event_rec = MemoryRecord(
            content="User is moving next year.",
            memory_type=MemoryType.EVENT,
            metadata={"topic_key": "user_residence"},
        )
        result = service.write(event_rec)

        assert result.invalidated_ids == []
        fetched = store.get(fact_rec.id)
        assert fetched is not None
        assert fetched.invalid_at is None

    def test_no_topic_key_never_triggers_conflict_check(
        self, store: SQLiteMemoryStore
    ) -> None:
        service = MemoryTemporalService(store=store)
        service.write(_fact("User lives in Istanbul."))  # topic_key yok
        result = service.write(_fact("User lives in Ankara."))  # topic_key yok

        assert result.invalidated_ids == []
        assert store.count() == 2
        assert len(store.list_active(memory_type=MemoryType.FACT)) == 2


# ---------------------------------------------------------------------------
# 11-14. Kayıt bütünlüğü
# ---------------------------------------------------------------------------


class TestRecordIntegrity:
    def test_memory_ids_remain_stable(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        old = _fact("User lives in Istanbul.", topic_key="user_residence")
        old_id = old.id
        service.write(old)
        new = _fact("User lives in Ankara.", topic_key="user_residence")
        new_id = new.id
        service.write(new)

        fetched_old = store.get(old_id)
        fetched_new = store.get(new_id)
        assert fetched_old is not None and fetched_old.id == old_id
        assert fetched_new is not None and fetched_new.id == new_id

    def test_created_at_unchanged_when_invalidating(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        old = _fact("User lives in Istanbul.", topic_key="user_residence")
        original_created_at = old.created_at
        service.write(old)
        service.write(_fact("User lives in Ankara.", topic_key="user_residence"))

        fetched = store.get(old.id)
        assert fetched is not None
        assert fetched.created_at == original_created_at

    def test_invalid_at_is_set_correctly(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        old = _fact("User lives in Istanbul.", topic_key="user_residence")
        service.write(old)

        before = datetime.now(UTC)
        service.write(_fact("User lives in Ankara.", topic_key="user_residence"))
        after = datetime.now(UTC)

        fetched = store.get(old.id)
        assert fetched is not None
        assert fetched.invalid_at is not None
        assert before <= fetched.invalid_at <= after

    def test_updated_at_changes_when_invalidated(self, store: SQLiteMemoryStore) -> None:
        service = MemoryTemporalService(store=store)
        old = _fact("User lives in Istanbul.", topic_key="user_residence")
        service.write(old)
        original_updated_at = store.get(old.id).updated_at  # type: ignore[union-attr]

        time.sleep(0.01)
        service.write(_fact("User lives in Ankara.", topic_key="user_residence"))

        fetched = store.get(old.id)
        assert fetched is not None
        assert fetched.updated_at > original_updated_at


# ---------------------------------------------------------------------------
# 15. Getirme, geçersizleştirilmiş kayıtları varsayılan olarak dışlar
# ---------------------------------------------------------------------------


class TestRetrievalExcludesInvalidated:
    def test_list_active_excludes_invalidated_after_replacement(
        self, store: SQLiteMemoryStore
    ) -> None:
        service = MemoryTemporalService(store=store)
        old = _fact("User lives in Istanbul.", topic_key="user_residence")
        service.write(old)
        service.write(_fact("User lives in Ankara.", topic_key="user_residence"))

        active_ids = {r.id for r in store.list_active(memory_type=MemoryType.FACT)}
        assert old.id not in active_ids


# ---------------------------------------------------------------------------
# 19. Hiçbir fiziksel DELETE yapılmaz
# ---------------------------------------------------------------------------


class TestNoPhysicalDelete:
    def test_no_records_are_physically_deleted_across_multiple_replacements(
        self, store: SQLiteMemoryStore
    ) -> None:
        service = MemoryTemporalService(store=store)
        for city in ["Istanbul", "Ankara", "Izmir"]:
            service.write(_fact(f"User lives in {city}.", topic_key="user_residence"))

        # count(include_deleted=True) fiziksel satır sayısını yansıtır —
        # üç yazımın hepsi hâlâ SQLite'ta.
        assert store.count(include_deleted=True) == 3
        assert len(store.list_active(memory_type=MemoryType.FACT)) == 1

    def test_store_add_never_uses_delete(self, store: SQLiteMemoryStore) -> None:
        """MemoryTemporalService, MemoryStore Protocol'ünde delete() metodunu
        hiç çağırmaz — yalnızca add() ve invalidate() kullanır."""

        class _DeleteTrackingStore:
            def __init__(self, real: SQLiteMemoryStore) -> None:
                self._real = real
                self.delete_called = False

            def add(self, record: MemoryRecord) -> MemoryRecord:
                return self._real.add(record)

            def update(self, record: MemoryRecord) -> MemoryRecord:
                return self._real.update(record)

            def invalidate(self, memory_id: str, *, at=None) -> bool:
                return self._real.invalidate(memory_id, at=at)

            def delete(self, memory_id: str, *, at=None) -> bool:
                self.delete_called = True
                return self._real.delete(memory_id, at=at)

            def get(self, memory_id: str):
                return self._real.get(memory_id)

            def list_active(self, **kwargs: object):
                return self._real.list_active(**kwargs)  # type: ignore[arg-type]

            def list_by_session(self, session_id: str, *, include_invalidated: bool = False):
                return self._real.list_by_session(session_id, include_invalidated=include_invalidated)

            def search(self, query: str, **kwargs: object):
                return self._real.search(query, **kwargs)  # type: ignore[arg-type]

        tracking_store = _DeleteTrackingStore(store)
        service = MemoryTemporalService(store=tracking_store)  # type: ignore[arg-type]
        service.write(_fact("User lives in Istanbul.", topic_key="user_residence"))
        service.write(_fact("User lives in Ankara.", topic_key="user_residence"))

        assert tracking_store.delete_called is False
