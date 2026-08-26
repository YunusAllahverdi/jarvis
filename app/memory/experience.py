"""Phase 2A — Experience modeli (yalnızca tasarım/veri şekli).

Deneyim (Experience), etkileşim sırasında OLAN BİTENİ — bağlamı, zamanı,
kullanıcı durumunu, konuşma/ifade bağlamını ve sonucu — temsil eder.
Bellek (MemoryRecord), "hatırlanabilecek/getirilebilecek" damıtılmış bilgiyi
temsil eder. İkisi arasındaki ilişki bire-çoktur: bir deneyim sıfır, bir
veya birden fazla bellek kaydı üretebilir — bu yüzden Experience,
MemoryRecord'un bir alt sınıfı DEĞİLDİR ve ondan tamamen bağımsızdır.

Bu modül BİLİNÇLİ OLARAK henüz:
- hiçbir kalıcı depoya (SQLite dahil) yazılmaz,
- ChatOrchestrator/MemoryExtractor/MemoryWriteService'e bağlanmaz,
- emotion engine veya learning mantığı içermez (`user_state` ve
  `emotional_context` alanları yalnızca geleceğe hazır yer tutuculardır —
  hiçbir kod onları doldurmaz).

Bir Experience ileride bir MemoryRecord üretirse, bağlantı mevcut
`MemoryRecord.metadata` alanı üzerinden kurulur (ör. `metadata["experience_id"]`)
— tıpkı `topic_key`'in zamansal çakışma çözümü için kullanıldığı gibi.
Bu, hiçbir şema/migration değişikliği gerektirmez.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _new_id() -> str:
    return str(uuid4())


class ExperienceOutcome(StrEnum):
    """Bir deneyimin deterministik sonuç sınıflandırması.

    LLM tarafından tahmin edilmez; ileride çağıran kod tarafından
    (ör. tool başarısı/başarısızlığı, sohbetin tamamlanıp tamamlanmadığı gibi
    deterministik sinyallerden) ayarlanması beklenir.
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Experience(BaseModel):
    """Etkileşim sırasında olan biteni temsil eden bağımsız veri modeli.

    MemoryRecord'dan tamamen ayrıdır: hiçbir alanı veya doğrulama mantığı
    paylaşmaz, MemoryStore Protocol'üne bağımlı değildir ve şu an hiçbir
    kalıcı depoya yazılmaz.
    """

    model_config = ConfigDict(frozen=False)

    # ------------------------------------------------------------------ kimlik
    id: str = Field(default_factory=_new_id)

    # ------------------------------------------------------------ oturum/zaman
    session_id: str | None = None
    occurred_at: datetime

    # --------------------------------------------------------- konuşma bağlamı
    user_message: str
    assistant_response: str | None = None
    tool_calls: list[str] = Field(default_factory=list)

    # ------------------------------------------------- geleceğe hazır (BOŞ) ---
    # Bu iki alan kasıtlı olarak yer tutucudur — bu fazda hiçbir mantık
    # tarafından doldurulmaz veya okunmaz. Emotion engine implementasyonu
    # sonraki, ayrı bir fazın kapsamındadır.
    user_state: dict[str, Any] | None = None
    emotional_context: dict[str, Any] | None = None

    # -------------------------------------------------------------- sonuç/çıktı
    outcome: ExperienceOutcome = ExperienceOutcome.UNKNOWN
    derived_memory_ids: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------------ ek veri
    metadata: dict[str, Any] = Field(default_factory=dict)
