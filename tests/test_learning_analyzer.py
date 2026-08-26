"""Learning katmanı — deterministik Experience analizi testleri.

Kapsam:
 1. Boş girdi geçerli ama tamamen boş bir sonuç üretir
 2. Temel etkileşim istatistikleri doğru hesaplanır
 3. Tool kullanım sıklığı ve payları doğru
 4. Konu tespiti DÖKÜMAN frekansı kullanır (ham tekrar değil)
 5. Durak kelimeler (TR + EN) elenir
 6. Kısa kelimeler ve rakamlar elenir
 7. Aktiflik ritmi ve baskın bölüm doğru
 8. hour_offset saat yorumunu kaydırır
 9. Analiz girdi SIRASINDAN bağımsızdır (deterministik)
10. Analiz saftır: girdiyi değiştirmez, I/O yapmaz, saat okumaz
11. max_topics / max_tools sınırları uygulanır
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from datetime import UTC, datetime

from app.learning import analyzer as analyzer_module
from app.learning.analyzer import (
    AFTERNOON,
    EVENING,
    MORNING,
    NIGHT,
    analyze_experiences,
    extract_terms,
)
from app.memory.experience import Experience

_BASE = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)


def _exp(
    *,
    user_message: str = "test mesajı",
    session_id: str | None = "sess-1",
    hour: int = 9,
    tool_calls: Sequence[str] = (),
    day: int = 26,
) -> Experience:
    return Experience(
        session_id=session_id,
        occurred_at=datetime(2026, 8, day, hour, 0, tzinfo=UTC),
        user_message=user_message,
        assistant_response="cevap",
        tool_calls=list(tool_calls),
    )


# ---------------------------------------------------------------------------
# 1. Boş girdi
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_empty_sequence_yields_empty_but_valid_analysis(self) -> None:
        analysis = analyze_experiences([])

        assert analysis.stats.total_experiences == 0
        assert analysis.stats.first_seen_at is None
        assert analysis.stats.last_seen_at is None
        assert analysis.tool_usage == []
        assert analysis.topics == []
        assert analysis.rhythm.dominant_bucket is None
        assert analysis.rhythm.dominant_share == 0.0


# ---------------------------------------------------------------------------
# 2. Etkileşim istatistikleri
# ---------------------------------------------------------------------------


class TestInteractionStats:
    def test_counts_experiences_and_sessions(self) -> None:
        analysis = analyze_experiences([
            _exp(session_id="a"),
            _exp(session_id="a"),
            _exp(session_id="b"),
        ])

        assert analysis.stats.total_experiences == 3
        assert analysis.stats.session_count == 2
        assert analysis.stats.average_turns_per_session == 1.5

    def test_first_and_last_seen_span_the_whole_history(self) -> None:
        analysis = analyze_experiences([
            _exp(day=20, hour=8),
            _exp(day=26, hour=22),
            _exp(day=23, hour=13),
        ])

        assert analysis.stats.first_seen_at == datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
        assert analysis.stats.last_seen_at == datetime(2026, 8, 26, 22, 0, tzinfo=UTC)

    def test_counts_tool_calls_and_average_per_turn(self) -> None:
        analysis = analyze_experiences([
            _exp(tool_calls=["get_time", "calculator"]),
            _exp(tool_calls=["get_time"]),
            _exp(),
        ])

        assert analysis.stats.total_tool_calls == 3
        assert analysis.stats.average_tools_per_turn == 1.0

    def test_experiences_without_a_session_are_not_counted_as_sessions(self) -> None:
        analysis = analyze_experiences([_exp(session_id=None), _exp(session_id=None)])

        assert analysis.stats.total_experiences == 2
        assert analysis.stats.session_count == 0
        assert analysis.stats.average_turns_per_session == 0.0


# ---------------------------------------------------------------------------
# 3. Tool kullanımı
# ---------------------------------------------------------------------------


class TestToolUsage:
    def test_counts_and_shares_are_correct(self) -> None:
        analysis = analyze_experiences([
            _exp(tool_calls=["get_time", "get_time"]),
            _exp(tool_calls=["get_time", "calculator"]),
        ])

        usage = {u.name: u for u in analysis.tool_usage}
        assert usage["get_time"].count == 3
        assert usage["get_time"].share == 0.75
        assert usage["calculator"].count == 1
        assert usage["calculator"].share == 0.25

    def test_ordered_by_count_descending(self) -> None:
        analysis = analyze_experiences([
            _exp(tool_calls=["calculator"]),
            _exp(tool_calls=["get_time", "get_time"]),
        ])

        assert [u.name for u in analysis.tool_usage] == ["get_time", "calculator"]

    def test_max_tools_limit_is_respected(self) -> None:
        experiences = [_exp(tool_calls=[f"tool_{i}"] * (10 - i)) for i in range(6)]
        analysis = analyze_experiences(experiences, max_tools=2)

        assert len(analysis.tool_usage) == 2
        assert analysis.tool_usage[0].name == "tool_0"


# ---------------------------------------------------------------------------
# 4-6. Konu tespiti
# ---------------------------------------------------------------------------


class TestTopicDetection:
    def test_uses_document_frequency_not_raw_repetition(self) -> None:
        """Tek bir uzun mesaj bir kelimeyi tek başına "ilgi alanı" yapamamalı."""
        analysis = analyze_experiences([
            _exp(user_message="python python python python python python"),
            _exp(user_message="django projesi"),
        ])

        topics = {t.term: t.document_frequency for t in analysis.topics}
        assert topics["python"] == 1  # 6 kez geçti ama tek turda

    def test_counts_distinct_turns(self) -> None:
        analysis = analyze_experiences([
            _exp(user_message="python öğreniyorum"),
            _exp(user_message="python ile ilgili soru"),
            _exp(user_message="bugün hava güzel"),
        ])

        topics = {t.term: t.document_frequency for t in analysis.topics}
        assert topics["python"] == 2

    def test_turkish_stopwords_are_removed(self) -> None:
        analysis = analyze_experiences([
            _exp(user_message="bunu bana çünkü şimdi lütfen teşekkürler"),
            _exp(user_message="bunu bana çünkü şimdi lütfen teşekkürler"),
        ])

        assert analysis.topics == []

    def test_english_stopwords_are_removed(self) -> None:
        analysis = analyze_experiences([
            _exp(user_message="what about these things please thanks"),
            _exp(user_message="what about these things please thanks"),
        ])

        assert [t.term for t in analysis.topics] == ["things"]

    def test_short_words_and_digits_are_ignored(self) -> None:
        analysis = analyze_experiences([_exp(user_message="abc 12345 xy kalibrasyon")])

        assert [t.term for t in analysis.topics] == ["kalibrasyon"]

    def test_min_term_length_is_configurable(self) -> None:
        analysis = analyze_experiences([_exp(user_message="abc kalibrasyon")], min_term_length=3)

        assert {t.term for t in analysis.topics} == {"abc", "kalibrasyon"}

    def test_extract_terms_returns_a_set_so_repeats_count_once(self) -> None:
        assert extract_terms("kalibrasyon kalibrasyon kalibrasyon") == {"kalibrasyon"}

    def test_max_topics_limit_is_respected(self) -> None:
        # Rakamlar kelime sınırı sayıldığından terimler kasıtlı olarak
        # yalnızca harflerden oluşur (aksi halde "terim0kelime" ikiye bölünür).
        words = [f"kelime{chr(97 + i // 5)}{chr(97 + i % 5)}" for i in range(30)]
        analysis = analyze_experiences([_exp(user_message=" ".join(words))], max_topics=5)

        assert len(analysis.topics) == 5

    def test_digits_split_words_rather_than_joining_them(self) -> None:
        """Kelime deseni yalnızca harfleri kabul eder; rakam sınır sayılır."""
        assert extract_terms("terim0kelime") == {"terim", "kelime"}


# ---------------------------------------------------------------------------
# 7-8. Aktiflik ritmi
# ---------------------------------------------------------------------------


class TestActivityRhythm:
    def test_buckets_hours_into_parts_of_day(self) -> None:
        analysis = analyze_experiences([
            _exp(hour=2),
            _exp(hour=8),
            _exp(hour=14),
            _exp(hour=21),
        ])

        assert analysis.rhythm.bucket_counts == {
            AFTERNOON: 1,
            EVENING: 1,
            MORNING: 1,
            NIGHT: 1,
        }

    def test_dominant_bucket_and_share(self) -> None:
        analysis = analyze_experiences([
            _exp(hour=20),
            _exp(hour=21),
            _exp(hour=22),
            _exp(hour=9),
        ])

        assert analysis.rhythm.dominant_bucket == EVENING
        assert analysis.rhythm.dominant_share == 0.75

    def test_hour_counts_only_include_observed_hours(self) -> None:
        analysis = analyze_experiences([_exp(hour=9), _exp(hour=9), _exp(hour=13)])

        assert analysis.rhythm.hour_counts == {"9": 2, "13": 1}

    def test_hour_offset_shifts_interpretation(self) -> None:
        """UTC 22:00, +3 ofsetle yerel 01:00 (gece) olur."""
        utc_analysis = analyze_experiences([_exp(hour=22)])
        shifted = analyze_experiences([_exp(hour=22)], hour_offset=3)

        assert utc_analysis.rhythm.dominant_bucket == EVENING
        assert shifted.rhythm.dominant_bucket == NIGHT
        assert shifted.rhythm.hour_offset == 3

    def test_hour_offset_wraps_around_midnight(self) -> None:
        analysis = analyze_experiences([_exp(hour=23)], hour_offset=2)
        assert analysis.rhythm.hour_counts == {"1": 1}


# ---------------------------------------------------------------------------
# 9-10. Determinizm ve saflık
# ---------------------------------------------------------------------------


class TestDeterminismAndPurity:
    def test_result_is_independent_of_input_order(self) -> None:
        experiences = [
            _exp(user_message="python django", tool_calls=["get_time"], hour=9),
            _exp(user_message="python flask", tool_calls=["calculator"], hour=20),
            _exp(user_message="rust tooling", tool_calls=["get_time"], hour=14),
        ]

        forward = analyze_experiences(experiences)
        backward = analyze_experiences(list(reversed(experiences)))

        assert forward.model_dump() == backward.model_dump()

    def test_ties_are_broken_alphabetically(self) -> None:
        """Eşit sayımda sıra, girdi sırasına değil alfabeye bağlı olmalı."""
        analysis = analyze_experiences([
            _exp(tool_calls=["zebra"]),
            _exp(tool_calls=["alpha"]),
        ])

        assert [u.name for u in analysis.tool_usage] == ["alpha", "zebra"]

    def test_repeated_calls_produce_identical_results(self) -> None:
        experiences = [_exp(user_message="python", hour=20), _exp(user_message="python")]

        assert analyze_experiences(experiences).model_dump() == (
            analyze_experiences(experiences).model_dump()
        )

    def test_input_experiences_are_not_mutated(self) -> None:
        experiences = [_exp(user_message="python", tool_calls=["get_time"])]
        before = [e.model_dump() for e in experiences]

        analyze_experiences(experiences)

        assert [e.model_dump() for e in experiences] == before

    def test_module_performs_no_io_and_reads_no_clock(self) -> None:
        """Saflık iddiası kaynak düzeyinde de korunmalı."""
        source = inspect.getsource(analyzer_module)

        assert "sqlite" not in source.lower()
        assert "datetime.now" not in source
        assert "open(" not in source
        assert "import requests" not in source
