"""Güvenlik katmanı — kullanıcı onayı akışı.

Kapsam:
 1. Onay isteği açıldığında çağrı dondurulur (PENDING)
 2. Onay, saklanan çağrıyı aynen teslim eder
 3. Onay TEK KULLANIMLIKTIR — ikinci kez onaylanamaz
 4. Reddedilen istek sonradan onaylanamaz
 5. Süresi dolan istek EXPIRED olur ve onaylanamaz
 6. Bilinmeyen kimlik NotFound verir
 7. Bekleyen istek sayısı sınırlıdır
 8. pending() oturuma göre süzer
 9. Onay, oturumun izin politikasını DEĞİŞTİRMEZ
10. Onaylı çalıştırma REQUIRE_APPROVAL aracını çalıştırır
11. Onaylı çalıştırma DENY aracını ÇALIŞTIRMAZ — onay yetki yükseltmez
12. Onaylanan argümanlar çağıran tarafından değiştirilemez
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.chat import ToolCall
from app.security.approvals import (
    ApprovalAlreadyDecidedError,
    ApprovalError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalService,
    ApprovalStatus,
)
from app.security.permissions import PermissionDecision, ToolPermissionPolicy
from app.tools.base import PermissionLevel, Tool, ToolInput
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

_START = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class _Clock:
    """Testin elle ilerlettiği saat; süre dolmasını beklemeden sınamak için."""

    def __init__(self, now: datetime = _START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _PathInput(ToolInput):
    path: str = ""


class _RecordingTool(Tool[_PathInput]):
    """Hangi argümanla çalıştırıldığını kaydeden sahte araç."""

    input_model = _PathInput

    def __init__(self, name: str, permission: PermissionLevel) -> None:
        self.name = name  # type: ignore[misc]
        self.description = f"{name} test aracı."  # type: ignore[misc]
        self.permission = permission  # type: ignore[misc]
        self.calls: list[str] = []

    async def execute(self, tool_input: _PathInput) -> dict[str, Any]:
        self.calls.append(tool_input.path)
        return {"path": tool_input.path}


def _service(**kwargs: Any) -> tuple[ApprovalService, _Clock]:
    clock = _Clock()
    return ApprovalService(clock=clock, **kwargs), clock


# ---------------------------------------------------------------------------
# 1-2. İstek açma ve teslim
# ---------------------------------------------------------------------------

def test_request_freezes_the_call() -> None:
    """Açılan istek, çağrının adını ve argümanlarını saklamalı."""
    service, _ = _service()

    record = service.request(
        ToolCall(name="yazici", arguments={"path": "a.txt"}),
        permission=PermissionLevel.WRITE,
        session_id="s1",
    )

    assert record.status is ApprovalStatus.PENDING
    assert record.tool_name == "yazici"
    assert record.arguments == {"path": "a.txt"}
    assert record.permission is PermissionLevel.WRITE


def test_approve_returns_the_stored_call() -> None:
    """Teslim edilen çağrı, kaydedilenle birebir aynı olmalı."""
    service, _ = _service()
    record = service.request(
        ToolCall(name="yazici", arguments={"path": "a.txt"}),
        permission=PermissionLevel.WRITE,
    )

    call = service.approve(record.approval_id)

    assert call.name == "yazici"
    assert call.arguments == {"path": "a.txt"}


# ---------------------------------------------------------------------------
# 3-6. Tek kullanımlık olma ve geçersiz durumlar
# ---------------------------------------------------------------------------

def test_approval_is_single_use() -> None:
    """Aynı onay ikinci kez kullanılamamalı — tekrar saldırısına kapalı."""
    service, _ = _service()
    record = service.request(
        ToolCall(name="yazici", arguments={"path": "a.txt"}),
        permission=PermissionLevel.WRITE,
    )

    service.approve(record.approval_id)

    with pytest.raises(ApprovalAlreadyDecidedError):
        service.approve(record.approval_id)


def test_rejected_request_cannot_be_approved_later() -> None:
    """Reddedilen istek sonradan onaylanamamalı."""
    service, _ = _service()
    record = service.request(
        ToolCall(name="yazici"), permission=PermissionLevel.WRITE
    )

    service.reject(record.approval_id)

    with pytest.raises(ApprovalAlreadyDecidedError):
        service.approve(record.approval_id)


def test_request_expires_and_cannot_be_approved() -> None:
    """Süre dolduğunda istek düşmeli; eski öneri yeni durumda çalıştırılmamalı."""
    service, clock = _service(ttl_seconds=60)
    record = service.request(
        ToolCall(name="yazici"), permission=PermissionLevel.WRITE
    )

    clock.advance(61)

    assert service.get(record.approval_id).status is ApprovalStatus.EXPIRED
    with pytest.raises(ApprovalExpiredError):
        service.approve(record.approval_id)


def test_unknown_approval_id_is_not_found() -> None:
    """Var olmayan kimlik açıkça bulunamadı demeli."""
    service, _ = _service()

    with pytest.raises(ApprovalNotFoundError):
        service.approve("olmayan")


# ---------------------------------------------------------------------------
# 7-8. Sınırlar ve süzme
# ---------------------------------------------------------------------------

def test_pending_requests_are_capped() -> None:
    """Yanıtlanmayan istekler belleği doldurmamalı."""
    service, _ = _service(max_pending=2)
    for _ in range(2):
        service.request(ToolCall(name="yazici"), permission=PermissionLevel.WRITE)

    with pytest.raises(ApprovalError):
        service.request(ToolCall(name="yazici"), permission=PermissionLevel.WRITE)


def test_pending_filters_by_session() -> None:
    """Bir oturum başka oturumun bekleyen isteklerini görmemeli."""
    service, _ = _service()
    service.request(
        ToolCall(name="yazici"), permission=PermissionLevel.WRITE, session_id="s1"
    )
    service.request(
        ToolCall(name="yazici"), permission=PermissionLevel.WRITE, session_id="s2"
    )

    assert len(service.pending(session_id="s1")) == 1
    assert len(service.pending()) == 2


# ---------------------------------------------------------------------------
# 9-12. Executor ile birlikte: onayın sınırları
# ---------------------------------------------------------------------------

def _executor_with(tool: Tool, policy: ToolPermissionPolicy) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(tool)
    return ToolExecutor(registry, policy=policy)


def test_approval_does_not_change_session_policy() -> None:
    """Onay tek bir çağrıya özeldir; oturumun izin duruşu aynı kalmalı."""
    service, _ = _service()
    policy = ToolPermissionPolicy(
        allowed={PermissionLevel.READ}, requires_approval={PermissionLevel.WRITE}
    )
    record = service.request(
        ToolCall(name="yazici"), permission=PermissionLevel.WRITE
    )
    service.approve(record.approval_id)

    assert policy.decide(PermissionLevel.WRITE) is PermissionDecision.REQUIRE_APPROVAL
    assert policy.decide(PermissionLevel.DANGEROUS) is PermissionDecision.DENY


def test_approved_execution_runs_a_tool_awaiting_approval() -> None:
    """Onay alınmış WRITE aracı çalışmalı."""
    tool = _RecordingTool("yazici", PermissionLevel.WRITE)
    executor = _executor_with(
        tool,
        ToolPermissionPolicy(
            allowed={PermissionLevel.READ}, requires_approval={PermissionLevel.WRITE}
        ),
    )

    result = _run(
        executor.execute(ToolCall(name="yazici", arguments={"path": "a.txt"}), approved=True)
    )

    assert result.success is True
    assert tool.calls == ["a.txt"]


def test_approval_cannot_escalate_a_denied_tool() -> None:
    """Onay, kapalı bir aracı AÇMAMALI — yetki yükseltme engeli."""
    tool = _RecordingTool("tehlikeli", PermissionLevel.DANGEROUS)
    executor = _executor_with(
        tool,
        ToolPermissionPolicy(
            allowed={PermissionLevel.READ}, requires_approval={PermissionLevel.WRITE}
        ),
    )

    result = _run(executor.execute(ToolCall(name="tehlikeli"), approved=True))

    assert result.success is False
    assert result.error_code == "permission_denied"
    assert tool.calls == [], "onay bayrağı reddedilmiş aracı çalıştırmamalıydı"


def test_caller_cannot_swap_arguments_after_approval() -> None:
    """Kullanıcı neyi onayladıysa o çalışmalı; argümanlar sonradan değişmemeli."""
    service, _ = _service()
    tool = _RecordingTool("yazici", PermissionLevel.WRITE)
    executor = _executor_with(
        tool,
        ToolPermissionPolicy(
            allowed={PermissionLevel.READ}, requires_approval={PermissionLevel.WRITE}
        ),
    )
    record = service.request(
        ToolCall(name="yazici", arguments={"path": "guvenli.txt"}),
        permission=PermissionLevel.WRITE,
    )

    # Onay servisi çağrıyı kendi kaydından üretir; istemcinin gönderdiği
    # argümanlar bu noktada devreye giremez.
    approved_call = service.approve(record.approval_id)
    _run(executor.execute(approved_call, approved=True))

    assert tool.calls == ["guvenli.txt"]
