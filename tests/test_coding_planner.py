"""Kodlama döngüsü — planlayıcı, LLM çıktısını VERİ olarak doğrular.

Kapsam:
 1. Geçerli plan doğrulanıp AgentAction'lara çevrilir
 2. Kayıtlı olmayan bir tool planın TAMAMINI reddettirir
 3. Şemada olmayan argüman planın tamamını reddettirir
 4. İleriye dönük adım başvurusu reddedilir
 5. Adım sınırını aşan plan KIRPILMAZ, reddedilir
 6. requires_confirmation LLM'den okunmaz, araç tanımından hesaplanır
 7. Model "onay gerekmiyor" diyerek güvenlik sınırını gevşetemez
 8. Bozuk JSON boş plan üretir
 9. Sağlayıcı hatası boş plan üretir, istisna sızmaz
10. Markdown sarmalayıcısı temizlenir
11. Görev anlama: uydurulmuş doğrulama komutu reddedilir
12. Görev anlama: model çöktüğünde istek hedef sayılır
13. Düzeltme turu boş plan döndürebilir (dürüst cevap)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

from app.agent.models import ToolDescriptor
from app.coding.models import Diagnosis, DiagnosisCategory, TaskSpec
from app.coding.planner import CodingPlanner
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.adapters.llm.base import LLMProviderError
from app.tools.base import PermissionLevel


class _ScriptedProvider:
    """Sırayla önceden yazılmış cevapları döndüren sahte sağlayıcı."""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.calls: list[Sequence[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(messages)
        if not self._responses:
            return "{}"
        return self._responses.pop(0)

    async def generate_with_tools(
        self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]
    ) -> LLMResponse:  # pragma: no cover - planlayıcı bu yolu kullanmaz
        raise AssertionError("Planlayıcı generate_with_tools kullanmamalı.")


class _FailingProvider:
    """Her çağrıda sağlayıcı hatası veren sahte sağlayıcı."""

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        raise LLMProviderError("sağlayıcıya ulaşılamadı")

    async def generate_with_tools(
        self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]
    ) -> LLMResponse:  # pragma: no cover
        raise AssertionError("kullanılmamalı")


_READ_TOOL = ToolDescriptor(
    name="read_file",
    description="Dosya okur.",
    permission=PermissionLevel.READ,
    input_schema={"properties": {"path": {"type": "string"}}},
    requires_confirmation=False,
)

_EDIT_TOOL = ToolDescriptor(
    name="edit_file",
    description="Dosyayı değiştirir.",
    permission=PermissionLevel.WRITE,
    input_schema={
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
        }
    },
    # Bu oturumda WRITE onaya tabidir.
    requires_confirmation=True,
)

_TOOLS = [_READ_TOOL, _EDIT_TOOL]

_TASK = TaskSpec(goal="Bir hatayı düzelt.", verification_command="pytest -q")


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _plan_json(steps: list[dict], reason: str = "test") -> str:
    return json.dumps({"steps": steps, "reason": reason})


def test_valid_plan_is_accepted() -> None:
    provider = _ScriptedProvider(
        _plan_json([{"tool": "read_file", "arguments": {"path": "app/x.py"}, "purpose": "oku"}])
    )
    planner = CodingPlanner(provider=provider)

    plan = _run(planner.plan(_TASK, tools=_TOOLS))

    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "read_file"
    assert plan.steps[0].arguments == {"path": "app/x.py"}


def test_unknown_tool_rejects_the_whole_plan() -> None:
    """Yarım doğrulanmış bir plan, dosyayı yarı değiştirilmiş bırakırdı."""
    provider = _ScriptedProvider(
        _plan_json(
            [
                {"tool": "read_file", "arguments": {"path": "a.py"}, "purpose": "oku"},
                {"tool": "delete_everything", "arguments": {}, "purpose": "sil"},
            ]
        )
    )
    planner = CodingPlanner(provider=provider)

    plan = _run(planner.plan(_TASK, tools=_TOOLS))

    assert plan.steps == []


def test_argument_outside_schema_rejects_the_plan() -> None:
    provider = _ScriptedProvider(
        _plan_json([{"tool": "read_file", "arguments": {"filename": "a.py"}, "purpose": "oku"}])
    )
    planner = CodingPlanner(provider=provider)

    assert _run(planner.plan(_TASK, tools=_TOOLS)).steps == []


def test_forward_reference_is_rejected() -> None:
    """İleriye başvuru yürütmede zaten reddedilirdi; burada hiç yürütülmez."""
    provider = _ScriptedProvider(
        _plan_json(
            [
                {
                    "tool": "read_file",
                    "arguments": {"path": {"$from": {"step": 3, "path": "content"}}},
                    "purpose": "oku",
                }
            ]
        )
    )
    planner = CodingPlanner(provider=provider)

    assert _run(planner.plan(_TASK, tools=_TOOLS)).steps == []


def test_plan_over_the_step_limit_is_rejected_not_truncated() -> None:
    """Bir planı sessizce kısaltmak, isteği sessizce değiştirmektir."""
    steps = [
        {"tool": "read_file", "arguments": {"path": f"a{i}.py"}, "purpose": "oku"}
        for i in range(5)
    ]
    provider = _ScriptedProvider(_plan_json(steps))
    planner = CodingPlanner(provider=provider, max_steps=3)

    assert _run(planner.plan(_TASK, tools=_TOOLS)).steps == []


def test_confirmation_is_recomputed_from_the_tool_definition() -> None:
    provider = _ScriptedProvider(
        _plan_json(
            [
                {
                    "tool": "edit_file",
                    "arguments": {"path": "a.py", "old_string": "x", "new_string": "y"},
                    "purpose": "değiştir",
                }
            ]
        )
    )
    planner = CodingPlanner(provider=provider)

    plan = _run(planner.plan(_TASK, tools=_TOOLS))

    assert plan.steps[0].requires_confirmation is True
    assert plan.requires_confirmation is True


def test_model_cannot_disable_confirmation() -> None:
    """Model kendi kendine yetki veremez: ek alan planı tamamen reddettirir."""
    raw = json.dumps(
        {
            "steps": [
                {
                    "tool": "edit_file",
                    "arguments": {"path": "a.py", "old_string": "x", "new_string": "y"},
                    "purpose": "değiştir",
                    "requires_confirmation": False,
                }
            ],
            "reason": "test",
        }
    )
    planner = CodingPlanner(provider=_ScriptedProvider(raw))

    assert _run(planner.plan(_TASK, tools=_TOOLS)).steps == []


def test_malformed_json_yields_an_empty_plan() -> None:
    planner = CodingPlanner(provider=_ScriptedProvider("bu JSON değil"))

    assert _run(planner.plan(_TASK, tools=_TOOLS)).steps == []


def test_provider_failure_never_escapes() -> None:
    planner = CodingPlanner(provider=_FailingProvider())

    plan = _run(planner.plan(_TASK, tools=_TOOLS))

    assert plan.steps == []


def test_markdown_fence_is_stripped() -> None:
    raw = (
        "```json\n"
        + _plan_json([{"tool": "read_file", "arguments": {"path": "a.py"}, "purpose": "oku"}])
        + "\n```"
    )
    planner = CodingPlanner(provider=_ScriptedProvider(raw))

    assert len(_run(planner.plan(_TASK, tools=_TOOLS)).steps) == 1


def test_invented_verification_command_is_replaced() -> None:
    """Model, komut politikasının tanımadığı bir komut uyduramaz."""
    raw = json.dumps(
        {
            "goal": "Bir şey yap.",
            "rationale": "test",
            "files_of_interest": [],
            "verification_command": "rm -rf /",
        }
    )
    planner = CodingPlanner(provider=_ScriptedProvider(raw))

    task = _run(planner.understand("bir şey yap", verification_candidates=("pytest -q",)))

    assert task.verification_command == "pytest -q"


def test_unusable_task_output_falls_back_to_the_request() -> None:
    planner = CodingPlanner(provider=_ScriptedProvider("çöp"))

    task = _run(planner.understand("testi düzelt", verification_candidates=("pytest -q",)))

    assert task.goal == "testi düzelt"
    assert task.verification_command == "pytest -q"


def test_repair_may_decline_with_an_empty_plan() -> None:
    """Boş düzeltme planı dürüst bir cevaptır; tahmin edilmiş bir düzenleme değildir."""
    planner = CodingPlanner(provider=_ScriptedProvider(_plan_json([], reason="anlaşılmadı")))
    diagnosis = Diagnosis(category=DiagnosisCategory.UNKNOWN, summary="belirsiz")

    plan = _run(planner.repair(_TASK, diagnosis, tools=_TOOLS))

    assert plan.has_steps is False
