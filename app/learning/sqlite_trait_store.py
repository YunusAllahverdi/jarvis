"""UserTraitStore Protocol'ünün SQLite tabanlı implementasyonu.

Standart kütüphane `sqlite3` kullanılır; harici bağımlılık yoktur.
SQLiteMemoryStore ve SQLiteExperienceStore ile AYNI fiziksel veritabanı
dosyasını paylaşabilir, ama şema sorumluluğu tamamen bağımsızdır:
- MemoryStore / ExperienceStore Protocol'lerini hiç import etmez,
- diğer somut store sınıflarını hiç import etmez,
- kendi tablosunu (`user_traits`) idempotent olarak kendi başına oluşturur.

Tasarım ilkeleri (mevcut iki store ile tutarlı):
- Tüm zaman damgaları UTC, ISO 8601 formatında saklanır.
- Fiziksel silme YOKTUR — yalnızca mantıksal geçersizleştirme (`invalid_at`).
- Ham SQLite bağlantısı bu modülün dışına sızdırılmaz.
- Her işlem ayrı bir `with self._connect()` bloğunda çalışır.
- FTS5 yoktur: trait'ler tam metin aranacak veri değil, sınırlı sayıda
  yapılandırılmış gözlemdir.

Etkin kimlik kısıtı:
    `(trait_type, trait_key)` üzerinde KISMİ (partial) bir UNIQUE indeks
    vardır ve yalnızca `invalid_at IS NULL` satırlarını kapsar. Böylece aynı
    kavram için aynı anda iki etkin trait oluşması veritabanı düzeyinde
    imkânsızdır, ama geçersizleştirilmiş tarihsel kayıtlar sınırsızca
    birikebilir — tarihçe korunur.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.learning.trait import TraitSource, TraitType, UserTrait

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Şema
# ---------------------------------------------------------------------------

_DDL_USER_TRAITS = """
CREATE TABLE IF NOT EXISTS user_traits (
    id                 TEXT PRIMARY KEY,
    trait_type         TEXT NOT NULL,
    trait_key          TEXT NOT NULL,
    value              TEXT NOT NULL,
    evidence_count     INTEGER NOT NULL DEFAULT 0,
    confidence         REAL NOT NULL DEFAULT 0.0,
    source             TEXT NOT NULL,
    first_observed_at  TEXT NOT NULL,
    last_observed_at   TEXT NOT NULL,
    invalid_at         TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    metadata           TEXT NOT NULL DEFAULT '{}'
);
"""

_DDL_IDX_ACTIVE_IDENTITY = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_traits_active_identity
    ON user_traits (trait_type, trait_key)
    WHERE invalid_at IS NULL;
"""

_DDL_IDX_TYPE = """
CREATE INDEX IF NOT EXISTS idx_user_traits_type
    ON user_traits (trait_type)
    WHERE invalid_at IS NULL;
"""

_DDL_IDX_CONFIDENCE = """
CREATE INDEX IF NOT EXISTS idx_user_traits_confidence
    ON user_traits (confidence DESC)
    WHERE invalid_at IS NULL;
"""

_ALL_DDL = [
    _DDL_USER_TRAITS,
    _DDL_IDX_ACTIVE_IDENTITY,
    _DDL_IDX_TYPE,
    _DDL_IDX_CONFIDENCE,
]

# ---------------------------------------------------------------------------
# Yardımcı dönüşümler
# ---------------------------------------------------------------------------


def _dt_to_str(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _opt_dt_to_str(dt: datetime | None) -> str | None:
    return _dt_to_str(dt) if dt is not None else None


def _str_to_dt(s: str) -> datetime:
    parsed = datetime.fromisoformat(s)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _opt_str_to_dt(s: str | None) -> datetime | None:
    return _str_to_dt(s) if s is not None else None


def _row_to_trait(row: sqlite3.Row) -> UserTrait:
    return UserTrait(
        id=row["id"],
        trait_type=TraitType(row["trait_type"]),
        key=row["trait_key"],
        value=row["value"],
        evidence_count=row["evidence_count"],
        confidence=row["confidence"],
        source=TraitSource(row["source"]),
        first_observed_at=_str_to_dt(row["first_observed_at"]),
        last_observed_at=_str_to_dt(row["last_observed_at"]),
        invalid_at=_opt_str_to_dt(row["invalid_at"]),
        created_at=_str_to_dt(row["created_at"]),
        updated_at=_str_to_dt(row["updated_at"]),
        metadata=json.loads(row["metadata"]),
    )


# ---------------------------------------------------------------------------
# SQLiteUserTraitStore
# ---------------------------------------------------------------------------


class SQLiteUserTraitStore:
    """UserTraitStore Protocol'ünü SQLite üzerinde uygular.

    Kullanım:
        store = SQLiteUserTraitStore("/path/to/memory.db")
        stored = store.upsert(trait)
    """

    def __init__(self, db_path: str) -> None:
        """
        Args:
            db_path: SQLite dosyasının yolu. SQLiteMemoryStore ve
                SQLiteExperienceStore ile aynı dosya kullanılabilir — üç sınıf
                birbirinden bağımsız şekilde kendi tablolarını yönetir.
                ":memory:" test amaçlı kullanılabilir.
        """
        self._db_path = db_path
        self._ensure_dir()
        self._initialize_schema()
        logger.info("user_trait_store_initialized", extra={"db_path": db_path})

    # ------------------------------------------------------------------
    # Başlatma
    # ------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        if self._db_path == ":memory:":
            return
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize_schema(self) -> None:
        """`user_traits` tablosunu ve indekslerini henüz yoksa oluşturur.

        Diğer store'ların tablolarına hiç dokunmaz; aynı dosyada onlardan
        önce veya sonra çağrılması sonucu değiştirmez (idempotent).
        """
        with self._connect() as conn:
            for ddl in _ALL_DDL:
                conn.executescript(ddl)
            conn.commit()

    # ------------------------------------------------------------------
    # Yazma
    # ------------------------------------------------------------------

    def upsert(self, trait: UserTrait) -> UserTrait:
        """Trait'i ekler veya aynı `(trait_type, key)` için etkin kaydı tazeler.

        Mevcut etkin kayıt varsa `id`, `created_at` ve `first_observed_at`
        korunur; böylece bir gözlemin ne zaman İLK kez görüldüğü bilgisi
        sonraki geçişlerde kaybolmaz.
        """
        existing = self.find_active(trait.trait_type, trait.key)
        now = datetime.now(UTC)

        if existing is None:
            stored = trait.model_copy(deep=True)
            stored.created_at = now
            stored.updated_at = now
            self._insert(stored)
            logger.debug(
                "user_trait_created",
                extra={"trait_id": stored.id, "trait_key": stored.key},
            )
            return stored

        stored = existing.model_copy(deep=True)
        stored.value = trait.value
        stored.evidence_count = trait.evidence_count
        stored.confidence = trait.confidence
        stored.source = trait.source
        stored.last_observed_at = trait.last_observed_at
        stored.metadata = dict(trait.metadata)
        stored.updated_at = now
        self._update(stored)
        logger.debug(
            "user_trait_updated",
            extra={"trait_id": stored.id, "trait_key": stored.key},
        )
        return stored

    def _insert(self, trait: UserTrait) -> None:
        sql = """
        INSERT INTO user_traits
            (id, trait_type, trait_key, value, evidence_count, confidence, source,
             first_observed_at, last_observed_at, invalid_at, created_at, updated_at,
             metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            trait.id,
            trait.trait_type.value,
            trait.key,
            trait.value,
            trait.evidence_count,
            trait.confidence,
            trait.source.value,
            _dt_to_str(trait.first_observed_at),
            _dt_to_str(trait.last_observed_at),
            _opt_dt_to_str(trait.invalid_at),
            _dt_to_str(trait.created_at),
            _dt_to_str(trait.updated_at),
            json.dumps(trait.metadata, ensure_ascii=False, default=str),
        )
        with self._connect() as conn:
            conn.execute(sql, params)
            conn.commit()

    def _update(self, trait: UserTrait) -> None:
        sql = """
        UPDATE user_traits
           SET value = ?, evidence_count = ?, confidence = ?, source = ?,
               last_observed_at = ?, updated_at = ?, metadata = ?
         WHERE id = ?
        """
        params = (
            trait.value,
            trait.evidence_count,
            trait.confidence,
            trait.source.value,
            _dt_to_str(trait.last_observed_at),
            _dt_to_str(trait.updated_at),
            json.dumps(trait.metadata, ensure_ascii=False, default=str),
            trait.id,
        )
        with self._connect() as conn:
            conn.execute(sql, params)
            conn.commit()

    def invalidate(self, trait_id: str, *, at: datetime | None = None) -> bool:
        """Etkin bir trait'i mantıksal olarak geçersizleştirir.

        Fiziksel kayıt korunur. Zaten geçersiz veya bulunamayan bir kimlik
        için False döner.
        """
        moment = at or datetime.now(UTC)
        sql = """
        UPDATE user_traits
           SET invalid_at = ?, updated_at = ?
         WHERE id = ? AND invalid_at IS NULL
        """
        with self._connect() as conn:
            cursor = conn.execute(sql, (_dt_to_str(moment), _dt_to_str(moment), trait_id))
            conn.commit()
            changed = cursor.rowcount > 0
        if changed:
            logger.info("user_trait_invalidated", extra={"trait_id": trait_id})
        return changed

    # ------------------------------------------------------------------
    # Okuma
    # ------------------------------------------------------------------

    def get(self, trait_id: str) -> UserTrait | None:
        """Kimliğe göre tek bir trait döndürür (geçersizler dahil)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_traits WHERE id = ?", (trait_id,)
            ).fetchone()
        return _row_to_trait(row) if row else None

    def find_active(self, trait_type: TraitType, key: str) -> UserTrait | None:
        """`(trait_type, key)` için etkin kaydı döndürür; yoksa None."""
        sql = """
        SELECT * FROM user_traits
         WHERE trait_type = ? AND trait_key = ? AND invalid_at IS NULL
        """
        with self._connect() as conn:
            row = conn.execute(sql, (trait_type.value, key)).fetchone()
        return _row_to_trait(row) if row else None

    def list_active(
        self,
        *,
        trait_type: TraitType | None = None,
        min_confidence: float = 0.0,
        limit: int = 50,
        offset: int = 0,
    ) -> list[UserTrait]:
        """Etkin trait'leri güven (sonra tazelik) sırasına göre döndürür."""
        clauses = ["invalid_at IS NULL", "confidence >= ?"]
        params: list[object] = [min_confidence]
        if trait_type is not None:
            clauses.append("trait_type = ?")
            params.append(trait_type.value)

        sql = (
            f"SELECT * FROM user_traits WHERE {' AND '.join(clauses)} "
            "ORDER BY confidence DESC, last_observed_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_trait(r) for r in rows]

    # ------------------------------------------------------------------
    # Yardımcı (Protocol'ün parçası değil — test/gözlem kolaylığı)
    # ------------------------------------------------------------------

    def count(self, *, include_invalidated: bool = False) -> int:
        """Trait sayısını döndürür."""
        sql = "SELECT COUNT(*) FROM user_traits"
        if not include_invalidated:
            sql += " WHERE invalid_at IS NULL"
        with self._connect() as conn:
            row = conn.execute(sql).fetchone()
        return row[0] if row else 0
