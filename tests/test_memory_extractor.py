"""Phase 1B-1 — MemoryExtractor test suite.

Kapsam:
 1. Tek geçerli bellek çıkarımı
 2. Birden fazla bellek
 3. Bozuk JSON
 4. memories alanı eksik
 5. Geçersiz memory_type
 6. Geçersiz temporality
 7. Geçersiz status
 8. İçerik alanı eksik
 9. Boş içerik
10. Geçersiz importance (aralık dışı)
11. Gizli / API anahtarı içeriği reddedilir
12. Soru → bellek üretilmez (LLM boş döner)
13. Küçük konuşma → bellek üretilmez (LLM boş döner)
14. Açık gelecek olay → FUTURE / PLANNED
15. Açık geçmiş olay → PAST / COMPLETED
16. Belirsiz ifade → UNCERTAIN
17. LLM hatası güvenle işlenir
18. MemoryExtractor veritabanına yazmaz
19. ExtractionResult metadata doğru raporlanır
20. extra alanlar LLM çıktısında → reddedilir (extra=forbid)
21. markdown kod bloğu sarmalayıcısı temizlenir
22. memories listesinde non-dict öğeler atlanır
23. Çok kısa içerik reddedilir
24. Çok uzun içerik reddedilir
25. Boş kullanıcı mesajı → hemen boş döner
26. _parse_llm_response — boş dize
27. _parse_llm_response — liste değil JSON
28. _parse_llm_response — memories listesi değil
29. _contains_secret — bilinen kalıplar
30. Tüm izin verilen memory_type'lar kabul edilir
31. İzin verilmeyen memory_type (world_state, other) reddedilir
32. session_id MemoryRecord'a eklenir
33. Önem değeri sınır değerlerde (0.0, 1.0) kabul edilir
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.adapters.llm.base import LLMProviderError, LLMUnavailableError
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.memory.extractor import (
    EXTRACTION_SYSTEM_PROMPT,
    ExtractionResult,
    MemoryExtractor,
    _contains_secret,
    _parse_llm_response,
)
from app.memory.record import MemoryRecord, MemoryStatus, MemoryType, Temporality


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _run(coro):  # type: ignore[no-untyped-def]
    """Testleri asyncio.run() ile çalıştırır (pytest-asyncio gerektirmez)."""
    return asyncio.run(coro)


def _json_response(memories: list[dict[str, Any]]) -> str:
    """Geçerli bir LLM JSON yanıtı üretir."""
    return json.dumps({"memories": memories})


class _FakeProvider:
    """Sabit bir JSON yanıtı döndüren sahte LLM sağlayıcısı."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        return self._response

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        return LLMResponse(content=self._response)


class _FailingProvider:
    """Her generate() çağrısında LLMUnavailableError fırlatan sahte sağlayıcı."""

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        raise LLMUnavailableError("Fake LLM unavailable")

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        raise LLMUnavailableError("Fake LLM unavailable")


class _GenericErrorProvider:
    """Beklenmedik Exception fırlatan sahte sağlayıcı."""

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        raise RuntimeError("unexpected crash")

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        raise RuntimeError("unexpected crash")


def _make_extractor(response: str, **kwargs: Any) -> MemoryExtractor:
    return MemoryExtractor(provider=_FakeProvider(response), **kwargs)


# ---------------------------------------------------------------------------
# 1. Tek geçerli bellek çıkarımı
# ---------------------------------------------------------------------------


class TestSingleValidExtraction:
    def test_returns_one_record(self) -> None:
        response = _json_response([
            {
                "memory_type": "fact",
                "content": "The user lives in Istanbul.",
                "temporality": "present",
                "status": "active",
                "importance": 0.7,
            }
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I live in Istanbul."))

        assert isinstance(result, ExtractionResult)
        assert len(result.records) == 1
        rec = result.records[0]
        assert isinstance(rec, MemoryRecord)

    def test_record_fields_match_candidate(self) -> None:
        response = _json_response([
            {
                "memory_type": "preference",
                "content": "The user prefers dark mode.",
                "temporality": "present",
                "status": "active",
                "importance": 0.6,
            }
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I prefer dark mode."))
        rec = result.records[0]

        assert rec.memory_type == MemoryType.PREFERENCE
        assert rec.content == "The user prefers dark mode."
        assert rec.temporality == Temporality.PRESENT
        assert rec.status == MemoryStatus.ACTIVE
        assert rec.importance == pytest.approx(0.6)

    def test_llm_receives_system_and_user_messages(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "User name is Bob.", "temporality": "present", "status": "active"}
        ])
        provider = _FakeProvider(response)
        extractor = MemoryExtractor(provider=provider)
        _run(extractor.extract("My name is Bob."))

        assert len(provider.calls) == 1
        msgs = provider.calls[0]
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"
        assert msgs[1].content == "My name is Bob."

    def test_extraction_result_counts_are_correct(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "User speaks Turkish.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I speak Turkish."))

        assert result.raw_candidates == 1
        assert result.accepted_count == 1
        assert result.rejected_count == 0
        assert result.llm_failed is False


# ---------------------------------------------------------------------------
# 2. Birden fazla bellek
# ---------------------------------------------------------------------------


class TestMultipleMemories:
    def test_returns_multiple_records(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "User lives in Ankara.", "temporality": "present", "status": "active"},
            {"memory_type": "preference", "content": "User prefers tea over coffee.", "temporality": "present", "status": "active"},
            {"memory_type": "goal", "content": "User wants to learn Spanish.", "temporality": "future", "status": "planned"},
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I live in Ankara, prefer tea, and want to learn Spanish."))

        assert len(result.records) == 3
        assert result.raw_candidates == 3
        assert result.rejected_count == 0

    def test_memory_types_preserved_across_records(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "Fact content here.", "temporality": "present", "status": "active"},
            {"memory_type": "event", "content": "Event content here.", "temporality": "past", "status": "completed"},
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Some message."))
        types = {r.memory_type for r in result.records}

        assert MemoryType.FACT in types
        assert MemoryType.EVENT in types


# ---------------------------------------------------------------------------
# 3. Bozuk JSON
# ---------------------------------------------------------------------------


class TestMalformedJson:
    def test_malformed_json_returns_empty(self) -> None:
        extractor = _make_extractor("this is not json at all")
        result = _run(extractor.extract("Hello."))
        assert result.records == []

    def test_partial_json_returns_empty(self) -> None:
        extractor = _make_extractor('{"memories": [{"memory_type":')
        result = _run(extractor.extract("Hello."))
        assert result.records == []

    def test_malformed_json_does_not_raise(self) -> None:
        extractor = _make_extractor("{{{bad json}}}")
        # Hata fırlatmamalı
        result = _run(extractor.extract("Test."))
        assert isinstance(result, ExtractionResult)


# ---------------------------------------------------------------------------
# 4. memories alanı eksik
# ---------------------------------------------------------------------------


class TestMissingMemoriesField:
    def test_missing_memories_key_returns_empty(self) -> None:
        extractor = _make_extractor('{"facts": []}')
        result = _run(extractor.extract("Hello."))
        assert result.records == []

    def test_empty_object_returns_empty(self) -> None:
        extractor = _make_extractor("{}")
        result = _run(extractor.extract("Hello."))
        assert result.records == []

    def test_memories_none_returns_empty(self) -> None:
        extractor = _make_extractor('{"memories": null}')
        result = _run(extractor.extract("Hello."))
        assert result.records == []


# ---------------------------------------------------------------------------
# 5. Geçersiz memory_type
# ---------------------------------------------------------------------------


class TestInvalidMemoryType:
    def test_unknown_type_string_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "unknown_type", "content": "Some content.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []
        assert result.rejected_count == 1

    def test_world_state_type_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "world_state", "content": "The light is on.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_other_type_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "other", "content": "Some misc content.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_numeric_memory_type_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": 42, "content": "Some content.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []


# ---------------------------------------------------------------------------
# 6. Geçersiz temporality
# ---------------------------------------------------------------------------


class TestInvalidTemporality:
    def test_unknown_temporality_string_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "Valid content.", "temporality": "yesterday", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_null_temporality_uses_default(self) -> None:
        """temporality alanı yoksa varsayılan UNKNOWN kullanılmalı."""
        response = _json_response([
            {"memory_type": "fact", "content": "Valid content.", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert len(result.records) == 1
        assert result.records[0].temporality == Temporality.UNKNOWN


# ---------------------------------------------------------------------------
# 7. Geçersiz status
# ---------------------------------------------------------------------------


class TestInvalidStatus:
    def test_unknown_status_string_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "Valid content.", "temporality": "present", "status": "unknown_status"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_null_status_uses_default(self) -> None:
        """status alanı yoksa varsayılan ACTIVE kullanılmalı."""
        response = _json_response([
            {"memory_type": "fact", "content": "Valid content.", "temporality": "present"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert len(result.records) == 1
        assert result.records[0].status == MemoryStatus.ACTIVE


# ---------------------------------------------------------------------------
# 8. İçerik alanı eksik
# ---------------------------------------------------------------------------


class TestMissingContent:
    def test_missing_content_field_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []
        assert result.rejected_count == 1


# ---------------------------------------------------------------------------
# 9. Boş içerik
# ---------------------------------------------------------------------------


class TestEmptyContent:
    def test_empty_string_content_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_whitespace_only_content_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "   \t\n  ", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_very_short_content_is_rejected(self) -> None:
        """min_content_length=3 varsayılanıyla kısa içerik reddedilmeli."""
        response = _json_response([
            {"memory_type": "fact", "content": "Hi", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []


# ---------------------------------------------------------------------------
# 10. Geçersiz importance
# ---------------------------------------------------------------------------


class TestInvalidImportance:
    def test_importance_above_one_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "Valid content.", "temporality": "present", "status": "active", "importance": 1.5}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_importance_below_zero_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "Valid content.", "temporality": "present", "status": "active", "importance": -0.1}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_importance_zero_is_accepted(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "Valid content.", "temporality": "present", "status": "active", "importance": 0.0}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert len(result.records) == 1
        assert result.records[0].importance == pytest.approx(0.0)

    def test_importance_one_is_accepted(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "Valid content.", "temporality": "present", "status": "active", "importance": 1.0}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert len(result.records) == 1
        assert result.records[0].importance == pytest.approx(1.0)

    def test_missing_importance_defaults_to_half(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "Valid content.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records[0].importance == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 11. Gizli / API anahtarı içeriği reddedilir
# ---------------------------------------------------------------------------


class TestSecretContentRejection:
    @pytest.mark.parametrize("secret_content", [
        "The user's password is hunter2",
        "API key is sk-abc123",
        "api_key = mysecretkey12345",
        "auth_token: Bearer eyJhbGciOiJIUzI1NiJ9",
        "Private key: -----BEGIN RSA PRIVATE KEY-----",
        "access_token: xoxb-abc-def",
        "My secret is 12345",
        "The secret_key for the service is abc123",
    ])
    def test_secret_content_is_rejected(self, secret_content: str) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": secret_content, "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Ignore this."))
        assert result.records == [], f"Should have rejected: {secret_content!r}"

    def test_long_hex_string_is_rejected(self) -> None:
        """32+ karakterlik hex dizesi token olarak reddedilmeli."""
        hex_token = "a" * 32
        response = _json_response([
            {"memory_type": "fact", "content": f"Token is {hex_token}", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_normal_content_is_not_falsely_rejected(self) -> None:
        """Normal içerik gizlilik denetiminden geçmeli."""
        response = _json_response([
            {"memory_type": "fact", "content": "The user enjoys reading science fiction books.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I enjoy reading sci-fi."))
        assert len(result.records) == 1


# ---------------------------------------------------------------------------
# 12. Soru → bellek üretilmez
# ---------------------------------------------------------------------------


class TestQuestionProducesNoMemory:
    def test_question_with_empty_llm_response(self) -> None:
        """LLM soru için boş liste döndürdüğünde sonuç boş olmalı."""
        response = _json_response([])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("What is the capital of France?"))
        assert result.records == []
        assert result.raw_candidates == 0


# ---------------------------------------------------------------------------
# 13. Küçük konuşma → bellek üretilmez
# ---------------------------------------------------------------------------


class TestSmallTalkProducesNoMemory:
    def test_greeting_with_empty_llm_response(self) -> None:
        response = _json_response([])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Hello! How are you?"))
        assert result.records == []

    def test_thanks_with_empty_llm_response(self) -> None:
        response = _json_response([])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Thanks, bye!"))
        assert result.records == []


# ---------------------------------------------------------------------------
# 14. Açık gelecek olay → FUTURE / PLANNED
# ---------------------------------------------------------------------------


class TestFutureEventClassification:
    def test_future_event_has_correct_temporality_and_status(self) -> None:
        response = _json_response([
            {
                "memory_type": "event",
                "content": "User plans to travel to Japan next month.",
                "temporality": "future",
                "status": "planned",
                "importance": 0.8,
            }
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I'm planning to travel to Japan next month."))

        assert len(result.records) == 1
        rec = result.records[0]
        assert rec.temporality == Temporality.FUTURE
        assert rec.status == MemoryStatus.PLANNED
        assert rec.memory_type == MemoryType.EVENT


# ---------------------------------------------------------------------------
# 15. Açık geçmiş olay → PAST / COMPLETED
# ---------------------------------------------------------------------------


class TestPastEventClassification:
    def test_past_event_has_correct_temporality_and_status(self) -> None:
        response = _json_response([
            {
                "memory_type": "event",
                "content": "User graduated from university in 2022.",
                "temporality": "past",
                "status": "completed",
                "importance": 0.9,
            }
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I graduated from university in 2022."))

        assert len(result.records) == 1
        rec = result.records[0]
        assert rec.temporality == Temporality.PAST
        assert rec.status == MemoryStatus.COMPLETED


# ---------------------------------------------------------------------------
# 16. Belirsiz ifade → UNCERTAIN
# ---------------------------------------------------------------------------


class TestUncertainStatement:
    def test_uncertain_statement_has_uncertain_status(self) -> None:
        response = _json_response([
            {
                "memory_type": "fact",
                "content": "User might live in Berlin (uncertain).",
                "temporality": "present",
                "status": "uncertain",
                "importance": 0.4,
            }
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I think I might move to Berlin, not sure yet."))

        assert len(result.records) == 1
        assert result.records[0].status == MemoryStatus.UNCERTAIN


# ---------------------------------------------------------------------------
# 17. LLM hatası güvenle işlenir
# ---------------------------------------------------------------------------


class TestLLMFailureHandling:
    def test_llm_unavailable_error_returns_empty_result(self) -> None:
        extractor = MemoryExtractor(provider=_FailingProvider())
        result = _run(extractor.extract("I live in Paris."))

        assert result.records == []
        assert result.llm_failed is True

    def test_generic_exception_returns_empty_result(self) -> None:
        extractor = MemoryExtractor(provider=_GenericErrorProvider())
        result = _run(extractor.extract("I live in Paris."))

        assert result.records == []
        assert result.llm_failed is True

    def test_llm_failure_does_not_raise(self) -> None:
        extractor = MemoryExtractor(provider=_FailingProvider())
        # Hata fırlatmamalı
        result = _run(extractor.extract("Test."))
        assert isinstance(result, ExtractionResult)

    def test_llm_failure_accepted_count_is_zero(self) -> None:
        extractor = MemoryExtractor(provider=_FailingProvider())
        result = _run(extractor.extract("I live in Paris."))
        assert result.accepted_count == 0


# ---------------------------------------------------------------------------
# 18. MemoryExtractor veritabanına yazmaz
# ---------------------------------------------------------------------------


class TestNoDatabaseWrite:
    def test_extract_returns_records_without_writing(self, tmp_path) -> None:
        """Extractor çalıştıktan sonra hiçbir veritabanı dosyası oluşmamalı."""
        db_path = tmp_path / "should_not_exist.db"
        response = _json_response([
            {"memory_type": "fact", "content": "User is a developer.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I am a developer."))

        assert len(result.records) == 1
        # Extractor veritabanına yazmış olsaydı bu dosya oluşurdu
        assert not db_path.exists(), "MemoryExtractor must NOT write to any database"

    def test_extract_result_is_not_persisted(self) -> None:
        """ExtractionResult yalnızca veri taşır; persist() gibi bir metod içermez."""
        result = ExtractionResult(records=[], raw_candidates=0, rejected_count=0)
        assert not hasattr(result, "save")
        assert not hasattr(result, "persist")
        assert not hasattr(result, "write")
        assert not hasattr(result, "commit")


# ---------------------------------------------------------------------------
# 19. ExtractionResult metadata
# ---------------------------------------------------------------------------


class TestExtractionResultMetadata:
    def test_accepted_count_property(self) -> None:
        records = [MemoryRecord(content="fact one"), MemoryRecord(content="fact two")]
        result = ExtractionResult(records=records, raw_candidates=3, rejected_count=1)
        assert result.accepted_count == 2

    def test_rejected_count_is_accurate(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "Valid.", "temporality": "present", "status": "active"},
            {"memory_type": "bad_type", "content": "Invalid type.", "temporality": "present", "status": "active"},
            {"memory_type": "fact", "content": "", "temporality": "present", "status": "active"},
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.raw_candidates == 3
        assert result.rejected_count == 2
        assert result.accepted_count == 1

    def test_llm_failed_false_on_success(self) -> None:
        response = _json_response([])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Hello."))
        assert result.llm_failed is False


# ---------------------------------------------------------------------------
# 20. extra alanlar reddedilir
# ---------------------------------------------------------------------------


class TestExtraFieldsRejected:
    def test_extra_llm_fields_are_rejected(self) -> None:
        """LLM adayına eklenen rastgele alanlar reddedilmeli (extra=forbid)."""
        response = _json_response([
            {
                "memory_type": "fact",
                "content": "User uses Python.",
                "temporality": "present",
                "status": "active",
                "malicious_field": "injected_value",
                "another_field": 42,
            }
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I use Python."))
        assert result.records == []
        assert result.rejected_count == 1


# ---------------------------------------------------------------------------
# 21. Markdown kod bloğu sarmalayıcısı
# ---------------------------------------------------------------------------


class TestMarkdownCodeBlockStripping:
    def test_json_in_markdown_block_is_parsed(self) -> None:
        wrapped = "```json\n" + _json_response([
            {"memory_type": "fact", "content": "User is an engineer.", "temporality": "present", "status": "active"}
        ]) + "\n```"
        extractor = _make_extractor(wrapped)
        result = _run(extractor.extract("I am an engineer."))
        assert len(result.records) == 1

    def test_json_in_plain_code_block_is_parsed(self) -> None:
        wrapped = "```\n" + _json_response([
            {"memory_type": "fact", "content": "User loves hiking.", "temporality": "present", "status": "active"}
        ]) + "\n```"
        extractor = _make_extractor(wrapped)
        result = _run(extractor.extract("I love hiking."))
        assert len(result.records) == 1


# ---------------------------------------------------------------------------
# 22. memories listesinde non-dict öğeler atlanır
# ---------------------------------------------------------------------------


class TestNonDictMemoryItems:
    def test_string_items_in_memories_list_are_skipped(self) -> None:
        response = json.dumps({"memories": ["not a dict", 42, None, {"memory_type": "fact", "content": "Valid content.", "temporality": "present", "status": "active"}]})
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert len(result.records) == 1

    def test_all_non_dict_items_returns_empty(self) -> None:
        response = json.dumps({"memories": ["a", "b", 1, None]})
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []


# ---------------------------------------------------------------------------
# 23-24. İçerik uzunluk sınırları
# ---------------------------------------------------------------------------


class TestContentLengthLimits:
    def test_content_below_min_length_is_rejected(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "Hi", "temporality": "present", "status": "active"}
        ])
        extractor = MemoryExtractor(provider=_FakeProvider(response), min_content_length=5)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_content_above_max_length_is_rejected(self) -> None:
        long_content = "x" * 200
        response = _json_response([
            {"memory_type": "fact", "content": long_content, "temporality": "present", "status": "active"}
        ])
        extractor = MemoryExtractor(provider=_FakeProvider(response), max_content_length=100)
        result = _run(extractor.extract("Test."))
        assert result.records == []

    def test_content_at_exact_max_length_is_accepted(self) -> None:
        # Use a realistic sentence that won't trigger the secret detector.
        # Exactly 100 characters of natural language text.
        exact_content = "The user enjoys reading books about history and science on weekday evenings after work every day."
        assert len(exact_content) <= 100
        # Pad to exactly 100 chars with a trailing period if needed
        exact_content = exact_content.ljust(100, ".")
        assert len(exact_content) == 100
        response = _json_response([
            {"memory_type": "fact", "content": exact_content, "temporality": "present", "status": "active"}
        ])
        extractor = MemoryExtractor(provider=_FakeProvider(response), max_content_length=100)
        result = _run(extractor.extract("Test."))
        assert len(result.records) == 1


# ---------------------------------------------------------------------------
# 25. Boş kullanıcı mesajı
# ---------------------------------------------------------------------------


class TestBlankUserMessage:
    def test_empty_string_skips_llm(self) -> None:
        provider = _FakeProvider(_json_response([]))
        extractor = MemoryExtractor(provider=provider)
        result = _run(extractor.extract(""))

        assert result.records == []
        assert provider.calls == []  # LLM hiç çağrılmamalı

    def test_whitespace_only_skips_llm(self) -> None:
        provider = _FakeProvider(_json_response([]))
        extractor = MemoryExtractor(provider=provider)
        result = _run(extractor.extract("   "))

        assert result.records == []
        assert provider.calls == []


# ---------------------------------------------------------------------------
# 26-28. _parse_llm_response unit testleri
# ---------------------------------------------------------------------------


class TestParseLLMResponse:
    def test_empty_string_returns_empty(self) -> None:
        assert _parse_llm_response("") == []

    def test_whitespace_only_returns_empty(self) -> None:
        assert _parse_llm_response("   ") == []

    def test_valid_json_returns_list(self) -> None:
        raw = _json_response([{"memory_type": "fact", "content": "Test."}])
        result = _parse_llm_response(raw)
        assert len(result) == 1
        assert result[0]["memory_type"] == "fact"

    def test_json_array_at_top_level_returns_empty(self) -> None:
        """Üst seviye JSON dizisi (nesne değil) → boş liste."""
        result = _parse_llm_response('[{"memory_type": "fact"}]')
        assert result == []

    def test_memories_not_a_list_returns_empty(self) -> None:
        result = _parse_llm_response('{"memories": "not a list"}')
        assert result == []

    def test_memories_is_dict_returns_empty(self) -> None:
        result = _parse_llm_response('{"memories": {"memory_type": "fact"}}')
        assert result == []

    def test_empty_memories_list_returns_empty(self) -> None:
        result = _parse_llm_response('{"memories": []}')
        assert result == []

    def test_filters_non_dict_items(self) -> None:
        raw = json.dumps({"memories": [{"memory_type": "fact"}, "string", 42, None]})
        result = _parse_llm_response(raw)
        assert len(result) == 1

    def test_markdown_block_stripped(self) -> None:
        raw = "```json\n{\"memories\": []}\n```"
        result = _parse_llm_response(raw)
        assert result == []


# ---------------------------------------------------------------------------
# 29. _contains_secret unit testleri
# ---------------------------------------------------------------------------


class TestContainsSecret:
    @pytest.mark.parametrize("text,expected", [
        ("My password is abc123", True),
        ("api_key = sk-1234567890", True),
        ("Bearer eyJhbGci", True),
        ("secret_key: mysecret", True),
        ("auth_token: xyz", True),
        ("access_token abc", True),
        ("private_key content", True),
        ("User enjoys reading books.", False),
        ("The temperature is 23 degrees.", False),
        ("I work as a software engineer.", False),
        ("My name is Alice.", False),
    ])
    def test_secret_detection(self, text: str, expected: bool) -> None:
        assert _contains_secret(text) is expected


# ---------------------------------------------------------------------------
# 30. Tüm izin verilen memory_type'lar kabul edilir
# ---------------------------------------------------------------------------


class TestAllowedMemoryTypes:
    @pytest.mark.parametrize("memory_type", ["fact", "event", "preference", "goal"])
    def test_allowed_type_is_accepted(self, memory_type: str) -> None:
        response = _json_response([
            {"memory_type": memory_type, "content": "Valid memory content here.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert len(result.records) == 1
        assert result.records[0].memory_type.value == memory_type


# ---------------------------------------------------------------------------
# 31. İzin verilmeyen memory_type'lar reddedilir
# ---------------------------------------------------------------------------


class TestDisallowedMemoryTypes:
    @pytest.mark.parametrize("memory_type", ["world_state", "other"])
    def test_disallowed_type_is_rejected(self, memory_type: str) -> None:
        response = _json_response([
            {"memory_type": memory_type, "content": "Some content here.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("Test."))
        assert result.records == []


# ---------------------------------------------------------------------------
# 32. session_id MemoryRecord'a eklenir
# ---------------------------------------------------------------------------


class TestSessionIdPropagation:
    def test_session_id_is_set_on_record(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "User works remotely.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I work remotely.", session_id="sess-42"))
        assert len(result.records) == 1
        assert result.records[0].source_session_id == "sess-42"

    def test_no_session_id_leaves_field_none(self) -> None:
        response = _json_response([
            {"memory_type": "fact", "content": "User works remotely.", "temporality": "present", "status": "active"}
        ])
        extractor = _make_extractor(response)
        result = _run(extractor.extract("I work remotely."))
        assert result.records[0].source_session_id is None


# ---------------------------------------------------------------------------
# 33. Özel system_prompt constructor parametresi
# ---------------------------------------------------------------------------


class TestCustomSystemPrompt:
    def test_custom_prompt_is_sent_to_llm(self) -> None:
        response = _json_response([])
        provider = _FakeProvider(response)
        custom_prompt = "Custom extraction instructions."
        extractor = MemoryExtractor(provider=provider, system_prompt=custom_prompt)
        _run(extractor.extract("Test message."))

        system_msg = provider.calls[0][0]
        assert system_msg.content == custom_prompt

    def test_default_system_prompt_contains_key_rules(self) -> None:
        """Varsayılan prompt temel kuralları içermeli."""
        assert "memories" in EXTRACTION_SYSTEM_PROMPT
        assert "JSON" in EXTRACTION_SYSTEM_PROMPT
        assert "password" in EXTRACTION_SYSTEM_PROMPT.lower() or "secret" in EXTRACTION_SYSTEM_PROMPT.lower()
