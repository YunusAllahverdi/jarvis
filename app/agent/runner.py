"""Kararın yürütülmesi: eylemleri mevcut ToolExecutor sınırından geçirir.

Mimari kurallar:
- Agent hiçbir tool'un nasıl çalıştığını BİLMEZ. Tek yürütme yolu
  `ToolExecutor`'dır; izin kontrolü, şema doğrulaması ve hata yakalama
  zaten orada yapılır ve o katman hiçbir zaman istisna fırlatmaz.
- Runner ayrı bir tool mekanizması İCAT ETMEZ; mevcut sınırı yeniden kullanır.
- ONAY SINIRI: onay gerektiren bir plandaki HİÇBİR eylem çalıştırılmaz.
  Bu, "önce birkaçını çalıştırıp sonra onay iste" gibi yarım kalmış bir
  duruma düşmeyi imkânsız kılar.
- Bir eylemin başarısızlığı planı çökertmez; her eylem kendi sonucunu üretir
  ve toplu durum sonuçlardan deterministik olarak türetilir.

ADIMLAR ARASI VERİ AKIŞI:
    Bir adımın argümanı, kendisinden ÖNCEKİ bir adımın sonucundan bir değere
    başvurabilir (bkz. `app.agent.references`). Başvuru kod değil veridir;
    çözümleme yalnızca sözlük anahtarları ve liste indeksleri üzerinde yürür.
    Çözülemeyen bir başvuruda adım ÇALIŞTIRILMAZ — yanlış argümanla tool
    çağırmaktansa adımı başarısız saymak tercih edilir.

    Hâlâ kapsam dışı: koşullu dallanma ve yeniden planlama (replanning).
    Plan, karar anında sabittir; yürütme sırasında büyümez.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.models import ActionOutcome, AgentDecision, AgentResult, AgentStatus, status_for
from app.agent.references import (
    ERROR_UNRESOLVED_REFERENCE,
    ReferenceError,
    resolve_arguments,
)
from app.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


class AgentRunner:
    """Bir `AgentDecision`'ı yürütüp yapılandırılmış `AgentResult` üretir."""

    def __init__(self, *, tool_executor: ToolExecutor) -> None:
        """
        Args:
            tool_executor: Eylemlerin geçeceği tek yürütme sınırı.
        """
        self._tool_executor = tool_executor

    @property
    def tool_executor(self) -> ToolExecutor:
        """Eylemlerin geçtiği yürütme sınırı.

        Onay akışı da onaylanmış çağrıyı buradan geçirir: iki ayrı sınır
        oluşsaydı, biri sıkılaştırıldığında diğeri gevşek kalabilirdi.
        """
        return self._tool_executor

    async def execute(self, decision: AgentDecision) -> AgentResult:
        """Karardaki eylemleri sırayla yürütür.

        Hiçbir zaman istisna fırlatmaz: tool hataları `ToolExecutor` tarafından
        yapılandırılmış sonuçlara çevrilir, beklenmedik hatalar burada yutulur.
        """
        if not decision.has_actions:
            return AgentResult(
                decision=decision, outcomes=[], status=AgentStatus.NO_ACTION
            )

        if decision.requires_confirmation:
            logger.info(
                "agent_execution_pending_confirmation",
                extra={
                    "intent": decision.intent.value,
                    "action_count": len(decision.actions),
                },
            )
            return AgentResult(
                decision=decision,
                outcomes=[self._pending_outcome(action) for action in decision.actions],
                status=AgentStatus.PENDING_CONFIRMATION,
            )

        outcomes: list[ActionOutcome] = []
        # Önceki adımların sonuç verileri; başarısız adımlar için None.
        # Bu liste aynı zamanda geriye başvuru sınırını taşır: bir adım
        # yalnızca kendisinden önce çalışmış adımlara başvurabilir.
        previous_results: list[dict[str, Any] | None] = []

        for action in decision.actions:
            try:
                arguments = resolve_arguments(
                    action.arguments, previous_results=previous_results
                )
            except ReferenceError as exc:
                logger.warning(
                    "agent_action_reference_unresolved",
                    extra={"tool_name": action.tool_name, "error": str(exc)},
                )
                outcomes.append(
                    ActionOutcome(
                        tool_name=action.tool_name,
                        success=False,
                        error_code=ERROR_UNRESOLVED_REFERENCE,
                        error_message=(
                            "Bir önceki adımın sonucuna yapılan başvuru çözülemedi; "
                            "bu adım çalıştırılmadı."
                        ),
                    )
                )
                previous_results.append(None)
                continue

            outcome = await self._execute_action(decision, action, arguments)
            outcomes.append(outcome)
            previous_results.append(outcome.data if outcome.success else None)

        status = status_for(outcomes)
        logger.info(
            "agent_execution_complete",
            extra={
                "intent": decision.intent.value,
                "status": status.value,
                "action_count": len(decision.actions),
                "failed_count": sum(1 for o in outcomes if not o.success and not o.skipped),
            },
        )
        return AgentResult(decision=decision, outcomes=outcomes, status=status)

    def _pending_outcome(self, action) -> ActionOutcome:  # noqa: ANN001
        """Onay bekleyen bir eylem için, kayıt açılabilecek bir sonuç üretir.

        BURASI BİR BOŞLUĞU KAPATIR. Daha önce bu eylemler yalnızca
        `skipped=True` ile işaretleniyordu; `AgentService._open_pending_approvals`
        ise `requires_approval` alanına baktığı için hiçbir onay kaydı
        açmıyordu. Sonuç: ajan "onay gerekiyor" diyor, kullanıcı ise
        onaylayacak bir istek göremiyordu.

        Argümanlar HAM hâlleriyle taşınır ve bir uyarı ile birlikte gelir:
        bu yolda hiçbir adım çalışmadığı için, önceki adımlara yapılan
        başvurular (`$from`) henüz çözülememiştir. Onay katmanı bunu
        `requires_resolution` ile görür ve çözülmemiş argümanlı bir çağrı
        için kayıt AÇMAZ — kullanıcının neye dönüşeceği belli olmayan bir
        taslağı onaylaması, onayın anlamını boşaltırdı.

        Tek adımlı planlarda böyle bir başvuru olamaz ve akış sorunsuz
        çalışır; çok adımlı planlarda ise doğru cevap kodlama döngüsüdür
        (bkz. `app.coding.loop`), çünkü orada önceki adımlar gerçekten
        çalışmış olur ve argümanlar somuttur.
        """
        return ActionOutcome(
            tool_name=action.tool_name,
            skipped=True,
            requires_approval=True,
            arguments=dict(action.arguments),
            error_message="Bu eylem kullanıcı onayı bekliyor.",
        )

    async def _execute_action(
        self,
        decision: AgentDecision,
        action,  # noqa: ANN001
        arguments: dict[str, Any],
    ) -> ActionOutcome:
        """Tek bir eylemi çözülmüş argümanlarla yürütür; hiçbir hata dışarı sızmaz.

        Argümanlar burada yeniden doğrulanmaz: şema doğrulaması ve izin
        kontrolü `ToolExecutor` içinde yapılır ve o sınır atlanmaz.
        """
        call = action.as_tool_call()
        call.arguments = arguments
        try:
            result = await self._tool_executor.execute(call)
        except Exception:  # noqa: BLE001
            # ToolExecutor sözleşmesi gereği buraya düşülmemeli; yine de bir
            # savunma katmanı bırakıldı, çünkü tek bir tool'un beklenmedik
            # davranışı asla tüm planı çökertmemeli.
            logger.exception(
                "agent_action_unexpected_error",
                extra={"tool_name": action.tool_name, "intent": decision.intent.value},
            )
            return ActionOutcome(
                tool_name=action.tool_name,
                success=False,
                error_code="action_execution_failed",
                error_message="Eylem çalıştırılırken beklenmeyen bir hata oluştu.",
            )

        if not result.success:
            logger.warning(
                "agent_action_failed",
                extra={"tool_name": action.tool_name, "error_code": result.error_code},
            )
        return ActionOutcome.from_execution(result, arguments)
