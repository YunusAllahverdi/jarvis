"""Çalışma belleği (Working Memory) soyut sözleşmesi.

Çalışma belleği, aktif bir konuşma veya görev oturumu boyunca geçici olarak
tutulan kısa vadeli bağlamdır. Oturum sona erdiğinde veya bağlam boşaldığında
içerik temizlenebilir; ancak önemli kısımlar episodik belleğe aktarılabilir.

Bu modül yalnızca sözleşmeyi tanımlar. Somut implementasyon
(örneğin InMemoryWorkingMemory) ayrı bir modülde sağlanacaktır.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.core.chat import ChatMessage
from app.memory.base import Fact


@runtime_checkable
class WorkingMemoryStore(Protocol):
    """Aktif oturum bağlamını tutan geçici bellek sağlayıcısı.

    Uygulamalar bu Protocol'ü implemente ederek RAM, Redis veya
    başka bir geçici depolama mekanizması kullanabilir.
    """

    def get_recent_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ChatMessage]:
        """Oturumun son N konuşma mesajını döndürür.

        Args:
            session_id: Oturum tanımlayıcısı.
            limit: Döndürülecek maksimum mesaj sayısı. None ise tamamı.
        """
        ...

    def append_messages(self, session_id: str, messages: list[ChatMessage]) -> None:
        """Oturuma yeni mesajlar ekler."""
        ...

    def get_context_facts(self, session_id: str) -> list[Fact]:
        """Aktif oturum için geçici olarak not edilen gerçekleri döndürür.

        Bu gerçekler konuşma sırasında tespit edilmiş ama henüz
        anlamsal belleğe yazılmamış geçici bilgilerdir.
        """
        ...

    def set_context_value(self, session_id: str, key: str, value: Any) -> None:
        """Oturuma özgü bir bağlam değeri kaydeder.

        Örnek: aktif görev adı, kullanıcı duygu durumu tahmini,
        son konuşulan konu.
        """
        ...

    def get_context_value(self, session_id: str, key: str) -> Any | None:
        """Oturuma özgü bir bağlam değerini döndürür; yoksa None."""
        ...

    def clear_session(self, session_id: str) -> None:
        """Bir oturuma ait tüm çalışma belleğini temizler."""
        ...
