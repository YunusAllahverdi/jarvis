"""Görev anlama ve plan üretimi — LLM'e sorar, deterministik doğrular.

Akış (`app.agent.llm_policy` ile aynı iskelet):

    istek → prompt → LLMProvider.generate() → ham metin
                                                 ↓
                                    parse_decision_payload()
                                                 ↓
                                       katı pydantic aday
                                                 ↓
                                   deterministik doğrulama
                                                 ↓
                                     TaskSpec / CodingPlan

Mimari kurallar:
- MEVCUT sağlayıcı soyutlaması kullanılır (`app.adapters.llm.base.LLMProvider`).
  İkinci bir LLM istemcisi yoktur; bu modül hiçbir HTTP çağrısı yapmaz ve
  hiçbir API anahtarı görmez.
- LLM ÇIKTISI VERİDİR:
  * tool adı kullanılabilir araçlar listesinden doğrulanır,
  * argüman anahtarları tool'un şemasına karşı denetlenir,
  * `requires_confirmation` LLM'den HİÇ OKUNMAZ — araç tanımından yeniden
    hesaplanır, böylece model kendi kendine yetki veremez,
  * tam şema ve izin denetimi `ToolExecutor` içinde yapılır ve atlanmaz.
- Planlayıcı HİÇBİR ZAMAN istisna fırlatmaz. Sağlayıcı hatası, bozuk JSON,
  bilinmeyen araç, adım sınırı aşımı — hepsinde BOŞ plan döner. Boş plan
  dürüst bir cevaptır; tahmin edilmiş bir düzenleme değildir.
- Doğrulama komutu, modelin uydurabileceği bir metin DEĞİLDİR: yalnızca
  çağıranın verdiği aday listesinden seçilebilir. Aksi hâlde model, komut
  politikasının izin vermediği ya da hiç var olmayan bir komut yazabilirdi.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.llm.base import LLMProvider, LLMProviderError
from app.agent.llm_policy import parse_decision_payload
from app.agent.models import AgentAction, ToolDescriptor
from app.agent.validation import arguments_match_schema, references_point_backwards
from app.coding.models import MAX_STEPS, CodingPlan, Diagnosis, TaskSpec
from app.coding.prompts import (
    build_plan_messages,
    build_repair_messages,
    build_task_messages,
)

logger = logging.getLogger(__name__)

# Reddetme sebepleri (gözlemlenebilirlik için kararlı etiketler).
REJECT_PROVIDER_FAILED = "provider_failed"
REJECT_UNPARSABLE = "unparsable_output"
REJECT_INVALID_SCHEMA = "invalid_schema"
REJECT_UNKNOWN_TOOL = "unknown_tool"
REJECT_INVALID_ARGUMENTS = "invalid_arguments"
REJECT_TOO_MANY_STEPS = "too_many_steps"
REJECT_UNKNOWN_COMMAND = "unknown_verification_command"


class _StepCandidate(BaseModel):
    """LLM'den gelen tek bir adım adayı için katı doğrulama şeması."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: str = Field(default="", max_length=200)


class _PlanCandidate(BaseModel):
    """LLM'den gelen planın katı doğrulama şeması.

    `extra="forbid"`: modelin uydurduğu ek alanlar (ör. kendine verdiği
    izinler) sessizce kabul edilmez, plan tamamen reddedilir.
    """

    model_config = ConfigDict(extra="forbid")

    steps: list[_StepCandidate] = Field(default_factory=list)
    reason: str = Field(default="", max_length=300)


class _TaskCandidate(BaseModel):
    """LLM'den gelen görev tanımının katı doğrulama şeması."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=500)
    rationale: str = Field(default="", max_length=300)
    files_of_interest: list[str] = Field(default_factory=list)
    verification_command: str | None = None


class CodingPlanner:
    """Bir isteği göreve, görevi de doğrulanmış bir plana çevirir."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        max_steps: int = MAX_STEPS,
        model_label: str | None = None,
    ) -> None:
        """
        Args:
            provider: MEVCUT sağlayıcı soyutlaması. Somut sınıf (Ollama vb.)
                bu katmana sızmaz; yalnızca `generate()` çağrılır.
            max_steps: Bir planda izin verilen maksimum adım sayısı.
            model_label: Loglara yazılacak model etiketi. Gizli bilgi
                İÇERMEMELİDİR (API anahtarı, uç nokta kimlik bilgisi vb.).
        """
        self._provider = provider
        self._max_steps = max_steps
        self._model_label = model_label

    # ------------------------------------------------------------------
    # Görev anlama
    # ------------------------------------------------------------------

    async def understand(
        self,
        request: str,
        *,
        repository_overview: str | None = None,
        verification_candidates: tuple[str, ...] = (),
    ) -> TaskSpec:
        """İsteği yapılandırılmış bir göreve çevirir.

        Hiçbir zaman istisna fırlatmaz: model kullanılamazsa veya çıktısı
        reddedilirse, isteğin kendisini hedef kabul eden asgari bir görev
        döner. Böylece döngü hiç başlamamak yerine, en azından planlama
        aşamasına geçebilir.

        `verification_command` yalnızca `verification_candidates` içinden
        seçilebilir; model uydurursa alan None'a düşürülür. Uydurulmuş bir
        komut, komut politikasında zaten reddedilirdi — ama o noktada bir
        tur harcanmış olurdu.
        """
        raw = await self._ask(build_task_messages(
            request,
            repository_overview=repository_overview,
            verification_candidates=verification_candidates,
        ))
        candidate = self._parse(raw, _TaskCandidate)
        if candidate is None:
            return TaskSpec(
                goal=request[:500],
                rationale="Görev modeli okunamadı; istek doğrudan hedef sayıldı.",
                verification_command=(
                    verification_candidates[0] if verification_candidates else None
                ),
            )

        command = candidate.verification_command
        if command is not None:
            command = command.strip() or None
        if command is not None and command not in verification_candidates:
            logger.warning(
                "coding_task_command_rejected",
                extra={"reason": REJECT_UNKNOWN_COMMAND, "command": command[:120]},
            )
            command = verification_candidates[0] if verification_candidates else None

        task = TaskSpec(
            goal=candidate.goal.strip(),
            rationale=candidate.rationale.strip(),
            files_of_interest=[
                path.strip() for path in candidate.files_of_interest[:20] if path.strip()
            ],
            verification_command=command,
        )
        logger.info(
            "coding_task_understood",
            extra={
                "model": self._model_label,
                "file_count": len(task.files_of_interest),
                "has_verification": task.verification_command is not None,
            },
        )
        return task

    # ------------------------------------------------------------------
    # Planlama
    # ------------------------------------------------------------------

    async def plan(
        self,
        task: TaskSpec,
        *,
        tools: list[ToolDescriptor],
        repository_overview: str | None = None,
    ) -> CodingPlan:
        """Görev için ilk planı üretir; reddedilirse boş plan döner."""
        raw = await self._ask(
            build_plan_messages(task, tools=tools, repository_overview=repository_overview)
        )
        return self._plan_from(raw, tools=tools, stage="plan")

    async def repair(
        self,
        task: TaskSpec,
        diagnosis: Diagnosis,
        *,
        tools: list[ToolDescriptor],
        applied_summary: str | None = None,
    ) -> CodingPlan:
        """Başarısız doğrulamayı gidermek için bir düzeltme planı üretir.

        Boş plan dönmesi bir hata DEĞİLDİR: model, verilen çıktıdan ne
        yapacağını çıkaramadığında boş plan döndürmeye açıkça yönlendirilir
        ve döngü bunu "daha fazla denemeye değmez" olarak okur.
        """
        raw = await self._ask(
            build_repair_messages(
                task, diagnosis, tools=tools, applied_summary=applied_summary
            )
        )
        return self._plan_from(raw, tools=tools, stage="repair")

    # ------------------------------------------------------------------
    # Sağlayıcı çağrısı ve doğrulama
    # ------------------------------------------------------------------

    async def _ask(self, messages: list) -> str | None:
        """Sağlayıcıyı çağırır; her hatada None döner.

        `generate()` kullanılır, `generate_with_tools()` DEĞİL: buradaki amaç
        tool ÇAĞIRMAK değil, hangi tool'ların gerektiğine dair yapılandırılmış
        bir plan almaktır. Yürütme yalnızca `ToolExecutor` üzerinden yapılır.
        """
        try:
            return await self._provider.generate(messages)
        except LLMProviderError as exc:
            logger.warning("coding_provider_failed", extra={"error": str(exc)})
            return None
        except Exception:  # noqa: BLE001
            logger.exception("coding_provider_unexpected_error")
            return None

    def _parse(self, raw: str | None, model: type[BaseModel]) -> Any | None:
        """Ham metni katı bir şemaya çevirir; başarısızsa None."""
        if raw is None:
            return None
        payload = parse_decision_payload(raw)
        if payload is None:
            logger.warning("coding_output_rejected", extra={"reason": REJECT_UNPARSABLE})
            return None
        try:
            return model.model_validate(payload)
        except ValidationError:
            logger.warning("coding_output_rejected", extra={"reason": REJECT_INVALID_SCHEMA})
            return None

    def _plan_from(
        self, raw: str | None, *, tools: list[ToolDescriptor], stage: str
    ) -> CodingPlan:
        """Ham metni doğrulanmış bir plana çevirir; reddedilirse boş plan.

        Boş plan, "hiçbir şey yapma" anlamına gelir ve döngü bunu güvenle
        işleyebilir. Yarım doğrulanmış bir plan ise en tehlikeli çıktı
        olurdu: bir adımı geçerli, bir adımı uydurma bir plan çalıştırmak,
        dosyayı yarı değiştirilmiş bırakır.
        """
        candidate = self._parse(raw, _PlanCandidate)
        if candidate is None:
            return CodingPlan(steps=[], reason="Plan üretilemedi.")

        if len(candidate.steps) > self._max_steps:
            logger.warning(
                "coding_plan_rejected",
                extra={
                    "stage": stage,
                    "reason": REJECT_TOO_MANY_STEPS,
                    "step_count": len(candidate.steps),
                    "max_steps": self._max_steps,
                },
            )
            return CodingPlan(steps=[], reason="Plan adım sınırını aştı.")

        by_name = {tool.name: tool for tool in tools}
        steps: list[AgentAction] = []
        for index, raw_step in enumerate(candidate.steps):
            descriptor = by_name.get(raw_step.tool)
            if descriptor is None:
                logger.warning(
                    "coding_plan_rejected",
                    extra={
                        "stage": stage,
                        "reason": REJECT_UNKNOWN_TOOL,
                        "tool_name": raw_step.tool[:64],
                    },
                )
                return CodingPlan(steps=[], reason="Plan kayıtlı olmayan bir araç istedi.")

            if not arguments_match_schema(raw_step.arguments, descriptor.input_schema):
                logger.warning(
                    "coding_plan_rejected",
                    extra={
                        "stage": stage,
                        "reason": REJECT_INVALID_ARGUMENTS,
                        "tool_name": descriptor.name,
                    },
                )
                return CodingPlan(steps=[], reason="Plan şemaya uymayan argüman içeriyor.")

            if not references_point_backwards(raw_step.arguments, index):
                logger.warning(
                    "coding_plan_rejected",
                    extra={
                        "stage": stage,
                        "reason": REJECT_INVALID_ARGUMENTS,
                        "tool_name": descriptor.name,
                    },
                )
                return CodingPlan(steps=[], reason="Plan ileriye dönük bir başvuru içeriyor.")

            steps.append(
                AgentAction(
                    tool_name=descriptor.name,
                    arguments=raw_step.arguments,
                    purpose=raw_step.purpose.strip() or f"{descriptor.name} çalıştır.",
                    # GÜVENLİK: onay gereksinimi LLM'den DEĞİL, araç
                    # tanımından alınır. Model bunu gevşetemez.
                    requires_confirmation=descriptor.requires_confirmation,
                )
            )

        logger.info(
            "coding_plan_built",
            extra={
                "stage": stage,
                "model": self._model_label,
                "step_count": len(steps),
                "selected_tools": [step.tool_name for step in steps],
            },
        )
        return CodingPlan(steps=steps, reason=candidate.reason.strip() or "Plan üretildi.")
