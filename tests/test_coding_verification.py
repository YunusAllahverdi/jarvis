"""Kodlama döngüsü — doğrulama, sonucu bir modele değil çıkış koduna sorar.

Kapsam:
 1. Sıfır çıkış kodu geçti demektir
 2. Sıfır olmayan çıkış kodu geçmedi demektir ve teşhis üretilir
 3. Çıktının iyimser içeriği çıkış kodunu geçersiz kılamaz
 4. Zaman aşımı başarı sayılmaz
 5. Komut yoksa doğrulama çalışmaz ve başarı sayılmaz
 6. Araç kayıtlı değilse doğrulama çalışmaz
 7. Onay bekleyen doğrulama başarısızlık DEĞİL, çalışmamış sayılır
 8. Doğrulama mevcut yürütme sınırını kullanır
 9. Doğrulama hiçbir durumda istisna sızdırmaz
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import Field

from app.coding.verification import (
    SKIP_NEEDS_APPROVAL,
    SKIP_NO_COMMAND,
    SKIP_TOOL_MISSING,
    Verifier,
)
from app.security.permissions import ToolPermissionPolicy
from app.tools.base import PermissionLevel, Tool, ToolInput
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class _RunCommandInput(ToolInput):
    command: str = Field(min_length=1)
    timeout_seconds: float = 60.0


def _command_tool(result: dict[str, Any], *, permission=PermissionLevel.READ) -> Tool:
    class _FakeRunCommandTool(Tool[_RunCommandInput]):
        name = "run_command"
        description = "Komut çalıştırır."
        input_model = _RunCommandInput

        async def execute(self, tool_input: _RunCommandInput) -> dict[str, Any]:
            return {
                "command": tool_input.command,
                "exit_code": result.get("exit_code", 0),
                "timed_out": result.get("timed_out", False),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "truncated": False,
            }

    _FakeRunCommandTool.permission = permission
    return _FakeRunCommandTool()


def _verifier(*tools: Tool, allow_dangerous: bool = True) -> Verifier:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    policy = ToolPermissionPolicy(
        allowed={PermissionLevel.READ},
        requires_approval=({PermissionLevel.DANGEROUS} if allow_dangerous else set()),
    )
    return Verifier(tool_executor=ToolExecutor(registry, policy=policy))


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_zero_exit_code_passes() -> None:
    verification = _run(_verifier(_command_tool({"exit_code": 0})).verify("pytest -q"))

    assert verification.ran is True
    assert verification.passed is True
    assert verification.diagnosis is None


def test_non_zero_exit_code_fails_with_a_diagnosis() -> None:
    verification = _run(
        _verifier(
            _command_tool({"exit_code": 1, "stdout": "FAILED tests/t.py::x - boom"})
        ).verify("pytest -q")
    )

    assert verification.passed is False
    assert verification.diagnosis is not None
    assert verification.exit_code == 1


def test_optimistic_output_cannot_override_the_exit_code() -> None:
    """"Her şey yolunda" diyen bir çıktı, sıfır olmayan çıkış kodunu geçersiz kılamaz."""
    verification = _run(
        _verifier(
            _command_tool({"exit_code": 2, "stdout": "All tests passed! Everything is fine."})
        ).verify("pytest -q")
    )

    assert verification.passed is False


def test_timeout_is_not_success() -> None:
    verification = _run(
        _verifier(_command_tool({"exit_code": 0, "timed_out": True})).verify("pytest -q")
    )

    assert verification.passed is False
    assert verification.timed_out is True


def test_missing_command_does_not_run() -> None:
    verification = _run(_verifier(_command_tool({"exit_code": 0})).verify(None))

    assert verification.ran is False
    assert verification.passed is False
    assert verification.skipped_reason == SKIP_NO_COMMAND


def test_unregistered_tool_does_not_run() -> None:
    verification = _run(_verifier().verify("pytest -q"))

    assert verification.ran is False
    assert verification.skipped_reason == SKIP_TOOL_MISSING


def test_pending_approval_is_not_a_failure() -> None:
    """Çalıştırılmamış bir testin sonucu yoktur; başarısızlık sayılamaz."""
    verification = _run(
        _verifier(
            _command_tool({"exit_code": 0}, permission=PermissionLevel.DANGEROUS)
        ).verify("pytest -q")
    )

    assert verification.ran is False
    assert verification.passed is False
    assert verification.skipped_reason == SKIP_NEEDS_APPROVAL


def test_denied_permission_does_not_run() -> None:
    verification = _run(
        _verifier(
            _command_tool({"exit_code": 0}, permission=PermissionLevel.DANGEROUS),
            allow_dangerous=False,
        ).verify("pytest -q")
    )

    assert verification.ran is False
    assert verification.passed is False


def test_verification_never_raises() -> None:
    class _ExplodingExecutor:
        policy = ToolPermissionPolicy(allowed={PermissionLevel.READ})
        registry = ToolRegistry()

        async def execute(self, call, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    verifier = Verifier(tool_executor=_ExplodingExecutor())  # type: ignore[arg-type]
    verification = _run(verifier.verify("pytest -q"))

    assert verification.ran is False
    assert verification.passed is False
