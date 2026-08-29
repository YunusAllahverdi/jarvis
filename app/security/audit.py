"""Ajanın yaptıklarının değiştirilemez kaydı.

Denetim kaydı iki soruyu cevaplamak içindir: *ne oldu* ve *neden izin
verildi*. Bu yüzden yalnızca başarılı eylemler değil, reddedilenler ve
onay bekleyenler de yazılır — bir saldırının izi çoğu zaman başarısız
denemelerdedir.

Kayıt yalnızca eklenir. Güncelleme ve silme arayüzü bilerek yoktur:
sonradan düzenlenebilen bir denetim kaydı, denetim kaydı değildir.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import deque
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.security.permissions import PermissionDecision
from app.security.redaction import redact_arguments
from app.tools.base import PermissionLevel

logger = logging.getLogger(__name__)


class AuditAction(StrEnum):
    """Kaydedilen olayın türü."""

    TOOL_CALL = "TOOL_CALL"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"


class AuditOutcome(StrEnum):
    """Olayın sonucu."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    BLOCKED = "BLOCKED"
    """İzin politikası çalıştırmayı engelledi."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    """Çalıştırılmadı; kullanıcı onayı bekleniyor."""


class AuditEvent(BaseModel):
    """Tek bir denetlenebilir olay.

    `arguments` alanı model doğrulamasında maskelenir. Bu bilerek burada
    yapılır: olayı kimin, nereden oluşturduğundan bağımsız olarak
    maskelenmemiş bir argümanın kayda girmesi mümkün olmasın.
    """

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    action: AuditAction
    outcome: AuditOutcome

    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    permission: PermissionLevel | None = None
    decision: PermissionDecision | None = None

    session_id: str | None = None
    approval_id: str | None = None
    error_code: str | None = None
    duration_ms: float | None = None

    @field_validator("arguments")
    @classmethod
    def _mask_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        return redact_arguments(value)


class AuditLog(Protocol):
    """Denetim kaydının sözleşmesi — yalnızca yazma ve okuma."""

    def record(self, event: AuditEvent) -> None:
        """Olayı kalıcı olarak ekler."""
        ...

    def recent(self, *, limit: int = 50, session_id: str | None = None) -> list[AuditEvent]:
        """En yeniden eskiye doğru olayları döndürür."""
        ...


class InMemoryAuditLog:
    """Süreç ömrü boyunca yaşayan, sınırlı kapasiteli kayıt.

    Varsayılan olarak bu kullanılır: kalıcı kayıt bir dosya yolu
    gerektirir ve testlerin ya da geçici kurulumların diske yazması
    beklenmemelidir. Kapasite dolunca en eski olay düşer.
    """

    def __init__(self, *, capacity: int = 1000) -> None:
        if capacity <= 0:
            raise ValueError("capacity pozitif olmalıdır.")
        self._events: deque[AuditEvent] = deque(maxlen=capacity)
        self._lock = RLock()

    def record(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def recent(self, *, limit: int = 50, session_id: str | None = None) -> list[AuditEvent]:
        with self._lock:
            events = list(self._events)
        selected = [e for e in reversed(events) if session_id is None or e.session_id == session_id]
        return selected[:limit]


_DDL_EVENTS = """
CREATE TABLE IF NOT EXISTS audit_events (
    event_id    TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    action      TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    tool_name   TEXT,
    arguments   TEXT NOT NULL DEFAULT '{}',
    permission  TEXT,
    decision    TEXT,
    session_id  TEXT,
    approval_id TEXT,
    error_code  TEXT,
    duration_ms REAL
);
"""

_DDL_IDX_OCCURRED = """
CREATE INDEX IF NOT EXISTS idx_audit_occurred_at
    ON audit_events (occurred_at DESC);
"""

_DDL_IDX_SESSION = """
CREATE INDEX IF NOT EXISTS idx_audit_session
    ON audit_events (session_id)
    WHERE session_id IS NOT NULL;
"""


class SQLiteAuditLog:
    """Yeniden başlatmayı atlatan kalıcı denetim kaydı."""

    def __init__(self, db_path: str) -> None:
        """
        Args:
            db_path: SQLite dosyasının yolu. ":memory:" test amaçlı kullanılabilir.
        """
        self._db_path = db_path
        self._lock = RLock()
        self._ensure_dir()
        self._initialize_schema()
        logger.info("audit_log_initialized", extra={"db_path": db_path})

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
            conn.execute(_DDL_EVENTS)
            conn.execute(_DDL_IDX_OCCURRED)
            conn.execute(_DDL_IDX_SESSION)

    def record(self, event: AuditEvent) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    event_id, occurred_at, action, outcome, tool_name, arguments,
                    permission, decision, session_id, approval_id, error_code, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.occurred_at.isoformat(),
                    str(event.action),
                    str(event.outcome),
                    event.tool_name,
                    json.dumps(event.arguments, ensure_ascii=False, default=str),
                    str(event.permission) if event.permission else None,
                    str(event.decision) if event.decision else None,
                    event.session_id,
                    event.approval_id,
                    event.error_code,
                    event.duration_ms,
                ),
            )

    def recent(self, *, limit: int = 50, session_id: str | None = None) -> list[AuditEvent]:
        query = "SELECT * FROM audit_events"
        params: list[Any] = []
        if session_id is not None:
            query += " WHERE session_id = ?"
            params.append(session_id)
        query += " ORDER BY occurred_at DESC, rowid DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            event_id=row["event_id"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            action=AuditAction(row["action"]),
            outcome=AuditOutcome(row["outcome"]),
            tool_name=row["tool_name"],
            arguments=json.loads(row["arguments"]),
            permission=PermissionLevel(row["permission"]) if row["permission"] else None,
            decision=PermissionDecision(row["decision"]) if row["decision"] else None,
            session_id=row["session_id"],
            approval_id=row["approval_id"],
            error_code=row["error_code"],
            duration_ms=row["duration_ms"],
        )


def safe_record(audit_log: AuditLog | None, event: AuditEvent) -> None:
    """Kayıt hatası asıl işlemi bozmamalı, ama sessiz de kalmamalı.

    Denetim kaydı yazılamıyorsa bu başlı başına bir bulgudur; yine de
    kullanıcının isteğini düşürmek için bir sebep değildir.
    """
    if audit_log is None:
        return
    try:
        audit_log.record(event)
    except Exception:  # noqa: BLE001
        logger.exception(
            "audit_record_failed",
            extra={"action": str(event.action), "tool_name": event.tool_name},
        )
