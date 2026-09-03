"""Notların kalıcı deposu.

Tasarım kararları:
- Silme GERÇEKTİR. Bellek katmanı mantıksal silme kullanır çünkü orada
  "ne zaman neyi biliyordun?" sorusunun cevabı önemlidir. Notta böyle bir
  soru yoktur: kullanıcı bir notu sildiğinde gitmesini bekler.
- Arama FTS değil basit `LIKE`'tır. Notlar onlarca mertebesindedir, binlerce
  değil; FTS5 tablosu bakım maliyeti getirir ve burada ölçülebilir bir şey
  kazandırmaz.
- Diğer kalıcı depolarla AYNI SQLite dosyası kullanılır.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MAX_TITLE_CHARS = 200
MAX_CONTENT_CHARS = 20_000
"""Bir notun en fazla uzunluğu.

Sınır, notu yazanın ajan olabilmesinden gelir: sınırsız bir alan, tek bir
tur içinde veritabanına sınırsız metin yazılabilmesi demek olurdu.
"""

MAX_NOTES = 500


class Note(BaseModel):
    """Tek bir not."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str = Field(default="", max_length=MAX_TITLE_CHARS)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)

    created_at: datetime
    updated_at: datetime

    created_by: str = "user"
    """Notu kimin yazdığı: "user" veya "agent".

    Kaydedilmesi bilinçlidir: kullanıcı, kendi yazdığı bir notla ajanın
    yazdığını ayırt edebilmelidir. Ajanın yazdığı bir not, ajanın o anki
    anlayışını taşır ve yanlış olabilir.
    """

    session_id: str | None = None


class NoteListResponse(BaseModel):
    """Not listesi yanıtı."""

    notes: list[Note] = Field(default_factory=list)
    count: int = 0


_DDL_NOTES = """
CREATE TABLE IF NOT EXISTS notes (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    created_by  TEXT NOT NULL DEFAULT 'user',
    session_id  TEXT
);
"""

_DDL_IDX_UPDATED = """
CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes (updated_at DESC);
"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


class NoteStore:
    """Notları kalıcı olarak saklar."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = RLock()
        self._ensure_dir()
        self._initialize_schema()

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
        with self._connect() as conn:
            conn.execute(_DDL_NOTES)
            conn.execute(_DDL_IDX_UPDATED)
        logger.info("note_store_initialized", extra={"db_path": self._db_path})

    # ------------------------------------------------------------------
    # Okuma
    # ------------------------------------------------------------------

    def list(self, *, query: str = "", limit: int = 50) -> list[Note]:
        """Notları en son güncellenenden başlayarak döndürür.

        `query` verilirse başlık ve içerikte arar. Arama ile listeleme aynı
        metottadır: ikisi de "hangi notlar var?" sorusunun cevabıdır.
        """
        limit = max(1, min(limit, MAX_NOTES))
        with self._lock, self._connect() as conn:
            if query.strip():
                pattern = f"%{query.strip()}%"
                rows = conn.execute(
                    """
                    SELECT * FROM notes
                    WHERE title LIKE ? OR content LIKE ?
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (pattern, pattern, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notes ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [_row_to_note(row) for row in rows]

    def get(self, note_id: str) -> Note | None:
        """Tek bir notu döndürür; yoksa None."""
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return _row_to_note(row) if row is not None else None

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"])

    # ------------------------------------------------------------------
    # Yazma
    # ------------------------------------------------------------------

    def add(
        self,
        *,
        content: str,
        title: str = "",
        created_by: str = "user",
        session_id: str | None = None,
    ) -> Note:
        """Yeni bir not ekler.

        Raises:
            ValueError: Not sınırı dolduysa. Sessizce en eskiyi silmek,
                kullanıcının yazdığı bir notu haber vermeden yok etmek
                olurdu.
        """
        now = _utcnow()
        note = Note(
            title=title.strip()[:MAX_TITLE_CHARS],
            content=content.strip()[:MAX_CONTENT_CHARS],
            created_at=now,
            updated_at=now,
            created_by=created_by,
            session_id=session_id,
        )
        with self._lock:
            if self.count() >= MAX_NOTES:
                raise ValueError(f"En fazla {MAX_NOTES} not saklanabilir.")
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO notes
                        (id, title, content, created_at, updated_at, created_by, session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note.id,
                        note.title,
                        note.content,
                        note.created_at.isoformat(),
                        note.updated_at.isoformat(),
                        note.created_by,
                        note.session_id,
                    ),
                )
        logger.info(
            "note_added", extra={"note_id": note.id, "created_by": created_by}
        )
        return note

    def update(self, note_id: str, *, content: str, title: str | None = None) -> Note | None:
        """Bir notu günceller; kayıt yoksa None."""
        existing = self.get(note_id)
        if existing is None:
            return None

        now = _utcnow()
        new_title = existing.title if title is None else title.strip()[:MAX_TITLE_CHARS]
        new_content = content.strip()[:MAX_CONTENT_CHARS]

        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE notes SET title = ?, content = ?, updated_at = ? WHERE id = ?",
                (new_title, new_content, now.isoformat(), note_id),
            )
        return existing.model_copy(
            update={"title": new_title, "content": new_content, "updated_at": now}
        )

    def delete(self, note_id: str) -> bool:
        """Notu KALICI olarak siler. Kayıt yoksa False."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        removed = cursor.rowcount > 0
        if removed:
            logger.info("note_deleted", extra={"note_id": note_id})
        return removed


def _row_to_note(row: sqlite3.Row) -> Note:
    return Note(
        id=row["id"],
        title=row["title"],
        content=row["content"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        created_by=row["created_by"],
        session_id=row["session_id"],
    )
