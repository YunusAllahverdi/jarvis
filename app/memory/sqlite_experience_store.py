"""Phase 2D — Experience için SQLite tabanlı kalıcı depolama (append-only).

Standart kütüphane sqlite3 modülü kullanılır; harici bağımlılık yoktur.
SQLiteMemoryStore ile AYNI fiziksel veritabanı dosyasını (`memory_db_path`)
paylaşabilir, ama şema sorumluluğu tamamen bağımsızdır:
- SQLiteMemoryStore'u hiç import etmez,
- MemoryStore Protocol'ünü hiç import etmez,
- kendi tablosunu (`experiences`) kendi başına, idempotent olarak oluşturur.

İki sınıf aynı `.db` dosyasında bağımsız olarak var olabilir — SQLite,
birbirinden habersiz `CREATE TABLE IF NOT EXISTS` ifadelerini güvenle
birlikte çalıştırır (sıra önemsizdir; bkz. tests/test_experience_store.py
"iki store aynı dosyada birlikte var olur" testleri).

Tasarım ilkeleri (SQLiteMemoryStore ile tutarlı):
- Tüm zaman damgaları UTC, ISO 8601 formatında saklanır.
- Deneyimler ekle-yalnızcadır (append-only) — bu fazda update()/delete() yok,
  hiçbir fiziksel/mantıksal silme mekanizması yok.
- Ham SQLite bağlantısı bu modülün dışına sızdırılmaz.
- Her işlem ayrı bir `with self._connect()` bloğunda çalışır (thread
  güvenliği, uzun ömürlü bağlantı sızıntısını önleme).

---------------------------------------------------------------------------
GÜVENLİK/GİZLİLİK SINIRI — Secure Vault BU FAZDA YOKTUR
---------------------------------------------------------------------------
Bu sınıf NORMAL konuşma deneyimlerini olduğu gibi (şifrelemeden, hassas
içerik sınıflandırması yapmadan) saklar — Jarvis'in uzun vadeli epizodik
geçmiş oluşturması için gereken normal konuşma bağlamı budur. TC kimlik
no, şifre, API anahtarı gibi son derece hassas bilgiler için ayrı, ŞİFRELİ,
muhtemelen Face ID/cihaz kimlik doğrulaması gerektiren bir **Secure Vault**
GELECEKTE, ayrı bir bileşen olarak eklenecektir — bu dosyada ona hiçbir
bağlantı/coupling kurulmadı ve bu veritabanı BU FAZDA şifrelenmiyor.
Ayrıntı için app/memory/experience_store.py'nin modül docstring'ine bakın.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.memory.experience import Experience, ExperienceOutcome

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Şema
# ---------------------------------------------------------------------------

_DDL_EXPERIENCES = """
CREATE TABLE IF NOT EXISTS experiences (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT,
    occurred_at         TEXT NOT NULL,
    user_message        TEXT NOT NULL,
    assistant_response  TEXT NOT NULL,
    tool_calls          TEXT NOT NULL DEFAULT '[]',
    user_state          TEXT,
    emotional_context   TEXT,
    outcome             TEXT NOT NULL DEFAULT 'unknown',
    derived_memory_ids  TEXT NOT NULL DEFAULT '[]',
    metadata            TEXT NOT NULL DEFAULT '{}',
    persisted_at        TEXT NOT NULL
);
"""

_DDL_IDX_OCCURRED_AT = """
CREATE INDEX IF NOT EXISTS idx_experiences_occurred_at
    ON experiences (occurred_at DESC);
"""

_DDL_IDX_SESSION = """
CREATE INDEX IF NOT EXISTS idx_experiences_session
    ON experiences (session_id)
    WHERE session_id IS NOT NULL;
"""

_DDL_IDX_OUTCOME = """
CREATE INDEX IF NOT EXISTS idx_experiences_outcome
    ON experiences (outcome);
"""

# Bilinçli olarak: Experience için hiçbir FTS5 virtual table YOK. Experience,
# Memory gibi anahtar-kelime aranabilir olmak zorunda değil (bu fazda bir
# gereksinim değil) — eklenmesi erken/gereksiz bir arama altyapısı olurdu.
_ALL_DDL = [
    _DDL_EXPERIENCES,
    _DDL_IDX_OCCURRED_AT,
    _DDL_IDX_SESSION,
    _DDL_IDX_OUTCOME,
]

# ---------------------------------------------------------------------------
# Yardımcı dönüşümler (SQLiteMemoryStore ile aynı kural: UTC, ISO 8601)
# ---------------------------------------------------------------------------


def _dt_to_str(dt: datetime) -> str:
    """datetime → ISO 8601 UTC string."""
    return dt.astimezone(UTC).isoformat()


def _str_to_dt(s: str) -> datetime:
    """ISO 8601 UTC string → timezone-aware datetime."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _row_to_experience(row: sqlite3.Row) -> Experience:
    """sqlite3.Row → Experience."""
    return Experience(
        id=row["id"],
        session_id=row["session_id"],
        occurred_at=_str_to_dt(row["occurred_at"]),
        user_message=row["user_message"],
        assistant_response=row["assistant_response"],
        tool_calls=json.loads(row["tool_calls"]),
        user_state=json.loads(row["user_state"]) if row["user_state"] is not None else None,
        emotional_context=(
            json.loads(row["emotional_context"])
            if row["emotional_context"] is not None
            else None
        ),
        outcome=ExperienceOutcome(row["outcome"]),
        derived_memory_ids=json.loads(row["derived_memory_ids"]),
        metadata=json.loads(row["metadata"]),
    )


# ---------------------------------------------------------------------------
# SQLiteExperienceStore
# ---------------------------------------------------------------------------


class SQLiteExperienceStore:
    """ExperienceStore Protocol'ünü SQLite üzerinde uygular (append-only).

    Kullanım:
        store = SQLiteExperienceStore("/path/to/memory.db")
        stored = store.add(experience)

    Not: `experience.assistant_response` şu anki üretim ardışık düzeninde
    (build_experience_from_turn yalnızca başarılı, boş olmayan bir nihai
    cevaptan sonra çağrılır) her zaman dolu bir metindir; `experiences`
    tablosundaki `assistant_response` sütunu buna göre NOT NULL'dur.
    """

    def __init__(self, db_path: str) -> None:
        """
        Args:
            db_path: SQLite dosyasının yolu. SQLiteMemoryStore ile aynı
                dosya kullanılabilir — iki sınıf birbirinden bağımsız
                şekilde kendi tablolarını yönetir. ":memory:" test amaçlı
                kullanılabilir.
        """
        self._db_path = db_path
        self._ensure_dir()
        self._initialize_schema()
        logger.info("experience_store_initialized", extra={"db_path": db_path})

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
        return conn

    def _initialize_schema(self) -> None:
        """`experiences` tablosunu ve indekslerini henüz yoksa oluşturur.

        SQLiteMemoryStore'un tablolarına hiç dokunmaz — yalnızca kendi
        DDL'ini çalıştırır. Aynı dosyada SQLiteMemoryStore'dan önce veya
        sonra çağrılması sonucu değiştirmez (idempotent, sıra bağımsız).
        """
        with self._connect() as conn:
            for ddl in _ALL_DDL:
                conn.executescript(ddl)
            conn.commit()

    # ------------------------------------------------------------------
    # Yazma
    # ------------------------------------------------------------------

    def add(self, experience: Experience) -> Experience:
        """Yeni bir Experience ekler (ekle-yalnızca — güncelleme/silme yok)."""
        persisted_at = datetime.now(UTC)
        sql = """
        INSERT INTO experiences
            (id, session_id, occurred_at, user_message, assistant_response,
             tool_calls, user_state, emotional_context, outcome,
             derived_memory_ids, metadata, persisted_at)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            experience.id,
            experience.session_id,
            _dt_to_str(experience.occurred_at),
            experience.user_message,
            experience.assistant_response,
            json.dumps(experience.tool_calls, ensure_ascii=False),
            (
                json.dumps(experience.user_state, ensure_ascii=False)
                if experience.user_state is not None
                else None
            ),
            (
                json.dumps(experience.emotional_context, ensure_ascii=False)
                if experience.emotional_context is not None
                else None
            ),
            experience.outcome.value,
            json.dumps(experience.derived_memory_ids, ensure_ascii=False),
            json.dumps(experience.metadata, ensure_ascii=False, default=str),
            _dt_to_str(persisted_at),
        )
        with self._connect() as conn:
            conn.execute(sql, params)
            conn.commit()
        logger.debug("experience_added", extra={"experience_id": experience.id})
        return experience

    # ------------------------------------------------------------------
    # Okuma
    # ------------------------------------------------------------------

    def get(self, experience_id: str) -> Experience | None:
        """Kimliğe göre tek bir Experience döndürür; bulunamazsa None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM experiences WHERE id = ?", (experience_id,)
            ).fetchone()
        return _row_to_experience(row) if row else None

    def list_by_session(self, session_id: str, *, limit: int = 50) -> list[Experience]:
        """Bir oturuma ait deneyimleri, occurred_at artan sırayla döndürür."""
        sql = "SELECT * FROM experiences WHERE session_id = ? ORDER BY occurred_at ASC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(sql, (session_id, limit)).fetchall()
        return [_row_to_experience(r) for r in rows]

    def list_recent(
        self,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[Experience]:
        """En son deneyimleri occurred_at azalan sırayla döndürür.

        `before` verilirse, yalnızca o zamandan kesinlikle önce gerçekleşen
        deneyimler döner (sayfalama için).
        """
        if before is not None:
            sql = (
                "SELECT * FROM experiences WHERE occurred_at < ? "
                "ORDER BY occurred_at DESC LIMIT ?"
            )
            params: tuple[object, ...] = (_dt_to_str(before), limit)
        else:
            sql = "SELECT * FROM experiences ORDER BY occurred_at DESC LIMIT ?"
            params = (limit,)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_experience(r) for r in rows]

    # ------------------------------------------------------------------
    # Yardımcı (Protocol'ün parçası değil — test/gözlem kolaylığı)
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Toplam deneyim sayısını döndürür (ekle-yalnızca olduğundan
        silinen/geçersizleştirilen kayıt kavramı yoktur)."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM experiences").fetchone()
        return row[0] if row else 0
