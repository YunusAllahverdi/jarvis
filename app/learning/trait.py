"""Kullanıcı modeli için türetilmiş özellik (trait) veri modeli.

Bir `UserTrait`, Memory ve Experience kayıtlarından DETERMİNİSTİK olarak
türetilen, kullanıcı hakkında zaman içinde biriken bir gözlemdir:

    "Kullanıcı sık sık saat soruyor."        → RECURRING_NEED
    "Kullanıcı Python konusuyla ilgileniyor." → INTEREST
    "Kullanıcı akşamları aktif."              → PATTERN
    "Kullanıcı sade cevapları tercih ediyor." → PREFERENCE

Mimari kurallar:
- Trait'ler TÜRETİLMİŞ veridir; gerçeğin kaynağı her zaman MemoryRecord ve
  Experience kayıtlarıdır. Bir trait silinse bile bir sonraki öğrenme
  geçişinde kaynaklardan yeniden üretilebilir.
- Bir trait'in kimliği `(trait_type, key)` çiftidir. Aynı çift için aynı anda
  yalnızca BİR etkin trait bulunabilir (depo katmanında kısıtla zorlanır).
- Güven (confidence) bir LLM tahmini DEĞİLDİR: yalnızca kanıt sayısının
  deterministik bir fonksiyonudur (aşağıdaki `confidence_from_evidence`).
- Fiziksel silme yoktur — MemoryRecord'daki gibi mantıksal geçersizleştirme
  (`invalid_at`) kullanılır.
- Bu modül saf veri modelidir: hiçbir depoya yazmaz, hiçbir LLM çağırmaz,
  hiçbir I/O yapmaz.

Duygu/emotion modellemesi bu katmanın KAPSAMI DIŞINDADIR. Trait'ler
davranışsal ve olgusal gözlemlerdir; içsel bir duygu durumu simülasyonu
ileride ayrı bir bileşen olarak ele alınacaktır.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Güven (confidence) modeli
# ---------------------------------------------------------------------------

_CONFIDENCE_SMOOTHING = 4.0
"""Yumuşatma sabiti. Büyüdükçe aynı kanıt sayısı için güven düşer."""


def confidence_from_evidence(evidence_count: int) -> float:
    """Kanıt sayısını 0..1 aralığında deterministik bir güven değerine çevirir.

    Formül (Bayesçi yumuşatmaya benzer, doyuma ulaşan bir eğri):

        confidence = evidence / (evidence + 4)

    Örnek değerler:
        1 kanıt  → 0.20
        2 kanıt  → 0.33
        4 kanıt  → 0.50
        12 kanıt → 0.75
        36 kanıt → 0.90

    Değer hiçbir zaman 1.0'a ULAŞMAZ. Bu bilinçlidir: hiçbir gözlem sayısı
    kullanıcı hakkında mutlak kesinlik anlamına gelmez ve sistem hiçbir
    zaman "bundan eminim" diyecek bir eşiğe kilitlenmemelidir.

    Args:
        evidence_count: Bu trait'i destekleyen bağımsız gözlem sayısı.
            Sıfır veya negatif değerler 0.0 döndürür.
    """
    if evidence_count <= 0:
        return 0.0
    return round(evidence_count / (evidence_count + _CONFIDENCE_SMOOTHING), 4)


# ---------------------------------------------------------------------------
# Sınıflandırmalar
# ---------------------------------------------------------------------------


class TraitType(StrEnum):
    """Türetilmiş kullanıcı özelliğinin anlamsal türü."""

    PREFERENCE = "preference"
    """Kullanıcının açıkça belirttiği tercih (Memory PREFERENCE kayıtlarından)."""

    GOAL = "goal"
    """Kullanıcının sürmekte olan hedefi (Memory GOAL kayıtlarından)."""

    ATTRIBUTE = "attribute"
    """Kullanıcının kalıcı özelliği/gerçeği (Memory FACT kayıtlarından)."""

    INTEREST = "interest"
    """Konuşmalarda tekrar eden konu (Experience geçmişinden)."""

    RECURRING_NEED = "recurring_need"
    """Tekrar eden somut ihtiyaç, ör. sık kullanılan bir tool (Experience'tan)."""

    PATTERN = "pattern"
    """Davranış kalıbı: aktiflik ritmi, oturum derinliği (Experience'tan)."""


class TraitSource(StrEnum):
    """Trait'in hangi kaynaktan türetildiği."""

    MEMORY = "memory"
    EXPERIENCE = "experience"


_KEY_MAX_LENGTH = 120
_KEY_EXTRA_CHARS = frozenset("_:.-")

_DOTTED_I_LOWERED = "i̇"
"""Python'da `"İ".lower()` sonucu: "i" + BİRLEŞİK NOKTA (U+0307).

Birleşik nokta bir harf değildir, dolayısıyla anahtar normalizasyonunda alt
çizgiye dönüşür ve "İLGİ" ile "ilgi" FARKLI anahtarlar üretirdi — aynı kavram
iki ayrı satıra bölünürdü. Türkçe metinlerde sık görülen bu durum, çift
karakterin sade "i"ye indirgenmesiyle giderilir.
"""


def _is_allowed_key_char(char: str) -> bool:
    """Bir karakterin trait anahtarında kullanılabilir olup olmadığını söyler.

    İzin verilenler: küçük harfli HERHANGİ BİR dilin harfleri, rakamlar ve
    `_ : . -` ayırıcıları.

    Anahtar kümesi bilinçli olarak ASCII ile SINIRLI DEĞİLDİR. ASCII'ye
    kısıtlamak Türkçe terimleri bozardı ("başlık" → "ba_l_k") ve daha kötüsü
    farklı kelimeleri aynı anahtara çökerterek ilgisiz gözlemleri tek bir
    trait'te birleştirirdi. Küçük/büyük harf ayrımı korunur: anahtarlar her
    zaman küçük harflidir, böylece aynı kavram tek bir satıra düşer.
    """
    return char in _KEY_EXTRA_CHARS or (char.isalnum() and not char.isupper())


def _new_id() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_trait_key(raw: str) -> str:
    """Serbest metni deterministik, tekrarlanabilir bir trait anahtarına çevirir.

    Aynı girdi her zaman aynı anahtarı üretir — öğrenme geçişlerinin
    idempotent (tekrar çalıştırılabilir) olması buna dayanır.

    Küçük harfe indirilir; izin verilmeyen karakterler alt çizgiye dönüşür;
    ardışık alt çizgiler tekilleştirilir; 120 karakterde kesilir.
    """
    lowered = raw.strip().lower().replace(_DOTTED_I_LOWERED, "i")
    replaced = "".join(char if _is_allowed_key_char(char) else "_" for char in lowered)
    collapsed = re.sub(r"_{2,}", "_", replaced).strip("_")
    return collapsed[:_KEY_MAX_LENGTH] or "unknown"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class UserTrait(BaseModel):
    """Kullanıcı hakkında türetilmiş, kanıta dayalı tek bir gözlem."""

    model_config = ConfigDict(frozen=False)

    # ------------------------------------------------------------------ kimlik
    id: str = Field(default_factory=_new_id)

    trait_type: TraitType
    """Gözlemin anlamsal türü."""

    key: str = Field(min_length=1, max_length=120)
    """Normalize edilmiş kimlik anahtarı, ör. `tool:get_time`, `topic:python`.

    `(trait_type, key)` çifti bir trait'i benzersiz kılar: aynı çift için
    aynı anda yalnızca bir ETKİN trait bulunabilir.
    """

    # ----------------------------------------------------------------- içerik
    value: str = Field(min_length=1, max_length=2000)
    """İnsan tarafından okunabilir gözlem metni."""

    # ------------------------------------------------------------------ kanıt
    evidence_count: int = Field(default=1, ge=0)
    """Bu gözlemi destekleyen bağımsız kaynak sayısı."""

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    """`confidence_from_evidence(evidence_count)` ile hesaplanan güven."""

    source: TraitSource
    """Trait'in türetildiği kaynak katman."""

    # --------------------------------------------------------------- zamansal
    first_observed_at: datetime = Field(default_factory=_utcnow)
    """İlk kez gözlendiği an. Sonraki geçişlerde KORUNUR."""

    last_observed_at: datetime = Field(default_factory=_utcnow)
    """En son gözlendiği an. Her öğrenme geçişinde tazelenir."""

    invalid_at: datetime | None = None
    """None ise etkin. Dolu ise mantıksal olarak geçersiz (fiziksel silme yok)."""

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # ---------------------------------------------------------------- ek veri
    metadata: dict[str, Any] = Field(default_factory=dict)
    """Türetme ayrıntıları (ör. kaynak memory id'leri, ham sayımlar)."""

    @field_validator("key")
    @classmethod
    def key_must_be_normalized(cls, v: str) -> str:
        """Anahtarın normalize edilmiş biçimde olmasını zorunlu kılar.

        Serbest metin anahtarları sessizce kabul edilirse aynı kavram farklı
        geçişlerde farklı satırlar üretir ve idempotentlik bozulur.
        """
        if not v or len(v) > _KEY_MAX_LENGTH or not all(map(_is_allowed_key_char, v)):
            raise ValueError(
                f"trait key {v!r} normalize edilmemiş; yalnızca küçük harfler, "
                "rakamlar ve `_:.-` karakterleri kullanılabilir "
                "(bkz. normalize_trait_key)"
            )
        return v

    @property
    def is_active(self) -> bool:
        """Mantıksal olarak geçersizleştirilmemişse True."""
        return self.invalid_at is None
