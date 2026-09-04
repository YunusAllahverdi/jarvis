"""Bekleyen UI aksiyonlarının tutulduğu kanal.

Tasarım kararları:

- **KAPALI KÜME.** Açılabilecek paneller `UIPanel` enum'ıdır. Ajan buraya
  yeni bir değer uyduramaz; uydurursa araç şema doğrulamasında reddedilir.
- **TEK KULLANIMLIK.** Aksiyonlar okunduğunda tüketilir. Kalsalardı panel
  her yoklamada yeniden açılır ve kullanıcı kapattığı paneli tekrar tekrar
  görürdü.
- **OTURUMA BAĞLI.** Bir oturumda kuyruğa girmiş aksiyon başka bir oturumda
  görünmez; iki sekme açık olan kullanıcı, diğerinin panelini görmemelidir.
- **SINIRLI KUYRUK.** Döngüye giren bir ajan sınırsız panel açamaz; sınır
  dolduğunda EN ESKİ atılır. Burada en eskiyi atmak doğrudur çünkü aksiyonlar
  geçici niyetlerdir — notlarda olduğu gibi kullanıcının yazdığı kalıcı bir
  şey değildir.
- **KALICI DEĞİL.** Bellekte tutulur ve yeniden başlatmada silinir. Bir panel
  açma isteği ANLIK bir niyettir; yeniden başlatmadan sonra açılması, bağlamı
  çoktan kaybolmuş bir pencere göstermek olurdu.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MAX_ACTIONS_PER_SESSION = 5
"""Bir oturumda bekleyebilecek en fazla aksiyon.

Küçük tutulmasının sebebi, aksiyonların birikmemesi gerektiğidir: kullanıcı
kabuğu açtığında beş pencerenin birden açılması yardımcı olmaz.
"""

MAX_SESSIONS = 100
"""Aksiyon tutulan en fazla oturum; sınırsız sözlük bir sızıntıdır."""


class UIPanel(StrEnum):
    """Ajanın açabileceği paneller — KAPALI küme.

    Yeni bir panel eklemek, buraya bir değer eklemeyi gerektirir. Bu bilinçli
    bir sürtünmedir: ajanın ekranda ne açabileceği, kod incelemesinden geçmiş
    bir liste olmalıdır.
    """

    NOTES = "notes"
    MEMORY = "memory"
    EXPERIENCES = "experiences"
    TRAITS = "traits"
    USER_MODEL = "user_model"
    SYSTEM = "system"
    CODING = "coding"


class UIAction(BaseModel):
    """Kullanıcının ekranında yapılması istenen tek bir değişiklik."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    panel: UIPanel

    reason: str = Field(default="", max_length=200)
    """Panelin NEDEN açıldığına dair kısa, olgusal ifade.

    Kullanıcıya gösterilebilir: ekranında kendiliğinden açılan bir pencerenin
    sebebini bilmek, onu bir hata sanmasını engeller.
    """

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str | None = None


class UIActionBus:
    """Bekleyen UI aksiyonlarını oturum başına tutar ve tek kullanımlık verir."""

    def __init__(
        self,
        *,
        max_per_session: int = MAX_ACTIONS_PER_SESSION,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self._max_per_session = max(1, max_per_session)
        self._max_sessions = max(1, max_sessions)
        self._queues: dict[str, deque[UIAction]] = {}
        self._lock = RLock()

    def publish(
        self, panel: UIPanel, *, session_id: str | None = None, reason: str = ""
    ) -> UIAction:
        """Bir panel açma isteğini kuyruğa alır.

        Oturumsuz istekler de kabul edilir ve `"__global__"` kuyruğuna girer:
        ajan bir oturum kimliği olmadan da çalıştırılabilir ve o durumda
        isteği düşürmek, kanalı sessizce çalışmaz kılardı.
        """
        action = UIAction(panel=panel, reason=reason.strip()[:200], session_id=session_id)
        key = session_id or "__global__"

        with self._lock:
            self._evict_oldest_session_if_needed(key)
            queue = self._queues.setdefault(key, deque())
            if len(queue) >= self._max_per_session:
                # En eskiyi at: aksiyonlar geçici niyetlerdir ve en yeni
                # niyet, kullanıcının şu an konuştuğu şeye en yakın olandır.
                dropped = queue.popleft()
                logger.debug(
                    "ui_action_dropped", extra={"panel": dropped.panel.value}
                )
            queue.append(action)

        logger.info(
            "ui_action_published",
            extra={"panel": panel.value, "session_id": session_id},
        )
        return action

    def consume(self, *, session_id: str | None = None) -> list[UIAction]:
        """Bekleyen aksiyonları döndürür ve kuyruğu BOŞALTIR.

        Tüketim okuma anında olur: aksiyonlar kalsaydı panel her yoklamada
        yeniden açılır ve kullanıcının kapattığı pencere geri gelirdi.
        """
        key = session_id or "__global__"
        with self._lock:
            queue = self._queues.pop(key, None)
        return list(queue) if queue else []

    def pending_count(self, *, session_id: str | None = None) -> int:
        """Bekleyen aksiyon sayısı; tüketmez (test ve gözlemlenebilirlik için)."""
        key = session_id or "__global__"
        with self._lock:
            return len(self._queues.get(key, ()))

    def _evict_oldest_session_if_needed(self, incoming_key: str) -> None:
        """Oturum sayısı sınırı aşılıyorsa en eski oturumun kuyruğunu atar.

        Sınırsız bir sözlük, her yeni oturum kimliğiyle büyüyen bir sızıntı
        olurdu — kimlikler istemciden gelir ve tekrar kullanılmayabilir.
        """
        if incoming_key in self._queues or len(self._queues) < self._max_sessions:
            return
        oldest = next(iter(self._queues))
        del self._queues[oldest]
        logger.debug("ui_action_session_evicted")
