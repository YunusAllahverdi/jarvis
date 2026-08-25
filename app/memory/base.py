"""Jarvis bellek sistemi için temel veri modelleri ve paylaşılan türler.

Bu modül, tüm bellek katmanlarında kullanılan temel kavramları tanımlar.
Depolama seçimi (SQLite, vektör veritabanı, Redis vb.) bu sözleşmelere
bağımlı değildir; ilgili ImplementasyonStore sınıfları bu sözleşmeleri uygular.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Temel kimlik türleri
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Zaman bilinci: geçmiş / şimdiki / gelecek
# ---------------------------------------------------------------------------

class Temporality(StrEnum):
    """Bir bellek öğesinin zamansal konumu."""

    PAST = "past"
    PRESENT = "present"
    FUTURE = "future"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Temel bellek öğesi
# ---------------------------------------------------------------------------

class MemoryEntry(BaseModel):
    """Herhangi bir bellek katmanında saklanan en küçük birim.

    Tüm daha özelleşmiş bellek tipleri (olaylar, gerçekler, hedefler vb.)
    bu modelin alanlarını içerir veya bunu temel alır.
    """

    id: str = Field(default_factory=_new_id)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Hangi kullanıcı/oturuma ait — ileride çoklu kullanıcı desteği için.
    owner_id: str | None = None
    # Serbest biçimli etiketler — arama ve filtreleme için.
    tags: list[str] = Field(default_factory=list)
    # Ek bağlam verisi — katman özelinde genişletilebilir.
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Anlamsal gerçekler ve varlıklar
# ---------------------------------------------------------------------------

class Fact(MemoryEntry):
    """Dünya veya kullanıcı hakkında kalıcı bir bilgi parçası.

    Örnekler:
    - "Kullanıcının adı Ahmet"
    - "Paris, Fransa'nın başkentidir"
    - "Favori rengi mavi"
    """

    subject: str
    predicate: str
    object_value: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str | None = None  # nereden öğrenildi


class Entity(MemoryEntry):
    """Jarvis'in dünya modelindeki adlandırılmış bir varlık.

    Örnekler: kişi, yer, cihaz, uygulama, hizmet.
    """

    name: str
    entity_type: str  # "person", "place", "device", "service", ...
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Relationship(MemoryEntry):
    """İki varlık arasındaki ilişki.

    Örnek: "Ahmet" — "çalışıyor" — "ABC Şirketi"
    """

    source_entity_id: str
    relation_type: str
    target_entity_id: str
    attributes: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Episodik olaylar
# ---------------------------------------------------------------------------

class Event(MemoryEntry):
    """Belirli bir zamanda gerçekleşen veya gerçekleşecek bir olay.

    Geçmiş, şimdiki veya gelecek zamanlı olabilir.
    """

    title: str
    description: str = ""
    temporality: Temporality = Temporality.UNKNOWN
    occurred_at: datetime | None = None       # kesin zaman (geçmiş/şimdi)
    scheduled_at: datetime | None = None      # planlanan zaman (gelecek)
    location: str | None = None
    participants: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Kullanıcı tercihleri ve hedefler
# ---------------------------------------------------------------------------

class Preference(MemoryEntry):
    """Kullanıcıya ait bir tercih veya kişisel ayar.

    Örnek: "Yanıtlar kısa olsun", "Türkçe konuş", "Sabah hatırlatmaları istiyor"
    """

    category: str          # "communication", "schedule", "privacy", ...
    key: str
    value: Any
    is_explicit: bool = True  # kullanıcı açıkça mı belirtti?


class Goal(MemoryEntry):
    """Kullanıcının kısa veya uzun vadeli bir hedefi.

    Jarvis bu hedeflere göre proaktif öneri veya hatırlatma yapabilir.
    """

    title: str
    description: str = ""
    temporality: Temporality = Temporality.FUTURE
    deadline: datetime | None = None
    is_completed: bool = False
    progress_notes: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dünya/durum modeli
# ---------------------------------------------------------------------------

class WorldStateEntry(MemoryEntry):
    """Jarvis'in izlediği bir dış sistemin veya ortamın anlık durumu.

    Örnekler:
    - Home Assistant cihaz durumları
    - Kullanıcının fiziksel konumu
    - Hava durumu
    - Uçuş/taşıma durumu
    """

    domain: str        # "home_assistant", "location", "weather", "transport", ...
    key: str           # durum anahtarı, domain içinde benzersiz
    value: Any         # anlık değer
    expires_at: datetime | None = None  # bu durumun geçerlilik süresi
