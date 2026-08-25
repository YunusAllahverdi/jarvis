"""Kalıcı bellek depolaması için soyut sözleşme.

ChatOrchestrator ve diğer servisler yalnızca bu Protocol'e bağımlı olur;
SQLiteMemoryStore'a değil. Bu sayede depolama backend'i değiştirilebilir
(SQLite → vektör veritabanı, bulut servisi vb.) çağıran kodu etkilemeden.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.memory.record import MemoryRecord, MemoryStatus, MemoryType, Temporality


@runtime_checkable
class MemoryStore(Protocol):
    """Kalıcı bellek depolaması için değiştirilebilir sözleşme.

    Tüm yazma işlemleri bu arayüz üzerinden geçer; hiçbir katman
    doğrudan SQLite veya başka bir depolama mekanizmasına bağlı değildir.
    """

    # ------------------------------------------------------------------ yazma

    def add(self, record: MemoryRecord) -> MemoryRecord:
        """Yeni bir bellek kaydı ekler ve kaydedilen kopyayı döndürür.

        id, created_at ve updated_at alanları implementasyon tarafından
        ayarlanmışsa korunur; ayarlanmamışsa otomatik oluşturulur.
        """
        ...

    def update(self, record: MemoryRecord) -> MemoryRecord:
        """Var olan bir kaydı günceller ve güncellenmiş kopyayı döndürür.

        updated_at otomatik olarak şimdiki zamana ayarlanır.
        Kayıt bulunamazsa KeyError fırlatır.
        """
        ...

    def invalidate(self, memory_id: str, *, at: datetime | None = None) -> bool:
        """Bir kaydı mantıksal olarak geçersizleştirir.

        `invalid_at` alanı `at` değerine (veya şimdiki zamana) ayarlanır.
        Fiziksel kayıt silinmez — tarihsel iz korunur.
        Başarılıysa True, kayıt bulunamazsa False döner.
        """
        ...

    def delete(self, memory_id: str, *, at: datetime | None = None) -> bool:
        """Bir kaydı mantıksal olarak siler ("unut" komutu için).

        `deleted_at` alanı ayarlanır; fiziksel kayıt silinmez.
        Silinen kayıtlar normal sorgularda gösterilmez ama denetim
        amaçlı erişilebilir kalır.
        Başarılıysa True, kayıt bulunamazsa False döner.
        """
        ...

    # ------------------------------------------------------------------ okuma

    def get(self, memory_id: str) -> MemoryRecord | None:
        """Kimliğe göre tek bir kaydı döndürür; bulunamazsa None.

        Silinmiş veya geçersizleştirilmiş kayıtlar da döndürülür.
        """
        ...

    def list_active(
        self,
        *,
        memory_type: MemoryType | None = None,
        temporality: Temporality | None = None,
        status: MemoryStatus | None = None,
        source_session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """Aktif (silinmemiş ve geçersizleştirilmemiş) kayıtları döndürür.

        Tüm filtreler isteğe bağlıdır ve AND mantığıyla birleştirilir.
        Sonuçlar `valid_at` azalan sırayla döner (en yeni önce).
        """
        ...

    def list_by_session(
        self,
        session_id: str,
        *,
        include_invalidated: bool = False,
    ) -> list[MemoryRecord]:
        """Belirli bir oturuma ait kayıtları döndürür.

        `include_invalidated=False` (varsayılan) silinmemiş ve
        geçersizleştirilmemiş kayıtları döndürür.
        """
        ...

    # -------------------------------------------------------------- arama

    def search(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        temporality: Temporality | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """Tam metin araması ile eşleşen aktif kayıtları döndürür.

        Phase 1A'da FTS5 keyword araması kullanılır.
        Gelecekte vektör benzerlik aramasıyla değiştirilebilir —
        bu imza sabit kalır.
        """
        ...
