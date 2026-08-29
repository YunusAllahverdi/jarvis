"""Terminal tool'u — run_command.

Kapsam:
 1. Tanınan komut çalışır ve çıktısını döndürür
 2. Komut çalışma dizininde çalışır
 3. Çıkış kodu taşınır
 4. Tanınmayan komut çalıştırılmaz
 5. Zincirleme denemesi çalıştırılmaz
 6. Zaman aşımı süreci sonlandırır ve bildirilir
 7. Çağıran kendi zaman sınırını yükseltemez
 8. ORTAM DEVRALINMAZ — gizli değişkenler alt sürece geçmez
 9. Araç DANGEROUS izinlidir
10. Terminal kapalıyken araç kaydedilmez
11. Kök veya politika yoksa araç kaydedilmez
12. Terminal kapalıyken DANGEROUS reddedilir, açıkken onaya tabidir
13. Onaysız çalıştırma engellenir
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.core.chat import ToolCall
from app.main import _build_agent_policy
from app.security.commands import CommandPolicy
from app.security.paths import PathGuard
from app.security.permissions import PermissionDecision
from app.tools.base import PermissionLevel, ToolExecutionError
from app.tools.builtin.terminal import RunCommandTool
from app.tools.defaults import register_terminal_tool
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

_SECRET_VARIABLE = "JARVIS_TEST_SECRET"


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "isaret.txt").write_text("burada", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def tool(workspace: Path) -> RunCommandTool:
    # Testler kendi yorumlayıcısını çağırabilsin diye adı listeye eklenir.
    program = Path(sys.executable).stem
    return RunCommandTool(
        guard=PathGuard(workspace),
        command_policy=CommandPolicy(allowed_commands=("python", "python3", program)),
        max_timeout_seconds=10.0,
    )


def _python(code: str) -> str:
    """Tek satırlık bir Python komutu üretir."""

    return f'{Path(sys.executable).stem} -c "{code}"'


# ---------------------------------------------------------------------------
# 1-3. Normal çalışma
# ---------------------------------------------------------------------------

def test_allowed_command_runs_and_returns_output(tool: RunCommandTool) -> None:
    """Komut çalışmalı ve çıktısı taşınmalı."""
    result = _run(tool.execute(tool.input_model(command=_python("print('selam')"))))

    assert result["exit_code"] == 0
    assert "selam" in result["stdout"]
    assert result["timed_out"] is False


def test_command_runs_in_the_workspace(tool: RunCommandTool, workspace: Path) -> None:
    """Çalışma dizini bekçinin kökü olmalı."""
    result = _run(
        tool.execute(
            tool.input_model(command=_python("import os; print(os.listdir('.'))"))
        )
    )

    assert "isaret.txt" in result["stdout"]


def test_exit_code_is_reported(tool: RunCommandTool) -> None:
    """Başarısız komut sessizce başarılı görünmemeli."""
    result = _run(tool.execute(tool.input_model(command=_python("raise SystemExit(3)"))))

    assert result["exit_code"] == 3


# ---------------------------------------------------------------------------
# 4-5. Politika reddi
# ---------------------------------------------------------------------------

def test_unknown_command_is_not_run(tool: RunCommandTool) -> None:
    """Listede olmayan program çalıştırılmamalı."""
    with pytest.raises(ToolExecutionError):
        _run(tool.execute(tool.input_model(command="rm -rf /")))


def test_chaining_is_not_run(tool: RunCommandTool) -> None:
    """Zincirleme denemesi reddedilmeli."""
    with pytest.raises(ToolExecutionError):
        _run(tool.execute(tool.input_model(command="python --version ; rm -rf /")))


# ---------------------------------------------------------------------------
# 6-7. Zaman sınırı
# ---------------------------------------------------------------------------

def test_timeout_stops_the_process_and_is_reported(tool: RunCommandTool) -> None:
    """Süresi dolan komut sonlandırılmalı ve bu bildirilmeli."""
    result = _run(
        tool.execute(
            tool.input_model(
                command=_python("import time; time.sleep(30)"), timeout_seconds=1
            )
        )
    )

    assert result["timed_out"] is True


def test_caller_cannot_raise_its_own_limit(workspace: Path) -> None:
    """Model kendi zaman sınırını yükseltememeli."""
    program = Path(sys.executable).stem
    tool = RunCommandTool(
        guard=PathGuard(workspace),
        command_policy=CommandPolicy(allowed_commands=(program,)),
        max_timeout_seconds=1.0,
    )

    result = _run(
        tool.execute(
            tool.input_model(
                command=_python("import time; time.sleep(30)"), timeout_seconds=600
            )
        )
    )

    assert result["timed_out"] is True, "üst sınır uygulanmalıydı"


# ---------------------------------------------------------------------------
# 8. Ortam yalıtımı
# ---------------------------------------------------------------------------

def test_secrets_do_not_reach_the_child_process(
    tool: RunCommandTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ebeveynin ortamındaki gizli değer alt sürece GEÇMEMELİ.

    `.env` okumasını engellemenin anlamı, çalışan bir programın aynı değeri
    ortamdan okuyabilmesi hâlinde kalmazdı.
    """
    monkeypatch.setenv(_SECRET_VARIABLE, "cok-gizli-deger")
    assert os.environ[_SECRET_VARIABLE] == "cok-gizli-deger"

    result = _run(
        tool.execute(
            tool.input_model(
                command=_python(
                    f"import os; print(os.environ.get('{_SECRET_VARIABLE}', 'YOK'))"
                )
            )
        )
    )

    assert "cok-gizli-deger" not in result["stdout"]
    assert "YOK" in result["stdout"]


# ---------------------------------------------------------------------------
# 9-11. Kayıt ve izin seviyesi
# ---------------------------------------------------------------------------

def test_tool_is_dangerous(tool: RunCommandTool) -> None:
    """Komut çalıştırmak en yüksek risk seviyesinde olmalı."""
    assert tool.permission is PermissionLevel.DANGEROUS


def test_disabled_terminal_registers_nothing(workspace: Path) -> None:
    """Terminal kapalıyken araç hiç var olmamalı."""
    registry = ToolRegistry()

    registered = register_terminal_tool(
        registry,
        guard=PathGuard(workspace),
        command_policy=CommandPolicy(),
        enabled=False,
    )

    assert registered == []
    assert registry.list_tools() == []


def test_missing_prerequisites_register_nothing(workspace: Path) -> None:
    """Kök ya da politika eksikse araç kaydedilmemeli."""
    assert register_terminal_tool(ToolRegistry(), guard=None, enabled=True) == []
    assert (
        register_terminal_tool(
            ToolRegistry(), guard=PathGuard(workspace), command_policy=None, enabled=True
        )
        == []
    )


# ---------------------------------------------------------------------------
# 12-13. İzin duruşu
# ---------------------------------------------------------------------------

def _settings(**kwargs: object) -> Settings:
    defaults = dict(app_name="T", app_version="t", environment="test", ollama_model="x")
    defaults.update(kwargs)
    return Settings(**defaults)


def test_dangerous_is_refused_until_the_terminal_is_enabled() -> None:
    """Terminal kapalıyken DANGEROUS reddedilmeli, açıkken onaya tabi olmalı.

    Aradaki fark önemli: reddedilen bir seviye, kullanıcının yanlışlıkla
    onaylayarak açabileceği bir şey değildir.
    """
    closed = _build_agent_policy(_settings())
    assert closed.decide(PermissionLevel.DANGEROUS) is PermissionDecision.DENY

    opened = _build_agent_policy(_settings(terminal_enabled=True))
    assert opened.decide(PermissionLevel.DANGEROUS) is PermissionDecision.REQUIRE_APPROVAL


def test_running_without_approval_is_blocked(workspace: Path) -> None:
    """Terminal açık olsa bile onaysız komut çalışmamalı."""
    program = Path(sys.executable).stem
    registry = ToolRegistry()
    register_terminal_tool(
        registry,
        guard=PathGuard(workspace),
        command_policy=CommandPolicy(allowed_commands=(program,)),
        enabled=True,
    )
    executor = ToolExecutor(
        registry, policy=_build_agent_policy(_settings(terminal_enabled=True))
    )

    result = _run(
        executor.execute(ToolCall(name="run_command", arguments={"command": _python("print(1)")}))
    )

    assert result.success is False
    assert result.requires_approval is True
