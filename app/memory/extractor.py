"""Konuşma turlarından yapılandırılmış bellek adayları çıkaran servis.

Mimari kurallar:
- MemoryExtractor hiçbir zaman doğrudan veritabanına yazmaz.
- LLM çıktısı güvenilmez kabul edilir; her alan deterministic olarak doğrulanır.
- Geçersiz adaylar sessizce atılır (günlüğe kaydedilir); hata fırlatılmaz.
- Extractor, LLMProvider soyutlamasına bağımlıdır; Ollama'ya değil.
- Gizli bilgi içeren adaylar (şifre, token, API anahtarı vb.) reddedilir.

Çalışma akışı:
    Konuşma mesajı
        ↓
    MemoryExtractor.extract()
        ↓
    LLM → ham JSON
        ↓
    _parse_llm_response() → aday listesi
        ↓
    _validate_candidate()  ← deterministic doğrulama
        ↓
    MemoryRecord nesneleri  (depolama katmanına hazır)
        ↓
    ExtractionResult  (döndürülür; kaydedilmez)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.adapters.llm.base import LLMProvider, LLMProviderError
from app.core.chat import ChatMessage
from app.memory.record import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    Temporality,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Çıkarma için izin verilen tipler (Phase 1A)
# ---------------------------------------------------------------------------

_ALLOWED_MEMORY_TYPES: frozenset[MemoryType] = frozenset(
    {MemoryType.FACT, MemoryType.EVENT, MemoryType.PREFERENCE, MemoryType.GOAL}
)

# ---------------------------------------------------------------------------
# Gizlilik / güvenlik: reddedilecek içerik kalıpları
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"\bpasswd\b", re.IGNORECASE),
    re.compile(r"\bapi[_\s-]?key\b", re.IGNORECASE),
    re.compile(r"\bsecret[_\s-]?key\b", re.IGNORECASE),
    re.compile(r"\bauth[_\s-]?token\b", re.IGNORECASE),
    re.compile(r"\baccess[_\s-]?token\b", re.IGNORECASE),
    re.compile(r"\bprivate[_\s-]?key\b", re.IGNORECASE),
    re.compile(r"\bbearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bsecret\b", re.IGNORECASE),
    # Yaygın token formatları (hex ≥ 32 karakter, base64 ≥ 32 karakter)
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
    re.compile(r"[A-Za-z0-9+/]{32,}={0,2}"),
)

# ---------------------------------------------------------------------------
# LLM'e gönderilecek çıkarma sistemi prompt'u
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT: str = """You are a memory extraction assistant. Your ONLY job is to extract explicitly stated facts from the user's message and return them as a JSON object.

STRICT RULES:
1. Extract ONLY information the user explicitly states — do NOT infer or guess.
2. Do NOT invent dates, relationships, or facts not present in the text.
3. Uncertain statements must have status "uncertain".
4. Questions typically yield NO memories.
5. Greetings and small talk typically yield NO memories.
6. Do NOT extract passwords, API keys, tokens, or secrets of any kind.
7. Do NOT extract information from assistant messages as user facts.
8. If there is nothing to extract, return {"memories": []}.

ALLOWED memory_type values: "fact", "event", "preference", "goal"
ALLOWED temporality values: "past", "present", "future", "unknown"
ALLOWED status values: "active", "planned", "completed", "cancelled", "expired", "uncertain"

importance: float between 0.0 (trivial) and 1.0 (critical). Default 0.5.

OUTPUT FORMAT — respond with ONLY valid JSON, no markdown, no explanation:
{
  "memories": [
    {
      "memory_type": "fact",
      "content": "The user's name is Alice.",
      "temporality": "present",
      "status": "active",
      "importance": 0.7
    }
  ]
}"""

# ---------------------------------------------------------------------------
# LLM aday doğrulama modeli (Pydantic ile güvenli ayrıştırma)
# ---------------------------------------------------------------------------


class _MemoryCandidate(BaseModel):
    """LLM'den dönen tek bir bellek adayı için katı doğrulama şeması.

    extra="forbid": LLM'in rastgele alanlar eklemesi engellenir.
    """

    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType
    content: str = Field(min_length=1, max_length=2000)
    temporality: Temporality = Temporality.UNKNOWN
    status: MemoryStatus = MemoryStatus.ACTIVE
    importance: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("memory_type")
    @classmethod
    def only_allowed_types(cls, v: MemoryType) -> MemoryType:
        if v not in _ALLOWED_MEMORY_TYPES:
            raise ValueError(
                f"memory_type {v!r} not allowed in Phase 1A extraction. "
                f"Allowed: {sorted(t.value for t in _ALLOWED_MEMORY_TYPES)}"
            )
        return v

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be blank or whitespace-only")
        return v.strip()


# ---------------------------------------------------------------------------
# Çıkarma sonucu
# ---------------------------------------------------------------------------


@dataclass
class ExtractionResult:
    """extract() çağrısının çıktısı.

    Yalnızca veri taşır; depolama işlemi yapmaz.

    Attributes:
        records: Doğrulanmış, depoya yazılmaya hazır MemoryRecord listesi.
        raw_candidates: LLM'den gelen ham aday sayısı (debug için).
        rejected_count: Doğrulamayı geçemeyen aday sayısı.
        llm_failed: LLM çağrısı başarısız olduysa True.
    """

    records: list[MemoryRecord] = field(default_factory=list)
    raw_candidates: int = 0
    rejected_count: int = 0
    llm_failed: bool = False

    @property
    def accepted_count(self) -> int:
        return len(self.records)


# ---------------------------------------------------------------------------
# Ana servis
# ---------------------------------------------------------------------------


class MemoryExtractor:
    """Konuşma turlarından bellek adaylarını çıkarır.

    Kullanım:
        extractor = MemoryExtractor(provider=ollama_provider)
        result = await extractor.extract("I live in Istanbul.", session_id="s1")
        # result.records → [MemoryRecord(...)]
        # Depoya yazmak çağıranın sorumluluğundadır.

    MemoryExtractor hiçbir zaman MemoryStore'a yazmaz.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        system_prompt: str = EXTRACTION_SYSTEM_PROMPT,
        min_content_length: int = 3,
        max_content_length: int = 1000,
    ) -> None:
        """
        Args:
            provider: Çıkarma için kullanılacak LLM sağlayıcısı.
            system_prompt: Varsayılan EXTRACTION_SYSTEM_PROMPT yerine
                özel bir prompt kullanmak için geçilebilir (test/tuning).
            min_content_length: Kabul edilecek minimum içerik uzunluğu.
            max_content_length: Kabul edilecek maksimum içerik uzunluğu.
        """
        self._provider = provider
        self._system_prompt = system_prompt
        self._min_content_length = min_content_length
        self._max_content_length = max_content_length

    async def extract(
        self,
        user_message: str,
        *,
        session_id: str | None = None,
    ) -> ExtractionResult:
        """Bir kullanıcı mesajından bellek adayları çıkarır.

        Args:
            user_message: Analiz edilecek kullanıcı mesajı.
            session_id: Üretilen MemoryRecord'lara eklenecek oturum kimliği.

        Returns:
            ExtractionResult — doğrulanmış kayıtları taşır.
            Depolama işlemi yapmaz; yazma sorumluluğu çağırana aittir.
        """
        if not user_message or not user_message.strip():
            logger.debug("extraction_skipped_blank_message")
            return ExtractionResult()

        # LLM'i çağır
        raw_text = await self._call_llm(user_message)
        if raw_text is None:
            return ExtractionResult(llm_failed=True)

        # Ham metni aday listesine çevir
        candidates = _parse_llm_response(raw_text)
        raw_count = len(candidates)

        # Her adayı doğrula → MemoryRecord'a çevir
        records: list[MemoryRecord] = []
        rejected = 0
        for raw_candidate in candidates:
            record = self._validate_and_convert(raw_candidate, session_id=session_id)
            if record is not None:
                records.append(record)
            else:
                rejected += 1

        logger.debug(
            "extraction_complete",
            extra={
                "session_id": session_id,
                "raw_candidates": raw_count,
                "accepted": len(records),
                "rejected": rejected,
            },
        )
        return ExtractionResult(
            records=records,
            raw_candidates=raw_count,
            rejected_count=rejected,
        )

    # ------------------------------------------------------------------
    # Dahili yardımcılar
    # ------------------------------------------------------------------

    async def _call_llm(self, user_message: str) -> str | None:
        """LLM'e çıkarma isteği gönderir; hata durumunda None döner."""
        messages = [
            ChatMessage(role="system", content=self._system_prompt),
            ChatMessage(role="user", content=user_message),
        ]
        try:
            return await self._provider.generate(messages)
        except LLMProviderError as exc:
            logger.warning(
                "memory_extraction_llm_failed",
                extra={"error": str(exc)},
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "memory_extraction_unexpected_error",
                extra={"error": str(exc)},
            )
            return None

    def _validate_and_convert(
        self,
        raw: dict,
        *,
        session_id: str | None,
    ) -> MemoryRecord | None:
        """Tek bir ham adayı doğrular ve MemoryRecord'a çevirir.

        Doğrulama aşamaları (sırası önemlidir):
        1. Pydantic şema doğrulaması (_MemoryCandidate)
        2. İzin verilen memory_type kontrolü (Pydantic validator'da)
        3. Gizlilik / secret içerik denetimi
        4. İçerik uzunluğu denetimi
        5. MemoryRecord'a dönüştürme
        """
        # Aşama 1-2: Pydantic doğrulama
        try:
            candidate = _MemoryCandidate.model_validate(raw)
        except ValidationError as exc:
            logger.debug(
                "extraction_candidate_rejected_validation",
                extra={"reason": str(exc), "raw": raw},
            )
            return None

        # Aşama 3: Gizlilik denetimi
        if _contains_secret(candidate.content):
            logger.warning(
                "extraction_candidate_rejected_secret",
                extra={"content_preview": candidate.content[:40]},
            )
            return None

        # Aşama 4: İçerik uzunluk denetimi
        stripped = candidate.content.strip()
        if len(stripped) < self._min_content_length:
            logger.debug(
                "extraction_candidate_rejected_too_short",
                extra={"length": len(stripped)},
            )
            return None
        if len(stripped) > self._max_content_length:
            logger.debug(
                "extraction_candidate_rejected_too_long",
                extra={"length": len(stripped)},
            )
            return None

        # Aşama 5: MemoryRecord'a dönüştür
        return MemoryRecord(
            memory_type=candidate.memory_type,
            content=stripped,
            temporality=candidate.temporality,
            status=candidate.status,
            importance=candidate.importance,
            source_session_id=session_id,
        )


# ---------------------------------------------------------------------------
# Modül düzeyi yardımcı işlevler (test edilebilirlik için dışa aktarılır)
# ---------------------------------------------------------------------------


def _parse_llm_response(raw_text: str) -> list[dict]:
    """LLM'in ham metin çıktısından aday dict listesi çıkarır.

    JSON geçersizse veya beklenen yapıda değilse boş liste döner.
    Hata fırlatmaz.
    """
    if not raw_text or not raw_text.strip():
        return []

    # Markdown kod bloğu sarmalayıcısını temizle (```json ... ```)
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.debug("extraction_json_parse_failed", extra={"raw": raw_text[:200]})
        return []

    if not isinstance(parsed, dict):
        logger.debug("extraction_json_not_object", extra={"type": type(parsed).__name__})
        return []

    memories = parsed.get("memories")
    if memories is None:
        logger.debug("extraction_missing_memories_key")
        return []

    if not isinstance(memories, list):
        logger.debug("extraction_memories_not_list")
        return []

    # Yalnızca dict öğelerini al; diğerlerini at
    return [item for item in memories if isinstance(item, dict)]


def _contains_secret(content: str) -> bool:
    """İçeriğin gizli bilgi barındırıp barındırmadığını kontrol eder.

    Deterministik kural tabanlı denetim — LLM çıkışına güvenilmez.
    """
    return any(pattern.search(content) for pattern in _SECRET_PATTERNS)
