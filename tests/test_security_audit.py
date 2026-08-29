"""Güvenlik katmanı — denetim kaydı.

Kapsam:
 1. Başarılı çağrı kaydedilir, süresiyle birlikte
 2. Reddedilen çağrı da kaydedilir — başarısız denemeler iz bırakmalı
 3. Onay bekleyen çağrı kaydedilir
 4. Argümanlar maskelenerek yazılır; gizli değer kayda girmez
 5. Maskeleme model doğrulamasında olur, nasıl oluşturulursa oluşturulsun
 6. Bellek içi kayıt kapasitesi sınırlıdır
 7. recent() en yeniden eskiye sıralar ve oturuma göre süzer
 8. SQLite kaydı yeniden başlatmayı atlatır
 9. Kayıt hatası asıl işlemi düşürmez
10. Uygulama denetim kaydını bellek veritabanıyla AYNI dosyada tutar
11. Onay ve ret kararları kaydedilir
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.approvals import router as approvals_router
from app.config.settings import Settings
from app.core.chat import ToolCall
from app.main import create_app
from app.security.approvals import ApprovalService
from app.security.audit import (
    AuditAction,
    AuditEvent,
    AuditOutcome,
    InMemoryAuditLog,
    SQLiteAuditLog,
    safe_record,
)
from app.security.permissions import PermissionDecision, ToolPermissionPolicy
from app.security.redaction import REDACTED
from app.tools.base import PermissionLevel, Tool, ToolInput
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class _AnyInput(ToolInput):
    path: str = ""
    password: str = ""


class _EchoTool(Tool[_AnyInput]):
    input_model = _AnyInput

    def __init__(self, name: str, permission: PermissionLevel) -> None:
        self.name = name  # type: ignore[misc]
        self.description = f"{name} test aracı."  # type: ignore[misc]
        self.permission = permission  # type: ignore[misc]

    async def execute(self, tool_input: _AnyInput) -> dict[str, Any]:
        return {"path": tool_input.path}


def _executor(
    permission: PermissionLevel = PermissionLevel.READ,
    *,
    policy: ToolPermissionPolicy | None = None,
) -> tuple[ToolExecutor, InMemoryAuditLog]:
    registry = ToolRegistry()
    registry.register(_EchoTool("arac", permission))
    log = InMemoryAuditLog()
    return (
        ToolExecutor(
            registry,
            policy=policy or ToolPermissionPolicy.read_only(),
            audit_log=log,
        ),
        log,
    )


# ---------------------------------------------------------------------------
# 1-3. Her sonuç kaydedilir
# ---------------------------------------------------------------------------

def test_successful_call_is_recorded_with_duration() -> None:
    """Başarılı çağrı, süresiyle birlikte kaydedilmeli."""
    executor, log = _executor()

    _run(executor.execute(ToolCall(name="arac", arguments={"path": "a.txt"}), session_id="s1"))

    (event,) = log.recent()
    assert event.action is AuditAction.TOOL_CALL
    assert event.outcome is AuditOutcome.SUCCESS
    assert event.decision is PermissionDecision.ALLOW
    assert event.session_id == "s1"
    assert event.duration_ms is not None


def test_denied_call_leaves_a_trace() -> None:
    """Reddedilen çağrı da kaydedilmeli; iz başarısız denemelerde olur."""
    executor, log = _executor(PermissionLevel.DANGEROUS)

    _run(executor.execute(ToolCall(name="arac")))

    (event,) = log.recent()
    assert event.outcome is AuditOutcome.BLOCKED
    assert event.decision is PermissionDecision.DENY
    assert event.error_code == "permission_denied"
    assert event.duration_ms is None, "çalışmayan çağrının süresi olmamalı"


def test_pending_approval_is_recorded() -> None:
    """Onay bekleyen çağrı kaydedilmeli."""
    executor, log = _executor(
        PermissionLevel.WRITE,
        policy=ToolPermissionPolicy(
            allowed={PermissionLevel.READ}, requires_approval={PermissionLevel.WRITE}
        ),
    )

    _run(executor.execute(ToolCall(name="arac")))

    (event,) = log.recent()
    assert event.outcome is AuditOutcome.PENDING_APPROVAL
    assert event.decision is PermissionDecision.REQUIRE_APPROVAL


# ---------------------------------------------------------------------------
# 4-5. Maskeleme
# ---------------------------------------------------------------------------

def test_arguments_are_masked_in_the_record() -> None:
    """Gizli argüman denetim kaydına düz metin girmemeli."""
    executor, log = _executor()

    _run(
        executor.execute(
            ToolCall(name="arac", arguments={"path": "a.txt", "password": "hunter2"})
        )
    )

    (event,) = log.recent()
    assert event.arguments["password"] == REDACTED
    assert event.arguments["path"] == "a.txt"


def test_masking_happens_on_the_model_itself() -> None:
    """Olay nasıl oluşturulursa oluşturulsun argüman maskelenmeli."""
    event = AuditEvent(
        action=AuditAction.TOOL_CALL,
        outcome=AuditOutcome.SUCCESS,
        arguments={"api_key": "abc123"},
    )

    assert event.arguments["api_key"] == REDACTED


# ---------------------------------------------------------------------------
# 6-8. Depolar
# ---------------------------------------------------------------------------

def test_in_memory_log_is_bounded() -> None:
    """Kapasite dolunca en eski olay düşmeli."""
    log = InMemoryAuditLog(capacity=2)
    for name in ("a", "b", "c"):
        log.record(
            AuditEvent(action=AuditAction.TOOL_CALL, outcome=AuditOutcome.SUCCESS, tool_name=name)
        )

    assert [e.tool_name for e in log.recent()] == ["c", "b"]


def test_recent_orders_newest_first_and_filters_by_session() -> None:
    """Sıralama ve süzme beklendiği gibi olmalı."""
    log = InMemoryAuditLog()
    for name, session in (("a", "s1"), ("b", "s2"), ("c", "s1")):
        log.record(
            AuditEvent(
                action=AuditAction.TOOL_CALL,
                outcome=AuditOutcome.SUCCESS,
                tool_name=name,
                session_id=session,
            )
        )

    assert [e.tool_name for e in log.recent(session_id="s1")] == ["c", "a"]
    assert len(log.recent(limit=2)) == 2


def test_sqlite_log_survives_a_new_connection(tmp_path: Path) -> None:
    """Kalıcı kayıt yeniden başlatmayı atlatmalı."""
    db = str(tmp_path / "audit.db")
    SQLiteAuditLog(db).record(
        AuditEvent(
            action=AuditAction.TOOL_CALL,
            outcome=AuditOutcome.BLOCKED,
            tool_name="arac",
            arguments={"path": "a.txt"},
            permission=PermissionLevel.WRITE,
            decision=PermissionDecision.DENY,
            error_code="permission_denied",
        )
    )

    reopened = SQLiteAuditLog(db).recent()

    assert len(reopened) == 1
    assert reopened[0].tool_name == "arac"
    assert reopened[0].outcome is AuditOutcome.BLOCKED
    assert reopened[0].decision is PermissionDecision.DENY


# ---------------------------------------------------------------------------
# 9. Dayanıklılık
# ---------------------------------------------------------------------------

class _BrokenLog:
    def record(self, event: AuditEvent) -> None:
        raise RuntimeError("disk dolu")

    def recent(self, *, limit: int = 50, session_id: str | None = None) -> list[AuditEvent]:
        return []


def test_audit_failure_does_not_break_the_call() -> None:
    """Kayıt tutulamıyorsa bile kullanıcının isteği düşmemeli."""
    registry = ToolRegistry()
    registry.register(_EchoTool("arac", PermissionLevel.READ))
    executor = ToolExecutor(
        registry, policy=ToolPermissionPolicy.read_only(), audit_log=_BrokenLog()
    )

    result = _run(executor.execute(ToolCall(name="arac", arguments={"path": "a.txt"})))

    assert result.success is True


def test_safe_record_tolerates_no_log() -> None:
    """Kayıt bağlı değilse sessizce geçilmeli."""
    safe_record(None, AuditEvent(action=AuditAction.TOOL_CALL, outcome=AuditOutcome.SUCCESS))


# ---------------------------------------------------------------------------
# 10-11. Uygulama ve onay entegrasyonu
# ---------------------------------------------------------------------------

def test_audit_shares_the_one_database_file(tmp_path: Path) -> None:
    """Denetim kaydı ayrı bir dosya açmamalı; tek veri dosyası korunmalı."""
    settings = Settings(
        app_name="Test",
        app_version="t",
        environment="test",
        ollama_model="x",
        memory_db_path=str(tmp_path / "memory.db"),
    )
    app = create_app(settings=settings)

    with TestClient(app):
        assert [p.name for p in tmp_path.glob("*.db")] == ["memory.db"]
        assert isinstance(app.state.audit_log, SQLiteAuditLog)


def test_approval_decisions_are_recorded() -> None:
    """Onay ve ret kararları kayda geçmeli."""
    registry = ToolRegistry()
    registry.register(_EchoTool("arac", PermissionLevel.WRITE))
    policy = ToolPermissionPolicy(
        allowed={PermissionLevel.READ}, requires_approval={PermissionLevel.WRITE}
    )
    log = InMemoryAuditLog()
    service = ApprovalService()

    app = FastAPI()
    app.include_router(approvals_router, prefix="/api")
    app.state.approval_service = service
    app.state.approval_executor = ToolExecutor(registry, policy=policy, audit_log=log)
    app.state.audit_log = log
    client = TestClient(app)

    granted = service.request(ToolCall(name="arac"), permission=PermissionLevel.WRITE)
    refused = service.request(ToolCall(name="arac"), permission=PermissionLevel.WRITE)

    client.post(f"/api/approvals/{granted.approval_id}", json={"decision": "approve"})
    client.post(f"/api/approvals/{refused.approval_id}", json={"decision": "reject"})

    actions = {e.action for e in log.recent()}
    assert AuditAction.APPROVAL_GRANTED in actions
    assert AuditAction.APPROVAL_REJECTED in actions
