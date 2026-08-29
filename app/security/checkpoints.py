"""Ajanın yaptığı dosya değişikliklerinin geri alınabilmesi.

Checkpoint için git KULLANILMAZ. Üç gerekçesi var: çalışma dizini bir git
deposu olmayabilir; commit oluşturmak kullanıcının geçmişini kirletir; ve
`git stash` paylaşılan bir yığındır — başka bir süreç araya girerse yanlış
şeyi geri alırız. Bunun yerine, bir dosya değiştirilmeden ÖNCEKİ hâli
kaydedilir.

Kayıtlar kalıcıdır. Geri alma imkânının sunucu yeniden başladığında
kaybolması, hiç olmamasıyla neredeyse aynı kapıya çıkardı.

Her onaylanmış değişiklik kendi checkpoint'ini oluşturur; tur bazlı
gruplama, çok adımlı çalıştırmalar ortaya çıktığında anlam kazanacak.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_BYTES = 1024 * 1024
"""Anlık görüntüsü saklanacak en büyük dosya.

Bundan büyüğü kaydedilmez ve checkpoint geri alınamaz olarak işaretlenir.
Sessizce atlamak, kullanıcının var sandığı bir geri dönüşün aslında
olmaması demek olurdu.
"""


class CheckpointError(RuntimeError):
    """Checkpoint akışındaki kontrollü hataların tabanı."""


class CheckpointNotFoundError(CheckpointError):
    """Verilen kimlikte bir checkpoint yok."""


class CheckpointNotRestorableError(CheckpointError):
    """Checkpoint kaydedilemediği için geri alınamaz."""


class Checkpoint(BaseModel):
    """Tek bir dosyanın değiştirilmeden önceki hâli."""

    checkpoint_id: str
    created_at: datetime
    path: str
    """Çalışma köküne göreli yol."""

    existed: bool
    """Dosya değişiklikten önce var mıydı. False ise geri alma onu siler."""

    content: str | None = None
    restorable: bool = True
    session_id: str | None = None
    reason: str | None = None


class ChangeJournal(Protocol):
    """Bir dosya değiştirilmeden önce haber verilen sözleşme.

    Yazma araçları bunu bilir; checkpoint'in nasıl saklandığını bilmez.
    """

    def record(self, path: Path, *, session_id: str | None = None, reason: str | None = None) -> Checkpoint | None:
        """Dosyanın mevcut hâlini kaydeder ve checkpoint'i döndürür."""
        ...


_DDL_CHECKPOINTS = """
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    path          TEXT NOT NULL,
    existed       INTEGER NOT NULL,
    content       TEXT,
    restorable    INTEGER NOT NULL DEFAULT 1,
    session_id    TEXT,
    reason        TEXT,
    restored_at   TEXT
);
"""

_DDL_IDX_CREATED = """
CREATE INDEX IF NOT EXISTS idx_checkpoints_created_at
    ON checkpoints (created_at DESC);
"""


class SQLiteCheckpointStore:
    """Değişiklik öncesi hâlleri kalıcı olarak saklar ve geri yükler."""

    def __init__(
        self,
        db_path: str,
        *,
        root: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """
        Args:
            db_path: SQLite dosyasının yolu.
            root: Çalışma kökü. Yollar buna göre göreli saklanır ve geri
                yükleme yalnızca bu ağacın içine yazabilir.
            clock: Zaman kaynağı; testler için enjekte edilebilir.
        """
        self._db_path = db_path
        self._root = root.resolve()
        self._clock = clock
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
            conn.execute(_DDL_CHECKPOINTS)
            conn.execute(_DDL_IDX_CREATED)

    # ── kayıt ────────────────────────────────────────────────

    def record(
        self,
        path: Path,
        *,
        session_id: str | None = None,
        reason: str | None = None,
    ) -> Checkpoint | None:
        """Dosyanın değişiklikten önceki hâlini kaydeder.

        Var olmayan bir dosya da kaydedilir: geri alma onu silmelidir,
        çünkü değişiklikten önce yoktu.
        """
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self._root).as_posix()
        except ValueError:
            logger.warning("checkpoint_outside_root")
            return None

        existed = resolved.is_file()
        content: str | None = None
        restorable = True

        if existed:
            try:
                size = resolved.stat().st_size
                if size > MAX_SNAPSHOT_BYTES:
                    restorable = False
                else:
                    content = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # Okunamayan bir dosyanın geri alınabilir olduğunu iddia
                # etmemek, sessizce başarısız olmaktan iyidir.
                restorable = False

        checkpoint = Checkpoint(
            checkpoint_id=uuid4().hex,
            created_at=self._clock(),
            path=relative,
            existed=existed,
            content=content,
            restorable=restorable,
            session_id=session_id,
            reason=reason,
        )
        self._insert(checkpoint)
        return checkpoint

    def _insert(self, checkpoint: Checkpoint) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (
                    checkpoint_id, created_at, path, existed, content,
                    restorable, session_id, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.created_at.isoformat(),
                    checkpoint.path,
                    int(checkpoint.existed),
                    checkpoint.content,
                    int(checkpoint.restorable),
                    checkpoint.session_id,
                    checkpoint.reason,
                ),
            )

    # ── okuma ────────────────────────────────────────────────

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,)
            ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    def recent(self, *, limit: int = 20, session_id: str | None = None) -> list[Checkpoint]:
        query = "SELECT * FROM checkpoints"
        params: list[object] = []
        if session_id is not None:
            query += " WHERE session_id = ?"
            params.append(session_id)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_checkpoint(row) for row in rows]

    # ── geri alma ────────────────────────────────────────────

    def restore(self, checkpoint_id: str) -> Checkpoint:
        """Dosyayı checkpoint'teki hâline döndürür.

        Raises:
            CheckpointNotFoundError: Böyle bir kayıt yok.
            CheckpointNotRestorableError: İçerik kaydedilememişti.
            CheckpointError: Dosya sistemi işlemi başarısız olduysa.
        """
        checkpoint = self.get(checkpoint_id)
        if checkpoint is None:
            raise CheckpointNotFoundError("Böyle bir checkpoint yok.")
        if not checkpoint.restorable:
            raise CheckpointNotRestorableError(
                "Bu değişikliğin öncesi kaydedilemedi; geri alınamaz."
            )

        target = (self._root / checkpoint.path).resolve()
        # Kayıt köke göreli tutulur; yine de yazmadan önce doğrulanır.
        if target != self._root and self._root not in target.parents:
            raise CheckpointError("Checkpoint yolu çalışma dizininin dışında.")

        try:
            if checkpoint.existed:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(checkpoint.content or "", encoding="utf-8")
            elif target.exists():
                # Değişiklikten önce yoktu; geri almak onu kaldırmak demek.
                target.unlink()
        except OSError as exc:
            raise CheckpointError("Geri alma sırasında dosya yazılamadı.") from exc

        self._mark_restored(checkpoint_id)
        return checkpoint

    def _mark_restored(self, checkpoint_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE checkpoints SET restored_at = ? WHERE checkpoint_id = ?",
                (self._clock().isoformat(), checkpoint_id),
            )

    @staticmethod
    def _row_to_checkpoint(row: sqlite3.Row) -> Checkpoint:
        return Checkpoint(
            checkpoint_id=row["checkpoint_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            path=row["path"],
            existed=bool(row["existed"]),
            content=row["content"],
            restorable=bool(row["restorable"]),
            session_id=row["session_id"],
            reason=row["reason"],
        )
