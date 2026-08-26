"""Karar politikaları: bağlamdan yapılandırılmış bir `AgentDecision` üretme.

Mimari kurallar:
- `DecisionPolicy` küçük bir Protocol'dür. İleride LLM tabanlı bir politika
  eklendiğinde bu sözleşme değişmez; sağlayıcıya özgü hiçbir kod bu katmana
  girmez ve mevcut `LLMProvider` soyutlaması yeniden kullanılır.
- `decide()` bilinçli olarak ASENKRONDUR. Deterministik politika için gereksiz
  görünür, ama ileride bir LLM politikası eklendiğinde tüm zincirin (servis,
  runner, API) imzasını değiştirmek gerekmesin diye baştan böyle tanımlandı.
- Deterministik yol tercih edilir: LLM'siz karar verilebilen durumlarda LLM
  çağrılmaz.
- Bir politika ASLA emin olmadığı bir eylem uydurmaz. Kural eşleşmezse
  `Intent.CONVERSATION` döner ve çağıran normal sohbet cevabına düşer.
- Bir politika yalnızca bağlamda MEVCUT olan tool'lar için eylem planlayabilir;
  kayıtlı olmayan bir tool'a çağrı planlamak sessiz bir başarısızlık olurdu.

`RuleBasedDecisionPolicy` KASITLI OLARAK DARDIR. Bu bir doğal dil anlama
motoru değildir; yalnızca birkaç açık, okunabilir ve test edilebilir kalıbı
tanır. Amacı her isteği yakalamak değil, yakaladığında DOĞRU olmaktır —
tanımadığı her şeyi normal sohbete devreder.
"""

from __future__ import annotations

import logging
import re
from typing import Protocol, runtime_checkable

from app.agent.context import AgentContext
from app.agent.models import AgentAction, AgentDecision, Intent

logger = logging.getLogger(__name__)

# Tool adları — sabitler olarak tutulur, kodun içine dağılmış "magic string" yok.
TOOL_CALCULATOR = "calculator"
TOOL_GET_TIME = "get_time"
TOOL_GET_DATE = "get_date"
TOOL_SYSTEM_STATUS = "system_status"
TOOL_MEMORY_SEARCH = "memory_search"
TOOL_USER_PROFILE = "user_profile"


@runtime_checkable
class DecisionPolicy(Protocol):
    """Bağlamdan karar üreten değiştirilebilir sözleşme."""

    name: str
    """Kararın kaynağını görünür kılan kısa politika adı."""

    async def decide(self, context: AgentContext) -> AgentDecision:
        """Verilen bağlam için yapılandırılmış bir karar üretir."""
        ...


# ---------------------------------------------------------------------------
# Kalıplar
# ---------------------------------------------------------------------------

_ARITHMETIC_RE = re.compile(
    r"\d+(?:[.,]\d+)?(?:\s*[+\-*/%^]\s*\(?\s*\d+(?:[.,]\d+)?\s*\)?)+"
)
"""En az bir ikili işlem içeren sayısal ifade (tek başına "25" eşleşmez)."""

_CALC_CUES = (
    "kaç eder", "kaçtır", "hesapla", "hesaplar mısın",
    "what is", "what's", "calculate", "compute", "how much is",
)

_TIME_CUES = ("saat kaç", "saati söyle", "what time", "current time", "saat kaçta")
_DATE_CUES = (
    "bugün ayın kaçı", "bugünün tarihi", "hangi gündeyiz", "tarih ne",
    "what date", "what day", "today's date", "current date",
)
_SYSTEM_CUES = (
    "sistem durumu", "sistem raporu", "system status", "diagnostics",
    "cpu kullanımı", "ram kullanımı", "disk kullanımı",
)
_RECALL_CUES = (
    "ne biliyorsun", "neler biliyorsun", "hakkımda ne", "beni tanıyor musun",
    "hatırlıyor musun", "ne hatırlıyorsun", "neler hatırlıyorsun",
    "neye odaklan", "nelere odaklan", "son zamanlarda ne",
    "what do you know about me", "what do you remember",
    "what have i been", "what am i focusing",
)

_EXPRESSION_COVERAGE_THRESHOLD = 0.6
"""İfadenin mesajın ne kadarını kaplaması gerektiği (ipucu yoksa).

Bu eşik yanlış pozitifleri engeller: "5-3 arası bir sayı söyle" cümlesinde
bir aritmetik kalıp bulunsa da mesajın çoğu başka bir isteği anlatır, bu
yüzden hesaplama kararı verilmez.
"""


def _normalize(message: str) -> str:
    return message.strip().lower()


def _contains_any(message: str, cues: tuple[str, ...]) -> bool:
    return any(cue in message for cue in cues)


def extract_arithmetic_expression(message: str) -> str | None:
    """Mesajdan güvenle hesaplanabilir bir aritmetik ifade çıkarır.

    İfade yalnızca şu durumlarda döndürülür:
    - mesajda açık bir hesaplama ipucu varsa ("kaç eder", "what is", ...), veya
    - bulunan ifade mesajın büyük bölümünü kaplıyorsa (yani mesaj zaten
      esasen bir işlemden ibaretse).

    Aksi halde None döner ve hesaplama kararı VERİLMEZ.
    """
    normalized = _normalize(message)
    match = _ARITHMETIC_RE.search(normalized)
    if match is None:
        return None

    expression = match.group().strip()
    if _contains_any(normalized, _CALC_CUES):
        return expression

    stripped_message = re.sub(r"[\s?!.]+", "", normalized)
    stripped_expression = re.sub(r"\s+", "", expression)
    if not stripped_message:
        return None
    coverage = len(stripped_expression) / len(stripped_message)
    return expression if coverage >= _EXPRESSION_COVERAGE_THRESHOLD else None


# ---------------------------------------------------------------------------
# Deterministik politika
# ---------------------------------------------------------------------------


class RuleBasedDecisionPolicy:
    """LLM kullanmadan, açık kalıplarla karar veren deterministik politika.

    Aynı bağlam her zaman aynı kararı üretir. Tanımadığı her isteği
    `Intent.CONVERSATION` olarak devreder — asla eylem uydurmaz.
    """

    name = "rule_based"

    async def decide(self, context: AgentContext) -> AgentDecision:
        """Bağlamdan deterministik bir karar üretir."""
        message = _normalize(context.user_message)

        for rule in (
            self._decide_calculate,
            self._decide_recall,
            self._decide_time,
            self._decide_date,
            self._decide_system_status,
        ):
            decision = rule(context, message)
            if decision is not None:
                logger.info(
                    "agent_decision",
                    extra={
                        "policy": self.name,
                        "intent": decision.intent.value,
                        "action_count": len(decision.actions),
                        "requires_confirmation": decision.requires_confirmation,
                        "session_id": context.session_id,
                    },
                )
                return decision

        return self._conversation(
            "Deterministik bir kural eşleşmedi; normal sohbet cevabı yeterli."
        )

    # ------------------------------------------------------------------
    # Kurallar
    # ------------------------------------------------------------------

    def _decide_calculate(self, context: AgentContext, message: str) -> AgentDecision | None:
        expression = extract_arithmetic_expression(message)
        if expression is None or not context.has_tool(TOOL_CALCULATOR):
            return None
        return self._single(
            context,
            intent=Intent.CALCULATE,
            tool_name=TOOL_CALCULATOR,
            arguments={"expression": expression.replace(",", ".")},
            purpose="Kullanıcının sorduğu aritmetik ifadeyi hesapla.",
            reason="Mesajda hesaplanabilir bir aritmetik ifade tespit edildi.",
        )

    def _decide_recall(self, context: AgentContext, message: str) -> AgentDecision | None:
        """Çok adımlı örnek: hem belleği hem kullanıcı modelini getir.

        Adımlar arasında veri akışı YOKTUR; her adım bağımsız çalışır ve
        sonuçların yorumlanması çağırana bırakılır. Adım çıktısını bir sonraki
        adımın girdisine bağlayan gerçek bir planlayıcı sonraki bir fazın
        konusudur.
        """
        if not _contains_any(message, _RECALL_CUES):
            return None

        actions: list[AgentAction] = []
        if context.has_tool(TOOL_MEMORY_SEARCH):
            actions.append(
                self._action(
                    context,
                    TOOL_MEMORY_SEARCH,
                    {"query": context.user_message},
                    "Kullanıcıyla ilgili saklanmış bellek kayıtlarını getir.",
                )
            )
        if context.has_tool(TOOL_USER_PROFILE):
            actions.append(
                self._action(
                    context,
                    TOOL_USER_PROFILE,
                    {},
                    "Kullanıcı hakkında öğrenilmiş kalıcı örüntüleri getir.",
                )
            )

        if not actions:
            return None
        return AgentDecision(
            intent=Intent.RECALL,
            actions=actions,
            reason="Kullanıcı kendisi hakkında bilinenleri sordu.",
            policy=self.name,
        )

    def _decide_time(self, context: AgentContext, message: str) -> AgentDecision | None:
        if not _contains_any(message, _TIME_CUES) or not context.has_tool(TOOL_GET_TIME):
            return None
        return self._single(
            context,
            intent=Intent.GET_TIME,
            tool_name=TOOL_GET_TIME,
            arguments={},
            purpose="Mevcut sistem saatini oku.",
            reason="Mesajda saat sorgusu tespit edildi.",
        )

    def _decide_date(self, context: AgentContext, message: str) -> AgentDecision | None:
        if not _contains_any(message, _DATE_CUES) or not context.has_tool(TOOL_GET_DATE):
            return None
        return self._single(
            context,
            intent=Intent.GET_DATE,
            tool_name=TOOL_GET_DATE,
            arguments={},
            purpose="Mevcut sistem tarihini oku.",
            reason="Mesajda tarih sorgusu tespit edildi.",
        )

    def _decide_system_status(
        self, context: AgentContext, message: str
    ) -> AgentDecision | None:
        if not _contains_any(message, _SYSTEM_CUES) or not context.has_tool(TOOL_SYSTEM_STATUS):
            return None
        return self._single(
            context,
            intent=Intent.SYSTEM_STATUS,
            tool_name=TOOL_SYSTEM_STATUS,
            arguments={},
            purpose="Sistem kaynak kullanımını oku.",
            reason="Mesajda sistem durumu sorgusu tespit edildi.",
        )

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def _action(
        self,
        context: AgentContext,
        tool_name: str,
        arguments: dict,
        purpose: str,
    ) -> AgentAction:
        """Eylemi, tool'un bu oturumdaki onay gereksinimiyle birlikte kurar."""
        descriptor = context.tool(tool_name)
        return AgentAction(
            tool_name=tool_name,
            arguments=arguments,
            purpose=purpose,
            requires_confirmation=bool(descriptor and descriptor.requires_confirmation),
        )

    def _single(
        self,
        context: AgentContext,
        *,
        intent: Intent,
        tool_name: str,
        arguments: dict,
        purpose: str,
        reason: str,
    ) -> AgentDecision:
        return AgentDecision(
            intent=intent,
            actions=[self._action(context, tool_name, arguments, purpose)],
            reason=reason,
            policy=self.name,
        )

    def _conversation(self, reason: str) -> AgentDecision:
        return AgentDecision(
            intent=Intent.CONVERSATION,
            actions=[],
            reason=reason,
            policy=self.name,
        )
