"""LLM tabanlı karar politikası.

`DecisionPolicy` Protocol'ünün ikinci implementasyonudur; `RuleBasedDecisionPolicy`
yerini ALMAZ, onun yanında yaşar ve hangisinin kullanılacağı bağımlılık
enjeksiyonuyla seçilir.

Akış:

    AgentContext → prompt → LLMProvider.generate() → ham metin
                                                        ↓
                                          _parse_decision_payload()
                                                        ↓
                                     _DecisionCandidate (katı pydantic)
                                                        ↓
                                        deterministik doğrulama
                                                        ↓
                                              AgentDecision

Mimari kurallar:
- MEVCUT sağlayıcı soyutlaması kullanılır: `app.adapters.llm.base.LLMProvider`.
  İkinci bir LLM istemcisi veya sağlayıcıya özgü kod YOKTUR; bu modül hiçbir
  HTTP çağrısı yapmaz, hiçbir API anahtarı görmez.
- LLM ÇIKTISI VERİDİR, talimat değil. Hiçbir alanına körü körüne güvenilmez:
  * tool adı `AgentContext.available_tools` üzerinden doğrulanır,
  * argüman anahtarları tool'un input şemasına karşı denetlenir,
  * `requires_confirmation` LLM'den HİÇ OKUNMAZ — bağlamdaki tool tanımından
    yeniden hesaplanır (kullanıcı veya model "onay gerekmiyor" diyerek
    güvenlik sınırını gevşetemez),
  * izin kontrolü ve tam şema doğrulaması `ToolExecutor` içinde yapılır ve
    bu politika o sınırı atlamaz.
- Politika HİÇBİR ZAMAN istisna fırlatmaz. Sağlayıcı hatası, bozuk JSON,
  bilinmeyen intent, kayıtlı olmayan tool, eylem sınırı aşımı — hepsinde
  kontrollü geri çekilme yapılır (varsa yedek politika, yoksa CONVERSATION).
- Gizli akıl yürütme saklanmaz: modelden yalnızca kısa, olgusal bir `reason`
  istenir ve uzunluğu şemayla sınırlandırılır.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.llm.base import LLMProvider, LLMProviderError
from app.agent.context import AgentContext
from app.agent.models import AgentAction, AgentDecision, Intent
from app.agent.policy import DecisionPolicy
from app.agent.prompts import build_decision_messages
from app.agent.validation import arguments_match_schema, references_point_backwards

logger = logging.getLogger(__name__)

MAX_ACTIONS = 4
"""Tek bir planda izin verilen maksimum eylem sayısı.

Sınırsız plan, sınırsız tool döngüsü demektir. Sabit, mevcut
`ChatOrchestrator.max_tool_rounds` varsayılanıyla (4) aynı ruhta seçildi.
Sınırı aşan bir plan kırpılmaz — reddedilir ve geri çekilme yapılır, çünkü
bir planı sessizce kısaltmak kullanıcının isteğini sessizce değiştirmektir.
"""

_MAX_REASON_LENGTH = 300

# Geri çekilme sebepleri (gözlemlenebilirlik için kararlı etiketler).
FALLBACK_PROVIDER_FAILED = "provider_failed"
FALLBACK_UNPARSABLE = "unparsable_output"
FALLBACK_INVALID_SCHEMA = "invalid_schema"
FALLBACK_UNKNOWN_INTENT = "unknown_intent"
FALLBACK_UNKNOWN_TOOL = "unknown_tool"
FALLBACK_INVALID_ARGUMENTS = "invalid_arguments"
FALLBACK_TOO_MANY_ACTIONS = "too_many_actions"


class _ActionCandidate(BaseModel):
    """LLM'den gelen tek bir eylem adayı için katı doğrulama şeması."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: str = Field(default="", max_length=200)


class _DecisionCandidate(BaseModel):
    """LLM'den gelen kararın katı doğrulama şeması.

    `extra="forbid"`: modelin uydurduğu ek alanlar (ör. kendi kendine verdiği
    izinler) sessizce kabul edilmez, karar tamamen reddedilir.
    """

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=64)
    actions: list[_ActionCandidate] = Field(default_factory=list)
    reason: str = Field(default="", max_length=_MAX_REASON_LENGTH)


def parse_decision_payload(raw_text: str) -> dict[str, Any] | None:
    """LLM'in ham metninden karar nesnesini çıkarır; başarısızsa None.

    Hata fırlatmaz. Markdown kod bloğu sarmalayıcısı temizlenir — mevcut
    `MemoryExtractor` çıktısında da görülen yaygın model davranışıdır.
    """
    if not raw_text or not raw_text.strip():
        return None

    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.debug("agent_decision_json_parse_failed", extra={"length": len(raw_text)})
        return None

    if not isinstance(parsed, dict):
        logger.debug("agent_decision_json_not_object", extra={"type": type(parsed).__name__})
        return None
    return parsed


class LLMDecisionPolicy:
    """Kararı bir LLM'e verdirir, ardından deterministik olarak doğrular."""

    name = "llm"

    def __init__(
        self,
        *,
        provider: LLMProvider,
        fallback: DecisionPolicy | None = None,
        max_actions: int = MAX_ACTIONS,
        model_label: str | None = None,
    ) -> None:
        """
        Args:
            provider: MEVCUT sağlayıcı soyutlaması. Somut sınıf (Ollama vb.)
                bu katmana sızmaz; yalnızca `generate()` çağrılır.
            fallback: LLM kullanılamadığında veya çıktısı reddedildiğinde
                devreye girecek politika (tipik olarak `RuleBasedDecisionPolicy`).
                Verilmezse geri çekilme `Intent.CONVERSATION` üretir.
            max_actions: Bir planda izin verilen maksimum eylem sayısı.
            model_label: Loglara yazılacak model/sağlayıcı etiketi. Gizli
                bilgi İÇERMEMELİDİR (API anahtarı, uç nokta kimlik bilgisi vb.).
        """
        self._provider = provider
        self._fallback = fallback
        self._max_actions = max_actions
        self._model_label = model_label

    async def decide(self, context: AgentContext) -> AgentDecision:
        """Bağlam için LLM'den karar alır ve doğrulanmış hâlini döndürür."""
        raw = await self._ask_provider(context)
        if raw is None:
            return await self._fallback_to(context, FALLBACK_PROVIDER_FAILED)

        payload = parse_decision_payload(raw)
        if payload is None:
            return await self._fallback_to(context, FALLBACK_UNPARSABLE)

        try:
            candidate = _DecisionCandidate.model_validate(payload)
        except ValidationError:
            logger.warning("agent_decision_rejected", extra={"reason": FALLBACK_INVALID_SCHEMA})
            return await self._fallback_to(context, FALLBACK_INVALID_SCHEMA)

        decision, rejection = self._validate(candidate, context)
        if decision is None:
            return await self._fallback_to(context, rejection or FALLBACK_INVALID_SCHEMA)

        logger.info(
            "agent_decision",
            extra={
                "policy": self.name,
                "model": self._model_label,
                "intent": decision.intent.value,
                "action_count": len(decision.actions),
                "selected_tools": [action.tool_name for action in decision.actions],
                "requires_confirmation": decision.requires_confirmation,
                "session_id": context.session_id,
            },
        )
        return decision

    # ------------------------------------------------------------------
    # Sağlayıcı çağrısı
    # ------------------------------------------------------------------

    async def _ask_provider(self, context: AgentContext) -> str | None:
        """Karar turunu çalıştırır; sağlayıcı hatasında None döner.

        `generate()` kullanılır, `generate_with_tools()` DEĞİL: burada amaç
        tool ÇAĞIRMAK değil, hangi tool'ların gerektiğine dair yapılandırılmış
        bir plan almaktır. Yürütme yalnızca `ToolExecutor` üzerinden yapılır.
        """
        try:
            return await self._provider.generate(build_decision_messages(context))
        except LLMProviderError as exc:
            logger.warning("agent_decision_provider_failed", extra={"error": str(exc)})
            return None
        except Exception:  # noqa: BLE001
            logger.exception("agent_decision_provider_unexpected_error")
            return None

    # ------------------------------------------------------------------
    # Deterministik doğrulama
    # ------------------------------------------------------------------

    def _validate(
        self, candidate: _DecisionCandidate, context: AgentContext
    ) -> tuple[AgentDecision | None, str | None]:
        """Adayı doğrular. Kabul edilirse (karar, None), aksi halde (None, sebep)."""
        intent = _parse_intent(candidate.intent)
        if intent is None:
            logger.warning(
                "agent_decision_rejected",
                extra={"reason": FALLBACK_UNKNOWN_INTENT, "value": candidate.intent[:64]},
            )
            return None, FALLBACK_UNKNOWN_INTENT

        if len(candidate.actions) > self._max_actions:
            logger.warning(
                "agent_decision_rejected",
                extra={
                    "reason": FALLBACK_TOO_MANY_ACTIONS,
                    "action_count": len(candidate.actions),
                    "max_actions": self._max_actions,
                },
            )
            return None, FALLBACK_TOO_MANY_ACTIONS

        actions: list[AgentAction] = []
        for index, raw_action in enumerate(candidate.actions):
            descriptor = context.tool(raw_action.tool)
            if descriptor is None:
                logger.warning(
                    "agent_decision_rejected",
                    extra={"reason": FALLBACK_UNKNOWN_TOOL, "tool_name": raw_action.tool[:64]},
                )
                return None, FALLBACK_UNKNOWN_TOOL

            if not _arguments_match_schema(raw_action.arguments, descriptor.input_schema):
                logger.warning(
                    "agent_decision_rejected",
                    extra={
                        "reason": FALLBACK_INVALID_ARGUMENTS,
                        "tool_name": descriptor.name,
                    },
                )
                return None, FALLBACK_INVALID_ARGUMENTS

            if not _references_point_backwards(raw_action.arguments, index):
                logger.warning(
                    "agent_decision_rejected",
                    extra={
                        "reason": FALLBACK_INVALID_ARGUMENTS,
                        "tool_name": descriptor.name,
                    },
                )
                return None, FALLBACK_INVALID_ARGUMENTS

            actions.append(
                AgentAction(
                    tool_name=descriptor.name,
                    arguments=raw_action.arguments,
                    purpose=raw_action.purpose.strip() or f"{descriptor.name} çalıştır.",
                    # GÜVENLİK: onay gereksinimi LLM'den DEĞİL, bağlamdaki
                    # tool tanımından alınır. Model bunu gevşetemez.
                    requires_confirmation=descriptor.requires_confirmation,
                )
            )

        if intent is Intent.CONVERSATION and actions:
            # Tutarsız çıktı: "konuşma" diyip eylem planlamak. Reddet.
            logger.warning(
                "agent_decision_rejected",
                extra={"reason": FALLBACK_INVALID_SCHEMA, "detail": "conversation_with_actions"},
            )
            return None, FALLBACK_INVALID_SCHEMA

        reason = candidate.reason.strip() or "LLM politikası karar üretti."
        return (
            AgentDecision(
                intent=intent,
                actions=actions,
                reason=reason[:_MAX_REASON_LENGTH],
                policy=self.name,
            ),
            None,
        )

    # ------------------------------------------------------------------
    # Geri çekilme
    # ------------------------------------------------------------------

    async def _fallback_to(self, context: AgentContext, reason: str) -> AgentDecision:
        """Yedek politikaya düşer; yoksa güvenli bir konuşma kararı üretir."""
        logger.info(
            "agent_decision_fallback",
            extra={
                "policy": self.name,
                "model": self._model_label,
                "failure_category": reason,
                "session_id": context.session_id,
                "has_fallback": self._fallback is not None,
            },
        )
        if self._fallback is not None:
            try:
                return await self._fallback.decide(context)
            except Exception:  # noqa: BLE001
                logger.exception("agent_decision_fallback_failed")

        return AgentDecision(
            intent=Intent.CONVERSATION,
            actions=[],
            reason="Karar üretilemedi; normal sohbet cevabı verilecek.",
            policy=self.name,
        )


# ---------------------------------------------------------------------------
# Modül düzeyi yardımcılar (test edilebilirlik için dışa aktarılır)
# ---------------------------------------------------------------------------


def _parse_intent(raw: str) -> Intent | None:
    """Metni bilinen bir Intent'e çevirir; tanınmazsa None.

    Kapalı küme bilinçlidir: model keyfi bir amaç uyduramaz.
    """
    normalized = raw.strip().lower()
    try:
        return Intent(normalized)
    except ValueError:
        return None


# Doğrulama yardımcıları `app.agent.validation`'da tek kez tanımlıdır; burada
# yalnızca yerel adlarla kullanılır. Aynı denetim kodlama planlayıcısında da
# gerekiyor ve iki kopya bırakılsaydı biri sıkılaştırıldığında diğeri sessizce
# zayıf kalırdı.
_arguments_match_schema = arguments_match_schema
_references_point_backwards = references_point_backwards
