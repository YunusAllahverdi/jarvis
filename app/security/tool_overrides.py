"""Araç izin override'larının kalıcı (SQLite) deposu.

Kararın KENDİSİ burada verilmez: hangi override'ın kabul edilebilir olduğunu
`app.security.permissions.plan_override` söyler. Bu modül yalnızca kabul
edilmiş kararları saklar ve geri okur — ikinci bir karar mercii kurmaz.

Diğer kalıcı depolarla AYNI dosyayı kullanır (`council_config` deseni):
ikinci bir veritabanı dosyası, yedeklemede unutulabilecek ikinci bir şey
demek olurdu.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from threading import RLock

from app.security.permissions import ToolOverride
from app.tools.base import PermissionLevel

logger = logging.getLogger(__name__)

_DDL_OVERRIDES = """
CREATE TABLE IF NOT EXISTS tool_overrides (
    tool_name   TEXT PRIMARY KEY,
    enabled     INTEGER NOT NULL DEFAULT 1,
    permission  TEXT
);
"""


class ToolOverrideStore:
    """Kullanıcının araç başına kararlarını kalıcı olarak saklar."""

    def __init__(self, db_path: str) -> None:
        """
        Args:
            db_path: SQLite dosyasının yolu. ":memory:" verilirse bağlantı
                açık tutulur; aksi hâlde her bağlantı AYRI ve boş bir bellek
                veritabanı görürdü.
        """
        self._db_path = db_path
        self._lock = RLock()
        self._memory_conn: sqlite3.Connection | None = None
        if db_path == ":memory:":
            # Bellek veritabanı bağlantıya özeldir: kapatılırsa şema ve
            # satırlar kaybolur. Bu yüzden tek bir bağlantı açık tutulur.
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
        else:
            self._ensure_dir()
        self._initialize_schema()

    def _ensure_dir(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize_schema(self) -> None:
        conn = self._connect()
        if self._memory_conn is not None:
            conn.execute(_DDL_OVERRIDES)
            conn.commit()
            return
        with conn as managed:
            managed.execute(_DDL_OVERRIDES)

    def list(self) -> list[ToolOverride]:
        """Kayıtlı tüm override'ları araç adına göre sıralı döndürür."""

        with self._lock:
            conn = self._connect()
            rows = conn.execute("SELECT * FROM tool_overrides ORDER BY tool_name").fetchall()
            if self._memory_conn is None:
                conn.close()
        return [self._to_override(row) for row in rows]

    def get(self, tool_name: str) -> ToolOverride | None:
        """Tek bir aracın override'ını döndürür; yoksa None."""

        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM tool_overrides WHERE tool_name = ?", (tool_name,)
            ).fetchone()
            if self._memory_conn is None:
                conn.close()
        return self._to_override(row) if row is not None else None

    def set(self, override: ToolOverride) -> None:
        """Bir override'ı yazar (varsa üzerine)."""

        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO tool_overrides (tool_name, enabled, permission)
                VALUES (?, ?, ?)
                ON CONFLICT(tool_name) DO UPDATE SET
                    enabled = excluded.enabled,
                    permission = excluded.permission
                """,
                (
                    override.tool_name,
                    int(override.enabled),
                    str(override.permission) if override.permission else None,
                ),
            )
            conn.commit()
            if self._memory_conn is None:
                conn.close()
        logger.info(
            "tool_override_saved",
            extra={
                "tool_name": override.tool_name,
                "enabled": override.enabled,
                "permission": str(override.permission) if override.permission else None,
            },
        )

    def delete(self, tool_name: str) -> bool:
        """Bir override'ı siler (aracı beyan edilen hâline döndürür)."""

        with self._lock:
            conn = self._connect()
            cursor = conn.execute("DELETE FROM tool_overrides WHERE tool_name = ?", (tool_name,))
            conn.commit()
            rowcount = cursor.rowcount
            if self._memory_conn is None:
                conn.close()
        return rowcount > 0

    @staticmethod
    def _to_override(row: sqlite3.Row) -> ToolOverride:
        return ToolOverride(
            tool_name=row["tool_name"],
            enabled=bool(row["enabled"]),
            permission=PermissionLevel(row["permission"]) if row["permission"] else None,
        )
