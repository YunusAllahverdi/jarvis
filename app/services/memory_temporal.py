"""Zamansal bellek çakışma çözümü: aynı konudaki eski etkin kayıtları
geçersizleştirip yeni kaydı etkin olarak ekleyen deterministik servis.

Temel ilke (hiçbir zaman ihlal edilmez):
    Değişen bir bellek yüzünden hiçbir kayıt FİZİKSEL OLARAK SİLİNMEZ.
    Eski kayıt korunur; yalnızca `invalid_at` ayarlanır (SQLiteMemoryStore'un
    zaten sağladığı `invalidate()` üzerinden). Yeni kayıt, güncel/etkin
    durumu temsil eden ayrı bir kayıt olarak eklenir.

Mimari kurallar:
- Yalnızca MemoryStore Protocol'üne bağımlıdır; SQLiteMemoryStore'a değil.
- Çakışma tespiti tamamen deterministiktir ve `MemoryExtractor` tarafından
  ADAYA açıkça eklenmiş `metadata["topic_key"]` alanına dayanır. Serbest
  metin (content) üzerinde HİÇBİR subject/predicate ayrıştırması veya
  benzerlik/skorlama YAPILMAZ — mevcut MemoryRecord şeması (yapılandırılmamış
  `content: str`) bunu güvenle desteklemiyor, ve böyle bir ayrıştırıcı
  icat etmek bu fazın kapsamı dışında bırakıldı.
- topic_key yoksa (extractor sağlamadıysa) çakışma kontrolü tamamen atlanır
  ve kayıt olduğu gibi eklenir — YANLIŞ POZİTİF geçersizleştirmeye karşı
  kasıtlı olarak muhafazakâr (conservative) davranır.
- LLM hiçbir zaman hangi veritabanı kaydının geçersizleştirileceğine karar
  vermez: LLM yalnızca YENİ adaya bir topic_key ETİKETİ ekler (mevcut
  kayıtları hiç görmez, hiçbir ID bilmez). Hangi eski kaydın (varsa)
  geçersizleştirileceği kararı tamamen bu serviste, deterministik eşitlik
  karşılaştırmasıyla verilir.

BİLİNEN SINIRLAMA: topic_key tutarlılığı LLM'in aynı gerçek-dünya "yuvası"
için farklı turlarda AYNI etiketi üretmesine bağlıdır. Bu gerçek bir varlık
çözümlemesi (entity resolution) değildir. LLM tutarsız bir topic_key
üretirse (örn. bir seferinde "residence", diğerinde "user_city"), çakışma
YAKALANMAZ — eski kayıt geçersizleştirilmeden etkin kalır. Bu, güvenli
tarafta bir hata modudur (asla ilgisiz bir belleği yanlışlıkla
geçersizleştirmez; olsa olsa gerçek bir çakışmayı gözden kaçırır).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from app.memory.record import MemoryRecord
from app.memory.store import MemoryStore

logger = logging.getLogger(__name__)

_TOPIC_KEY_FIELD = "topic_key"

# Aynı memory_type için taranacak maksimum etkin kayıt sayısı. Şema yeni bir
# sorgulanabilir sütun eklemeden (metadata düz bir JSON metin alanı olduğundan
# SQL düzeyinde filtrelenemiyor) bu, bilinçli bir ölçeklenebilirlik sınırıdır.
_MAX_CANDIDATES_SCANNED = 1000


class TemporalWriteResult(BaseModel):
    """write() çağrısının çağırana döndürdüğü sonuç."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    record: MemoryRecord
    """Depoya eklenen (yeni etkin) kayıt."""

    invalidated_ids: list[str] = Field(default_factory=list)
    """Bu yazma nedeniyle geçersizleştirilen önceki kayıtların id'leri."""

    @property
    def replaced_conflict(self) -> bool:
        """En az bir önceki kayıt geçersizleştirildiyse True."""
        return len(self.invalidated_ids) > 0


class MemoryTemporalService:
    """Yeni bir bellek kaydını, aynı konudaki önceki etkin kayıtları
    geçersizleştirdikten sonra depoya ekler.

    Kullanım:
        service = MemoryTemporalService(store=store)
        result = service.write(new_record)
        # result.invalidated_ids -> geçersizleştirilen eski kayıtların id'leri

    Yalnızca MemoryStore Protocol'üne bağımlıdır — çağıranlar (ör.
    MemoryWriteService) bu servisin SQLite mi yoksa başka bir backend mi
    kullandığını bilmek zorunda değildir.
    """

    def __init__(self, *, store: MemoryStore) -> None:
        self._store = store

    def write(self, record: MemoryRecord) -> TemporalWriteResult:
        """Yeni kaydı depoya ekler; önce aynı konudaki etkin çakışmaları
        geçersizleştirir.

        Fiziksel silme asla yapılmaz — yalnızca `MemoryStore.invalidate()`
        (invalid_at) kullanılır. `record`'un kendisi hiç değiştirilmez.
        """
        topic_key = _topic_key_of(record)
        invalidated_ids: list[str] = []

        if topic_key is not None:
            for conflicting in self._find_active_conflicts(record, topic_key):
                if self._store.invalidate(conflicting.id):
                    invalidated_ids.append(conflicting.id)
                    logger.info(
                        "memory_conflict_invalidated",
                        extra={
                            "old_memory_id": conflicting.id,
                            "new_memory_id": record.id,
                            "memory_type": record.memory_type.value,
                            "topic_key": topic_key,
                        },
                    )

        stored = self._store.add(record)
        return TemporalWriteResult(record=stored, invalidated_ids=invalidated_ids)

    def _find_active_conflicts(
        self, record: MemoryRecord, topic_key: str
    ) -> list[MemoryRecord]:
        """Aynı memory_type ve aynı topic_key'e sahip, hâlâ etkin olan
        (silinmemiş, geçersizleştirilmemiş) kayıtları döndürür."""
        candidates = self._store.list_active(
            memory_type=record.memory_type,
            limit=_MAX_CANDIDATES_SCANNED,
        )
        return [
            existing
            for existing in candidates
            if existing.id != record.id and _topic_key_of(existing) == topic_key
        ]


def _topic_key_of(record: MemoryRecord) -> str | None:
    """Bir kaydın metadata'sından topic_key'i çıkarır; yoksa/boşsa None."""
    value = record.metadata.get(_TOPIC_KEY_FIELD)
    return value if isinstance(value, str) and value.strip() else None
