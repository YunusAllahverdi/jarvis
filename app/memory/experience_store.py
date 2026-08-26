"""Phase 2D — Kalıcı Experience depolaması için soyut sözleşme.

Deneyimler (Experience) ekle-yalnızcadır (append-only) — bu ilk fazda
hiçbir güncelleme/silme metodu yoktur; deneyimler tarihsel bir günlük
olarak biriktirilir. İleride ChatOrchestrator ve diğer tüketiciler
yalnızca bu Protocol'e bağımlı olacak; SQLiteExperienceStore'a değil —
böylece depolama backend'i (SQLite → başka bir mekanizma) çağıran kodu
etkilemeden değiştirilebilir.

Bu Protocol, MemoryStore Protocol'ünden TAMAMEN bağımsızdır: Experience
ile MemoryRecord birbirinden ayrı kavramlardır (bkz. app/memory/experience.py)
ve bu dosya MemoryStore'u hiç import etmez.

---------------------------------------------------------------------------
GÜVENLİK/GİZLİLİK SINIRI — Secure Vault BU FAZDA YOKTUR
---------------------------------------------------------------------------
Bu Protocol yalnızca NORMAL konuşma deneyimleri içindir. Kullanıcının
normal sohbet geçmişi/bağlamı (Jarvis'in uzun vadeli epizodik geçmiş
oluşturması için gerekli olan) burada olduğu gibi saklanır — bu fazda
hiçbir hassas-içerik sınıflandırması veya filtrelemesi YAPILMAZ.

Gelecekte, ayrı bir güvenlik mimarisi olarak bir **Secure Vault**
eklenecektir — TC kimlik numarası, şifreler, API anahtarları, kimlik
doğrulama sırları, kullanıcının açıkça "son derece hassas" olarak
işaretlediği bilgiler gibi veriler için. Secure Vault:
- ayrı, şifrelenmiş/korumalı bir depolama katmanı olacak,
- Face ID, cihaz kimlik doğrulaması veya kullanıcı tanımlı bir şifre
  gerektirebilecek,
- bu ExperienceStore'dan TAMAMEN ayrı bir bileşen olacak.

Bu fazda Secure Vault'a hiçbir bağlantı/coupling kurulmadı — ne bu
Protocol'de ne de SQLiteExperienceStore'da. Gelecekteki Vault eklendiğinde
bu Protocol'ün yeniden yazılması GEREKMEZ; Vault, konuşma → Experience →
ExperienceStore akışının tamamen dışında, ayrı bir akış olarak var olacak:

    Normal:  Konuşma → Experience → ExperienceStore (bu dosya)
    Gelecek: Hassas bilgi → Secure Vault → şifreli/korumalı depolama → açık kimlik doğrulama
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.memory.experience import Experience


@runtime_checkable
class ExperienceStore(Protocol):
    """Kalıcı Experience depolaması için değiştirilebilir sözleşme.

    Ekle-yalnızca (append-only): bu Protocol'de update()/delete() yoktur.
    """

    def add(self, experience: Experience) -> Experience:
        """Yeni bir Experience ekler ve kaydedilen kopyayı döndürür."""
        ...

    def get(self, experience_id: str) -> Experience | None:
        """Kimliğe göre tek bir Experience döndürür; bulunamazsa None."""
        ...

    def list_by_session(self, session_id: str, *, limit: int = 50) -> list[Experience]:
        """Belirli bir oturuma ait deneyimleri döndürür.

        Sonuçlar `occurred_at` artan sırayla döner (en eski önce — doğal
        konuşma okuma sırası).
        """
        ...

    def list_recent(
        self,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[Experience]:
        """En son deneyimleri döndürür.

        Sonuçlar `occurred_at` azalan sırayla döner (en yeni önce).
        `before` verilirse, yalnızca o zamandan KESİNLİKLE ÖNCE gerçekleşen
        deneyimler döner (sayfalama/pagination için).
        """
        ...
