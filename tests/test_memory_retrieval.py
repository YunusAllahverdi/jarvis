"""Phase 1B-3B — MemoryRetrievalService test suite.

Kapsam:
 1. İlgili bellek döndürülür
 2. İlgisiz bellek döndürülmez
 3. Birden fazla ilgili bellek döndürülür
 4. limit'e uyulur
 5. Boş sorgu güvenle işlenir
 6. Silinmiş kayıtlar döndürülmez
 7. Geçersizleştirilmiş kayıtlar döndürülmez
 8. Oturumdan bağımsız (session-independent) getirme çalışır
 9. Servis, sahte bir MemoryStore Protocol implementasyonuyla çalışır
10. Servis kayıtlı bellekleri değiştirmez
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.memory.record import MemoryRecord, MemoryStatus, MemoryType, Temporality
from app.memory.sqlite_store import SQLiteMemoryStore
from app.memory.store import MemoryStore
from app.services.memory_retrieval import MemoryRetrievalService


# ---------------------------------------------------------------------------
# Fixture / yardımcılar
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteMemoryStore:
    """Her test için izole, geçici bir SQLiteMemoryStore döner."""
    return SQLiteMemoryStore(str(tmp_path / "retrieval_test.db"))


class _FakeMemoryStore:
    """MemoryStore Protocol'ünü karşılayan, çağrıları kaydeden sahte store.

    Amaç: MemoryRetrievalService'in somut SQLiteMemoryStore'a değil,
    yalnızca MemoryStore Protocol'üne bağımlı olduğunu kanıtlamak.
    """

    def __init__(self, *, search_results: list[MemoryRecord] | None = None) -> None:
        self.search_calls: list[dict[str, Any]] = []
        self._search_results = search_results or []

    def add(self, record: MemoryRecord) -> MemoryRecord:
        raise AssertionError("MemoryRetrievalService add() çağırmamalı")

    def update(self, record: MemoryRecord) -> MemoryRecord:
        raise AssertionError("MemoryRetrievalService update() çağırmamalı")

    def invalidate(self, memory_id: str, *, at=None) -> bool:
        raise AssertionError("MemoryRetrievalService invalidate() çağırmamalı")

    def delete(self, memory_id: str, *, at=None) -> bool:
        raise AssertionError("MemoryRetrievalService delete() çağırmamalı")

    def get(self, memory_id: str) -> MemoryRecord | None:
        raise AssertionError("MemoryRetrievalService get() çağırmamalı")

    def list_active(self, **kwargs: Any) -> list[MemoryRecord]:
        raise AssertionError("MemoryRetrievalService list_active() çağırmamalı")

    def list_by_session(self, session_id: str, *, include_invalidated: bool = False) -> list[MemoryRecord]:
        raise AssertionError("MemoryRetrievalService list_by_session() çağırmamalı")

    def search(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        temporality: Temporality | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        self.search_calls.append(
            {"query": query, "memory_type": memory_type, "temporality": temporality, "limit": limit}
        )
        return self._search_results


# ---------------------------------------------------------------------------
# 1. İlgili bellek döndürülür
# ---------------------------------------------------------------------------


class TestRelevantMemoryReturned:
    def test_matching_record_is_returned(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="The user lives in Istanbul."))
        retrieval = MemoryRetrievalService(store=store)

        results = retrieval.retrieve("Istanbul")

        assert len(results) == 1
        assert results[0].content == "The user lives in Istanbul."


# ---------------------------------------------------------------------------
# 2. İlgisiz bellek döndürülmez
# ---------------------------------------------------------------------------


class TestIrrelevantMemoryNotReturned:
    def test_non_matching_record_is_excluded(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="The user lives in Istanbul."))
        store.add(MemoryRecord(content="User likes pizza on weekends."))
        retrieval = MemoryRetrievalService(store=store)

        results = retrieval.retrieve("Istanbul")

        assert len(results) == 1
        assert "pizza" not in results[0].content.lower()

    def test_no_match_returns_empty_list(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="Java is a programming language."))
        retrieval = MemoryRetrievalService(store=store)

        results = retrieval.retrieve("Rust")

        assert results == []


# ---------------------------------------------------------------------------
# 3. Birden fazla ilgili bellek döndürülür
# ---------------------------------------------------------------------------


class TestMultipleRelevantMemoriesReturned:
    def test_multiple_matches_are_all_returned(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="User travels to Istanbul often."))
        store.add(MemoryRecord(content="Istanbul has great food."))
        store.add(MemoryRecord(content="User owns a cat."))
        retrieval = MemoryRetrievalService(store=store)

        results = retrieval.retrieve("Istanbul")

        assert len(results) == 2
        contents = {r.content for r in results}
        assert "User travels to Istanbul often." in contents
        assert "Istanbul has great food." in contents


# ---------------------------------------------------------------------------
# 4. limit'e uyulur
# ---------------------------------------------------------------------------


class TestLimitIsRespected:
    def test_explicit_limit_caps_results(self, store: SQLiteMemoryStore) -> None:
        for i in range(5):
            store.add(MemoryRecord(content=f"Istanbul record number {i}."))
        retrieval = MemoryRetrievalService(store=store)

        results = retrieval.retrieve("Istanbul", limit=2)

        assert len(results) == 2

    def test_default_limit_is_used_when_not_specified(self, store: SQLiteMemoryStore) -> None:
        for i in range(10):
            store.add(MemoryRecord(content=f"Istanbul record number {i}."))
        retrieval = MemoryRetrievalService(store=store, default_limit=3)

        results = retrieval.retrieve("Istanbul")

        assert len(results) == 3

    def test_zero_limit_returns_empty_without_querying_store(self) -> None:
        fake_store = _FakeMemoryStore(search_results=[MemoryRecord(content="should not appear")])
        retrieval = MemoryRetrievalService(store=fake_store)

        results = retrieval.retrieve("anything", limit=0)

        assert results == []
        assert fake_store.search_calls == []


# ---------------------------------------------------------------------------
# 5. Boş sorgu güvenle işlenir
# ---------------------------------------------------------------------------


class TestEmptyQueryHandledSafely:
    def test_empty_string_returns_empty_list(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="Some content here."))
        retrieval = MemoryRetrievalService(store=store)

        assert retrieval.retrieve("") == []

    def test_whitespace_only_returns_empty_list(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="Some content here."))
        retrieval = MemoryRetrievalService(store=store)

        assert retrieval.retrieve("   \t\n  ") == []

    def test_empty_query_does_not_touch_the_store(self) -> None:
        fake_store = _FakeMemoryStore(search_results=[MemoryRecord(content="irrelevant")])
        retrieval = MemoryRetrievalService(store=fake_store)

        results = retrieval.retrieve("")

        assert results == []
        assert fake_store.search_calls == []


# ---------------------------------------------------------------------------
# 6. Silinmiş kayıtlar döndürülmez
# ---------------------------------------------------------------------------


class TestDeletedMemoriesExcluded:
    def test_deleted_record_is_not_returned(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="Findme keyword content."))
        store.delete(rec.id)
        retrieval = MemoryRetrievalService(store=store)

        results = retrieval.retrieve("Findme")

        assert results == []


# ---------------------------------------------------------------------------
# 7. Geçersizleştirilmiş kayıtlar döndürülmez
# ---------------------------------------------------------------------------


class TestInvalidatedMemoriesExcluded:
    def test_invalidated_record_is_not_returned(self, store: SQLiteMemoryStore) -> None:
        rec = store.add(MemoryRecord(content="Searchme keyword content."))
        store.invalidate(rec.id)
        retrieval = MemoryRetrievalService(store=store)

        results = retrieval.retrieve("Searchme")

        assert results == []


# ---------------------------------------------------------------------------
# 8. Oturumdan bağımsız getirme çalışır
# ---------------------------------------------------------------------------


class TestSessionIndependentRetrieval:
    def test_matches_across_different_sessions_are_all_returned(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="Ankara weather is nice.", source_session_id="sess-A"))
        store.add(MemoryRecord(content="Ankara traffic is bad.", source_session_id="sess-B"))
        store.add(MemoryRecord(content="Ankara has old architecture."))  # session yok
        retrieval = MemoryRetrievalService(store=store)

        results = retrieval.retrieve("Ankara")

        assert len(results) == 3
        session_ids = {r.source_session_id for r in results}
        assert session_ids == {"sess-A", "sess-B", None}


# ---------------------------------------------------------------------------
# 9. Servis, sahte bir MemoryStore Protocol implementasyonuyla çalışır
# ---------------------------------------------------------------------------


class TestWorksWithFakeMemoryStoreProtocol:
    def test_fake_store_satisfies_memory_store_protocol(self) -> None:
        fake_store = _FakeMemoryStore()
        assert isinstance(fake_store, MemoryStore)

    def test_retrieval_delegates_to_store_search_with_correct_arguments(self) -> None:
        expected = [MemoryRecord(content="fake result")]
        fake_store = _FakeMemoryStore(search_results=expected)
        retrieval = MemoryRetrievalService(store=fake_store, default_limit=7)

        results = retrieval.retrieve(
            "some query", memory_type=MemoryType.FACT, temporality=Temporality.PAST
        )

        assert results is expected
        assert fake_store.search_calls == [
            {
                "query": "some query",
                "memory_type": MemoryType.FACT,
                "temporality": Temporality.PAST,
                "limit": 7,
            }
        ]

    def test_explicit_limit_overrides_default_limit_for_fake_store(self) -> None:
        fake_store = _FakeMemoryStore(search_results=[])
        retrieval = MemoryRetrievalService(store=fake_store, default_limit=7)

        retrieval.retrieve("query", limit=2)

        assert fake_store.search_calls[0]["limit"] == 2


# ---------------------------------------------------------------------------
# 10. Servis kayıtlı bellekleri değiştirmez
# ---------------------------------------------------------------------------


class TestRetrievalDoesNotModifyStore:
    def test_record_count_unchanged_after_retrieval(self, store: SQLiteMemoryStore) -> None:
        store.add(MemoryRecord(content="First fact about Istanbul."))
        store.add(MemoryRecord(content="Second fact about Ankara."))
        retrieval = MemoryRetrievalService(store=store)

        before = store.count(include_deleted=True)
        retrieval.retrieve("Istanbul")
        retrieval.retrieve("Ankara")
        retrieval.retrieve("nonexistent keyword")
        after = store.count(include_deleted=True)

        assert before == after == 2

    def test_record_fields_unchanged_after_retrieval(self, store: SQLiteMemoryStore) -> None:
        original = store.add(
            MemoryRecord(
                content="User prefers dark mode.",
                memory_type=MemoryType.PREFERENCE,
                status=MemoryStatus.ACTIVE,
                importance=0.6,
            )
        )
        retrieval = MemoryRetrievalService(store=store)

        retrieval.retrieve("dark mode")

        fetched = store.get(original.id)
        assert fetched is not None
        assert fetched.content == original.content
        assert fetched.memory_type == original.memory_type
        assert fetched.status == original.status
        assert fetched.importance == original.importance
        assert fetched.updated_at == original.updated_at

    def test_fake_store_add_never_called_by_retrieval(self) -> None:
        """_FakeMemoryStore.add() çağrılırsa AssertionError fırlatır — retrieve() bunu tetiklememeli."""
        fake_store = _FakeMemoryStore(search_results=[])
        retrieval = MemoryRetrievalService(store=fake_store)

        retrieval.retrieve("herhangi bir sorgu")  # add/update/delete tetiklenirse test zaten patlar
