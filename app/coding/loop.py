"""Kodlama döngüsü: anla → planla → uygula → doğrula → teşhis et → düzelt.

Bu, karar katmanı ile kodlama ajanı arasındaki farkın kendisidir. Karar
katmanı bir plan üretip yürütür ve orada durur; burada yürütmenin SONUCU
doğrulanır, başarısızlık deterministik olarak teşhis edilir ve sınırlı
sayıda düzeltme turu denenir.

    ┌─ anla ──────── TaskSpec (hedef + DOĞRULAMA KOMUTU)
    │
    ├─ planla ────── CodingPlan (doğrulanmış adımlar)
    │                     │
    │   ┌─────────────────┤
    │   │                 ▼
    │   │             uygula (ToolExecutor)
    │   │                 │
    │   │                 ▼
    │   │             doğrula (çıkış kodu)
    │   │                 │
    │   │            geçti?├── evet ─→ COMPLETED
    │   │                 │
    │   │                hayır
    │   │                 ▼
    │   └───── teşhis + düzeltme planı  (tur sınırına kadar)
    │
    └─ özetle ────── deterministik açıklama + git diff

Mimari kurallar:
- AYRI BİR YÜRÜTME MEKANİZMASI YOKTUR. Her adım, döngünün diğer her adımıyla
  AYNI `ToolExecutor` örneğinden geçer. İkinci bir sınır açılsaydı, biri
  sıkılaştırıldığında diğeri gevşek kalırdı.
- ONAY SINIRI: onay gerektiren bir adıma gelindiğinde döngü DURUR. Kalan
  adımlar çalıştırılmaz ve onay kaydı ÇÖZÜLMÜŞ argümanlarla açılır. Bu,
  karar katmanındaki onay boşluğunun bu yolda kapanması demektir: orada
  argümanlar önceki adımlara başvurabildiği için kayıt açılamıyordu, burada
  önceki adımlar zaten çalışmış olduğundan argümanlar somuttur.
- Döngü HİÇBİR ZAMAN istisna fırlatmaz; her başarısızlık yapılandırılmış bir
  `CodingResult`'a dönüşür.
- Döngü kendi kendini "başarılı" ilan edemez: `COMPLETED` yalnızca gerçek bir
  doğrulama komutunun sıfır çıkış koduyla verilir.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agent.models import ActionOutcome, AgentAction, ToolDescriptor
from app.agent.references import (
    ERROR_UNRESOLVED_REFERENCE,
    ReferenceError,
    resolve_arguments,
)
from app.coding.models import (
    MAX_ITERATIONS,
    CodingPlan,
    CodingResult,
    CodingStatus,
    Diagnosis,
    Iteration,
    TaskSpec,
    Verification,
)
from app.coding.planner import CodingPlanner
from app.coding.summary import build_summary
from app.coding.verification import Verifier
from app.core.chat import ToolCall
from app.security.approvals import ApprovalService
from app.security.permissions import PermissionDecision
from app.tools.base import PermissionLevel
from app.tools.builtin.git_tools import GIT_DIFF_TOOL_NAME
from app.tools.builtin.project import PROJECT_OVERVIEW_TOOL_NAME
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_OVERVIEW_CHARS = 6000
"""Depo görünümünün prompt'a girecek en fazla karakteri.

Sınırsız bir görünüm, sınırsız bir prompt demektir; büyük depolarda tek bir
planlama turu bağlam penceresini doldurabilirdi.
"""

_ERROR_NO_TOOLS = "Kodlama araçları bu oturumda kayıtlı değil."
_ERROR_NO_PLAN = "Planlayıcı uygulanabilir bir adım üretmedi."


class CodingLoop:
    """Bir kodlama isteğini uçtan uca yürütür ve sonucunu doğrular."""

    def __init__(
        self,
        *,
        planner: CodingPlanner,
        verifier: Verifier,
        tool_executor: ToolExecutor,
        approval_service: ApprovalService | None = None,
        verification_candidates: tuple[str, ...] = (),
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        """
        Args:
            planner: Görevi ve planları üreten katman.
            verifier: Doğrulama komutunu çalıştıran katman. Executor'ı
                buradaki ile AYNI örnek olmalıdır.
            tool_executor: Adımların geçtiği tek yürütme sınırı. Araç kaydı
                da BURADAN okunur, ayrıca verilmez: iki ayrı kaynak olsaydı
                planlayan tarafın gördüğü araç yüzeyi ile çalıştıran tarafın
                yüzeyi ayrışabilir, model çalıştırılamayacak bir aracı
                planlayabilirdi.
            approval_service: Onay bekleyen adımlar için kayıt açan servis.
                Verilmezse döngü yine durur, ama kullanıcı yanıtlayacak bir
                istek göremez.
            verification_candidates: Görev modelinin seçebileceği doğrulama
                komutları. Model bu listenin dışına ÇIKAMAZ.
            max_iterations: Uygula-doğrula turlarının üst sınırı.
        """
        self._planner = planner
        self._verifier = verifier
        self._tool_executor = tool_executor
        self._tool_registry: ToolRegistry = tool_executor.registry
        self._approval_service = approval_service
        self._verification_candidates = verification_candidates
        self._max_iterations = max(1, max_iterations)

    # ------------------------------------------------------------------
    # Genel akış
    # ------------------------------------------------------------------

    async def run(self, request: str, *, session_id: str | None = None) -> CodingResult:
        """İsteği uçtan uca yürütür; hiçbir zaman istisna fırlatmaz."""
        tools = self._available_tools()
        if not tools:
            return self._finish(
                CodingResult(
                    request=request,
                    session_id=session_id,
                    status=CodingStatus.FAILED,
                    error=_ERROR_NO_TOOLS,
                )
            )

        overview = await self._repository_overview(session_id)
        task = await self._planner.understand(
            request,
            repository_overview=overview,
            verification_candidates=self._verification_candidates,
        )

        plan = await self._planner.plan(task, tools=tools, repository_overview=overview)
        if not plan.has_steps:
            return self._finish(
                CodingResult(
                    request=request,
                    session_id=session_id,
                    status=CodingStatus.NO_PLAN,
                    task=task,
                    error=_ERROR_NO_PLAN,
                )
            )

        result = CodingResult(
            request=request,
            session_id=session_id,
            status=CodingStatus.FAILED,
            task=task,
        )
        await self._iterate(result, task, plan, tools=tools, session_id=session_id)
        result.diff = await self._collect_diff(session_id)
        return self._finish(result)

    async def _iterate(
        self,
        result: CodingResult,
        task: TaskSpec,
        plan: CodingPlan,
        *,
        tools: list[ToolDescriptor],
        session_id: str | None,
    ) -> None:
        """Uygula-doğrula turlarını sınıra kadar yürütür ve durumu belirler.

        `result` yerinde güncellenir: döngü yarıda kesilse bile (onay,
        çözülemeyen başvuru) o ana kadar yapılanlar sonuçta durur ve
        kullanıcı neyin uygulandığını görebilir.
        """
        diagnosis: Diagnosis | None = None

        for index in range(self._max_iterations):
            iteration = Iteration(index=index, plan=plan, repairs=diagnosis)
            result.iterations.append(iteration)

            stopped = await self._apply(iteration, result, session_id=session_id)
            if stopped:
                result.status = CodingStatus.PENDING_APPROVAL
                return

            if not iteration.applied_outcomes:
                # Hiçbir adım çalışmadıysa doğrulamanın anlamı yok: doğrulanacak
                # bir değişiklik ortada değil.
                result.status = CodingStatus.FAILED
                result.error = "Planlanan adımların hiçbiri çalıştırılamadı."
                return

            verification = await self._verifier.verify(
                task.verification_command, session_id=session_id
            )
            iteration.verification = verification

            if not verification.ran:
                result.status = CodingStatus.APPLIED_UNVERIFIED
                return
            if verification.passed:
                result.status = CodingStatus.COMPLETED
                return

            result.status = CodingStatus.VERIFICATION_FAILED
            diagnosis = verification.diagnosis
            if diagnosis is None or not diagnosis.is_actionable:
                # Reddedilmiş bir komutta düzeltilecek KOD yoktur; yeni bir
                # tur, aynı engele yeniden çarpmaktan başka bir şey yapmaz.
                return
            if index + 1 >= self._max_iterations:
                return

            plan = await self._planner.repair(
                task,
                diagnosis,
                tools=tools,
                applied_summary=_applied_summary(result),
            )
            if not plan.has_steps:
                # Boş düzeltme planı dürüst bir cevaptır: model verilen
                # çıktıdan ne yapacağını çıkaramadı. Tur harcamaya devam
                # etmek yerine burada durulur.
                logger.info(
                    "coding_repair_declined",
                    extra={"iteration": index, "session_id": session_id},
                )
                return

    # ------------------------------------------------------------------
    # Adım yürütme
    # ------------------------------------------------------------------

    async def _apply(
        self, iteration: Iteration, result: CodingResult, *, session_id: str | None
    ) -> bool:
        """Turun adımlarını sırayla yürütür.

        Returns:
            Onay beklendiği için döngünün DURDURULMASI gerekiyorsa True.

        Onay gerektiren bir adıma gelindiğinde kalan adımlar çalıştırılmaz.
        "Önce birkaçını çalıştırıp sonra onay iste" durumu, kullanıcının
        onaylamadığı bir işin yarısının çoktan yapılmış olması demek olurdu.
        """
        previous_results: list[dict[str, Any] | None] = []

        for position, step in enumerate(iteration.plan.steps):
            try:
                arguments = resolve_arguments(
                    step.arguments, previous_results=previous_results
                )
            except ReferenceError as exc:
                logger.warning(
                    "coding_step_reference_unresolved",
                    extra={"tool_name": step.tool_name, "error": str(exc)},
                )
                iteration.outcomes.append(
                    ActionOutcome(
                        tool_name=step.tool_name,
                        success=False,
                        error_code=ERROR_UNRESOLVED_REFERENCE,
                        error_message=(
                            "Bir önceki adımın sonucuna yapılan başvuru çözülemedi; "
                            "bu adım çalıştırılmadı."
                        ),
                        arguments=dict(step.arguments),
                    )
                )
                previous_results.append(None)
                continue

            outcome = await self._execute(step, arguments, session_id=session_id)
            iteration.outcomes.append(outcome)

            if outcome.requires_approval:
                self._open_approval(outcome, result, session_id=session_id)
                self._skip_remaining(iteration, position)
                return True

            previous_results.append(outcome.data if outcome.success else None)

        return False

    async def _execute(
        self, step: AgentAction, arguments: dict[str, Any], *, session_id: str | None
    ) -> ActionOutcome:
        """Tek bir adımı yürütme sınırından geçirir; hiçbir hata dışarı sızmaz.

        Argümanlar burada yeniden doğrulanmaz: şema doğrulaması ve izin
        kontrolü `ToolExecutor` içinde yapılır ve o sınır atlanmaz.
        """
        call = step.as_tool_call()
        call.arguments = arguments
        try:
            result = await self._tool_executor.execute(call, session_id=session_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "coding_step_unexpected_error", extra={"tool_name": step.tool_name}
            )
            return ActionOutcome(
                tool_name=step.tool_name,
                success=False,
                error_code="step_execution_failed",
                error_message="Adım çalıştırılırken beklenmeyen bir hata oluştu.",
                arguments=dict(arguments),
            )
        return ActionOutcome.from_execution(result, arguments)

    def _skip_remaining(self, iteration: Iteration, position: int) -> None:
        """Onaydan sonraki adımları çalıştırılmamış olarak işaretler.

        Sessizce atlanmaları, planın kısaldığı izlenimi verirdi; oysa plan
        aynı plandır, yalnızca durdurulmuştur.
        """
        for step in iteration.plan.steps[position + 1 :]:
            iteration.outcomes.append(
                ActionOutcome(
                    tool_name=step.tool_name,
                    skipped=True,
                    arguments=dict(step.arguments),
                )
            )

    def _open_approval(
        self, outcome: ActionOutcome, result: CodingResult, *, session_id: str | None
    ) -> None:
        """Onay bekleyen adım için kayıt açar ve kimliğini sonuca işler.

        Argümanlar ÇÖZÜLMÜŞ hâlleriyle dondurulur: kullanıcı, gerçekten
        çalıştırılacak olan çağrıyı onaylar — başvuru içeren, henüz neye
        dönüşeceği belli olmayan bir taslağı değil.

        Kayıt açılamazsa adım yine çalıştırılmamış kalır ve hata yalnızca
        loglanır: onay altyapısındaki bir aksaklık, engellenmiş bir yazmanın
        aniden gerçekleşmesine yol açmamalıdır.
        """
        if self._approval_service is None or outcome.permission is None:
            return
        try:
            record = self._approval_service.request(
                ToolCall(name=outcome.tool_name, arguments=dict(outcome.arguments)),
                permission=PermissionLevel(outcome.permission),
                session_id=session_id,
                reason=outcome.error_message,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "coding_approval_request_failed", extra={"tool_name": outcome.tool_name}
            )
            return
        outcome.approval_id = record.approval_id
        result.pending_approval_ids.append(record.approval_id)

    # ------------------------------------------------------------------
    # Salt-okunur yardımcılar
    # ------------------------------------------------------------------

    def _available_tools(self) -> list[ToolDescriptor]:
        """Kayıtlı araçları planlayıcıya sunulacak güvenli tanımlara çevirir.

        `Tool` nesnesinin kendisi prompt'a KONMAZ; yalnızca ad, açıklama,
        izin seviyesi, şema ve onay gereksinimi taşınır. Onay gereksinimi
        politikadan hesaplanır, araçtan değil: aynı araç farklı oturumlarda
        farklı onay gereksinimine sahip olabilir.
        """
        try:
            tools = self._tool_registry.list_tools()
        except Exception:  # noqa: BLE001
            logger.exception("coding_tool_registry_failed")
            return []

        policy = self._tool_executor.policy
        return [
            ToolDescriptor(
                name=tool.name,
                description=tool.description,
                permission=tool.permission,
                input_schema=tool.definition.input_schema,
                requires_confirmation=(
                    policy.decide(tool.permission) is not PermissionDecision.ALLOW
                ),
            )
            for tool in tools
        ]

    async def _repository_overview(self, session_id: str | None) -> str | None:
        """Depo yapısının sınırlanmış bir özetini toplar.

        Salt okunurdur ve başarısız olması bir hata DEĞİLDİR: görünüm
        olmadan da planlama yapılabilir, yalnızca model dosya adı öneremez —
        prompt ona zaten yalnızca GÖSTERİLEN yolları kullanmasını söyler.
        """
        if self._tool_registry.get(PROJECT_OVERVIEW_TOOL_NAME) is None:
            return None
        try:
            result = await self._tool_executor.execute(
                ToolCall(name=PROJECT_OVERVIEW_TOOL_NAME, arguments={"path": "."}),
                session_id=session_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("coding_overview_failed")
            return None
        if not result.success or result.data is None:
            return None

        text = json.dumps(result.data, ensure_ascii=False, default=str, sort_keys=True)
        return text[:MAX_OVERVIEW_CHARS]

    async def _collect_diff(self, session_id: str | None) -> str | None:
        """Yapılan değişikliklerin git diff'ini toplar.

        Salt okunurdur ve git deposu olmayan bir çalışma kökünde başarısız
        olması beklenir; bu durumda None döner ve döngünün sonucu değişmez.
        """
        if self._tool_registry.get(GIT_DIFF_TOOL_NAME) is None:
            return None
        try:
            result = await self._tool_executor.execute(
                ToolCall(name=GIT_DIFF_TOOL_NAME, arguments={}), session_id=session_id
            )
        except Exception:  # noqa: BLE001
            logger.exception("coding_diff_failed")
            return None
        if not result.success or result.data is None:
            return None
        diff = result.data.get("diff")
        return diff if isinstance(diff, str) and diff.strip() else None

    def _finish(self, result: CodingResult) -> CodingResult:
        """Açıklamayı üretir, sonucu loglar ve döndürür.

        Her çıkış yolu buradan geçer; yeni bir dal eklendiğinde özetin
        atlanması için ayrıca bir şey yapılması gerekir.
        """
        result.summary = build_summary(result)
        logger.info(
            "coding_loop_finished",
            extra={
                "status": result.status.value,
                "iteration_count": len(result.iterations),
                "changed_file_count": len(result.changed_files),
                "pending_approvals": len(result.pending_approval_ids),
                "session_id": result.session_id,
            },
        )
        return result


def _applied_summary(result: CodingResult) -> str | None:
    """Şimdiye kadar UYGULANMIŞ adımların düzeltme turuna verilecek özeti.

    Düzeltme turu bunu görmezse aynı düzenlemeyi ikinci kez planlayabilir;
    bir `edit_file` çağrısı ikinci kez çalıştırıldığında zaten değişmiş
    metni arayacağı için başarısız olur ve tur boşa giderdi.
    """
    lines: list[str] = []
    for iteration in result.iterations:
        for outcome in iteration.applied_outcomes:
            target = outcome.arguments.get("path")
            suffix = f" ({target})" if isinstance(target, str) and target else ""
            lines.append(f"- {outcome.tool_name}{suffix}")
    return "\n".join(lines) if lines else None
