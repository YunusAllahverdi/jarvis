"""Kodlama döngüsü — GERÇEK araçlarla, gerçek dosya sisteminde uçtan uca.

Diğer kodlama testleri sahte araçlar kullanır ve mantığı yalıtır. Bu dosya
tam tersini yapar: gerçek `PathGuard`, gerçek dosya araçları, gerçek komut
politikası ve gerçek terminal aracıyla çalışır. Yalnızca LLM taklit edilir —
çünkü taklit edilmeyen tek şey olamaz: modelin ne döndüreceği belirsizdir ve
belirsiz bir testin geçmesi hiçbir şey kanıtlamaz.

Kapsam:
 1. Bozuk bir dosya gerçekten düzeltilir ve doğrulama gerçekten geçer
 2. Başarısız doğrulamadan sonra düzeltme turu gerçek dosyayı düzeltir
 3. Yol bekçisi, çalışma kökü dışına yazmayı engeller
 4. Onay gerektiren yazma GERÇEKTEN diske dokunmaz
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.coding.loop import CodingLoop
from app.coding.models import CodingStatus
from app.coding.planner import CodingPlanner
from app.coding.verification import Verifier
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.security.approvals import ApprovalService
from app.security.commands import CommandPolicy
from app.security.paths import PathGuard
from app.security.permissions import ToolPermissionPolicy
from app.tools.base import PermissionLevel
from app.tools.defaults import register_filesystem_tools, register_terminal_tool
from app.tools.registry import ToolRegistry
from app.tools.executor import ToolExecutor

_BUGGY_SOURCE = "def add(a, b):\n    return a - b\n"
_FIXED_SOURCE = "def add(a, b):\n    return a + b\n"

_CHECK_SOURCE = (
    # Kaynak DOSYADAN derlenir, `import calc` ile DEĞİL. Sebebi gerçek bir
    # tuzaktır: Python'ın bytecode önbelleği geçerliliği (mtime, boyut)
    # ikilisiyle denetler ve bu testteki üç `calc.py` sürümü de AYNI
    # boyuttadır. `import` kullanılsaydı, döngü dosyayı doğru düzeltmiş
    # olmasına rağmen doğrulama bayat `.pyc`'yi çalıştırıp başarısız olurdu
    # — yani test, döngüyü değil önbelleği ölçerdi.
    "import sys\n"
    "namespace = {}\n"
    "source = open('calc.py', encoding='utf-8').read()\n"
    "exec(compile(source, 'calc.py', 'exec'), namespace)\n"
    "sys.exit(0 if namespace['add'](2, 3) == 5 else 1)\n"
)

_VERIFY_COMMAND = f"{Path(sys.executable).name} check.py"
"""Doğrulama komutu.

`pytest` yerine düz bir Python betiği kullanılır: bu test, kodlama
döngüsünün mekaniğini doğrular, pytest'in kendisini değil. İç içe bir
pytest çalıştırmak testi hem yavaşlatır hem de kırılganlaştırırdı.
"""


class _ScriptedProvider:
    """Sırayla önceden yazılmış cevapları döndüren sahte sağlayıcı."""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        return self._responses.pop(0) if self._responses else "{}"

    async def generate_with_tools(
        self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]
    ) -> LLMResponse:  # pragma: no cover
        raise AssertionError("Döngü generate_with_tools kullanmamalı.")


def _workspace(tmp_path: Path) -> Path:
    """Bozuk bir kaynak ve onu sınayan bir betik içeren çalışma kökü kurar."""
    root = tmp_path / "proje"
    root.mkdir()
    (root / "calc.py").write_text(_BUGGY_SOURCE, encoding="utf-8")
    (root / "check.py").write_text(_CHECK_SOURCE, encoding="utf-8")
    return root


def _task(command: str | None = _VERIFY_COMMAND) -> str:
    return json.dumps(
        {
            "goal": "add() fonksiyonundaki işaret hatasını düzelt.",
            "rationale": "Toplama yerine çıkarma yapılıyor.",
            "files_of_interest": ["calc.py"],
            "verification_command": command,
        }
    )


def _fix_plan(old: str = "return a - b", new: str = "return a + b") -> str:
    return json.dumps(
        {
            "steps": [
                {
                    "tool": "read_file",
                    "arguments": {"path": "calc.py"},
                    "purpose": "Mevcut hâlini gör.",
                },
                {
                    "tool": "edit_file",
                    "arguments": {
                        "path": "calc.py",
                        "old_string": old,
                        "new_string": new,
                    },
                    "purpose": "İşaret hatasını düzelt.",
                },
            ],
            "reason": "Dosya okunmadan değiştirilmez.",
        }
    )


def _build_loop(
    root: Path,
    provider: _ScriptedProvider,
    *,
    write_needs_approval: bool = False,
    approval_service: ApprovalService | None = None,
) -> CodingLoop:
    """GERÇEK araçlarla döngüyü kurar; yalnızca sağlayıcı sahtedir."""
    guard = PathGuard(str(root))
    registry = ToolRegistry()
    register_filesystem_tools(registry, guard=guard, writable=True)
    register_terminal_tool(
        registry, guard=guard, command_policy=CommandPolicy(), enabled=True
    )

    allowed = {PermissionLevel.READ, PermissionLevel.DANGEROUS}
    requires_approval: set[PermissionLevel] = set()
    if write_needs_approval:
        requires_approval.add(PermissionLevel.WRITE)
    else:
        allowed.add(PermissionLevel.WRITE)

    executor = ToolExecutor(
        registry,
        policy=ToolPermissionPolicy(allowed=allowed, requires_approval=requires_approval),
    )
    return CodingLoop(
        planner=CodingPlanner(provider=provider),
        verifier=Verifier(tool_executor=executor, timeout_seconds=60.0),
        tool_executor=executor,
        approval_service=approval_service,
        verification_candidates=(_VERIFY_COMMAND,),
        max_iterations=3,
    )


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_broken_file_is_actually_fixed_and_verified(tmp_path: Path) -> None:
    """Uçtan uca kanıt: dosya gerçekten değişir ve doğrulama gerçekten geçer."""
    root = _workspace(tmp_path)
    loop = _build_loop(root, _ScriptedProvider(_task(), _fix_plan()))

    result = _run(loop.run("add fonksiyonundaki hatayı düzelt"))

    assert result.status is CodingStatus.COMPLETED
    assert (root / "calc.py").read_text(encoding="utf-8") == _FIXED_SOURCE
    assert result.changed_files == ["calc.py"]
    assert result.iterations[-1].verification is not None
    assert result.iterations[-1].verification.passed is True


def test_repair_round_fixes_what_the_first_plan_broke(tmp_path: Path) -> None:
    """İlk plan yanlış düzeltir, doğrulama patlar, düzeltme turu gerçekten toparlar."""
    root = _workspace(tmp_path)
    loop = _build_loop(
        root,
        _ScriptedProvider(
            _task(),
            # Yanlış düzeltme: çarpma. Doğrulama bunu yakalayacak.
            _fix_plan(new="return a * b"),
            # Düzeltme turu doğrusunu yazar.
            _fix_plan(old="return a * b", new="return a + b"),
        ),
    )

    result = _run(loop.run("add fonksiyonundaki hatayı düzelt"))

    assert result.status is CodingStatus.COMPLETED
    assert (root / "calc.py").read_text(encoding="utf-8") == _FIXED_SOURCE
    assert len(result.iterations) == 2
    # İlk turun doğrulaması gerçekten başarısız olmuş olmalı.
    assert result.iterations[0].verification.passed is False
    assert result.iterations[1].repairs is not None


def test_path_guard_blocks_writing_outside_the_workspace(tmp_path: Path) -> None:
    """Çalışma kökü bir sınırdır; plan onu aşamaz."""
    root = _workspace(tmp_path)
    outside = tmp_path / "disarida.py"
    escape_plan = json.dumps(
        {
            "steps": [
                {
                    "tool": "write_file",
                    "arguments": {"path": "../disarida.py", "content": "zararli"},
                    "purpose": "kökün dışına yaz",
                }
            ],
            "reason": "test",
        }
    )
    loop = _build_loop(root, _ScriptedProvider(_task(command=None), escape_plan))

    result = _run(loop.run("dışarı yaz"))

    assert outside.exists() is False
    assert result.iterations[0].outcomes[0].success is False


def test_approval_required_write_never_touches_the_disk(tmp_path: Path) -> None:
    """Onay bekleyen bir yazma, onaylanana kadar dosyaya DOKUNMAMALIDIR."""
    root = _workspace(tmp_path)
    approvals = ApprovalService()
    loop = _build_loop(
        root,
        _ScriptedProvider(_task(), _fix_plan()),
        write_needs_approval=True,
        approval_service=approvals,
    )

    result = _run(loop.run("add fonksiyonundaki hatayı düzelt"))

    assert result.status is CodingStatus.PENDING_APPROVAL
    assert (root / "calc.py").read_text(encoding="utf-8") == _BUGGY_SOURCE
    assert len(result.pending_approval_ids) == 1

    # Kullanıcının onaylayacağı çağrı, gerçekten çalıştırılacak olan çağrıdır.
    record = approvals.get(result.pending_approval_ids[0])
    assert record is not None
    assert record.as_tool_call().arguments["path"] == "calc.py"
