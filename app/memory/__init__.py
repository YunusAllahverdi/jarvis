"""Jarvis bellek katmanı — soyut sözleşmeler ve temel veri modelleri.

Bu paket, depolama bağımsız bellek arayüzlerini tanımlar.
Somut implementasyonlar (RAM, SQLite, vektör veritabanı vb.) bu
sözleşmeleri uygulayan ayrı sınıflar olarak eklenecektir.

Katmanlar:
- base      : Tüm bellek tipleri için ortak veri modelleri
- working   : Çalışma belleği — aktif oturum bağlamı (geçici)
- episodic  : Episodik bellek — olaylar ve zaman çizgisi (kalıcı)
- semantic  : Anlamsal bellek — gerçekler, varlıklar, tercihler, hedefler (kalıcı)
"""

from app.memory.base import (
    Entity,
    Event,
    Fact,
    Goal,
    MemoryEntry,
    Preference,
    Relationship,
    Temporality,
    WorldStateEntry,
)
from app.memory.episodic import EpisodicMemoryStore
from app.memory.semantic import SemanticMemoryStore
from app.memory.working import WorkingMemoryStore

__all__ = [
    # Veri modelleri
    "Entity",
    "Event",
    "Fact",
    "Goal",
    "MemoryEntry",
    "Preference",
    "Relationship",
    "Temporality",
    "WorldStateEntry",
    # Sözleşmeler
    "EpisodicMemoryStore",
    "SemanticMemoryStore",
    "WorkingMemoryStore",
]
