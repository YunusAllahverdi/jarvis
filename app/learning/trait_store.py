"""Türetilmiş kullanıcı özellikleri (trait) için soyut depolama sözleşmesi.

Çağıran servisler (LearningService, UserModelService) yalnızca bu Protocol'e
bağımlıdır; SQLiteUserTraitStore'a değil. Bu sayede depolama backend'i
çağıran kodu etkilemeden değiştirilebilir.

Bu Protocol, MemoryStore ve ExperienceStore Protocol'lerinden TAMAMEN
bağımsızdır ve onları hiç import etmez — üç kavram (bilgi / olay / türetilmiş
model) ayrı sınırlar olarak kalır.

Yazma modeli — neden `upsert`?
    Trait'ler türetilmiş veridir ve her öğrenme geçişinde kaynaklardan
    YENİDEN hesaplanır. Bu yüzden doğal yazma işlemi "ekle" değil, "aynı
    (trait_type, key) için etkin kaydı tazele, yoksa oluştur"dur. Bu
    sayede aynı geçişi iki kez çalıştırmak kanıt sayılarını şişirmez
    (idempotentlik) — bkz. LearningService.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.learning.trait import TraitType, UserTrait


@runtime_checkable
class UserTraitStore(Protocol):
    """Türetilmiş kullanıcı özellikleri için değiştirilebilir sözleşme."""

    # ------------------------------------------------------------------ yazma

    def upsert(self, trait: UserTrait) -> UserTrait:
        """Trait'i ekler veya aynı `(trait_type, key)` için etkin kaydı tazeler.

        Etkin bir kayıt varsa: `value`, `evidence_count`, `confidence`,
        `last_observed_at`, `metadata` ve `updated_at` güncellenir; `id`,
        `created_at` ve `first_observed_at` KORUNUR (gözlemin tarihçesi
        kaybolmaz).

        Etkin kayıt yoksa yeni bir satır oluşturulur.

        Returns:
            Depoda oluşan güncel kayıt.
        """
        ...

    def invalidate(self, trait_id: str, *, at: datetime | None = None) -> bool:
        """Bir trait'i mantıksal olarak geçersizleştirir (fiziksel silme yok).

        Başarılıysa True; kayıt bulunamazsa veya zaten geçersizse False.
        """
        ...

    # ------------------------------------------------------------------ okuma

    def get(self, trait_id: str) -> UserTrait | None:
        """Kimliğe göre tek bir trait döndürür; bulunamazsa None.

        Geçersizleştirilmiş kayıtlar da döndürülür.
        """
        ...

    def find_active(self, trait_type: TraitType, key: str) -> UserTrait | None:
        """`(trait_type, key)` için ETKİN kaydı döndürür; yoksa None."""
        ...

    def list_active(
        self,
        *,
        trait_type: TraitType | None = None,
        min_confidence: float = 0.0,
        limit: int = 50,
        offset: int = 0,
    ) -> list[UserTrait]:
        """Etkin trait'leri döndürür.

        Sonuçlar `confidence` azalan, eşitlikte `last_observed_at` azalan
        sırayla döner (en güçlü ve en taze gözlem önce).
        """
        ...
