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
from app.agent.prompts import build_council_source_block
from app.agent.runner import AgentRunner
from app.core.chat import ToolCall
from app.security.approvals import ApprovalService
from app.tools.base import PermissionLevel
from app.tools.executor import ToolExecutor
from app.council.gate import CouncilGate
from app.council.models import CouncilRequest, CouncilResult
from app.services.council_service import CouncilService

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
        council_service: CouncilService | None = None,
        council_gate: CouncilGate | None = None,
        approval_service: ApprovalService | None = None,
    ) -> None:
        """
        Args:
            context_builder: Sınırlandırılmış bağlamı üreten bileşen.
            policy: Bağlamdan karar üreten politika (deterministik veya ileride LLM).
            runner: Kararı ToolExecutor üzerinden yürüten bileşen.
            council_service: Çok modelli müzakere servisi. None ise Council
                hiç çalışmaz ve `AgentResult.council` her zaman None kalır.
            approval_service: Onay bekleyen eylemler için kayıt açan servis.
                Verilmezse ajan yine durur, ama kullanıcı yanıtlayacak bir
                istek göremez.
            council_gate: Council'ın ne zaman çalışacağına karar veren
                DETERMİNİSTİK kapı. Servis verilip kapı verilmezse Council
                yine çalışmaz — kapısız bir Council her mesajda çalışırdı.
        """
        self._context_builder = context_builder
        self._policy = policy
        self._runner = runner
        self._council_service = council_service
        self._council_gate = council_gate
        self._approval_service = approval_service

    @property
    def tool_executor(self) -> ToolExecutor:
        """Ajanın eylemlerinin geçtiği yürütme sınırı."""

        return self._runner.tool_executor

    @property
    def council_service(self) -> CouncilService | None:
        """Bağlı Council servisi; yoksa None."""

        return self._council_service

    def set_council(
        self, service: CouncilService | None, gate: CouncilGate | None
    ) -> None:
        """Council'ı kurucudan sonra bağlar veya değiştirir (geç bağlama).

        `ChatOrchestrator.set_*` metodlarıyla aynı kalıp ve aynı gerekçe:
        yönetim panelinden üye listesi değiştirildiğinde Council'ın yeniden
        kurulması gerekir ve bunun için uygulamayı yeniden başlatmak
        istenmez — sağlayıcı değişiminde de aynı beklenti vardı.

        Servis ve kapı BİRLİKTE atanır: kapısız bir Council her mesajda
        çalışırdı, servissiz bir kapı ise hiçbir şey açmazdı. İkisini ayrı
        ayrı atanabilir bırakmak, aralarında tutarsız bir ara duruma izin
        vermek olurdu.
        """
        self._council_service = service
        self._council_gate = gate

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
            result = await self._runner.execute(decision)
        except Exception:  # noqa: BLE001
            logger.exception(
                "agent_execution_failed",
                extra={"session_id": session_id, "intent": decision.intent.value},
            )
            return AgentResult(decision=decision, outcomes=[], status=AgentStatus.FAILED)

        self._open_pending_approvals(result, session_id)
        result.council = await self._run_council_safely(context, decision, result)
        return result

    def _open_pending_approvals(self, result: AgentResult, session_id: str | None) -> None:
        """Onay bekleyen her eylem için bir kayıt açar ve kimliğini işler.

        Kaydı runner değil bu katman açar: runner'ın işi eylemi yürütme
        sınırından geçirmektir, dış dünyayla koordinasyon değil.

        Kayıt açılamazsa eylem yine çalıştırılmamış kalır ve hata yalnızca
        loglanır. Onay altyapısındaki bir aksaklık, engellenmiş bir yazmanın
        aniden gerçekleşmesine yol açmamalıdır.
        """
        if self._approval_service is None:
            return
        for outcome in result.outcomes:
            if not outcome.requires_approval or outcome.approval_id:
                continue
            try:
                record = self._approval_service.request(
                    ToolCall(name=outcome.tool_name, arguments=outcome.arguments),
                    permission=PermissionLevel(outcome.permission),
                    session_id=session_id,
                    reason=outcome.error_message,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "agent_approval_request_failed",
                    extra={"tool_name": outcome.tool_name},
                )
                continue
            outcome.approval_id = record.approval_id

    # ------------------------------------------------------------------
    # Council
    # ------------------------------------------------------------------

    async def _run_council_safely(
        self, context: AgentContext, decision: AgentDecision, result: AgentResult
    ) -> CouncilResult | None:
        """Gerekliyse çok modelli müzakereyi çalıştırır; asla istisna sızdırmaz.

        Council YALNIZCA deterministik kapı açtığında çalışır. Kapı kapalıysa,
        servis bağlı değilse veya bir hata olursa None döner ve sistemin
        davranışı Council eklenmeden önceki hâliyle aynı kalır.

        Council'a `AgentContext` verilmez: bağlam ve tool sonuçları önceden
        sınırlandırılmış düz metne çevrilir. Böylece Council katmanı agent
        veri yapılarını hiç tanımaz.
        """
        if self._council_service is None or self._council_gate is None:
            return None

        try:
            gate_decision = self._council_gate.evaluate(
                user_message=context.user_message, intent=decision.intent.value
            )
            if not gate_decision.run:
                logger.debug(
                    "council_skipped",
                    extra={"reason": gate_decision.reason, "session_id": context.session_id},
                )
                return None

            council_result = await self._council_service.deliberate(
                CouncilRequest(
                    task=context.user_message,
                    context_block=build_council_source_block(context, result),
                    session_id=context.session_id,
                ),
                trigger=gate_decision.trigger,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "council_invocation_failed", extra={"session_id": context.session_id}
            )
            return None

        logger.info(
            "council_finished",
            extra={
                "status": council_result.status.value,
                "candidate_count": len(council_result.successful_candidates),
                "review_count": len(council_result.reviews),
                "session_id": context.session_id,
            },
        )
        return council_result

    def _fallback_decision(self) -> AgentDecision:
        """Agent kullanılamadığında üretilen kontrollü geri çekilme kararı."""
        return AgentDecision(
            intent=Intent.UNKNOWN,
            actions=[],
            reason=_FALLBACK_REASON,
            policy=getattr(self._policy, "name", "unknown"),
        )
