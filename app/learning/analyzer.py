"""Experience geçmişi üzerinde deterministik davranış analizi (saf fonksiyonlar).

Mimari kurallar:
- Bu modül TAMAMEN SAFTIR: hiçbir LLM çağırmaz, hiçbir depoya erişmez,
  hiçbir I/O yapmaz, saat okumaz (`generated_at` bile dışarıdan verilir).
  Aynı girdi her zaman aynı çıktıyı üretir — bu, öğrenme geçişlerinin
  tekrar çalıştırılabilir (idempotent) olmasının temelidir.
- Hiçbir embedding, vektör veritabanı veya benzerlik modeli kullanılmaz.
  Konu tespiti klasik, açıklanabilir bir yöntemle yapılır: durak kelimeler
  (stopword) elendikten sonra DÖKÜMAN FREKANSI (kaç ayrı konuşma turunda
  geçtiği) sayılır. Ham kelime tekrarı değil döküman frekansı kullanılır;
  böylece tek bir uzun mesaj bir konuyu tek başına "ilgi alanı" yapamaz.
- Hiçbir duygu/emotion çıkarımı YAPILMAZ. Buradaki sinyaller yalnızca
  davranışsal ve sayılabilir olgulardır.

Bilinen sınırlama — ZAMAN DİLİMİ:
    Experience zaman damgaları UTC saklanır. Aktiflik ritmi hesaplanırken
    `hour_offset` verilmezse saatler UTC olarak yorumlanır; bu, kullanıcının
    yerel gününe göre kaymış olabilir. Gerçek bir yerel saat dilimi
    çözümlemesi bu fazın kapsamı dışındadır, bu yüzden ofset açık bir
    parametre olarak dışarıya bırakılmıştır (varsayılan 0 = UTC).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from app.memory.experience import Experience

# ---------------------------------------------------------------------------
# Konu tespiti için durak kelimeler
# ---------------------------------------------------------------------------
#
# Liste bilinçli olarak kısa ve açıklanabilir tutulmuştur: amaç tam bir
# dilbilimsel kapsama değil, en sık görülen içerik taşımayan kelimeleri
# elemektir. Yetersiz kaldığı yerde `min_term_length` ve döküman frekansı
# eşiği ikinci bir savunma hattı oluşturur.

_TURKISH_STOPWORDS = frozenset(
    """
    acaba ama ancak artık aslında az bana bazı belki ben beni benim beri bile bir
    biraz birçok biri birkaç birşey biz bize bizi bizim bu buna bunda bundan bunlar
    bunları bunların bunu bunun burada çok çünkü da daha de defa değil diğer diye
    dolayı edilecek eden ederek edilen eğer en fakat gibi göre halen hangi hani hatta
    hem henüz hep hepsi her herhangi hiç için içinde ile ise itibaren kadar karşın
    kendi kez ki kim kimi kimse mi mı mu mü nasıl ne neden nedenle nerde nerede
    nereye niçin niye o olan olarak oldu olduğu olduğunu olsa olsun olup olur olursa
    oluyor ona ondan onlar onları onların onu onun orada öyle önce ötürü öyleyse
    sadece sanki şey şeyden şeye şeyi şeyler şöyle şu şuna şunda şundan şunu tarafından
    trilyon tüm üzere var vardı ve veya ya yani yerine yine yoksa zaten
    bugün şimdi sonra evet hayır tamam lütfen merhaba selam teşekkür teşekkürler
    nasılsın naber günaydın iyiyim rica ederim görüşürüz
    """.split()
)

_ENGLISH_STOPWORDS = frozenset(
    """
    a about after all also am an and any are as at be because been before being
    between both but by can could did do does doing don down during each few for
    from further had has have having he her here hers him his how i if in into is
    it its just me more most my no nor not now of off on once only or other our out
    over own same she should so some such than that the their them then there these
    they this those through to too under until up very was we were what when where
    which while who why will with you your yours
    please thanks thank hello hey okay yes
    """.split()
)

_STOPWORDS = _TURKISH_STOPWORDS | _ENGLISH_STOPWORDS

_WORD_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)
"""Yalnızca harflerden oluşan kelimeler; rakamlar ve noktalama elenir."""

# ---------------------------------------------------------------------------
# Günün bölümleri
# ---------------------------------------------------------------------------

NIGHT = "night"
MORNING = "morning"
AFTERNOON = "afternoon"
EVENING = "evening"

_BUCKET_RANGES: tuple[tuple[str, int, int], ...] = (
    (NIGHT, 0, 5),
    (MORNING, 6, 11),
    (AFTERNOON, 12, 17),
    (EVENING, 18, 23),
)


def _bucket_for_hour(hour: int) -> str:
    for name, start, end in _BUCKET_RANGES:
        if start <= hour <= end:
            return name
    return NIGHT  # ulaşılamaz; savunma amaçlı


# ---------------------------------------------------------------------------
# Analiz çıktısı modelleri
# ---------------------------------------------------------------------------


class ToolUsage(BaseModel):
    """Tek bir tool'un kullanım sıklığı."""

    name: str
    count: int
    share: float = Field(ge=0.0, le=1.0)
    """Bu tool'un tüm tool çağrıları içindeki payı."""


class TopicSignal(BaseModel):
    """Tekrar eden bir konu terimi."""

    term: str
    document_frequency: int
    """Terimin geçtiği AYRI konuşma turu sayısı (ham tekrar sayısı değil)."""


class ActivityRhythm(BaseModel):
    """Kullanıcının gün içindeki aktiflik dağılımı."""

    hour_counts: dict[str, int] = Field(default_factory=dict)
    """Saat (0-23, string anahtar) → tur sayısı. Yalnızca dolu saatler yer alır."""

    bucket_counts: dict[str, int] = Field(default_factory=dict)
    """night/morning/afternoon/evening → tur sayısı."""

    dominant_bucket: str | None = None
    """En yoğun bölüm; hiç veri yoksa None."""

    dominant_share: float = Field(default=0.0, ge=0.0, le=1.0)
    """Baskın bölümün toplam içindeki payı."""

    hour_offset: int = 0
    """Saatlerin UTC'ye göre kaydırıldığı ofset (0 = UTC yorumlanmıştır)."""


class InteractionStats(BaseModel):
    """Etkileşim geçmişinin sayısal özeti — frontend paneli için de uygundur."""

    total_experiences: int = 0
    session_count: int = 0
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    total_tool_calls: int = 0
    average_tools_per_turn: float = 0.0
    average_turns_per_session: float = 0.0


class ExperienceAnalysis(BaseModel):
    """`analyze_experiences()` çıktısının tamamı."""

    stats: InteractionStats = Field(default_factory=InteractionStats)
    tool_usage: list[ToolUsage] = Field(default_factory=list)
    topics: list[TopicSignal] = Field(default_factory=list)
    rhythm: ActivityRhythm = Field(default_factory=ActivityRhythm)


# ---------------------------------------------------------------------------
# Analiz
# ---------------------------------------------------------------------------


def extract_terms(text: str, *, min_term_length: int = 4) -> set[str]:
    """Bir metinden durak kelimeler elenmiş, benzersiz terim kümesi çıkarır.

    Küme döndürülür (liste değil): aynı turda tekrar eden bir kelime tek
    kanıt sayılır — döküman frekansı mantığının temeli budur.
    """
    terms: set[str] = set()
    for match in _WORD_PATTERN.finditer(text.lower()):
        word = match.group()
        if len(word) < min_term_length or word in _STOPWORDS:
            continue
        terms.add(word)
    return terms


def analyze_experiences(
    experiences: Sequence[Experience],
    *,
    hour_offset: int = 0,
    max_topics: int = 20,
    max_tools: int = 20,
    min_term_length: int = 4,
) -> ExperienceAnalysis:
    """Experience listesinden deterministik davranış sinyalleri çıkarır.

    Args:
        experiences: Analiz edilecek deneyimler. Sıra önemsizdir.
        hour_offset: Aktiflik ritmi için UTC saatlerine eklenecek saat ofseti.
            Varsayılan 0 (saatler UTC olarak yorumlanır).
        max_topics: Döndürülecek maksimum konu sayısı (frekansa göre en üstten).
        max_tools: Döndürülecek maksimum tool sayısı.
        min_term_length: Bir kelimenin konu sayılması için minimum uzunluk.

    Returns:
        ExperienceAnalysis. Boş girdi için tamamen boş ama geçerli bir sonuç.
    """
    if not experiences:
        return ExperienceAnalysis()

    occurred = [e.occurred_at for e in experiences]
    sessions = [e.session_id for e in experiences if e.session_id]
    session_counter = Counter(sessions)

    tool_counter: Counter[str] = Counter()
    for experience in experiences:
        tool_counter.update(experience.tool_calls)
    total_tool_calls = sum(tool_counter.values())

    term_counter: Counter[str] = Counter()
    for experience in experiences:
        term_counter.update(extract_terms(experience.user_message, min_term_length=min_term_length))

    hour_counter: Counter[int] = Counter()
    for moment in occurred:
        hour_counter[(moment.hour + hour_offset) % 24] += 1

    bucket_counter: Counter[str] = Counter()
    for hour, count in hour_counter.items():
        bucket_counter[_bucket_for_hour(hour)] += count

    total = len(experiences)
    # Baskın bölüm de kararlı sıralamayla seçilir: eşit sayımda `most_common`
    # ekleme sırasına düşer ve aynı veri farklı sırayla geldiğinde farklı bir
    # "baskın bölüm" üretirdi.
    dominant_bucket, dominant_count = (
        _stable_most_common(bucket_counter, 1)[0] if bucket_counter else (None, 0)
    )

    stats = InteractionStats(
        total_experiences=total,
        session_count=len(session_counter),
        first_seen_at=min(occurred),
        last_seen_at=max(occurred),
        total_tool_calls=total_tool_calls,
        average_tools_per_turn=round(total_tool_calls / total, 4),
        average_turns_per_session=(
            round(len(sessions) / len(session_counter), 4) if session_counter else 0.0
        ),
    )

    return ExperienceAnalysis(
        stats=stats,
        tool_usage=[
            ToolUsage(name=name, count=count, share=round(count / total_tool_calls, 4))
            for name, count in _stable_most_common(tool_counter, max_tools)
        ],
        topics=[
            TopicSignal(term=term, document_frequency=count)
            for term, count in _stable_most_common(term_counter, max_topics)
        ],
        rhythm=ActivityRhythm(
            hour_counts={str(hour): count for hour, count in sorted(hour_counter.items())},
            bucket_counts=dict(sorted(bucket_counter.items())),
            dominant_bucket=dominant_bucket,
            dominant_share=round(dominant_count / total, 4) if total else 0.0,
            hour_offset=hour_offset,
        ),
    )


def _stable_most_common(counter: Counter[str], limit: int) -> list[tuple[str, int]]:
    """Sayıma göre azalan, eşitlikte alfabetik sırayla ilk `limit` öğeyi döndürür.

    `Counter.most_common()` eşit sayımlarda ekleme sırasını korur; bu, aynı
    veri kümesinin farklı sırayla gelmesi durumunda farklı çıktı üretebilir.
    Alfabetik ikincil sıralama, analizi girdi sırasından tamamen bağımsız
    (deterministik) kılar.
    """
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
