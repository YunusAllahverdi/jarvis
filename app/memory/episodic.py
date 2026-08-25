"""Episodik bellek (Episodic Memory) soyut sözleşmesi.

Episodik bellek, Jarvis'in yaşadığı veya gözlemlediği olayların ve
konuşmaların kalıcı kaydını tutar. "Ne oldu, ne zaman oldu, kim vardı?"
sorularını yanıtlayan katmandır.

Bu modül yalnızca sözleşmeyi tanımlar. Somut implementasyon
(örneğin SQLiteEpisodicMemory) ayrı bir modülde sağlanacaktır.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.memory.base import Event, Temporality


@runtime_checkable
class EpisodicMemoryStore(Protocol):
    """Olayları ve konuşma özetlerini kalıcı olarak saklayan bellek katmanı.

    Zaman çizgisi bilinci (geçmiş/şimdiki/gelecek olaylar),
    proaktif hatırlatmalar ve geçmiş oturumları özetleme bu katmana dayanır.
    """

    def record_event(self, event: Event) -> Event:
        """Yeni bir olayı belleğe kaydeder ve kaydedilen kopyayı döndürür."""
        ...

    def get_event(self, event_id: str) -> Event | None:
        """Kimliğe göre bir olayı döndürür; bulunamazsa None."""
        ...

    def query_events(
        self,
        *,
        owner_id: str | None = None,
        temporality: Temporality | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[Event]:
        """Filtrelere göre olayları sorgular.

        Args:
            owner_id: Belirli bir kullanıcıya ait olayları filtreler.
            temporality: PAST, PRESENT veya FUTURE olaylarını filtreler.
            after: Bu tarihten sonraki olayları döndürür.
            before: Bu tarihten önceki olayları döndürür.
            tags: Bu etiketlerin tamamına sahip olayları döndürür.
            limit: Döndürülecek maksimum olay sayısı.
        """
        ...

    def update_event(self, event: Event) -> Event:
        """Var olan bir olayı günceller ve güncellenmiş kopyayı döndürür."""
        ...

    def delete_event(self, event_id: str) -> bool:
        """Bir olayı siler; başarılıysa True döner."""
        ...

    def get_upcoming_events(
        self,
        owner_id: str | None = None,
        within_hours: float = 24.0,
    ) -> list[Event]:
        """Yaklaşan gelecek olayları döndürür.

        Proaktif hatırlatmalar ve ajanda farkındalığı için kullanılır.
        """
        ...
