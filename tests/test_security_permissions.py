"""Güvenlik katmanı — araç izin politikası.

Kapsam:
 1. Politika deny-by-default'tur; listelenmeyen seviye reddedilir
 2. Serbest seviye ALLOW döner
 3. Onaylı seviye REQUIRE_APPROVAL döner
 4. Bir seviye hem serbest hem onaylı olamaz
 5. read_only ve deny_all kısayolları beklendiği gibi davranır
 6. Executor serbest aracı çalıştırır
 7. Executor reddedilen aracı çalıştırmaz (permission_denied)
 8. Executor onay bekleyen aracı ÇALIŞTIRMAZ, approval_required döner
 9. Reddedilen ile onay bekleyen sonuç birbirinden ayırt edilebilir
10. Executor'ın geriye dönük allowed_permissions kısayolu korunur
11. Executor iki izin kaynağını birden ya da hiçbirini kabul etmez
12. ContextBuilder onay işaretini aynı politikadan üretir
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.agent.context import ContextBuilder
from app.core.chat import ToolCall
from app.security.permissions import PermissionDecision, ToolPermissionPolicy
from app.tools.base import PermissionLevel, Tool, ToolInput
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class _EmptyInput(ToolInput):
    pass


class _RecordingTool(Tool[_EmptyInput]):
    """Çalıştırıldığını kaydeden, izin seviyesi ayarlanabilir sahte araç."""

    input_model = _EmptyInput

    def __init__(self, name: str, permission: PermissionLevel) -> None:
        self.name = name  # type: ignore[misc]
        self.description = f"{name} test aracı."  # type: ignore[misc]
        self.permission = permission  # type: ignore[misc]
        self.ran = False

    async def execute(self, tool_input: _EmptyInput) -> dict[str, Any]:
        self.ran = True
        return {"ok": True}


def _registry_with(tool: Tool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


# ---------------------------------------------------------------------------
# 1-5. Politika davranışı
# ---------------------------------------------------------------------------

def test_policy_denies_unlisted_levels() -> None:
    """Hiçbir listede geçmeyen seviye reddedilmeli."""
    policy = ToolPermissionPolicy(allowed={PermissionLevel.READ})

    assert policy.decide(PermissionLevel.WRITE) is PermissionDecision.DENY
    assert policy.decide(PermissionLevel.DANGEROUS) is PermissionDecision.DENY


def test_policy_allows_listed_levels() -> None:
    """Serbest listedeki seviye doğrudan çalıştırılabilmeli."""
    policy = ToolPermissionPolicy(allowed={PermissionLevel.READ})

    assert policy.decide(PermissionLevel.READ) is PermissionDecision.ALLOW
    assert policy.is_allowed(PermissionLevel.READ)


def test_policy_requires_approval_for_listed_levels() -> None:
    """Onaylı listedeki seviye onay istemeli, reddedilmemeli."""
    policy = ToolPermissionPolicy(
        allowed={PermissionLevel.READ},
        requires_approval={PermissionLevel.WRITE},
    )

    assert policy.decide(PermissionLevel.WRITE) is PermissionDecision.REQUIRE_APPROVAL
    assert not policy.is_allowed(PermissionLevel.WRITE)


def test_policy_rejects_level_in_both_lists() -> None:
    """Aynı seviye hem serbest hem onaylı olamaz — sessiz varsayım olmasın."""
    with pytest.raises(ValueError):
        ToolPermissionPolicy(
            allowed={PermissionLevel.WRITE},
            requires_approval={PermissionLevel.WRITE},
        )


def test_policy_shortcuts() -> None:
    """read_only yalnızca okumayı açar, deny_all hiçbir şeyi açmaz."""
    read_only = ToolPermissionPolicy.read_only()
    assert read_only.decide(PermissionLevel.READ) is PermissionDecision.ALLOW
    assert read_only.decide(PermissionLevel.WRITE) is PermissionDecision.DENY

    deny_all = ToolPermissionPolicy.deny_all()
    assert deny_all.decide(PermissionLevel.READ) is PermissionDecision.DENY


# ---------------------------------------------------------------------------
# 6-11. Executor entegrasyonu
# ---------------------------------------------------------------------------

def test_executor_runs_allowed_tool() -> None:
    """Serbest araç çalışmalı ve sonucu dönmeli."""
    tool = _RecordingTool("okuyucu", PermissionLevel.READ)
    executor = ToolExecutor(_registry_with(tool), policy=ToolPermissionPolicy.read_only())

    result = _run(executor.execute(ToolCall(name="okuyucu")))

    assert result.success is True
    assert tool.ran is True


def test_executor_denies_unlisted_tool_without_running_it() -> None:
    """Reddedilen araç hiç çalıştırılmamalı."""
    tool = _RecordingTool("yazici", PermissionLevel.WRITE)
    executor = ToolExecutor(_registry_with(tool), policy=ToolPermissionPolicy.read_only())

    result = _run(executor.execute(ToolCall(name="yazici")))

    assert result.success is False
    assert result.error_code == "permission_denied"
    assert result.requires_approval is False
    assert tool.ran is False, "reddedilen araç çalıştırılmamalıydı"


def test_executor_pauses_for_approval_without_running_the_tool() -> None:
    """Onay bekleyen araç, onay alınmadan çalıştırılmamalı."""
    tool = _RecordingTool("yazici", PermissionLevel.WRITE)
    policy = ToolPermissionPolicy(
        allowed={PermissionLevel.READ},
        requires_approval={PermissionLevel.WRITE},
    )
    executor = ToolExecutor(_registry_with(tool), policy=policy)

    result = _run(executor.execute(ToolCall(name="yazici")))

    assert result.success is False
    assert result.requires_approval is True
    assert result.error_code == "approval_required"
    assert tool.ran is False, "onay alınmadan araç çalıştırılmamalıydı"


def test_denied_and_pending_results_are_distinguishable() -> None:
    """Ret ile onay bekleme aynı şey değil; çağıran ikisini ayırabilmeli."""
    denied_tool = _RecordingTool("tehlikeli", PermissionLevel.DANGEROUS)
    pending_tool = _RecordingTool("yazici", PermissionLevel.WRITE)
    registry = ToolRegistry()
    registry.register(denied_tool)
    registry.register(pending_tool)
    executor = ToolExecutor(
        registry,
        policy=ToolPermissionPolicy(
            allowed={PermissionLevel.READ},
            requires_approval={PermissionLevel.WRITE},
        ),
    )

    denied = _run(executor.execute(ToolCall(name="tehlikeli")))
    pending = _run(executor.execute(ToolCall(name="yazici")))

    assert (denied.requires_approval, pending.requires_approval) == (False, True)
    assert denied.error_code != pending.error_code


def test_executor_keeps_allowed_permissions_shorthand() -> None:
    """Mevcut çağrı biçimi bozulmamalı: allowed_permissions hâlâ çalışmalı."""
    tool = _RecordingTool("okuyucu", PermissionLevel.READ)
    executor = ToolExecutor(_registry_with(tool), allowed_permissions={PermissionLevel.READ})

    result = _run(executor.execute(ToolCall(name="okuyucu")))

    assert result.success is True
    assert executor.policy.decide(PermissionLevel.WRITE) is PermissionDecision.DENY


def test_executor_rejects_ambiguous_permission_source() -> None:
    """İzin kaynağı tek olmalı: ikisi birden de, hiçbiri de kabul edilmemeli."""
    registry = ToolRegistry()

    with pytest.raises(ValueError):
        ToolExecutor(
            registry,
            allowed_permissions={PermissionLevel.READ},
            policy=ToolPermissionPolicy.read_only(),
        )

    with pytest.raises(ValueError):
        ToolExecutor(registry)


# ---------------------------------------------------------------------------
# 12. Bağlam entegrasyonu
# ---------------------------------------------------------------------------

def test_context_builder_marks_confirmation_from_policy() -> None:
    """Onay işareti executor ile aynı politikadan gelmeli."""
    registry = ToolRegistry()
    registry.register(_RecordingTool("okuyucu", PermissionLevel.READ))
    registry.register(_RecordingTool("yazici", PermissionLevel.WRITE))

    builder = ContextBuilder(
        tool_registry=registry,
        policy=ToolPermissionPolicy(
            allowed={PermissionLevel.READ},
            requires_approval={PermissionLevel.WRITE},
        ),
    )
    context = builder.build("merhaba", session_id="s1")

    flags = {tool.name: tool.requires_confirmation for tool in context.available_tools}
    assert flags == {"okuyucu": False, "yazici": True}
