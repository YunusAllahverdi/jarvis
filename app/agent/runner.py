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

Bilinen sınırlama — ADIMLAR ARASI VERİ AKIŞI YOK:
    Çok adımlı bir planda adımlar sırayla çalışır ama bir adımın çıktısı bir
    sonraki adımın girdisine BAĞLANMAZ. Bu bilinçlidir: gerçek bir planlayıcı
    (bağımlılık grafiği, koşullu dallanma) sonraki bir fazın konusudur ve
    burada sahte bir yerine koyma mekanizması uydurulmadı.
"""

from __future__ import annotations

import logging

from app.agent.models import ActionOutcome, AgentDecision, AgentResult, AgentStatus, status_for
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
                outcomes=[
                    ActionOutcome(tool_name=action.tool_name, skipped=True)
                    for action in decision.actions
                ],
                status=AgentStatus.PENDING_CONFIRMATION,
            )

        outcomes = [await self._execute_action(decision, action) for action in decision.actions]
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

    async def _execute_action(self, decision: AgentDecision, action) -> ActionOutcome:  # noqa: ANN001
        """Tek bir eylemi yürütür; hiçbir hata dışarı sızmaz."""
        try:
            result = await self._tool_executor.execute(action.as_tool_call())
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
        return ActionOutcome(
            tool_name=result.tool_name,
            success=result.success,
            data=result.data,
            error_code=result.error_code,
            error_message=result.error_message,
        )
