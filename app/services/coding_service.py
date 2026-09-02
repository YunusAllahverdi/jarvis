"""Kodlama döngüsünün dış cephesi (facade).

Zinciri tek bir yerde birleştirir:

    CodingPlanner → CodingLoop → Verifier → CodingResult

Mimari kurallar:
- Bu servis HİÇBİR ZAMAN istisna fırlatmaz. Zincirin herhangi bir yerinde
  beklenmedik bir hata olursa `CodingStatus.FAILED` taşıyan yapılandırılmış
  bir sonuç döner.
- SOHBET AKIŞININ PARÇASI DEĞİLDİR. `ChatOrchestrator` bu servisi tanımaz;
  bu sayede kodlama döngüsündeki bir sorun normal sohbeti hiçbir koşulda
  etkileyemez — karar katmanı için de geçerli olan aynı ilke.
- Somut bir tool, depo veya sağlayıcı bilmez; yalnızca kendisine verilen
  bileşenleri kullanır (dependency injection).
"""

from __future__ import annotations

import logging

from app.coding.loop import CodingLoop
from app.coding.models import CodingResult, CodingStatus
from app.coding.summary import build_summary

logger = logging.getLogger(__name__)

_FALLBACK_ERROR = "Kodlama döngüsü bu isteği işleyemedi."


class CodingService:
    """Bir kodlama isteğini alır, döngüyü çalıştırır ve sonucu döndürür."""

    def __init__(self, *, loop: CodingLoop) -> None:
        """
        Args:
            loop: Uçtan uca yürütmeyi yapan döngü.
        """
        self._loop = loop

    async def run(self, request: str, *, session_id: str | None = None) -> CodingResult:
        """Kodlama isteğini yürütür; hiçbir zaman istisna fırlatmaz."""
        try:
            return await self._loop.run(request, session_id=session_id)
        except Exception:  # noqa: BLE001
            logger.exception("coding_service_failed", extra={"session_id": session_id})
            result = CodingResult(
                request=request,
                session_id=session_id,
                status=CodingStatus.FAILED,
                error=_FALLBACK_ERROR,
            )
            result.summary = build_summary(result)
            return result
