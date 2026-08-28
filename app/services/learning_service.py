"""Memory ve Experience kayıtlarından kullanıcı modelini (trait) türeten servis.

Akış:

    ExperienceStore.list_recent()  ─┐
                                    ├─► derive_traits()  ─► UserTraitStore.upsert()
    MemoryStore.list_active()     ─┘      (saf fonksiyon)

Mimari kurallar:
- Yalnızca Protocol'lere bağımlıdır (MemoryStore, ExperienceStore,
  UserTraitStore); hiçbir somut SQLite sınıfını import etmez.
- HİÇBİR LLM ÇAĞRILMAZ. Türetme tamamen deterministiktir ve açıklanabilir
  eşiklere dayanır (aşağıdaki `_MIN_*` sabitleri). Bu, mevcut
  MemoryTemporalService'in tasarım felsefesiyle aynıdır: LLM etiket üretir,
  KARAR deterministik katmanda verilir.
- IDEMPOTENT: `run_pass()` kanıt sayılarını ARTIRMAZ; her geçişte kaynak
  pencereden YENİDEN hesaplar. Aynı geçişi arka arkaya iki kez çalıştırmak
  aynı sonucu verir. Bu, "her turda +1" yaklaşımının kaçınılmaz olarak
  ürettiği çift sayım hatalarını baştan imkânsız kılar.
- Sohbet akışının dışındadır: hiçbir ChatOrchestrator yolundan çağrılmaz.
  Öğrenme geçişi açık bir eylemdir (API veya doğrudan servis çağrısı), bu
  yüzden bir sohbet cevabını hiçbir koşulda geciktiremez veya bozamaz.
- Hiçbir istisna çağırana sızmaz: hata durumunda `failed=True` taşıyan bir
  sonuç döner (mevcut MemoryWriteService deseniyle aynı).

KAPSAM DIŞI (bilinçli):
- Emotion/duygu çıkarımı yoktur.
- Embedding, vektör veritabanı veya benzerlik modeli yoktur.
- Trait'lerin otomatik olarak "unutulması"/çürütülmesi (decay) yoktur:
  bir gözlem pencereden çıktığında ETKİN kalmaya devam eder. Bu bilinçli
  olarak muhafazakârdır — yanlışlıkla geçerli bir gözlemi silmektense
  eskimiş bir gözlemi tutmak tercih edilir. Geçersizleştirme yalnızca açık
  bir çağrıyla (`UserTraitStore.invalidate`) yapılır.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel

from app.learning.analyzer import ExperienceAnalysis, analyze_experiences
from app.learning.trait import (
    TraitSource,
    TraitType,
    UserTrait,
    confidence_from_evidence,
    normalize_trait_key,
)
from app.learning.trait_store import UserTraitStore
from app.memory.experience import Experience
from app.memory.experience_store import ExperienceStore
from app.memory.record import MemoryRecord, MemoryType
from app.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Türetme eşikleri
# ---------------------------------------------------------------------------
#
# Hepsi bilinçli olarak muhafazakârdır: tek bir gözlemden kullanıcı hakkında
# kalıcı bir sonuç çıkarmak, yanlış bir kullanıcı modeli oluşturmanın en hızlı
# yoludur. Eşiğin altında kalan sinyaller sessizce yok sayılır.

_MIN_TOOL_USES = 2
"""Bir tool'un "tekrar eden ihtiyaç" sayılması için minimum kullanım sayısı."""

_MIN_TOPIC_DOCUMENT_FREQUENCY = 3
"""Bir terimin "ilgi alanı" sayılması için geçmesi gereken ayrı tur sayısı."""

_MIN_EXPERIENCES_FOR_RHYTHM = 5
"""Aktiflik ritmi çıkarmak için gereken minimum tur sayısı."""

_MIN_RHYTHM_SHARE = 0.4
"""Baskın günün bölümünün kalıp sayılması için gereken minimum pay."""

_MIN_SESSIONS_FOR_DEPTH = 3
"""Oturum derinliği kalıbı için gereken minimum oturum sayısı."""

_DEFAULT_EXPERIENCE_WINDOW = 500
"""Tek geçişte incelenecek maksimum deneyim sayısı."""

_DEFAULT_MEMORY_WINDOW = 500
"""Tek geçişte incelenecek maksimum etkin bellek kaydı sayısı."""

_MEMORY_TRAIT_TYPES: dict[MemoryType, TraitType] = {
    MemoryType.PREFERENCE: TraitType.PREFERENCE,
    MemoryType.GOAL: TraitType.GOAL,
    MemoryType.FACT: TraitType.ATTRIBUTE,
}
"""Hangi bellek türünün hangi trait türüne dönüştüğü."""

_TOPIC_KEY_FIELD = "topic_key"


class LearningPassResult(BaseModel):
    """`run_pass()` çağrısının özeti. Hata durumunda da her zaman döner."""

    experiences_analyzed: int = 0
    memories_analyzed: int = 0
    traits_derived: int = 0
    traits_created: int = 0
    traits_updated: int = 0
    failed: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed


# ---------------------------------------------------------------------------
# Saf türetme fonksiyonları
# ---------------------------------------------------------------------------


def _content_key(record: MemoryRecord) -> str:
    """Bir bellek kaydı için deterministik, tekrarlanabilir trait anahtarı üretir.

    `topic_key` varsa o kullanılır (aynı konudaki kayıtlar tek bir trait'te
    birleşir). Yoksa içeriğin sha256 özetinin ilk 12 karakteri kullanılır —
    aynı içerik her geçişte aynı anahtarı üretir, dolayısıyla tekrarlanan
    geçişler yeni satır oluşturmaz.
    """
    topic_key = record.metadata.get(_TOPIC_KEY_FIELD)
    if isinstance(topic_key, str) and topic_key.strip():
        return normalize_trait_key(f"memory:{topic_key}")
    digest = hashlib.sha256(record.content.strip().lower().encode("utf-8")).hexdigest()
    return f"memory:sha256:{digest[:12]}"


def derive_traits_from_memories(
    memories: Sequence[MemoryRecord],
    *,
    now: datetime,
) -> list[UserTrait]:
    """Etkin bellek kayıtlarından profil trait'leri türetir.

    - PREFERENCE kayıtları → PREFERENCE trait
    - GOAL kayıtları       → GOAL trait
    - FACT kayıtları       → ATTRIBUTE trait, ANCAK yalnızca `topic_key`
      taşıyanlar. Bu bilinçli bir filtredir: her serbest gerçek kalıcı bir
      kullanıcı özelliği değildir; `topic_key`, çıkarıcının o kaydı kararlı
      bir "yuva" olarak gördüğünün işaretidir.

    Aynı anahtara düşen birden fazla kayıt tek bir trait'te birleşir ve kanıt
    sayısı kayıt adedi olur.
    """
    grouped: dict[tuple[TraitType, str], list[MemoryRecord]] = defaultdict(list)
    for record in memories:
        trait_type = _MEMORY_TRAIT_TYPES.get(record.memory_type)
        if trait_type is None:
            continue
        if trait_type is TraitType.ATTRIBUTE and not _has_topic_key(record):
            continue
        grouped[(trait_type, _content_key(record))].append(record)

    traits: list[UserTrait] = []
    for (trait_type, key), records in grouped.items():
        newest = max(records, key=lambda r: r.valid_at)
        evidence = len(records)
        traits.append(
            UserTrait(
                trait_type=trait_type,
                key=key,
                value=newest.content,
                evidence_count=evidence,
                confidence=confidence_from_evidence(evidence),
                source=TraitSource.MEMORY,
                first_observed_at=min(r.valid_at for r in records),
                last_observed_at=newest.valid_at,
                created_at=now,
                updated_at=now,
                metadata={
                    "memory_ids": sorted(r.id for r in records),
                    "memory_type": newest.memory_type.value,
                },
            )
        )
    return traits


def _has_topic_key(record: MemoryRecord) -> bool:
    value = record.metadata.get(_TOPIC_KEY_FIELD)
    return isinstance(value, str) and bool(value.strip())


def derive_traits_from_analysis(
    analysis: ExperienceAnalysis,
    *,
    now: datetime,
) -> list[UserTrait]:
    """Deneyim analizinden davranışsal trait'ler türetir.

    Üretilen türler:
    - RECURRING_NEED : yeterince sık kullanılan her tool
    - INTEREST       : yeterince çok turda geçen her terim
    - PATTERN        : baskın aktiflik bölümü ve oturum derinliği
    """
    traits: list[UserTrait] = []
    stats = analysis.stats

    for usage in analysis.tool_usage:
        if usage.count < _MIN_TOOL_USES:
            continue
        traits.append(
            UserTrait(
                trait_type=TraitType.RECURRING_NEED,
                key=normalize_trait_key(f"tool:{usage.name}"),
                value=usage.name,
                evidence_count=usage.count,
                confidence=confidence_from_evidence(usage.count),
                source=TraitSource.EXPERIENCE,
                first_observed_at=stats.first_seen_at or now,
                last_observed_at=stats.last_seen_at or now,
                created_at=now,
                updated_at=now,
                metadata={"share_of_tool_calls": usage.share},
            )
        )

    for topic in analysis.topics:
        if topic.document_frequency < _MIN_TOPIC_DOCUMENT_FREQUENCY:
            continue
        traits.append(
            UserTrait(
                trait_type=TraitType.INTEREST,
                key=normalize_trait_key(f"topic:{topic.term}"),
                value=topic.term,
                evidence_count=topic.document_frequency,
                confidence=confidence_from_evidence(topic.document_frequency),
                source=TraitSource.EXPERIENCE,
                first_observed_at=stats.first_seen_at or now,
                last_observed_at=stats.last_seen_at or now,
                created_at=now,
                updated_at=now,
                metadata={"document_frequency": topic.document_frequency},
            )
        )

    rhythm = analysis.rhythm
    if (
        stats.total_experiences >= _MIN_EXPERIENCES_FOR_RHYTHM
        and rhythm.dominant_bucket is not None
        and rhythm.dominant_share >= _MIN_RHYTHM_SHARE
    ):
        evidence = rhythm.bucket_counts.get(rhythm.dominant_bucket, 0)
        traits.append(
            UserTrait(
                trait_type=TraitType.PATTERN,
                key="active_period",
                value=rhythm.dominant_bucket,
                evidence_count=evidence,
                confidence=confidence_from_evidence(evidence),
                source=TraitSource.EXPERIENCE,
                first_observed_at=stats.first_seen_at or now,
                last_observed_at=stats.last_seen_at or now,
                created_at=now,
                updated_at=now,
                metadata={
                    "dominant_share": rhythm.dominant_share,
                    "bucket_counts": rhythm.bucket_counts,
                    "hour_offset": rhythm.hour_offset,
                },
            )
        )

    if stats.session_count >= _MIN_SESSIONS_FOR_DEPTH:
        depth = _session_depth_label(stats.average_turns_per_session)
        traits.append(
            UserTrait(
                trait_type=TraitType.PATTERN,
                key="session_depth",
                value=depth,
                evidence_count=stats.session_count,
                confidence=confidence_from_evidence(stats.session_count),
                source=TraitSource.EXPERIENCE,
                first_observed_at=stats.first_seen_at or now,
                last_observed_at=stats.last_seen_at or now,
                created_at=now,
                updated_at=now,
                metadata={"average_turns_per_session": stats.average_turns_per_session},
            )
        )

    return traits


def _session_depth_label(average_turns: float) -> str:
    """Ortalama oturum uzunluğunu açıklanabilir bir etikete çevirir."""
    if average_turns < 2:
        return "short"
    if average_turns < 5:
        return "medium"
    return "deep"


# ---------------------------------------------------------------------------
# Servis
# ---------------------------------------------------------------------------


class LearningService:
    """Kaynak kayıtlardan kullanıcı modelini türetip kalıcı hale getirir.

    Kullanım:
        service = LearningService(
            trait_store=trait_store,
            memory_store=memory_store,
            experience_store=experience_store,
        )
        result = service.run_pass()

    Kaynaklar isteğe bağlıdır: `memory_store` verilmezse bellek kaynaklı
    trait'ler, `experience_store` verilmezse davranışsal trait'ler üretilmez.
    Her ikisi de None ise geçiş boş bir sonuçla tamamlanır — hata değildir.
    """

    def __init__(
        self,
        *,
        trait_store: UserTraitStore,
        memory_store: MemoryStore | None = None,
        experience_store: ExperienceStore | None = None,
        experience_window: int = _DEFAULT_EXPERIENCE_WINDOW,
        memory_window: int = _DEFAULT_MEMORY_WINDOW,
        hour_offset: int = 0,
    ) -> None:
        """
        Args:
            trait_store: Türetilen trait'lerin yazılacağı depo.
            memory_store: Tercih/hedef/özellik trait'lerinin kaynağı.
            experience_store: Davranışsal trait'lerin kaynağı.
            experience_window: Tek geçişte incelenecek maksimum deneyim sayısı.
            memory_window: Tek geçişte incelenecek maksimum etkin bellek sayısı.
            hour_offset: Aktiflik ritmi için UTC saat ofseti (bkz. analyzer).
        """
        self._trait_store = trait_store
        self._memory_store = memory_store
        self._experience_store = experience_store
        self._experience_window = experience_window
        self._memory_window = memory_window
        self._hour_offset = hour_offset

    def run_pass(self, *, now: datetime | None = None) -> LearningPassResult:
        """Tek bir öğrenme geçişi çalıştırır ve özeti döndürür.

        Hiçbir zaman istisna fırlatmaz; beklenmedik bir hata olursa
        `failed=True` taşıyan bir sonuç döner.
        """
        moment = now or datetime.now(UTC)
        try:
            experiences = self._load_experiences()
            memories = self._load_memories()

            analysis = analyze_experiences(experiences, hour_offset=self._hour_offset)
            derived = [
                *derive_traits_from_analysis(analysis, now=moment),
                *derive_traits_from_memories(memories, now=moment),
            ]

            created = 0
            updated = 0
            for trait in derived:
                existing = self._trait_store.find_active(trait.trait_type, trait.key)
                self._trait_store.upsert(trait)
                if existing is None:
                    created += 1
                else:
                    updated += 1

            result = LearningPassResult(
                experiences_analyzed=len(experiences),
                memories_analyzed=len(memories),
                traits_derived=len(derived),
                traits_created=created,
                traits_updated=updated,
            )
            logger.info("learning_pass_complete", extra=result.model_dump())
            return result
        except Exception:  # noqa: BLE001
            logger.exception("learning_pass_failed")
            return LearningPassResult(failed=True)

    # ------------------------------------------------------------------
    # Kaynak okuma
    # ------------------------------------------------------------------

    def _load_experiences(self) -> list[Experience]:
        if self._experience_store is None:
            return []
        return self._experience_store.list_recent(limit=self._experience_window)

    def _load_memories(self) -> list[MemoryRecord]:
        if self._memory_store is None:
            return []
        return self._memory_store.list_active(limit=self._memory_window)
