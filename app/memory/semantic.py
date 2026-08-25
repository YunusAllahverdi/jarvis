"""Anlamsal bellek (Semantic Memory) soyut sözleşmesi.

Anlamsal bellek, dünya hakkındaki kalıcı bilgileri, varlıkları, ilişkileri,
kullanıcı tercihlerini ve hedeflerini tutar. "Ne bilinir? Kim kimdir? Ne istiyor?"
sorularını yanıtlayan katmandır.

Bu modül yalnızca sözleşmeyi tanımlar. Somut implementasyon
(örneğin bir vektör veritabanı + ilişkisel store kombinasyonu)
ayrı bir modülde sağlanacaktır.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.memory.base import Entity, Fact, Goal, Preference, Relationship


@runtime_checkable
class SemanticMemoryStore(Protocol):
    """Kalıcı bilgi, varlık, ilişki, tercih ve hedefleri saklayan bellek katmanı.

    Uzun vadeli kişisel bilgi tabanı, kullanıcı profili ve dünya modeli
    bu katmana dayanır.
    """

    # ------------------------------------------------------------------
    # Gerçekler (Facts)
    # ------------------------------------------------------------------

    def store_fact(self, fact: Fact) -> Fact:
        """Yeni bir gerçeği belleğe kaydeder."""
        ...

    def query_facts(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        tags: list[str] | None = None,
        owner_id: str | None = None,
        limit: int = 20,
    ) -> list[Fact]:
        """Filtrelere göre gerçekleri sorgular."""
        ...

    def delete_fact(self, fact_id: str) -> bool:
        """Bir gerçeği siler; başarılıysa True döner."""
        ...

    # ------------------------------------------------------------------
    # Varlıklar (Entities)
    # ------------------------------------------------------------------

    def store_entity(self, entity: Entity) -> Entity:
        """Yeni bir varlığı veya güncellenmiş varlığı kaydeder."""
        ...

    def get_entity(self, entity_id: str) -> Entity | None:
        """Kimliğe göre bir varlığı döndürür."""
        ...

    def find_entities(
        self,
        *,
        name: str | None = None,
        entity_type: str | None = None,
        attributes: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[Entity]:
        """İsim, tür veya özniteliklere göre varlıkları bulur."""
        ...

    # ------------------------------------------------------------------
    # İlişkiler (Relationships)
    # ------------------------------------------------------------------

    def store_relationship(self, relationship: Relationship) -> Relationship:
        """İki varlık arasındaki ilişkiyi kaydeder."""
        ...

    def get_relationships(
        self,
        entity_id: str,
        relation_type: str | None = None,
    ) -> list[Relationship]:
        """Bir varlığın ilişkilerini döndürür; isteğe bağlı tür filtresiyle."""
        ...

    # ------------------------------------------------------------------
    # Tercihler (Preferences)
    # ------------------------------------------------------------------

    def store_preference(self, preference: Preference) -> Preference:
        """Bir kullanıcı tercihini kaydeder veya günceller."""
        ...

    def get_preferences(
        self,
        owner_id: str,
        category: str | None = None,
    ) -> list[Preference]:
        """Kullanıcıya ait tercihleri döndürür."""
        ...

    # ------------------------------------------------------------------
    # Hedefler (Goals)
    # ------------------------------------------------------------------

    def store_goal(self, goal: Goal) -> Goal:
        """Bir kullanıcı hedefini kaydeder."""
        ...

    def get_goals(
        self,
        owner_id: str,
        *,
        include_completed: bool = False,
    ) -> list[Goal]:
        """Kullanıcının aktif (veya tüm) hedeflerini döndürür."""
        ...

    def update_goal(self, goal: Goal) -> Goal:
        """Var olan bir hedefi günceller."""
        ...

    # ------------------------------------------------------------------
    # Anlamsal arama (gelecekte vektör ile desteklenecek)
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        owner_id: str | None = None,
        limit: int = 10,
    ) -> list[Fact | Entity]:
        """Doğal dil sorgusuyla en alakalı gerçek ve varlıkları döndürür.

        Şu an anahtar kelime araması; ileride vektör benzerlik aramasıyla
        değiştirilebilir. Implementasyon değişse de bu imza sabit kalır.
        """
        ...
