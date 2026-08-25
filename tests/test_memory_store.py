"""Phase 1A bellek katmanı testleri.

Test kapsamı:
- MemoryRecord yapısı ve alan varsayılanları
- SQLiteMemoryStore → MemoryStore Protocol uyumu
- add / get döngüsü
- update ve updated_at tazelemesi
- update bilinmeyen id → KeyError
- invalidate (mantıksal geçersizleştirme)
- delete (mantıksal silme)
- list_active filtreleri (type, temporality, status, session, limit/offset)
- list_by_session (include_invalidated bayrağı)
- search — FTS5 anahtar kelime eşleşmesi
- search — boş sorgu
- search — eşleşme yok
- search — aktif olmayan kayıtlar dışlanır
- search — memory_type filtresi
- _sanitize_fts_query — özel karakter temizliği
- count yardımcısı

Phase 1C-1 — doğal dil bellek getirme testleri:
- search — İngilizce/Türkçe doğal dil soruları ilgili belleği bulur
- search — çok terimli sorular çalışır
- search — ilgisiz doğal dil soruları yanlış eşleşme yapmaz
- search — soru işareti/noktalama FTS5 sözdizim hatasına yol açmaz
- search — silinmiş/geçersizleştirilmiş kayıtlar doğal dil aramasında da dışlanır
- search — limit doğal dil sorgularında da uygulanır
- _extract_search_terms — dolgu kelime ayıklama
- _sanitize_fts_query — genel noktalama temizliği + Unicode koruması

Tüm testler geçici dosya tabanlı SQLite kullanır (pytest tmp_path fixture).
Gerçek kullanıcı veritabanına dokunulmaz.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.memory.record import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    Temporality,
)
from app.memory.sqlite_store import SQLiteMemoryStore, _extract_search_terms, _sanitize_fts_query
from app.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteMemoryStore:
    """Her test için izole, geçici bir SQLiteMemoryStore döner."""
    return SQLiteMemoryStore(str(tmp_path / "test_memory.db"))


# ---------------------------------------------------------------------------
# 1. MemoryRecord — yapı ve alan varsayılanları
# ---------------------------------------------------------------------------


class TestMemoryRecord:
    def test_minimal_construction_requires_only_content(self) -> None:
        rec = MemoryRecord(content="test fact")
        assert rec.content == "test fact"

    def test_default_memory_type_is_other(self) -> None:
        rec = MemoryRecord(content="x")
        assert rec.memory_type == MemoryType.OTHER

    def test_default_temporality_is_unknown(self) -> None:
        rec = MemoryRecord(content="x")
        assert rec.temporality == Temporality.UNKNOWN

    def test_default_status_is_active(self) -> None:
        rec = MemoryRecord(content="x")
        assert rec.status == MemoryStatus.ACTIVE

    def test_default_importance_is_half(self) -> None:
        rec = MemoryRecord(content="x")
        assert rec.importance == 0.5

    def test_default_sensitivity_is_zero(self) -> None:
        rec = MemoryRecord(content="x")
        assert rec.sensitivity == 0.0

    def test_default_optional_fields_are_none(self) -> None:
        rec = MemoryRecord(content="x")
        assert rec.invalid_at is None
        assert rec.deleted_at is None
        assert rec.source_session_id is None

    def test_default_metadata_is_empty_dict(self) -> None:
        rec = MemoryRecord(content="x")
        assert rec.metadata == {}

    def test_auto_generated_id_is_uuid_string(self) -> None:
        rec = MemoryRecord(content="x")
        # UUID4 formatı: 8-4-4-4-12 karakter hex grupları
        assert len(rec.id) == 36
        assert rec.id.count("-") == 4

    def test_two_records_get_different_ids(self) -> None:
        r1 = MemoryRecord(content="a")
        r2 = MemoryRecord(content="b")
        assert r1.id != r2.id

    def test_timestamps_are_timezone_aware_utc(self) -> None:
        rec = MemoryRecord(content="x")
        assert rec.created_at.tzinfo is not None
        assert rec.updated_at.tzinfo is not None
        assert rec.valid_at.tzinfo is not None

    def test_empty_content_is_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            MemoryRecord(content="")

    def test_importance_out_of_range_is_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            MemoryRecord(content="x", importance=1.5)

    def test_explicit_fields_are_stored(self) -> None:
        rec = MemoryRecord(
            content="User prefers dark mode",
            memory_type=MemoryType.PREFERENCE,
            temporality=Temporality.PRESENT,
            status=MemoryStatus.ACTIVE,
            importance=0.8,
            sensitivity=0.1,
            source_session_id="sess-001",
            metadata={"verified": True},
        )
        assert rec.memory_type == MemoryType.PREFERENCE
        assert rec.temporality == Temporality.PRESENT
        assert rec.importance == 0.8
        assert rec.sensitivity == 0.1
        assert rec.source_session_id == "sess-001"
        assert rec.metadata["verified"] is True


# ---------------------------------------------------------------------------
# 2. Protocol uyumu
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_sqlite_store_satisfies_memory_store_protocol(
        self, store: SQLiteMemoryStore
    ) -> None:
        """isinstance() ile runtime_checkable Protocol kontrolü."""
        assert isinstance(store, MemoryStore)

    def test_protocol_check_fails_for_arbitrary_object(self) -> None:
        class NotAStore:
            pass

        assert not isinstance(NotAStore(), MemoryStore)


# ---------------------------------------------------------------------------
# 3. add / get döngüsü
# ---------------------------------------------------------------------------


class TestAddGet:
    def test_add_returns_the_same_record(self, store: SQLiteMemoryStore) -> None:
        rec = MemoryRecord(content="added record")
        returned = store.add(rec)
        assert returned is rec

    def test_get_returns_matching_record(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="hello world"))
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.id == rec.id
        assert fetched.content == "hello world"

    def test_get_unknown_id_returns_none(self, store: SQLiteMemoryStore) -> None:
        assert store.get("nonexistent-id") is None

    def test_all_fields_round_trip_correctly(self, store: SQLiteMemoryStore) -> None:
        valid_at = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        rec = MemoryRecord(
            content="Round-trip test",
            memory_type=MemoryType.FACT,
            temporality=Temporality.PAST,
            status=MemoryStatus.COMPLETED,
            valid_at=valid_at,
            source_session_id="sess-rt",
            importance=0.9,
            sensitivity=0.2,
            metadata={"source": "unit test"},
        )
        store.add(rec)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.memory_type == MemoryType.FACT
        assert fetched.temporality == Temporality.PAST
        assert fetched.status == MemoryStatus.COMPLETED
        assert fetched.valid_at == valid_at
        assert fetched.source_session_id == "sess-rt"
        assert fetched.importance == 0.9
        assert fetched.sensitivity == 0.2
        assert fetched.metadata == {"source": "unit test"}

    def test_get_returns_deleted_record(self, store: SQLiteMemoryStore) -> None:
        """get() silinmiş kayıtları da döndürmelidir."""
        rec = store.add(MemoryRecord(content="to be deleted"))
        store.delete(rec.id)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.deleted_at is not None

    def test_get_returns_invalidated_record(self, store: SQLiteMemoryStore) -> None:
        """get() geçersizleştirilmiş kayıtları da döndürmelidir."""
        rec = store.add(MemoryRecord(content="to be invalidated"))
        store.invalidate(rec.id)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.invalid_at is not None


# ---------------------------------------------------------------------------
# 4. update ve updated_at tazelemesi
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_changes_content(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="original content"))
        rec.content = "updated content"
        store.update(rec)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.content == "updated content"

    def test_update_refreshes_updated_at(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="will be updated"))
        original_updated_at = rec.updated_at
        # Zaman damgası farkı için kısa gecikme
        time.sleep(0.01)
        rec.content = "new content"
        store.update(rec)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.updated_at > original_updated_at

    def test_update_does_not_change_created_at(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="stable"))
        original_created_at = rec.created_at
        rec.content = "changed"
        store.update(rec)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.created_at == original_created_at

    def test_update_returns_the_record(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="check return"))
        rec.content = "changed"
        returned = store.update(rec)
        assert returned is rec

    def test_update_all_mutable_fields(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="initial"))
        rec.content = "modified"
        rec.memory_type = MemoryType.EVENT
        rec.temporality = Temporality.PAST
        rec.status = MemoryStatus.COMPLETED
        rec.importance = 0.7
        rec.sensitivity = 0.3
        rec.metadata = {"updated": True}
        store.update(rec)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.memory_type == MemoryType.EVENT
        assert fetched.temporality == Temporality.PAST
        assert fetched.status == MemoryStatus.COMPLETED
        assert fetched.importance == 0.7
        assert fetched.metadata == {"updated": True}

    def test_update_unknown_id_raises_key_error(
        self, store: SQLiteMemoryStore
    ) -> None:
        ghost = MemoryRecord(content="ghost record")
        ghost.id = "does-not-exist"
        with pytest.raises(KeyError):
            store.update(ghost)


# ---------------------------------------------------------------------------
# 5. invalidate — mantıksal geçersizleştirme
# ---------------------------------------------------------------------------


class TestInvalidate:
    def test_invalidate_returns_true_on_success(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="to invalidate"))
        assert store.invalidate(rec.id) is True

    def test_invalidate_sets_invalid_at(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="will be invalidated"))
        store.invalidate(rec.id)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.invalid_at is not None

    def test_invalidate_uses_provided_timestamp(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="timestamp test"))
        custom_ts = datetime(2024, 1, 1, tzinfo=UTC)
        store.invalidate(rec.id, at=custom_ts)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.invalid_at is not None
        assert fetched.invalid_at.date() == custom_ts.date()

    def test_invalidate_unknown_id_returns_false(
        self, store: SQLiteMemoryStore
    ) -> None:
        assert store.invalidate("nonexistent") is False

    def test_invalidate_already_invalidated_returns_false(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="double invalidate"))
        store.invalidate(rec.id)
        assert store.invalidate(rec.id) is False

    def test_invalidated_record_excluded_from_list_active(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="should disappear"))
        store.invalidate(rec.id)
        active = store.list_active()
        ids = [r.id for r in active]
        assert rec.id not in ids

    def test_physical_record_still_exists_after_invalidate(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="physically present"))
        store.invalidate(rec.id)
        assert store.get(rec.id) is not None


# ---------------------------------------------------------------------------
# 6. delete — mantıksal silme
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_returns_true_on_success(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="to delete"))
        assert store.delete(rec.id) is True

    def test_delete_sets_deleted_at(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="will be deleted"))
        store.delete(rec.id)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.deleted_at is not None

    def test_delete_uses_provided_timestamp(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="timestamp delete"))
        custom_ts = datetime(2023, 12, 31, tzinfo=UTC)
        store.delete(rec.id, at=custom_ts)
        fetched = store.get(rec.id)
        assert fetched is not None
        assert fetched.deleted_at is not None
        assert fetched.deleted_at.date() == custom_ts.date()

    def test_delete_unknown_id_returns_false(self, store: SQLiteMemoryStore) -> None:
        assert store.delete("nonexistent") is False

    def test_delete_already_deleted_returns_false(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="double delete"))
        store.delete(rec.id)
        assert store.delete(rec.id) is False

    def test_deleted_record_excluded_from_list_active(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="invisible after delete"))
        store.delete(rec.id)
        active = store.list_active()
        ids = [r.id for r in active]
        assert rec.id not in ids

    def test_physical_record_still_exists_after_delete(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="physically kept"))
        store.delete(rec.id)
        assert store.get(rec.id) is not None


# ---------------------------------------------------------------------------
# 7. list_active — filtreler
# ---------------------------------------------------------------------------


class TestListActive:
    def test_returns_only_active_records(self, store: SQLiteMemoryStore) -> None:
        r1 = store.add(MemoryRecord(content="active one"))
        r2 = store.add(MemoryRecord(content="active two"))
        r3 = store.add(MemoryRecord(content="to delete"))
        store.delete(r3.id)
        active = store.list_active()
        ids = {r.id for r in active}
        assert r1.id in ids
        assert r2.id in ids
        assert r3.id not in ids

    def test_empty_store_returns_empty_list(self, store: SQLiteMemoryStore) -> None:
        assert store.list_active() == []

    def test_filter_by_memory_type(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="a fact", memory_type=MemoryType.FACT))
        store.add(MemoryRecord(content="an event", memory_type=MemoryType.EVENT))
        store.add(MemoryRecord(content="another fact", memory_type=MemoryType.FACT))

        facts = store.list_active(memory_type=MemoryType.FACT)
        assert len(facts) == 2
        assert all(r.memory_type == MemoryType.FACT for r in facts)

        events = store.list_active(memory_type=MemoryType.EVENT)
        assert len(events) == 1

    def test_filter_by_temporality(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="past event", temporality=Temporality.PAST))
        store.add(MemoryRecord(content="future goal", temporality=Temporality.FUTURE))

        past = store.list_active(temporality=Temporality.PAST)
        assert len(past) == 1
        assert past[0].content == "past event"

    def test_filter_by_status(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="active rec", status=MemoryStatus.ACTIVE))
        store.add(MemoryRecord(content="planned rec", status=MemoryStatus.PLANNED))

        planned = store.list_active(status=MemoryStatus.PLANNED)
        assert len(planned) == 1
        assert planned[0].content == "planned rec"

    def test_filter_by_source_session_id(self, store: SQLiteMemoryStore) -> None:
        store.add(
            MemoryRecord(content="session A record", source_session_id="sess-A")
        )
        store.add(
            MemoryRecord(content="session B record", source_session_id="sess-B")
        )
        store.add(MemoryRecord(content="no session"))

        results = store.list_active(source_session_id="sess-A")
        assert len(results) == 1
        assert results[0].source_session_id == "sess-A"

    def test_combined_filters_use_and_logic(self, store: SQLiteMemoryStore) -> None:
        store.add(
            MemoryRecord(
                content="fact past",
                memory_type=MemoryType.FACT,
                temporality=Temporality.PAST,
            )
        )
        store.add(
            MemoryRecord(
                content="fact present",
                memory_type=MemoryType.FACT,
                temporality=Temporality.PRESENT,
            )
        )
        store.add(
            MemoryRecord(
                content="event past",
                memory_type=MemoryType.EVENT,
                temporality=Temporality.PAST,
            )
        )

        results = store.list_active(
            memory_type=MemoryType.FACT, temporality=Temporality.PAST
        )
        assert len(results) == 1
        assert results[0].content == "fact past"

    def test_limit_restricts_result_count(self, store: SQLiteMemoryStore) -> None:
        for i in range(10):
            store.add(MemoryRecord(content=f"record {i}"))
        results = store.list_active(limit=3)
        assert len(results) == 3

    def test_offset_skips_records(self, store: SQLiteMemoryStore) -> None:
        # İki kayıt ekle, ikinci daha yeni valid_at ile
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2024, 1, 2, tzinfo=UTC)
        store.add(MemoryRecord(content="older", valid_at=t1))
        store.add(MemoryRecord(content="newer", valid_at=t2))

        # Sıralama valid_at DESC → önce newer
        page1 = store.list_active(limit=1, offset=0)
        page2 = store.list_active(limit=1, offset=1)
        assert len(page1) == 1
        assert len(page2) == 1
        assert page1[0].content == "newer"
        assert page2[0].content == "older"

    def test_results_ordered_by_valid_at_descending(
        self, store: SQLiteMemoryStore
    ) -> None:
        t1 = datetime(2024, 3, 1, tzinfo=UTC)
        t2 = datetime(2024, 6, 1, tzinfo=UTC)
        t3 = datetime(2024, 1, 1, tzinfo=UTC)
        store.add(MemoryRecord(content="march", valid_at=t1))
        store.add(MemoryRecord(content="june", valid_at=t2))
        store.add(MemoryRecord(content="january", valid_at=t3))

        results = store.list_active()
        assert results[0].content == "june"
        assert results[1].content == "march"
        assert results[2].content == "january"


# ---------------------------------------------------------------------------
# 8. list_by_session
# ---------------------------------------------------------------------------


class TestListBySession:
    def test_returns_only_records_for_given_session(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="sess-X rec 1", source_session_id="sess-X"))
        store.add(MemoryRecord(content="sess-X rec 2", source_session_id="sess-X"))
        store.add(MemoryRecord(content="sess-Y rec", source_session_id="sess-Y"))

        results = store.list_by_session("sess-X")
        assert len(results) == 2
        assert all(r.source_session_id == "sess-X" for r in results)

    def test_excludes_deleted_records_by_default(
        self, store: SQLiteMemoryStore
    ) -> None:
        r1 = store.add(MemoryRecord(content="keep", source_session_id="s"))
        r2 = store.add(MemoryRecord(content="delete me", source_session_id="s"))
        store.delete(r2.id)

        results = store.list_by_session("s")
        ids = [r.id for r in results]
        assert r1.id in ids
        assert r2.id not in ids

    def test_excludes_invalidated_by_default(self, store: SQLiteMemoryStore) -> None:
        r1 = store.add(MemoryRecord(content="valid", source_session_id="s"))
        r2 = store.add(MemoryRecord(content="invalidate me", source_session_id="s"))
        store.invalidate(r2.id)

        results = store.list_by_session("s")
        ids = [r.id for r in results]
        assert r1.id in ids
        assert r2.id not in ids

    def test_include_invalidated_flag_shows_invalidated_records(
        self, store: SQLiteMemoryStore
    ) -> None:
        r1 = store.add(MemoryRecord(content="valid", source_session_id="s"))
        r2 = store.add(MemoryRecord(content="invalidated", source_session_id="s"))
        store.invalidate(r2.id)

        results = store.list_by_session("s", include_invalidated=True)
        ids = [r.id for r in results]
        assert r1.id in ids
        assert r2.id in ids

    def test_include_invalidated_still_excludes_deleted(
        self, store: SQLiteMemoryStore
    ) -> None:
        r1 = store.add(MemoryRecord(content="valid", source_session_id="s"))
        r2 = store.add(MemoryRecord(content="deleted", source_session_id="s"))
        store.delete(r2.id)

        results = store.list_by_session("s", include_invalidated=True)
        ids = [r.id for r in results]
        assert r1.id in ids
        assert r2.id not in ids

    def test_unknown_session_returns_empty_list(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="irrelevant", source_session_id="other"))
        assert store.list_by_session("no-such-session") == []

    def test_results_ordered_by_created_at_ascending(
        self, store: SQLiteMemoryStore
    ) -> None:
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2024, 1, 2, tzinfo=UTC)
        r1 = store.add(
            MemoryRecord(content="first", source_session_id="s", valid_at=t1)
        )
        r2 = store.add(
            MemoryRecord(content="second", source_session_id="s", valid_at=t2)
        )
        results = store.list_by_session("s")
        # created_at ASC — ekleme sırası
        assert results[0].id == r1.id
        assert results[1].id == r2.id


# ---------------------------------------------------------------------------
# 9. search — FTS5
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_finds_matching_record(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="The user likes Python programming"))
        results = store.search("Python")
        assert len(results) == 1
        assert "Python" in results[0].content

    def test_search_returns_empty_for_no_match(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="Java is a programming language"))
        results = store.search("Rust")
        assert results == []

    def test_empty_query_returns_empty_list(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="some content"))
        assert store.search("") == []
        assert store.search("   ") == []

    def test_whitespace_only_query_returns_empty_list(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="some content"))
        assert store.search("   \t\n  ") == []

    def test_search_excludes_deleted_records(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="deleted keyword findme"))
        store.delete(rec.id)
        results = store.search("findme")
        assert results == []

    def test_search_excludes_invalidated_records(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="invalidated keyword searchme"))
        store.invalidate(rec.id)
        results = store.search("searchme")
        assert results == []

    def test_search_multiple_terms_finds_record_containing_any(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="The cat sat on the mat"))
        # FTS5 porter tokenizer ile "cat" ya da "sat" arar
        results = store.search("cat")
        assert len(results) == 1

    def test_search_filter_by_memory_type(self, store: SQLiteMemoryStore) -> None:
        store.add(
            MemoryRecord(
                content="machine learning model training",
                memory_type=MemoryType.FACT,
            )
        )
        store.add(
            MemoryRecord(
                content="machine learning conference event",
                memory_type=MemoryType.EVENT,
            )
        )

        facts = store.search("machine", memory_type=MemoryType.FACT)
        assert len(facts) == 1
        assert facts[0].memory_type == MemoryType.FACT

        events = store.search("machine", memory_type=MemoryType.EVENT)
        assert len(events) == 1
        assert events[0].memory_type == MemoryType.EVENT

    def test_search_filter_by_temporality(self, store: SQLiteMemoryStore) -> None:
        store.add(
            MemoryRecord(
                content="completed project milestone",
                temporality=Temporality.PAST,
            )
        )
        store.add(
            MemoryRecord(
                content="upcoming project release",
                temporality=Temporality.FUTURE,
            )
        )

        past = store.search("project", temporality=Temporality.PAST)
        assert len(past) == 1
        assert past[0].temporality == Temporality.PAST

    def test_search_respects_limit(self, store: SQLiteMemoryStore) -> None:
        for i in range(5):
            store.add(MemoryRecord(content=f"common keyword record {i}"))
        results = store.search("keyword", limit=3)
        assert len(results) <= 3

    def test_search_with_single_char_query_returns_empty(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="single character x test"))
        # _sanitize_fts_query 1 karakterlik token'ları atar
        results = store.search("x")
        assert results == []

    def test_fts_special_chars_in_query_do_not_raise(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="normal content here"))
        # Özel karakterler sanitize edilmeli; hata fırlatmamalı
        results = store.search('(dangerous "query")')
        # Hata yok; sonuç boş ya da dolu olabilir
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# 10. _sanitize_fts_query
# ---------------------------------------------------------------------------


class TestSanitizeFtsQuery:
    def test_plain_text_unchanged(self) -> None:
        assert _sanitize_fts_query("hello world") == "hello world"

    def test_removes_double_quotes(self) -> None:
        result = _sanitize_fts_query('"quoted phrase"')
        assert '"' not in result

    def test_removes_parentheses(self) -> None:
        result = _sanitize_fts_query("(AND OR)")
        assert "(" not in result
        assert ")" not in result

    def test_removes_asterisk(self) -> None:
        result = _sanitize_fts_query("prefix*")
        assert "*" not in result

    def test_removes_single_quotes(self) -> None:
        result = _sanitize_fts_query("user's preference")
        assert "'" not in result

    def test_removes_colon(self) -> None:
        result = _sanitize_fts_query("content:value")
        assert ":" not in result

    def test_drops_single_char_tokens(self) -> None:
        result = _sanitize_fts_query("a b c hello")
        tokens = result.split()
        assert all(len(t) > 1 for t in tokens)

    def test_collapses_extra_whitespace(self) -> None:
        result = _sanitize_fts_query("  hello   world  ")
        assert result == "hello world"

    def test_all_special_chars_returns_empty_string(self) -> None:
        result = _sanitize_fts_query('"\'()*^+-:~')
        assert result == ""

    def test_preserves_non_ascii_words(self) -> None:
        # Unicode kelimeler korunmalı (uzunluk > 1)
        result = _sanitize_fts_query("kullanıcı tercihleri")
        assert "kullanıcı" in result
        assert "tercihleri" in result


# ---------------------------------------------------------------------------
# 11. count yardımcısı
# ---------------------------------------------------------------------------


class TestCount:
    def test_empty_store_count_is_zero(self, store: SQLiteMemoryStore) -> None:
        assert store.count() == 0

    def test_count_reflects_added_records(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="one"))
        store.add(MemoryRecord(content="two"))
        store.add(MemoryRecord(content="three"))
        assert store.count() == 3

    def test_count_excludes_deleted_by_default(
        self, store: SQLiteMemoryStore
    ) -> None:
        r1 = store.add(MemoryRecord(content="keep"))
        r2 = store.add(MemoryRecord(content="remove"))
        store.delete(r2.id)
        assert store.count() == 1

    def test_count_includes_deleted_when_flag_set(
        self, store: SQLiteMemoryStore
    ) -> None:
        r1 = store.add(MemoryRecord(content="keep"))
        r2 = store.add(MemoryRecord(content="remove"))
        store.delete(r2.id)
        assert store.count(include_deleted=True) == 2


# ---------------------------------------------------------------------------
# 12. Phase 1C-1 — Doğal dil sorgusuyla bellek getirme
# ---------------------------------------------------------------------------
#
# Strateji: önce katı (implicit AND) FTS5 sorgusu denenir; hiçbir sonuç
# vermezse ve birden fazla anlamlı terim varsa, terimler OR ile birleştirilip
# tekrar denenir. Dolgu kelimeler (İngilizce + Türkçe soru kalıpları) çıkarım
# öncesinde elenir. Hiçbir alana özgü kelime (örn. "YKS") sabit kodlanmadı —
# aşağıdaki testler bunu genel amaçlı bir mekanizma olarak doğrular.


class TestNaturalLanguageQueries:
    def test_english_question_retrieves_relevant_memory(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="User's YKS goal is 100 TYT and 60 AYT."))
        results = store.search("What was my YKS goal?")
        assert len(results) == 1
        assert "YKS goal" in results[0].content

    def test_english_question_variant_also_retrieves_relevant_memory(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="User's YKS goal is 100 TYT and 60 AYT."))
        results = store.search("Do you remember my YKS target?")
        assert len(results) == 1

    def test_turkish_question_retrieves_relevant_memory(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="User's YKS goal is 100 TYT and 60 AYT."))
        results = store.search("YKS hedefim neydi?")
        assert len(results) == 1

    def test_multi_term_natural_question_retrieves_relevant_memory(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="User's YKS goal is 100 TYT and 60 AYT."))
        results = store.search("What are my TYT and AYT targets?")
        assert len(results) == 1

    def test_simple_keyword_query_still_works_unchanged(
        self, store: SQLiteMemoryStore
    ) -> None:
        """Mevcut, basit tek kelimelik anahtar kelime aramaları etkilenmemeli."""
        store.add(MemoryRecord(content="The user enjoys reading science fiction books."))
        results = store.search("science")
        assert len(results) == 1

    def test_irrelevant_natural_language_query_returns_nothing(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="User's YKS goal is 100 TYT and 60 AYT."))
        results = store.search("What is the weather like today?")
        assert results == []

    def test_irrelevant_query_does_not_pull_in_unrelated_memory(
        self, store: SQLiteMemoryStore
    ) -> None:
        """OR-gevşetme yalnızca sorgu ile paylaşılan bir terim varken işe
        yaramalı; hiçbir terim ortak değilse hiçbir kayıt dönmemeli."""
        store.add(MemoryRecord(content="User's YKS goal is 100 TYT and 60 AYT."))
        store.add(MemoryRecord(content="User likes pizza on weekends."))
        results = store.search("What did I say about my exam target?")
        assert results == []

    def test_natural_language_query_respects_limit(
        self, store: SQLiteMemoryStore
    ) -> None:
        for i in range(10):
            store.add(MemoryRecord(content=f"User's goal number {i} is important."))
        results = store.search("What was my goal again?", limit=3)
        assert len(results) <= 3

    def test_deleted_memory_excluded_from_natural_language_search(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="User's YKS goal is 100 TYT and 60 AYT."))
        store.delete(rec.id)
        results = store.search("What was my YKS goal?")
        assert results == []

    def test_invalidated_memory_excluded_from_natural_language_search(
        self, store: SQLiteMemoryStore
    ) -> None:
        rec = store.add(MemoryRecord(content="User's YKS goal is 100 TYT and 60 AYT."))
        store.invalidate(rec.id)
        results = store.search("What was my YKS goal?")
        assert results == []

    def test_empty_and_whitespace_queries_remain_safe(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(MemoryRecord(content="User's YKS goal is 100 TYT and 60 AYT."))
        assert store.search("") == []
        assert store.search("   ") == []
        assert store.search("?") == []

    def test_question_mark_and_punctuation_do_not_raise_or_swallow_matches(
        self, store: SQLiteMemoryStore
    ) -> None:
        """Doğal dil noktalaması (?, ., !, ,) FTS5 sözdizim hatasına yol
        açmamalı VE geçerli eşleşmeyi engellememeli."""
        store.add(MemoryRecord(content="The user's favorite color is blue."))
        for query in [
            "What is my favorite color?",
            "My favorite color, please?",
            "favorite color!!",
            "favorite... color.",
        ]:
            results = store.search(query)
            assert isinstance(results, list)
            assert len(results) == 1, f"query {query!r} should have matched"

    def test_protocol_conformance_unchanged(self, store: SQLiteMemoryStore) -> None:
        assert isinstance(store, MemoryStore)

    def test_memory_type_filter_still_applies_to_natural_language_query(
        self, store: SQLiteMemoryStore
    ) -> None:
        store.add(
            MemoryRecord(
                content="User's YKS goal is 100 TYT and 60 AYT.",
                memory_type=MemoryType.GOAL,
            )
        )
        store.add(
            MemoryRecord(
                content="User's YKS exam date is in June.",
                memory_type=MemoryType.EVENT,
            )
        )
        results = store.search("What was my YKS goal?", memory_type=MemoryType.GOAL)
        assert len(results) == 1
        assert results[0].memory_type == MemoryType.GOAL


# ---------------------------------------------------------------------------
# 13. _extract_search_terms — dolgu kelime ayıklama
# ---------------------------------------------------------------------------


class TestExtractSearchTerms:
    def test_removes_english_stopwords(self) -> None:
        terms = _extract_search_terms("What was my YKS goal?")
        assert terms == ["YKS", "goal"]

    def test_removes_turkish_stopwords(self) -> None:
        terms = _extract_search_terms("YKS hedefim neydi?")
        assert "neydi" not in [t.lower() for t in terms]
        assert "YKS" in terms

    def test_all_stopwords_returns_empty_list(self) -> None:
        assert _extract_search_terms("What is it?") == []

    def test_single_content_word_query_is_unaffected(self) -> None:
        assert _extract_search_terms("Istanbul") == ["Istanbul"]

    def test_does_not_hardcode_domain_specific_words(self) -> None:
        """Dolgu kelime listesi yalnızca genel fonksiyon kelimeleri içermeli;
        rastgele bir alan kelimesi ('kitap', 'book') asla elenmemeli."""
        terms = _extract_search_terms("What is my favorite book?")
        assert "book" in [t.lower() for t in terms]


# ---------------------------------------------------------------------------
# 14. _sanitize_fts_query — genişletilmiş noktalama temizliği
# ---------------------------------------------------------------------------


class TestSanitizeFtsQueryPunctuation:
    def test_question_mark_is_removed(self) -> None:
        assert _sanitize_fts_query("goal?") == "goal"

    def test_period_comma_exclamation_semicolon_removed(self) -> None:
        assert _sanitize_fts_query("goal.") == "goal"
        assert _sanitize_fts_query("goal,") == "goal"
        assert _sanitize_fts_query("goal!") == "goal"
        assert _sanitize_fts_query("goal;") == "goal"

    def test_unicode_letters_still_preserved_with_punctuation(self) -> None:
        result = _sanitize_fts_query("kullanıcı tercihleri?")
        assert "kullanıcı" in result
        assert "tercihleri" in result
        assert "?" not in result

    def test_digits_are_preserved(self) -> None:
        result = _sanitize_fts_query("100 TYT and 60 AYT?")
        assert "100" in result
        assert "60" in result
