"""Öğrenilmiş kullanıcı modelini okunabilir bir profil olarak birleştiren servis.

Bu katman SALT OKUNURDUR: hiçbir trait üretmez, hiçbir kaydı değiştirmez,
hiçbir LLM çağırmaz. Yalnızca `LearningService`'in ürettiği trait'leri ve
Experience geçmişinin sayısal özetini bir araya getirir.

Yazma (öğrenme) ile okuma (profil) bilinçli olarak ayrılmıştır:
- LearningService  → türetir ve yazar (açık bir eylem)
- UserModelService → okur ve sunar (yan etkisiz, her an çağrılabilir)

Bu ayrım sayesinde bir profil isteği asla veritabanını değiştirmez ve
frontend, profil sorgusunu istediği sıklıkta yapabilir.

Çıktı modelleri (`UserProfile`, `InteractionStats`) doğrudan API yanıtı
olarak serileştirilebilir; API katmanının ayrıca bir dönüşüm yapması
gerekmez.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.learning.analyzer import InteractionStats, analyze_experiences
from app.learning.trait import TraitType, UserTrait
from app.learning.trait_store import UserTraitStore
from app.memory.experience_store import ExperienceStore

logger = logging.getLogger(__name__)

_DEFAULT_TRAIT_LIMIT = 50
_DEFAULT_EXPERIENCE_WINDOW = 500

_TYPE_COUNT_SCAN_LIMIT = 500
"""Tür başına sayım için taranacak maksimum trait sayısı.

Sayım, sınırsız bir COUNT sorgusu yerine bilinçli olarak sınırlı bir tarama
ile yapılır: UserTraitStore Protocol'ünde bir `count()` metodu yoktur ve
yalnızca bu sayım için sözleşmeyi genişletmek, somut backend'lere gereksiz
bir zorunluluk yüklerdi.
"""


class UserProfile(BaseModel):
    """Kullanıcı hakkında öğrenilmiş her şeyin tek seferlik anlık görüntüsü."""

    generated_at: datetime
    """Bu görüntünün üretildiği an. Önbelleklenmiş bir değer değildir."""

    trait_count: int = 0
    """Etkin trait sayısı (tür başına sayımların toplamı)."""

    traits_by_type: dict[str, int] = Field(default_factory=dict)
    """Trait türü → etkin trait sayısı. Sıfır olan türler de yer alır."""

    traits: list[UserTrait] = Field(default_factory=list)
    """Güven sırasına göre en güçlü trait'ler (limit ile sınırlı)."""

    interaction: InteractionStats = Field(default_factory=InteractionStats)
    """Experience geçmişinin sayısal özeti; deneyim deposu yoksa boştur."""


class UserModelService:
    """Trait deposunu ve deneyim geçmişini okunabilir bir profile dönüştürür.

    Kullanım:
        service = UserModelService(trait_store=store, experience_store=experiences)
        profile = service.build_profile(min_confidence=0.3)
    """

    def __init__(
        self,
        *,
        trait_store: UserTraitStore,
        experience_store: ExperienceStore | None = None,
        experience_window: int = _DEFAULT_EXPERIENCE_WINDOW,
        hour_offset: int = 0,
    ) -> None:
        """
        Args:
            trait_store: Öğrenilmiş trait'lerin okunacağı depo.
            experience_store: Etkileşim istatistikleri için deneyim kaynağı.
                None ise istatistikler boş döner (hata değildir).
            experience_window: İstatistik için incelenecek maksimum deneyim sayısı.
            hour_offset: Aktiflik ritmi için UTC saat ofseti (bkz. analyzer).
        """
        self._trait_store = trait_store
        self._experience_store = experience_store
        self._experience_window = experience_window
        self._hour_offset = hour_offset

    def build_profile(
        self,
        *,
        min_confidence: float = 0.0,
        limit: int = _DEFAULT_TRAIT_LIMIT,
        now: datetime | None = None,
    ) -> UserProfile:
        """Kullanıcı profilinin güncel anlık görüntüsünü oluşturur.

        Args:
            min_confidence: Bu güvenin altındaki trait'ler listelenmez.
                Tür sayımları da aynı eşiğe tabidir — böylece sayılar
                gösterilen listeyle tutarlı kalır.
            limit: `traits` listesinde döndürülecek maksimum trait sayısı.
            now: `generated_at` için kullanılacak an (test edilebilirlik).
        """
        moment = now or datetime.now(UTC)
        traits = self._trait_store.list_active(min_confidence=min_confidence, limit=limit)
        counts = self._count_by_type(min_confidence=min_confidence)

        return UserProfile(
            generated_at=moment,
            trait_count=sum(counts.values()),
            traits_by_type=counts,
            traits=traits,
            interaction=self.interaction_stats(),
        )

    def list_traits(
        self,
        *,
        trait_type: TraitType | None = None,
        min_confidence: float = 0.0,
        limit: int = _DEFAULT_TRAIT_LIMIT,
        offset: int = 0,
    ) -> list[UserTrait]:
        """Etkin trait'leri filtreleyerek döndürür (güven sırasına göre)."""
        return self._trait_store.list_active(
            trait_type=trait_type,
            min_confidence=min_confidence,
            limit=limit,
            offset=offset,
        )

    def interaction_stats(self) -> InteractionStats:
        """Deneyim geçmişinin sayısal özetini döndürür.

        Deneyim deposu bağlı değilse boş ama geçerli bir özet döner.
        """
        if self._experience_store is None:
            return InteractionStats()
        experiences = self._experience_store.list_recent(limit=self._experience_window)
        return analyze_experiences(experiences, hour_offset=self._hour_offset).stats

    # ------------------------------------------------------------------
    # Dahili
    # ------------------------------------------------------------------

    def _count_by_type(self, *, min_confidence: float) -> dict[str, int]:
        """Her trait türü için etkin trait sayısını döndürür (sınırlı tarama)."""
        return {
            trait_type.value: len(
                self._trait_store.list_active(
                    trait_type=trait_type,
                    min_confidence=min_confidence,
                    limit=_TYPE_COUNT_SCAN_LIMIT,
                )
            )
            for trait_type in TraitType
        }
