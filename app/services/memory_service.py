"""Konuşma turlarından bellek çıkarımını ve kalıcı depolamayı koordine eden servis.

Mimari kurallar:
- MemoryWriteService, MemoryExtractor (çıkarma + deterministic doğrulama) ile
  MemoryStore Protocol'ü (kalıcılık) arasında ince bir koordinasyon katmanıdır.
- Somut bir depolama implementasyonuna (örn. SQLiteMemoryStore) hiçbir
  bağımlılığı yoktur — yalnızca MemoryStore Protocol'üne bağımlıdır.
- Çıkarma veya depolama sırasında oluşan herhangi bir hata bu katmanda
  yutulur ve günlüğe kaydedilir; çağırana asla fırlatılmaz. Bellek yazma
  başarısızlığı normal sohbet cevabını hiçbir zaman bozmamalıdır.
- Ham LLM çıktısı bu servise hiç ulaşmaz — MemoryExtractor tarafından
  zaten doğrulanmış MemoryRecord nesneleri alınır.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from app.memory.extractor import MemoryExtractor
from app.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class MemoryWriteResult(BaseModel):
    """process_turn() çağrısının çağırana döndürdüğü özet sonuç.

    Hata durumlarında da her zaman bir MemoryWriteResult döner;
    hiçbir zaman istisna fırlatılmaz.
    """

    stored_count: int = 0
    rejected_count: int = 0
    extraction_failed: bool = False
    store_failed: bool = False

    @property
    def ok(self) -> bool:
        """Hem çıkarma hem depolama sorunsuz tamamlandıysa True."""
        return not self.extraction_failed and not self.store_failed


class MemoryWriteService:
    """Bir konuşma turundan bellek çıkarır ve MemoryStore Protocol'ü üzerinden yazar.

    Kullanım:
        service = MemoryWriteService(extractor=extractor, store=store)
        result = await service.process_turn("I live in Istanbul.", session_id="s1")

    ChatOrchestrator yalnızca bu servise bağımlı olur; MemoryExtractor'ın
    hangi LLM'i kullandığını veya MemoryStore'un SQLite mi yoksa başka bir
    backend mi olduğunu bilmesi gerekmez.
    """

    def __init__(self, *, extractor: MemoryExtractor, store: MemoryStore) -> None:
        self._extractor = extractor
        self._store = store

    async def process_turn(
        self,
        user_message: str,
        *,
        session_id: str | None = None,
    ) -> MemoryWriteResult:
        """Bir kullanıcı mesajından bellek çıkarır ve doğrulanmış kayıtları depoya yazar.

        Args:
            user_message: Bellek çıkarımı için kullanılacak kullanıcı mesajı.
            session_id: Depolanacak kayıtlara eklenecek oturum kimliği.

        Returns:
            MemoryWriteResult — her koşulda döner, hiçbir zaman istisna fırlatmaz.
        """
        try:
            extraction = await self._extractor.extract(user_message, session_id=session_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "memory_extraction_unexpected_failure",
                extra={"session_id": session_id},
            )
            return MemoryWriteResult(extraction_failed=True)

        if extraction.llm_failed:
            logger.warning(
                "memory_extraction_llm_failed",
                extra={"session_id": session_id},
            )
            return MemoryWriteResult(
                extraction_failed=True,
                rejected_count=extraction.rejected_count,
            )

        stored_count = 0
        store_failed = False
        for record in extraction.records:
            try:
                self._store.add(record)
                stored_count += 1
            except Exception:  # noqa: BLE001
                store_failed = True
                logger.exception(
                    "memory_store_write_failed",
                    extra={"memory_id": record.id, "session_id": session_id},
                )

        return MemoryWriteResult(
            stored_count=stored_count,
            rejected_count=extraction.rejected_count,
            store_failed=store_failed,
        )
