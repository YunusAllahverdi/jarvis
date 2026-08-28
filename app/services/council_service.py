"""Council'ın dış cephesi (facade).

Üç aşamayı tek bir müzakerede birleştirir:

    Stage 1 (bağımsız görüşler) → Stage 2 (akran değerlendirmesi) → Stage 3 (Chairman)

Mimari kurallar:
- Bu servis HİÇBİR ZAMAN istisna fırlatmaz. Her başarısızlık yapılandırılmış
  bir `CouncilResult` olarak döner; çağıran (AgentService) normal yola güvenle
  düşebilir. Bir Council hatası sohbeti asla 500'e düşüremez.
- YALNIZCA `LLMProvider` soyutlamasına bağımlıdır. `ToolRegistry`,
  `ToolExecutor`, `AgentRunner` ve `AgentService` import EDİLMEZ —
  Council → Agent → Council özyinelemesi yapısal olarak imkânsızdır.
- Chairman çıktısı kullanıcıya DOĞRUDAN dönmez; çağıran onu sınırlanmış veri
  olarak normal cevap üretimine aktarır.
- Chairman başarısız olursa en yüksek skorlu aday kullanıcıya verilmez:
  sonuç `FAILED` olur ve sistem normal tek-LLM cevabına düşer. Yarım
  sentezlenmiş içerik sunmaktansa normal cevap yolu tercih edilir.
"""

from __future__ import annotations

import asyncio
import logging

from app.council.anonymizer import LabelMap
from app.council.models import (
    CouncilMember,
    CouncilRequest,
    CouncilResult,
    CouncilStatus,
    CouncilTrigger,
)
from app.council.stages import (
    run_candidate_stage,
    run_chairman_stage,
    run_review_stage,
)

logger = logging.getLogger(__name__)

FAILURE_NO_MEMBERS = "no_members"
FAILURE_INSUFFICIENT_CANDIDATES = "insufficient_candidates"
FAILURE_CHAIRMAN = "chairman_failed"
FAILURE_TOTAL_TIMEOUT = "total_timeout"
FAILURE_UNEXPECTED = "unexpected_error"


class CouncilService:
    """Birden fazla modelin bir görevi birlikte cevaplamasını yönetir."""

    def __init__(
        self,
        *,
        members: list[CouncilMember],
        chairman: CouncilMember,
        min_candidates: int = 2,
        review_enabled: bool = True,
        member_timeout_seconds: float = 60.0,
        total_timeout_seconds: float = 180.0,
        max_concurrency: int = 3,
        max_candidate_chars: int = 4000,
        max_review_chars: int = 2000,
    ) -> None:
        """
        Args:
            members: Council üyeleri. Her biri kendi `LLMProvider` örneğini
                taşır; model adı bu katmana hiç ulaşmaz.
            chairman: Sentezi üretecek üye. Üyelerden biri olabilir (aynı
                sağlayıcı örneği yeniden kullanılır).
            min_candidates: Sentez denenmesi için gereken minimum başarılı aday.
            review_enabled: Stage 2 çalıştırılsın mı.
            member_timeout_seconds: Üye başına LLM çağrısı timeout'u.
            total_timeout_seconds: Tüm müzakere için üst sınır.
            max_concurrency: Aynı anda çalışacak maksimum LLM çağrısı.
            max_candidate_chars: Prompt'a gömülürken aday cevabı sınırı.
            max_review_chars: Prompt'a gömülürken inceleme sınırı.
        """
        self._members = members
        self._chairman = chairman
        self._min_candidates = min_candidates
        self._review_enabled = review_enabled
        self._member_timeout_seconds = member_timeout_seconds
        self._total_timeout_seconds = total_timeout_seconds
        self._max_concurrency = max_concurrency
        self._max_candidate_chars = max_candidate_chars
        self._max_review_chars = max_review_chars

    @property
    def member_count(self) -> int:
        return len(self._members)

    async def deliberate(
        self, request: CouncilRequest, *, trigger: CouncilTrigger | None = None
    ) -> CouncilResult:
        """Tam bir müzakere yürütür ve yapılandırılmış sonucu döndürür.

        Hiçbir zaman istisna fırlatmaz. Toplam timeout aşılırsa müzakere
        iptal edilir ve `FAILED` döner.
        """
        if not self._members:
            return CouncilResult(
                status=CouncilStatus.FAILED,
                trigger=trigger,
                failure_reason=FAILURE_NO_MEMBERS,
            )

        try:
            return await asyncio.wait_for(
                self._deliberate(request, trigger),
                timeout=self._total_timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                "council_total_timeout",
                extra={"session_id": request.session_id, "member_count": len(self._members)},
            )
            return CouncilResult(
                status=CouncilStatus.FAILED,
                trigger=trigger,
                failure_reason=FAILURE_TOTAL_TIMEOUT,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("council_unexpected_failure", extra={"session_id": request.session_id})
            return CouncilResult(
                status=CouncilStatus.FAILED,
                trigger=trigger,
                failure_reason=FAILURE_UNEXPECTED,
            )

    # ------------------------------------------------------------------
    # Dahili akış
    # ------------------------------------------------------------------

    async def _deliberate(
        self, request: CouncilRequest, trigger: CouncilTrigger | None
    ) -> CouncilResult:
        # Anonim eşleme HER müzakere için yeniden üretilir; global durum yoktur.
        label_map = LabelMap([member.member_id for member in self._members])

        candidates = await run_candidate_stage(
            self._members,
            request,
            label_map=label_map,
            member_timeout_seconds=self._member_timeout_seconds,
            max_concurrency=self._max_concurrency,
        )

        successful = [candidate for candidate in candidates if candidate.succeeded]
        if len(successful) < self._min_candidates:
            logger.info(
                "council_insufficient_candidates",
                extra={
                    "successful": len(successful),
                    "required": self._min_candidates,
                    "session_id": request.session_id,
                },
            )
            return CouncilResult(
                status=CouncilStatus.INSUFFICIENT,
                candidates=candidates,
                trigger=trigger,
                failure_reason=FAILURE_INSUFFICIENT_CANDIDATES,
            )

        reviews = []
        if self._review_enabled:
            reviews = await run_review_stage(
                self._members,
                candidates,
                request,
                member_timeout_seconds=self._member_timeout_seconds,
                max_concurrency=self._max_concurrency,
                max_candidate_chars=self._max_candidate_chars,
            )

        final_answer, error = await run_chairman_stage(
            self._chairman,
            candidates,
            reviews,
            request,
            timeout_seconds=self._member_timeout_seconds,
            max_candidate_chars=self._max_candidate_chars,
            max_review_chars=self._max_review_chars,
        )

        if error is not None or not final_answer:
            logger.warning(
                "council_chairman_failed",
                extra={"reason": error, "session_id": request.session_id},
            )
            return CouncilResult(
                status=CouncilStatus.FAILED,
                candidates=candidates,
                reviews=reviews,
                trigger=trigger,
                failure_reason=FAILURE_CHAIRMAN,
            )

        logger.info(
            "council_completed",
            extra={
                "candidate_count": len(successful),
                "review_count": len(reviews),
                "trigger": trigger.value if trigger else None,
                "session_id": request.session_id,
            },
        )
        return CouncilResult(
            status=CouncilStatus.COMPLETED,
            final_answer=final_answer,
            candidates=candidates,
            reviews=reviews,
            trigger=trigger,
        )
