"""Kodlama döngüsü — uçtan uca davranış ve güvenlik sınırları.

Kapsam:
 1. Doğrulama geçtiğinde COMPLETED
 2. Döngü kendini başarılı ilan edemez: doğrulama yoksa APPLIED_UNVERIFIED
 3. Başarısız doğrulama düzeltme turunu tetikler ve düzelirse COMPLETED
 4. Tur sınırı dolduğunda VERIFICATION_FAILED
 5. Boş düzeltme planı turları erken bitirir
 6. Reddedilen komut için düzeltme turu HARCANMAZ
 7. Onay gerektiren adımda döngü durur ve kalan adımlar çalışmaz
 8. Onay kaydı ÇÖZÜLMÜŞ argümanlarla açılır (karar katmanındaki boşluk kapanır)
 9. Boş plan NO_PLAN üretir
10. Araç yoksa FAILED üretir
11. Adımlar arası başvuru çözülür
12. Çözülemeyen başvuru planı çökertmez
13. Patlayan tool döngüyü çökertmez
14. Değiştirilen dosyalar yalnızca yazma araçlarından toplanır
15. Özet her çıkış yolunda üretilir
16. Döngü ayrı bir yürütme mekanizması icat etmez
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

from pydantic import Field

from app.coding.loop import CodingLoop
from app.coding.models import CodingStatus
from app.coding.planner import CodingPlanner
from app.coding.verification import Verifier
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.security.approvals import ApprovalService
from app.security.permissions import ToolPermissionPolicy
from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Sahte araçlar
# ---------------------------------------------------------------------------


class _ReadInput(ToolInput):
    path: str = Field(min_length=1)


class _ReadTool(Tool[_ReadInput]):
    name = "read_file"
    description = "Dosya okur."
    permission = PermissionLevel.READ
    input_model = _ReadInput

    async def execute(self, tool_input: _ReadInput) -> dict[str, Any]:
        return {"path": tool_input.path, "content": "mevcut içerik"}


class _EditInput(ToolInput):
    path: str = Field(min_length=1)
    new_string: str = ""


class _EditTool(Tool[_EditInput]):
    name = "edit_file"
    description = "Dosyayı değiştirir."
    permission = PermissionLevel.WRITE
    input_model = _EditInput

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, tool_input: _EditInput) -> dict[str, Any]:
        self.calls.append({"path": tool_input.path, "new_string": tool_input.new_string})
        return {"path": tool_input.path, "changed": True}


class _ExplodingTool(Tool[_ReadInput]):
    name = "exploding_tool"
    description = "Her zaman patlar."
    permission = PermissionLevel.READ
    input_model = _ReadInput

    async def execute(self, tool_input: _ReadInput) -> dict[str, Any]:
        raise ToolExecutionError("patladı")


class _RunCommandInput(ToolInput):
    command: str = Field(min_length=1)
    timeout_seconds: float = 60.0


class _FakeRunCommandTool(Tool[_RunCommandInput]):
    """Önceden yazılmış çıkış kodlarını sırayla döndüren sahte terminal."""

    name = "run_command"
    description = "Komut çalıştırır."
    permission = PermissionLevel.READ
    """Testlerde READ: doğrulama komutunun onaya takılması ayrı bir senaryodur."""

    input_model = _RunCommandInput

    def __init__(self, *results: dict[str, Any]) -> None:
        self._results = list(results)
        self.calls: list[str] = []

    async def execute(self, tool_input: _RunCommandInput) -> dict[str, Any]:
        self.calls.append(tool_input.command)
        result = self._results.pop(0) if self._results else {"exit_code": 0, "stdout": ""}
        return {
            "command": tool_input.command,
            "exit_code": result.get("exit_code", 0),
            "timed_out": result.get("timed_out", False),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "truncated": False,
        }


# ---------------------------------------------------------------------------
# Sahte sağlayıcı
# ---------------------------------------------------------------------------


class _ScriptedProvider:
    """Sırayla önceden yazılmış cevapları döndürür.

    İlk cevap görev anlama turuna, sonrakiler plan ve düzeltme turlarına
    gider.
    """

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        self.call_count += 1
        return self._responses.pop(0) if self._responses else "{}"

    async def generate_with_tools(
        self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]
    ) -> LLMResponse:  # pragma: no cover
        raise AssertionError("Döngü generate_with_tools kullanmamalı.")


def _task(command: str | None = "pytest -q") -> str:
    return json.dumps(
        {
            "goal": "Hatayı düzelt.",
            "rationale": "test",
            "files_of_interest": ["app/x.py"],
            "verification_command": command,
        }
    )


def _plan(*steps: dict) -> str:
    return json.dumps({"steps": list(steps), "reason": "test planı"})


def _edit_step(path: str = "app/x.py", new_string: str = "düzeltilmiş") -> dict:
    return {
        "tool": "edit_file",
        "arguments": {"path": path, "new_string": new_string},
        "purpose": "değişikliği uygula",
    }


def _read_step(path: str = "app/x.py") -> dict:
    return {"tool": "read_file", "arguments": {"path": path}, "purpose": "dosyayı oku"}


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _build_loop(
    provider: _ScriptedProvider,
    *,
    tools: Sequence[Tool] = (),
    allow_write: bool = True,
    approval_service: ApprovalService | None = None,
    max_iterations: int = 3,
    verification_candidates: tuple[str, ...] = ("pytest -q",),
) -> CodingLoop:
    """Gerçek registry ve gerçek ToolExecutor ile döngüyü kurar.

    Yürütme sınırı taklit EDİLMEZ: döngünün izin ve şema denetimlerini
    gerçekten o sınırdan geçtiğini doğrulayabilmek için gerçek executor
    kullanılır.
    """
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)

    policy = ToolPermissionPolicy(
        allowed={PermissionLevel.READ},
        requires_approval=({PermissionLevel.WRITE} if allow_write else set()),
    )
    executor = ToolExecutor(registry, policy=policy)
    return CodingLoop(
        planner=CodingPlanner(provider=provider),
        verifier=Verifier(tool_executor=executor),
        tool_executor=executor,
        approval_service=approval_service,
        verification_candidates=verification_candidates,
        max_iterations=max_iterations,
    )


# ---------------------------------------------------------------------------
# Testler
# ---------------------------------------------------------------------------


def test_passing_verification_completes_the_loop() -> None:
    provider = _ScriptedProvider(_task(), _plan(_read_step()))
    loop = _build_loop(
        provider, tools=(_ReadTool(), _FakeRunCommandTool({"exit_code": 0}))
    )

    result = _run(loop.run("bir şey düzelt"))

    assert result.status is CodingStatus.COMPLETED
    assert result.ok is True


def test_loop_cannot_declare_success_without_verification() -> None:
    """Doğrulanmamış bir değişikliği başarılı saymak, olmayan bir güvence vermektir."""
    provider = _ScriptedProvider(_task(command=None), _plan(_read_step()))
    loop = _build_loop(provider, tools=(_ReadTool(),), verification_candidates=())

    result = _run(loop.run("bir şey düzelt"))

    assert result.status is CodingStatus.APPLIED_UNVERIFIED
    assert result.ok is False


def test_failing_verification_triggers_a_repair_round() -> None:
    provider = _ScriptedProvider(
        _task(),
        _plan(_read_step()),
        _plan(_read_step("app/y.py")),
    )
    command_tool = _FakeRunCommandTool(
        {"exit_code": 1, "stdout": "FAILED tests/test_a.py::test_b - AssertionError"},
        {"exit_code": 0},
    )
    loop = _build_loop(provider, tools=(_ReadTool(), command_tool))

    result = _run(loop.run("testi düzelt"))

    assert result.status is CodingStatus.COMPLETED
    assert len(result.iterations) == 2
    assert result.iterations[1].repairs is not None


def test_exhausted_iterations_report_verification_failure() -> None:
    """Üç turda düzelmeyen hata, düzelmiş gibi raporlanmaz."""
    provider = _ScriptedProvider(
        _task(), _plan(_read_step()), _plan(_read_step()), _plan(_read_step())
    )
    failing = {"exit_code": 1, "stdout": "FAILED tests/test_a.py::test_b - boom"}
    command_tool = _FakeRunCommandTool(failing, failing, failing)
    loop = _build_loop(provider, tools=(_ReadTool(), command_tool), max_iterations=3)

    result = _run(loop.run("testi düzelt"))

    assert result.status is CodingStatus.VERIFICATION_FAILED
    assert len(result.iterations) == 3


def test_empty_repair_plan_stops_the_loop_early() -> None:
    provider = _ScriptedProvider(_task(), _plan(_read_step()), _plan())
    failing = {"exit_code": 1, "stdout": "FAILED tests/test_a.py::test_b - boom"}
    loop = _build_loop(
        provider,
        tools=(_ReadTool(), _FakeRunCommandTool(failing, failing, failing)),
        max_iterations=3,
    )

    result = _run(loop.run("testi düzelt"))

    assert result.status is CodingStatus.VERIFICATION_FAILED
    assert len(result.iterations) == 1


def test_rejected_command_does_not_spend_a_repair_round() -> None:
    """Reddedilen komutta düzeltilecek KOD yoktur; yeni tur aynı engele çarpardı."""
    provider = _ScriptedProvider(_task(), _plan(_read_step()))
    # run_command hiç kayıtlı değil: doğrulama çalıştırılamaz.
    loop = _build_loop(provider, tools=(_ReadTool(),))

    result = _run(loop.run("testi düzelt"))

    assert result.status is CodingStatus.APPLIED_UNVERIFIED
    assert len(result.iterations) == 1


def test_approval_stops_the_loop_and_skips_remaining_steps() -> None:
    """Onaylanmamış bir işin yarısı çoktan yapılmış olmamalıdır."""
    provider = _ScriptedProvider(
        _task(), _plan(_edit_step(), _read_step("app/after.py"))
    )
    edit_tool = _EditTool()
    loop = _build_loop(
        provider,
        tools=(_ReadTool(), edit_tool, _FakeRunCommandTool()),
        approval_service=ApprovalService(),
    )

    result = _run(loop.run("dosyayı değiştir"))

    assert result.status is CodingStatus.PENDING_APPROVAL
    assert edit_tool.calls == []
    outcomes = result.iterations[0].outcomes
    assert outcomes[0].requires_approval is True
    assert outcomes[1].skipped is True


def test_approval_record_is_opened_with_resolved_arguments() -> None:
    """Karar katmanındaki onay boşluğu bu yolda kapanır.

    Kullanıcı, gerçekten çalıştırılacak çağrıyı onaylar — henüz neye
    dönüşeceği belli olmayan bir taslağı değil.
    """
    provider = _ScriptedProvider(
        _task(),
        _plan(
            _read_step(),
            {
                "tool": "edit_file",
                "arguments": {
                    "path": "app/x.py",
                    "new_string": {"$from": {"step": 0, "path": "content"}},
                },
                "purpose": "önceki adımın sonucunu yaz",
            },
        ),
    )
    approvals = ApprovalService()
    loop = _build_loop(
        provider,
        tools=(_ReadTool(), _EditTool(), _FakeRunCommandTool()),
        approval_service=approvals,
    )

    result = _run(loop.run("dosyayı değiştir"))

    assert result.status is CodingStatus.PENDING_APPROVAL
    assert len(result.pending_approval_ids) == 1

    record = approvals.get(result.pending_approval_ids[0])
    assert record is not None
    # Başvuru çözülmüş hâliyle dondurulmuş olmalı.
    assert record.as_tool_call().arguments["new_string"] == "mevcut içerik"


def test_empty_plan_yields_no_plan_status() -> None:
    provider = _ScriptedProvider(_task(), _plan())
    loop = _build_loop(provider, tools=(_ReadTool(), _FakeRunCommandTool()))

    result = _run(loop.run("bir şey yap"))

    assert result.status is CodingStatus.NO_PLAN


def test_missing_tools_yield_failure() -> None:
    provider = _ScriptedProvider(_task(), _plan(_read_step()))
    loop = _build_loop(provider, tools=())

    result = _run(loop.run("bir şey yap"))

    assert result.status is CodingStatus.FAILED
    assert result.error is not None


def test_step_reference_is_resolved() -> None:
    provider = _ScriptedProvider(
        _task(command=None),
        _plan(
            _read_step(),
            {
                "tool": "read_file",
                "arguments": {"path": {"$from": {"step": 0, "path": "path"}}},
                "purpose": "aynı dosyayı tekrar oku",
            },
        ),
    )
    loop = _build_loop(provider, tools=(_ReadTool(),), verification_candidates=())

    result = _run(loop.run("oku"))

    assert result.iterations[0].outcomes[1].arguments == {"path": "app/x.py"}


def test_unresolvable_reference_does_not_crash_the_plan() -> None:
    provider = _ScriptedProvider(
        _task(command=None),
        _plan(
            _read_step(),
            {
                "tool": "read_file",
                "arguments": {"path": {"$from": {"step": 0, "path": "yok.olan.alan"}}},
                "purpose": "çözülemeyecek başvuru",
            },
        ),
    )
    loop = _build_loop(provider, tools=(_ReadTool(),), verification_candidates=())

    result = _run(loop.run("oku"))

    outcomes = result.iterations[0].outcomes
    assert outcomes[0].success is True
    assert outcomes[1].success is False


def test_exploding_tool_does_not_crash_the_loop() -> None:
    provider = _ScriptedProvider(
        _task(command=None),
        _plan(
            _read_step(),
            {"tool": "exploding_tool", "arguments": {"path": "a"}, "purpose": "patla"},
        ),
    )
    loop = _build_loop(
        provider, tools=(_ReadTool(), _ExplodingTool()), verification_candidates=()
    )

    result = _run(loop.run("oku"))

    assert result.iterations[0].outcomes[1].success is False
    assert result.status is CodingStatus.APPLIED_UNVERIFIED


def test_changed_files_only_counts_writing_tools() -> None:
    """`read_file` da bir `path` argümanı alır; değişiklik sayılmamalıdır."""
    provider = _ScriptedProvider(_task(command=None), _plan(_read_step("app/only_read.py")))
    loop = _build_loop(provider, tools=(_ReadTool(),), verification_candidates=())

    result = _run(loop.run("oku"))

    assert result.changed_files == []


def test_summary_is_produced_on_every_exit_path() -> None:
    for provider, tools in (
        (_ScriptedProvider(_task(), _plan(_read_step())), (_ReadTool(), _FakeRunCommandTool())),
        (_ScriptedProvider(_task(), _plan()), (_ReadTool(),)),
        (_ScriptedProvider(_task(), _plan(_read_step())), ()),
    ):
        result = _run(_build_loop(provider, tools=tools).run("bir şey"))
        assert result.summary


def test_loop_does_not_invent_a_second_execution_path() -> None:
    """Her adım ToolExecutor'dan geçmelidir; ikinci bir sınır açılmamalıdır."""
    provider = _ScriptedProvider(_task(command=None), _plan(_read_step()))
    loop = _build_loop(provider, tools=(_ReadTool(),), verification_candidates=())
    seen: list[str] = []

    executor = loop._tool_executor  # noqa: SLF001 - sınırın kullanıldığını kanıtlamak için
    original = executor.execute

    async def _spy(call, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(call.name)
        return await original(call, **kwargs)

    executor.execute = _spy  # type: ignore[method-assign]
    _run(loop.run("oku"))

    assert "read_file" in seen
