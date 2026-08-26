"""Agent karar katmanının dış cephesi (facade).

Zinciri tek bir yerde birleştirir:

    ContextBuilder → DecisionPolicy → AgentRunner → AgentResult

Mimari kurallar:
- Bu servis HİÇBİR ZAMAN istisna fırlatmaz. Zincirin herhangi bir yerinde
  beklenmedik bir hata olursa `Intent.UNKNOWN` ve `AgentStatus.FAILED` taşıyan
  yapılandırılmış bir sonuç döner. Çağıran (API veya ileride sohbet akışı)
  bu durumda normal cevap yoluna güvenle düşebilir — kontrollü geri çekilme.
- Somut bir tool, depo veya sağlayıcı bilmez; yalnızca kendisine verilen
  bileşenleri kullanır (dependency injection).
- Sohbet akışının PARÇASI DEĞİLDİR. ChatOrchestrator bu servisi tanımaz;
  bu sayede agent katmanındaki bir sorun normal sohbeti hiçbir koşulda
  etkileyemez.
"""

from __future__ import annotations

import logging

from app.agent.context import AgentContext, ContextBuilder
from app.agent.models import AgentDecision, AgentResult, AgentStatus, Intent
from app.agent.policy import DecisionPolicy
from app.agent.runner import AgentRunner

logger = logging.getLogger(__name__)

_FALLBACK_REASON = "Agent katmanı bu isteği işleyemedi; normal cevap yoluna düşülmeli."


class AgentService:
    """Bir kullanıcı mesajı için bağlam kurar, karar verir ve yürütür."""

    def __init__(
        self,
        *,
        context_builder: ContextBuilder,
        policy: DecisionPolicy,
        runner: AgentRunner,
    ) -> None:
        """
        Args:
            context_builder: Sınırlandırılmış bağlamı üreten bileşen.
            policy: Bağlamdan karar üreten politika (deterministik veya ileride LLM).
            runner: Kararı ToolExecutor üzerinden yürüten bileşen.
        """
        self._context_builder = context_builder
        self._policy = policy
        self._runner = runner

    def build_context(self, user_message: str, *, session_id: str | None = None) -> AgentContext:
        """Yalnızca bağlamı kurar (karar vermez, yürütmez).

        Hata ayıklama ve test için kullanışlıdır; yan etkisizdir.
        """
        return self._context_builder.build(user_message, session_id=session_id)

    async def decide(
        self, user_message: str, *, session_id: str | None = None
    ) -> AgentDecision:
        """Karar üretir ama HİÇBİR eylemi yürütmez.

        Hiçbir zaman istisna fırlatmaz; hata durumunda `Intent.UNKNOWN` döner.
        """
        try:
            context = self._context_builder.build(user_message, session_id=session_id)
            return await self._policy.decide(context)
        except Exception:  # noqa: BLE001
            logger.exception("agent_decision_failed", extra={"session_id": session_id})
            return self._fallback_decision()

    async def run(self, user_message: str, *, session_id: str | None = None) -> AgentResult:
        """Karar verir ve kararı yürütür.

        Hiçbir zaman istisna fırlatmaz; hata durumunda `AgentStatus.FAILED`
        taşıyan yapılandırılmış bir sonuç döner.
        """
        try:
            context = self._context_builder.build(user_message, session_id=session_id)
            decision = await self._policy.decide(context)
        except Exception:  # noqa: BLE001
            logger.exception("agent_decision_failed", extra={"session_id": session_id})
            return AgentResult(
                decision=self._fallback_decision(), outcomes=[], status=AgentStatus.FAILED
            )

        try:
            return await self._runner.execute(decision)
        except Exception:  # noqa: BLE001
            logger.exception(
                "agent_execution_failed",
                extra={"session_id": session_id, "intent": decision.intent.value},
            )
            return AgentResult(decision=decision, outcomes=[], status=AgentStatus.FAILED)

    def _fallback_decision(self) -> AgentDecision:
        """Agent kullanılamadığında üretilen kontrollü geri çekilme kararı."""
        return AgentDecision(
            intent=Intent.UNKNOWN,
            actions=[],
            reason=_FALLBACK_REASON,
            policy=getattr(self._policy, "name", "unknown"),
        )
