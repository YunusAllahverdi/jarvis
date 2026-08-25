"""SQLite tabanlı kalıcı bellek depolaması.

Standart kütüphane sqlite3 modülü kullanılır; harici bağımlılık yoktur.
FTS5 virtual table ile tam metin araması desteklenir.
Gelecekte sqlite-vec eklenerek vektör araması etkinleştirilebilir.

Tasarım ilkeleri:
- Tüm zaman damgaları UTC, ISO 8601 formatında saklanır.
- Fiziksel silme yapılmaz; mantıksal silme (deleted_at) ve
  geçersizleştirme (invalid_at) kullanılır.
- FTS5 içerik tablosu otomatik senkronize edilir (content='memories').
- Ham SQLite bağlantısı bu modülün dışına sızdırılmaz.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.memory.record import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    Temporality,
    _utcnow,
)
from app.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Şema
# ---------------------------------------------------------------------------

_DDL_MEMORIES = """
CREATE TABLE IF NOT EXISTS memories (
    id                TEXT PRIMARY KEY,
    memory_type       TEXT NOT NULL DEFAULT 'other',
    content           TEXT NOT NULL,
    temporality       TEXT NOT NULL DEFAULT 'unknown',
    status            TEXT NOT NULL DEFAULT 'active',
    valid_at          TEXT NOT NULL,
    invalid_at        TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    source_session_id TEXT,
    importance        REAL NOT NULL DEFAULT 0.5,
    sensitivity       REAL NOT NULL DEFAULT 0.0,
    deleted_at        TEXT,
    metadata          TEXT NOT NULL DEFAULT '{}'
);
"""

_DDL_IDX_VALID_AT = """
CREATE INDEX IF NOT EXISTS idx_memories_valid_at
    ON memories (valid_at DESC);
"""

_DDL_IDX_TYPE = """
CREATE INDEX IF NOT EXISTS idx_memories_type
    ON memories (memory_type);
"""

_DDL_IDX_SESSION = """
CREATE INDEX IF NOT EXISTS idx_memories_session
    ON memories (source_session_id)
    WHERE source_session_id IS NOT NULL;
"""

_DDL_IDX_TEMPORALITY = """
CREATE INDEX IF NOT EXISTS idx_memories_temporality
    ON memories (temporality);
"""

_DDL_IDX_STATUS = """
CREATE INDEX IF NOT EXISTS idx_memories_status
    ON memories (status);
"""

# FTS5 virtual table — content='memories' ile ana tablo üzerinden rebuild
# desteklenir. content_rowid='rowid' ayarı trigger'ları bağlar.
_DDL_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    content='memories',
    content_rowid='rowid',
    tokenize='porter unicode61'
);
"""

# FTS senkronizasyon trigger'ları
_DDL_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS memories_ai
AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts (rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad
AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, content)
        VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_au
AFTER UPDATE OF content ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, content)
        VALUES ('delete', old.rowid, old.content);
    INSERT INTO memories_fts (rowid, content) VALUES (new.rowid, new.content);
END;
"""

_ALL_DDL = [
    _DDL_MEMORIES,
    _DDL_IDX_VALID_AT,
    _DDL_IDX_TYPE,
    _DDL_IDX_SESSION,
    _DDL_IDX_TEMPORALITY,
    _DDL_IDX_STATUS,
    _DDL_FTS,
    _DDL_FTS_TRIGGERS,
]

# ---------------------------------------------------------------------------
# Yardımcı dönüşümler
# ---------------------------------------------------------------------------

def _dt_to_str(dt: datetime | None) -> str | None:
    """datetime → ISO 8601 UTC string."""
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat()


def _str_to_dt(s: str | None) -> datetime | None:
    """ISO 8601 UTC string → timezone-aware datetime."""
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    """sqlite3.Row → MemoryRecord."""
    return MemoryRecord(
        id=row["id"],
        memory_type=MemoryType(row["memory_type"]),
        content=row["content"],
        temporality=Temporality(row["temporality"]),
        status=MemoryStatus(row["status"]),
        valid_at=_str_to_dt(row["valid_at"]),  # type: ignore[arg-type]
        invalid_at=_str_to_dt(row["invalid_at"]),
        created_at=_str_to_dt(row["created_at"]),  # type: ignore[arg-type]
        updated_at=_str_to_dt(row["updated_at"]),  # type: ignore[arg-type]
        source_session_id=row["source_session_id"],
        importance=row["importance"],
        sensitivity=row["sensitivity"],
        deleted_at=_str_to_dt(row["deleted_at"]),
        metadata=json.loads(row["metadata"]),
    )


# ---------------------------------------------------------------------------
# SQLiteMemoryStore
# ---------------------------------------------------------------------------

class SQLiteMemoryStore:
    """MemoryStore Protocol'ünü SQLite üzerinde uygular.

    Kullanım:
        store = SQLiteMemoryStore("/path/to/memory.db")
        record = store.add(MemoryRecord(content="...", memory_type=MemoryType.FACT))

    Bağlantı yönetimi: Her işlem ayrı bir `with self._connect()` bloğunda
    çalışır. Bu yaklaşım thread güvenliğini sağlar ve uzun yaşam süreli
    bağlantı sızıntısını önler.
    """

    def __init__(self, db_path: str) -> None:
        """
        Args:
            db_path: SQLite dosyasının yolu. ":memory:" test amaçlı kullanılabilir.
        """
        self._db_path = db_path
        self._ensure_dir()
        self._initialize_schema()
        logger.info("memory_store_initialized", extra={"db_path": db_path})

    # ------------------------------------------------------------------
    # Başlatma
    # ------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        """Veritabanı dosyasının bulunduğu dizini oluşturur."""
        if self._db_path == ":memory:":
            return
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """Yeni bir SQLite bağlantısı açar ve row_factory ayarlar."""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize_schema(self) -> None:
        """Tablolar ve indeksler henüz yoksa oluşturur."""
        with self._connect() as conn:
            for ddl in _ALL_DDL:
                # FTS trigger DDL'i tek blok olarak çalıştırmak gerekir
                conn.executescript(ddl)
            conn.commit()

    # ------------------------------------------------------------------
    # Yazma işlemleri
    # ------------------------------------------------------------------

    def add(self, record: MemoryRecord) -> MemoryRecord:
        """Yeni bir bellek kaydı ekler."""
        now = _utcnow()
        # Zaman damgaları ayarlanmamışsa şimdiyi kullan
        if record.created_at is None:  # type: ignore[redundant-expr]
            record.created_at = now
        if record.updated_at is None:  # type: ignore[redundant-expr]
            record.updated_at = now
        if record.valid_at is None:  # type: ignore[redundant-expr]
            record.valid_at = now

        sql = """
        INSERT INTO memories
            (id, memory_type, content, temporality, status,
             valid_at, invalid_at, created_at, updated_at,
             source_session_id, importance, sensitivity, deleted_at, metadata)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.id,
            record.memory_type.value,
            record.content,
            record.temporality.value,
            record.status.value,
            _dt_to_str(record.valid_at),
            _dt_to_str(record.invalid_at),
            _dt_to_str(record.created_at),
            _dt_to_str(record.updated_at),
            record.source_session_id,
            record.importance,
            record.sensitivity,
            _dt_to_str(record.deleted_at),
            json.dumps(record.metadata, ensure_ascii=False, default=str),
        )
        with self._connect() as conn:
            conn.execute(sql, params)
            conn.commit()
        logger.debug(
            "memory_added",
            extra={"memory_id": record.id, "memory_type": record.memory_type},
        )
        return record

    def update(self, record: MemoryRecord) -> MemoryRecord:
        """Var olan bir kaydı günceller.

        Raises:
            KeyError: Belirtilen id ile kayıt bulunamazsa.
        """
        record.updated_at = _utcnow()

        sql = """
        UPDATE memories SET
            memory_type = ?,
            content = ?,
            temporality = ?,
            status = ?,
            valid_at = ?,
            invalid_at = ?,
            updated_at = ?,
            source_session_id = ?,
            importance = ?,
            sensitivity = ?,
            deleted_at = ?,
            metadata = ?
        WHERE id = ?
        """
        params = (
            record.memory_type.value,
            record.content,
            record.temporality.value,
            record.status.value,
            _dt_to_str(record.valid_at),
            _dt_to_str(record.invalid_at),
            _dt_to_str(record.updated_at),
            record.source_session_id,
            record.importance,
            record.sensitivity,
            _dt_to_str(record.deleted_at),
            json.dumps(record.metadata, ensure_ascii=False, default=str),
            record.id,
        )
        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            if cursor.rowcount == 0:
                raise KeyError(f"Bellek kaydı bulunamadı: {record.id!r}")
        return record

    def invalidate(self, memory_id: str, *, at: datetime | None = None) -> bool:
        """Bir kaydı mantıksal olarak geçersizleştirir.

        Fiziksel kayıt silinmez; sadece `invalid_at` ayarlanır.
        """
        ts = _dt_to_str(at or _utcnow())
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE memories SET invalid_at = ?, updated_at = ? WHERE id = ? AND invalid_at IS NULL",
                (ts, ts, memory_id),
            )
            conn.commit()
        found = cursor.rowcount > 0
        if found:
            logger.debug("memory_invalidated", extra={"memory_id": memory_id})
        return found

    def delete(self, memory_id: str, *, at: datetime | None = None) -> bool:
        """Bir kaydı mantıksal olarak siler ("unut" komutu için).

        Fiziksel kayıt silinmez; `deleted_at` ayarlanır.
        """
        ts = _dt_to_str(at or _utcnow())
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE memories SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (ts, ts, memory_id),
            )
            conn.commit()
        found = cursor.rowcount > 0
        if found:
            logger.debug("memory_deleted", extra={"memory_id": memory_id})
        return found

    # ------------------------------------------------------------------
    # Okuma işlemleri
    # ------------------------------------------------------------------

    def get(self, memory_id: str) -> MemoryRecord | None:
        """Kimliğe göre tek bir kaydı döndürür; bulunamazsa None.

        Silinmiş ve geçersizleştirilmiş kayıtlar da döndürülür.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def list_active(
        self,
        *,
        memory_type: MemoryType | None = None,
        temporality: Temporality | None = None,
        status: MemoryStatus | None = None,
        source_session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """Aktif kayıtları döndürür (silinmemiş ve geçersizleştirilmemiş)."""
        conditions = ["deleted_at IS NULL", "invalid_at IS NULL"]
        params: list[object] = []

        if memory_type is not None:
            conditions.append("memory_type = ?")
            params.append(memory_type.value)
        if temporality is not None:
            conditions.append("temporality = ?")
            params.append(temporality.value)
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)
        if source_session_id is not None:
            conditions.append("source_session_id = ?")
            params.append(source_session_id)

        where = " AND ".join(conditions)
        params.extend([limit, offset])
        sql = f"SELECT * FROM memories WHERE {where} ORDER BY valid_at DESC LIMIT ? OFFSET ?"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_record(r) for r in rows]

    def list_by_session(
        self,
        session_id: str,
        *,
        include_invalidated: bool = False,
    ) -> list[MemoryRecord]:
        """Bir oturuma ait kayıtları döndürür."""
        conditions = ["source_session_id = ?", "deleted_at IS NULL"]
        params: list[object] = [session_id]

        if not include_invalidated:
            conditions.append("invalid_at IS NULL")

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM memories WHERE {where} ORDER BY created_at ASC"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_record(r) for r in rows]

    # ------------------------------------------------------------------
    # Arama
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        temporality: Temporality | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """FTS5 tam metin araması.

        Aktif (silinmemiş ve geçersizleştirilmemiş) kayıtlar arasında arama yapar.
        Phase 1A: keyword araması. Gelecekte vektör aramasıyla desteklenebilir.
        """
        if not query.strip():
            return []

        # FTS5 sorgusunu normalize et — özel karakterleri temizle
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            return []

        conditions = [
            "m.deleted_at IS NULL",
            "m.invalid_at IS NULL",
        ]
        params: list[object] = [safe_query]

        if memory_type is not None:
            conditions.append("m.memory_type = ?")
            params.append(memory_type.value)
        if temporality is not None:
            conditions.append("m.temporality = ?")
            params.append(temporality.value)

        params.append(limit)
        where = " AND ".join(conditions)
        sql = f"""
        SELECT m.*
        FROM memories m
        JOIN memories_fts f ON m.rowid = f.rowid
        WHERE memories_fts MATCH ?
          AND {where}
        ORDER BY rank, m.valid_at DESC
        LIMIT ?
        """

        with self._connect() as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # Hatalı FTS sözdizimi — boş liste döndür
                logger.warning("fts_query_failed", extra={"query": query})
                return []
        return [_row_to_record(r) for r in rows]

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def count(self, *, include_deleted: bool = False) -> int:
        """Toplam kayıt sayısını döndürür."""
        if include_deleted:
            sql = "SELECT COUNT(*) FROM memories"
            params: tuple = ()
        else:
            sql = "SELECT COUNT(*) FROM memories WHERE deleted_at IS NULL"
            params = ()
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def schema_version(self) -> int:
        """Basit bir şema versiyon değeri döndürür (user_version pragma)."""
        with self._connect() as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]


# ---------------------------------------------------------------------------
# FTS sorgusunu güvenli hale getirme
# ---------------------------------------------------------------------------

def _sanitize_fts_query(query: str) -> str:
    """FTS5 özel karakterlerini temizleyerek güvenli arama dizesi üretir.

    Karmaşık FTS sözdizimi (AND, OR, NOT, tırnak içi ifadeler) Phase 1A'da
    desteklenmez. Yalnızca temiz kelimeler aranır.
    """
    # FTS5 özel karakterlerini kaldır
    for ch in ('"', "'", "(", ")", "*", "^", "+", "-", ":", "~"):
        query = query.replace(ch, " ")
    # Birden fazla boşluğu tek boşluğa indir
    tokens = query.split()
    # Çok kısa token'ları at (1 karakter)
    tokens = [t for t in tokens if len(t) > 1]
    return " ".join(tokens)
