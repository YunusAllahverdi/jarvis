"""Kalıcı bellekten ilgili kayıtları getiren salt-okunur arama servisi.

Mimari kurallar:
- Yalnızca MemoryStore Protocol'üne bağımlıdır; SQLiteMemoryStore veya başka
  bir somut backend'e hiç değinmez.
- Veritabanını asla değiştirmez — yalnızca okuma yapar (MemoryStore.search()).
- LLM çağırmaz; sorgu yeniden yazımı veya semantik genişletme yapmaz.
- Phase 1B-3B: yalnızca FTS5 anahtar kelime araması. Sıralama tamamen
  MemoryStore.search() implementasyonuna (SQLite FTS5 rank) bırakılır —
  bu katmanda ek bir skorlama/yeniden sıralama yoktur.
- Bağlam enjeksiyonu (ChatOrchestrator'a bağlama) bu fazın kapsamı dışındadır.
"""

from __future__ import annotations

from app.memory.record import MemoryRecord, MemoryType, Temporality
from app.memory.store import MemoryStore

_DEFAULT_LIMIT = 5


class MemoryRetrievalService:
    """Doğal dil sorgusuyla kalıcı bellekten ilgili aktif kayıtları getirir.

    Kullanım:
        retrieval = MemoryRetrievalService(store=store)
        records = retrieval.retrieve("Kullanıcı nerede yaşıyor?")

    Çağıranlar (ör. ChatOrchestrator, ileride) yalnızca bu servise bağımlı
    olur; MemoryStore'un SQLite mi yoksa başka bir backend mi olduğunu
    bilmesi gerekmez.
    """

    def __init__(self, *, store: MemoryStore, default_limit: int = _DEFAULT_LIMIT) -> None:
        self._store = store
        self._default_limit = default_limit

    def retrieve(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        temporality: Temporality | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        """Sorguya en ilgili aktif bellek kayıtlarını döndürür.

        Args:
            query: Doğal dil arama sorgusu. Boş/whitespace ise arama
                hiç yapılmadan boş liste döner.
            memory_type: İsteğe bağlı memory_type filtresi.
            temporality: İsteğe bağlı temporality filtresi.
            limit: Döndürülecek maksimum kayıt sayısı. None ise
                constructor'da verilen default_limit kullanılır.

        Returns:
            MemoryStore.search()'ten dönen, silinmemiş ve geçersizleştirilmemiş
            (aktif) kayıtların listesi. Hiçbir kayıt değiştirilmez veya yazılmaz.
        """
        if not query or not query.strip():
            return []

        effective_limit = limit if limit is not None else self._default_limit
        if effective_limit <= 0:
            return []

        return self._store.search(
            query,
            memory_type=memory_type,
            temporality=temporality,
            limit=effective_limit,
        )
