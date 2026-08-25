"""Kalıcı bellek için birleşik veri modeli.

SQLite tabanlı depolamada tek bir tablo kullanılarak tüm bellek tipleri
(fact, event, preference ve diğerleri) bu modelle temsil edilir.
Bu yaklaşım şema basitliğini ve gelecekteki genişletilebilirliği dengeler.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class MemoryType(StrEnum):
    """Bellek kaydının anlamsal türü."""

    FACT = "fact"
    EVENT = "event"
    PREFERENCE = "preference"
    GOAL = "goal"
    WORLD_STATE = "world_state"
    OTHER = "other"


class MemoryStatus(StrEnum):
    """Bellek kaydının yaşam döngüsü durumu."""

    ACTIVE = "active"
    PLANNED = "planned"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNCERTAIN = "uncertain"


class Temporality(StrEnum):
    """Bellek kaydının zamansal konumu."""

    PAST = "past"
    PRESENT = "present"
    FUTURE = "future"
    UNKNOWN = "unknown"


class MemoryRecord(BaseModel):
    """Tüm bellek türlerini temsil eden birleşik kalıcı bellek kaydı.

    Hem episodik hem anlamsal bellek için tek şema kullanılır.
    `memory_type` alanı kayıtlar arasında ayrım yapar.
    `metadata` alanı tür-özelinde ek bilgi taşır.
    """

    model_config = ConfigDict(frozen=False)

    # ------------------------------------------------------------------ kimlik
    id: str = Field(default_factory=_new_id)
    memory_type: MemoryType = MemoryType.OTHER

    # ------------------------------------------------------------------ içerik
    content: str = Field(min_length=1)
    """İnsan tarafından okunabilir bellek metni. FTS5 bu alana indekslenir."""

    # --------------------------------------------------------------- zamansal
    temporality: Temporality = Temporality.UNKNOWN
    status: MemoryStatus = MemoryStatus.ACTIVE

    # Gerçek dünyada ne zaman geçerli olduğu (bi-temporal model).
    valid_at: datetime = Field(default_factory=_utcnow)
    """Belleğin gerçek dünyada geçerli olmaya başladığı an."""

    invalid_at: datetime | None = None
    """None ise hâlâ geçerli. Dolu ise bu andan itibaren geçersiz."""

    # ------------------------------------------------------- sistem zaman damgaları
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # --------------------------------------------------------------- kaynak
    source_session_id: str | None = None
    """Hangi konuşma oturumundan kaynaklandığı."""

    # ------------------------------------------------------------ önem / gizlilik
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    """0.0 = önemsiz, 1.0 = kritik. Retrieval sıralamasında kullanılır."""

    sensitivity: float = Field(default=0.0, ge=0.0, le=1.0)
    """0.0 = herkese açık, 1.0 = son derece hassas."""

    # --------------------------------------------------------------- silinme
    deleted_at: datetime | None = None
    """None ise silindi değil. Mantıksal silme — fiziksel kayıt korunur."""

    # ------------------------------------------------------------ ek veri
    metadata: dict = Field(default_factory=dict)
    """Tür-özelinde ek alanlar (JSON olarak saklanır)."""
