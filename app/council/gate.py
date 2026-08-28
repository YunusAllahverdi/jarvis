"""Council'ın ne zaman çalışacağına dair DETERMİNİSTİK karar.

Neden ayrı bir bileşen?
    "Council gerekli mi?" sorusunu bir LLM'e sormak, Council'ın tasarrufunu
    amaçladığı maliyeti geri getirir ve kararı denetlenemez kılar. Bu yüzden
    kapı tamamen deterministiktir: LLM ÇAĞIRMAZ, karmaşıklık puanlaması
    YAPMAZ, açık ve okunabilir koşullara dayanır.

Bu fazdaki koşullar bilinçli olarak DARDIR:
1. Council yapılandırmada etkin olmalı,
2. Yeterli sayıda üye yapılandırılmış olmalı,
3. ve ya kullanıcı açıkça birden fazla görüş istemeli, ya da kararın amacı
   yapılandırılmış tetikleyici kümesinde olmalı.

Kapı emin değilse ÇALIŞTIRMAZ. Council pahalıdır; şüphede kalındığında
normal tek-LLM yolu doğru varsayılandır.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.council.models import CouncilGateDecision, CouncilTrigger

logger = logging.getLogger(__name__)

_EXPLICIT_CUES: tuple[str, ...] = (
    "council",
    "farklı modellere sor",
    "farkli modellere sor",
    "birden fazla model",
    "modellere danış",
    "modellere danis",
    "birkaç görüş",
    "birkac gorus",
    "ikinci bir görüş",
    "ikinci bir gorus",
    "ask multiple models",
    "second opinion",
    "compare and synthesize",
    "compare and synthesise",
)
"""Kullanıcının Council'ı açıkça istediğini gösteren dar kalıplar."""


class CouncilGate:
    """Deterministik Council tetikleme kapısı."""

    def __init__(
        self,
        *,
        enabled: bool,
        member_count: int,
        min_candidates: int,
        trigger_intents: Sequence[str] = (),
    ) -> None:
        """
        Args:
            enabled: `council_enabled` ayarı.
            member_count: Yapılandırılmış üye sayısı.
            min_candidates: Anlamlı bir müzakere için gereken minimum aday.
            trigger_intents: Council'ı tetikleyen amaç değerleri (ör.
                `("information_request",)`). Boş bırakılırsa yalnızca açık
                kullanıcı isteği Council'ı tetikler.
        """
        self._enabled = enabled
        self._member_count = member_count
        self._min_candidates = min_candidates
        self._trigger_intents = frozenset(trigger_intents)

    def evaluate(self, *, user_message: str, intent: str | None = None) -> CouncilGateDecision:
        """Council'ın bu istek için çalışıp çalışmayacağına karar verir.

        Hiçbir zaman istisna fırlatmaz ve hiçbir yan etkisi yoktur.
        """
        if not self._enabled:
            return CouncilGateDecision(run=False, reason="Council yapılandırmada kapalı.")

        if self._member_count < self._min_candidates:
            return CouncilGateDecision(
                run=False,
                reason=(
                    f"Yapılandırılmış üye sayısı ({self._member_count}) minimum aday "
                    f"eşiğinin ({self._min_candidates}) altında."
                ),
            )

        if _has_explicit_cue(user_message):
            return self._run(
                CouncilTrigger.EXPLICIT_REQUEST,
                "Kullanıcı açıkça birden fazla modelin görüşünü istedi.",
            )

        if intent is not None and intent in self._trigger_intents:
            return self._run(
                CouncilTrigger.INTENT,
                f"Kararın amacı ({intent}) Council tetikleyicileri arasında.",
            )

        return CouncilGateDecision(
            run=False, reason="Deterministik bir Council tetikleyicisi eşleşmedi."
        )

    def _run(self, trigger: CouncilTrigger, reason: str) -> CouncilGateDecision:
        logger.info("council_gate_open", extra={"trigger": trigger.value})
        return CouncilGateDecision(run=True, reason=reason, trigger=trigger)


def _has_explicit_cue(message: str) -> bool:
    normalized = message.strip().lower()
    return any(cue in normalized for cue in _EXPLICIT_CUES)
