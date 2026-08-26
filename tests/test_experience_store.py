"""Phase 2D — SQLiteExperienceStore / ExperienceStore Protocol testleri.

Kapsam:
 1. ExperienceStore Protocol uyumu
 2. add/get round-trip
 3. session_id korunması (var/yok)
 4. occurred_at korunması
 5. assistant_response korunması
 6. tool_calls JSON round-trip
 7. user_state None ↔ SQL NULL
 8. emotional_context None ↔ SQL NULL
 9. metadata JSON round-trip
10. derived_memory_ids round-trip
11. outcome round-trip (tüm değerler)
12. persisted_at, occurred_at'tan ayrı saklanır
13. list_by_session
14. list_recent sıralaması
15. list_recent limit
16. list_recent before parametresi
17. Bulunamayan id → None
18. Aynı DB dosyasını kullanan iki store bir arada çalışır
19. SQLiteMemoryStore'dan ÖNCE kurulduğunda çalışır
20. SQLiteMemoryStore'dan SONRA kurulduğunda çalışır
21. Şema oluşturma idempotenttir
22. Experience için hiçbir FTS5 tablosu oluşturulmaz
23. Hiçbir harici bağımlılık eklenmedi
24. Normal konuşma metni aynen korunur (unicode, çok satırlı)
25. Secure Vault bu store'a kazara bağlanmadı/implemente edilmedi

Tüm testler geçici dosya tabanlı SQLite kullanır (pytest tmp_path fixture).
Gerçek kullanıcı veritabanına dokunulmaz. Bu dosya ChatOrchestrator'a veya
canlı sohbet akışına hiç değinmez (Phase 2D kapsamı: yalnızca bağımsız
kalıcılık katmanı).
"""

from __future__ import annotations

import inspect
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.memory.experience import Experience, ExperienceOutcome
from app.memory.experience_store import ExperienceStore
from app.memory.sqlite_experience_store import SQLiteExperienceStore


# ---------------------------------------------------------------------------
# Fixture / yardımcılar
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteExperienceStore:
    """Her test için izole, geçici bir SQLiteExperienceStore döner."""
    return SQLiteExperienceStore(str(tmp_path / "test_experiences.db"))


def _make_experience(**overrides: object) -> Experience:
    defaults: dict[str, object] = dict(
        session_id="sess-1",
        occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        user_message="I live in Istanbul.",
        assistant_response="Not aldım.",
    )
    defaults.update(overrides)
    return Experience(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Protocol uyumu
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_sqlite_store_satisfies_experience_store_protocol(
        self, store: SQLiteExperienceStore
    ) -> None:
        assert isinstance(store, ExperienceStore)

    def test_protocol_check_fails_for_arbitrary_object(self) -> None:
        class NotAStore:
            pass

        assert not isinstance(NotAStore(), ExperienceStore)


# ---------------------------------------------------------------------------
# 2-5. add/get round-trip ve temel alan korunması
# ---------------------------------------------------------------------------


class TestAddGetRoundTrip:
    def test_add_returns_the_same_experience(self, store: SQLiteExperienceStore) -> None:
        exp = _make_experience()
        returned = store.add(exp)
        assert returned is exp

    def test_get_returns_matching_experience(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience())
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.id == exp.id

    def test_session_id_is_preserved(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience(session_id="sess-xyz"))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.session_id == "sess-xyz"

    def test_session_id_none_is_preserved(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience(session_id=None))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.session_id is None

    def test_occurred_at_is_preserved_exactly(self, store: SQLiteExperienceStore) -> None:
        specific_time = datetime(2025, 6, 15, 8, 30, 45, tzinfo=UTC)
        exp = store.add(_make_experience(occurred_at=specific_time))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.occurred_at == specific_time

    def test_assistant_response_is_preserved(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience(assistant_response="Merhaba! Nasıl yardımcı olabilirim?"))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.assistant_response == "Merhaba! Nasıl yardımcı olabilirim?"


# ---------------------------------------------------------------------------
# 6. tool_calls JSON round-trip
# ---------------------------------------------------------------------------


class TestToolCallsRoundTrip:
    def test_empty_tool_calls_round_trips(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience(tool_calls=[]))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.tool_calls == []

    def test_ordered_tool_calls_with_duplicates_round_trip(
        self, store: SQLiteExperienceStore
    ) -> None:
        exp = store.add(_make_experience(tool_calls=["get_time", "calculator", "calculator"]))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.tool_calls == ["get_time", "calculator", "calculator"]


# ---------------------------------------------------------------------------
# 7-8. user_state / emotional_context — None ↔ SQL NULL
# ---------------------------------------------------------------------------


class TestNullableJsonFields:
    def test_user_state_none_round_trips_as_none(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience(user_state=None))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.user_state is None

    def test_user_state_dict_round_trips(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience(user_state={"mood": "curious"}))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.user_state == {"mood": "curious"}

    def test_emotional_context_none_round_trips_as_none(
        self, store: SQLiteExperienceStore
    ) -> None:
        exp = store.add(_make_experience(emotional_context=None))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.emotional_context is None

    def test_emotional_context_dict_round_trips(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience(emotional_context={"valence": 0.5}))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.emotional_context == {"valence": 0.5}

    def test_null_columns_are_actually_sql_null_not_the_string_null(
        self, store: SQLiteExperienceStore, tmp_path: Path
    ) -> None:
        """user_state/emotional_context None iken sütunda gerçek SQL NULL
        olmalı — 'null' metin dizesi ya da '{}' değil."""
        exp = store.add(_make_experience(user_state=None, emotional_context=None))

        conn = sqlite3.connect(store._db_path)  # type: ignore[attr-defined]
        row = conn.execute(
            "SELECT user_state, emotional_context FROM experiences WHERE id = ?", (exp.id,)
        ).fetchone()
        conn.close()

        assert row[0] is None
        assert row[1] is None


# ---------------------------------------------------------------------------
# 9. metadata JSON round-trip
# ---------------------------------------------------------------------------


class TestMetadataRoundTrip:
    def test_default_metadata_round_trips_as_empty_dict(
        self, store: SQLiteExperienceStore
    ) -> None:
        exp = store.add(_make_experience())
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.metadata == {}

    def test_populated_metadata_round_trips(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience(metadata={"source": "test", "count": 3}))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.metadata == {"source": "test", "count": 3}


# ---------------------------------------------------------------------------
# 10. derived_memory_ids round-trip
# ---------------------------------------------------------------------------


class TestDerivedMemoryIdsRoundTrip:
    def test_default_empty_list_round_trips(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience())
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.derived_memory_ids == []

    def test_populated_list_round_trips(self, store: SQLiteExperienceStore) -> None:
        exp = store.add(_make_experience(derived_memory_ids=["mem-1", "mem-2"]))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.derived_memory_ids == ["mem-1", "mem-2"]


# ---------------------------------------------------------------------------
# 11. outcome round-trip
# ---------------------------------------------------------------------------


class TestOutcomeRoundTrip:
    @pytest.mark.parametrize(
        "outcome",
        [
            ExperienceOutcome.SUCCESS,
            ExperienceOutcome.PARTIAL,
            ExperienceOutcome.FAILED,
            ExperienceOutcome.UNKNOWN,
        ],
    )
    def test_each_outcome_value_round_trips(
        self, store: SQLiteExperienceStore, outcome: ExperienceOutcome
    ) -> None:
        exp = store.add(_make_experience(outcome=outcome))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.outcome is outcome


# ---------------------------------------------------------------------------
# 12. persisted_at, occurred_at'tan ayrı saklanır
# ---------------------------------------------------------------------------


class TestPersistedAtSeparateFromOccurredAt:
    def test_persisted_at_is_set_independently_of_occurred_at(
        self, store: SQLiteExperienceStore
    ) -> None:
        old_occurred_at = datetime(2020, 1, 1, tzinfo=UTC)
        before_persist = datetime.now(UTC)
        exp = store.add(_make_experience(occurred_at=old_occurred_at))
        after_persist = datetime.now(UTC)

        conn = sqlite3.connect(store._db_path)  # type: ignore[attr-defined]
        row = conn.execute(
            "SELECT occurred_at, persisted_at FROM experiences WHERE id = ?", (exp.id,)
        ).fetchone()
        conn.close()

        stored_occurred_at = datetime.fromisoformat(row[0])
        stored_persisted_at = datetime.fromisoformat(row[1])

        assert stored_occurred_at == old_occurred_at
        assert before_persist <= stored_persisted_at <= after_persist
        assert stored_persisted_at != stored_occurred_at


# ---------------------------------------------------------------------------
# 13. list_by_session
# ---------------------------------------------------------------------------


class TestListBySession:
    def test_returns_only_records_for_given_session(
        self, store: SQLiteExperienceStore
    ) -> None:
        store.add(_make_experience(session_id="sess-A", user_message="a1"))
        store.add(_make_experience(session_id="sess-A", user_message="a2"))
        store.add(_make_experience(session_id="sess-B", user_message="b1"))

        results = store.list_by_session("sess-A")
        assert len(results) == 2
        assert all(r.session_id == "sess-A" for r in results)

    def test_results_ordered_by_occurred_at_ascending(
        self, store: SQLiteExperienceStore
    ) -> None:
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2024, 1, 2, tzinfo=UTC)
        store.add(_make_experience(session_id="sess-A", occurred_at=t2, user_message="second"))
        store.add(_make_experience(session_id="sess-A", occurred_at=t1, user_message="first"))

        results = store.list_by_session("sess-A")
        assert [r.user_message for r in results] == ["first", "second"]

    def test_unknown_session_returns_empty_list(self, store: SQLiteExperienceStore) -> None:
        store.add(_make_experience(session_id="sess-A"))
        assert store.list_by_session("no-such-session") == []


# ---------------------------------------------------------------------------
# 14-16. list_recent — sıralama, limit, before
# ---------------------------------------------------------------------------


class TestListRecent:
    def test_results_ordered_by_occurred_at_descending(
        self, store: SQLiteExperienceStore
    ) -> None:
        t1 = datetime(2024, 3, 1, tzinfo=UTC)
        t2 = datetime(2024, 6, 1, tzinfo=UTC)
        t3 = datetime(2024, 1, 1, tzinfo=UTC)
        store.add(_make_experience(occurred_at=t1, user_message="march"))
        store.add(_make_experience(occurred_at=t2, user_message="june"))
        store.add(_make_experience(occurred_at=t3, user_message="january"))

        results = store.list_recent()
        assert [r.user_message for r in results] == ["june", "march", "january"]

    def test_limit_restricts_result_count(self, store: SQLiteExperienceStore) -> None:
        for i in range(10):
            store.add(_make_experience(occurred_at=datetime(2024, 1, i + 1, tzinfo=UTC)))
        results = store.list_recent(limit=3)
        assert len(results) == 3

    def test_before_parameter_excludes_later_experiences(
        self, store: SQLiteExperienceStore
    ) -> None:
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2024, 1, 2, tzinfo=UTC)
        t3 = datetime(2024, 1, 3, tzinfo=UTC)
        store.add(_make_experience(occurred_at=t1, user_message="first"))
        store.add(_make_experience(occurred_at=t2, user_message="second"))
        store.add(_make_experience(occurred_at=t3, user_message="third"))

        results = store.list_recent(before=t3)
        assert [r.user_message for r in results] == ["second", "first"]

    def test_before_enables_pagination(self, store: SQLiteExperienceStore) -> None:
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2024, 1, 2, tzinfo=UTC)
        store.add(_make_experience(occurred_at=t1, user_message="older"))
        store.add(_make_experience(occurred_at=t2, user_message="newer"))

        page1 = store.list_recent(limit=1)
        assert [r.user_message for r in page1] == ["newer"]

        page2 = store.list_recent(limit=1, before=page1[0].occurred_at)
        assert [r.user_message for r in page2] == ["older"]


# ---------------------------------------------------------------------------
# 17. Bulunamayan id
# ---------------------------------------------------------------------------


class TestMissingId:
    def test_get_unknown_id_returns_none(self, store: SQLiteExperienceStore) -> None:
        assert store.get("nonexistent-id") is None


# ---------------------------------------------------------------------------
# 18-20. Aynı DB dosyasını SQLiteMemoryStore ile paylaşma
# ---------------------------------------------------------------------------


class TestCoexistenceWithSQLiteMemoryStore:
    def test_two_stores_on_same_file_coexist_correctly(self, tmp_path: Path) -> None:
        from app.memory.record import MemoryRecord
        from app.memory.sqlite_store import SQLiteMemoryStore

        db_path = str(tmp_path / "shared.db")
        memory_store = SQLiteMemoryStore(db_path)
        experience_store = SQLiteExperienceStore(db_path)

        memory_store.add(MemoryRecord(content="a fact"))
        experience_store.add(_make_experience())

        assert memory_store.count() == 1
        assert experience_store.count() == 1

    def test_experience_store_works_when_initialized_before_memory_store(
        self, tmp_path: Path
    ) -> None:
        from app.memory.record import MemoryRecord
        from app.memory.sqlite_store import SQLiteMemoryStore

        db_path = str(tmp_path / "shared.db")
        experience_store = SQLiteExperienceStore(db_path)
        memory_store = SQLiteMemoryStore(db_path)

        exp = experience_store.add(_make_experience())
        memory_store.add(MemoryRecord(content="a fact"))

        assert experience_store.get(exp.id) is not None
        assert memory_store.count() == 1

    def test_experience_store_works_when_initialized_after_memory_store(
        self, tmp_path: Path
    ) -> None:
        from app.memory.record import MemoryRecord
        from app.memory.sqlite_store import SQLiteMemoryStore

        db_path = str(tmp_path / "shared.db")
        memory_store = SQLiteMemoryStore(db_path)
        experience_store = SQLiteExperienceStore(db_path)

        memory_store.add(MemoryRecord(content="a fact"))
        exp = experience_store.add(_make_experience())

        assert memory_store.count() == 1
        assert experience_store.get(exp.id) is not None


# ---------------------------------------------------------------------------
# 21. Şema oluşturma idempotenttir
# ---------------------------------------------------------------------------


class TestSchemaIdempotence:
    def test_constructing_store_twice_on_same_file_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        db_path = str(tmp_path / "idempotent.db")
        first = SQLiteExperienceStore(db_path)
        first.add(_make_experience())

        second = SQLiteExperienceStore(db_path)  # yeniden şema oluşturma denemesi

        assert second.count() == 1  # önceki veriler korunmuş


# ---------------------------------------------------------------------------
# 22. Experience için FTS5 tablosu oluşturulmaz
# ---------------------------------------------------------------------------


class TestNoFts5Table:
    def test_no_fts5_virtual_table_exists_for_experiences(
        self, store: SQLiteExperienceStore
    ) -> None:
        conn = sqlite3.connect(store._db_path)  # type: ignore[attr-defined]
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()

        table_names = {r[0] for r in rows}
        assert "experiences" in table_names
        assert not any("fts" in name.lower() for name in table_names)


# ---------------------------------------------------------------------------
# 23. Hiçbir harici bağımlılık eklenmedi
# ---------------------------------------------------------------------------


class TestNoExternalDependency:
    def test_modules_only_import_stdlib_and_internal_experience_model(self) -> None:
        import app.memory.experience_store as protocol_module
        import app.memory.sqlite_experience_store as store_module

        for module in (protocol_module, store_module):
            import_lines = [
                line.strip()
                for line in inspect.getsource(module).splitlines()
                if line.strip().startswith(("import ", "from "))
            ]
            for line in import_lines:
                assert (
                    line.startswith("from app.memory.experience")
                    or line.split()[1].split(".")[0]
                    in {
                        "__future__",
                        "json",
                        "logging",
                        "sqlite3",
                        "datetime",
                        "pathlib",
                        "typing",
                    }
                ), f"beklenmeyen import: {line}"

    def test_store_module_does_not_import_sqlite_memory_store_or_protocol(self) -> None:
        import app.memory.sqlite_experience_store as store_module

        source = inspect.getsource(store_module)
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        joined = "\n".join(import_lines)
        assert "sqlite_store" not in joined
        assert "MemoryStore" not in joined


# ---------------------------------------------------------------------------
# 24. Normal konuşma metni aynen korunur
# ---------------------------------------------------------------------------


class TestConversationTextPreservedExactly:
    def test_unicode_and_turkish_characters_round_trip(
        self, store: SQLiteExperienceStore
    ) -> None:
        text = "Kullanıcı şöyle dedi: 'İstanbul'da yaşıyorum, çok güzel bir şehir!' 😊"
        exp = store.add(_make_experience(user_message=text, assistant_response=text))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.user_message == text
        assert fetched.assistant_response == text

    def test_multiline_text_round_trips(self, store: SQLiteExperienceStore) -> None:
        text = "Birinci satır.\nİkinci satır.\n\tSekmeli üçüncü satır."
        exp = store.add(_make_experience(user_message=text))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.user_message == text

    def test_text_is_not_truncated_or_filtered(self, store: SQLiteExperienceStore) -> None:
        """Normal konuşma metni, salt konuşma olduğu için filtrelenmez/kısaltılmaz —
        hassas içerik sınıflandırması bu fazda kasıtlı olarak YOK."""
        long_text = "Bu " * 200 + "uzun bir mesaj."
        exp = store.add(_make_experience(user_message=long_text))
        fetched = store.get(exp.id)
        assert fetched is not None
        assert fetched.user_message == long_text
        assert len(fetched.user_message) == len(long_text)


# ---------------------------------------------------------------------------
# 25. Secure Vault kazara implemente edilmedi/bağlanmadı
# ---------------------------------------------------------------------------


class TestSecureVaultNotImplementedOrCoupled:
    def test_no_encryption_or_authentication_mechanism_exists(self) -> None:
        """Bu faz normal Experience kalıcılığıdır — Secure Vault (şifreleme,
        Face ID/cihaz kimlik doğrulaması, şifre koruması) BU FAZDA implemente
        edilmedi. Kodda (docstring/açıklayıcı metin DEĞİL — gerçek fonksiyon/
        sınıf/değişken/attribute adları) böyle bir mekanizma olmamalı.

        Not: yalnızca gerçek Python tanımlayıcıları (AST üzerinden) taranır —
        modülün kendi docstring'lerinde "Secure Vault henüz yok" diye
        AÇIKLAYICI olarak geçen "vault" kelimesi (düz metin, bir tanımlayıcı
        değil) yanlışlıkla bu testi patlatmamalı.
        """
        import ast

        import app.memory.sqlite_experience_store as store_module

        tree = ast.parse(inspect.getsource(store_module))
        identifiers: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                identifiers.add(node.name.lower())
            elif isinstance(node, ast.Name):
                identifiers.add(node.id.lower())
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr.lower())

        forbidden_terms = [
            "encrypt",
            "decrypt",
            "faceid",
            "face_id",
            "fingerprint",
            "biometric",
            "password_hash",
            "vault",
        ]
        for term in forbidden_terms:
            assert not any(term in identifier for identifier in identifiers), (
                f"beklenmeyen Secure Vault tanımlayıcısı bulundu: {term!r}"
            )

    def test_experience_store_protocol_has_no_authentication_parameter(self) -> None:
        """ExperienceStore Protocol metodları hiçbir kimlik doğrulama/şifreleme
        parametresi almamalı — normal ve hassas veri akışları tamamen ayrı
        kalmalı (Secure Vault, gelecekte, bu Protocol'ün DIŞINDA ayrı bir
        bileşen olarak eklenecek)."""
        for method_name in ("add", "get", "list_by_session", "list_recent"):
            method = getattr(ExperienceStore, method_name)
            sig = inspect.signature(method)
            param_names = {p.lower() for p in sig.parameters}
            assert not any(
                "password" in p or "auth" in p or "token" in p or "key" in p
                for p in param_names
            )

    def test_database_file_is_plain_unencrypted_sqlite(
        self, store: SQLiteExperienceStore, tmp_path: Path
    ) -> None:
        """Bu fazda veritabanı dosyası düz (şifrelenmemiş) bir SQLite
        dosyasıdır — herhangi bir standart sqlite3 bağlantısıyla açılabilir
        olmalı, özel bir şifre/anahtar gerektirmemeli."""
        store.add(_make_experience())
        conn = sqlite3.connect(store._db_path)  # type: ignore[attr-defined]
        # Şifreli olsaydı bu sorgu PRAGMA key olmadan başarısız olurdu.
        row = conn.execute("SELECT COUNT(*) FROM experiences").fetchone()
        conn.close()
        assert row[0] == 1
