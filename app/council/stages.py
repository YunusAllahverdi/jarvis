"""Council'ın üç aşamasının orkestrasyonu.

Mimari kurallar:
- Bu modül YALNIZCA `LLMProvider` soyutlamasını kullanır. Somut sağlayıcı,
  model adı, HTTP istemcisi veya API anahtarı buraya hiç girmez.
- Hiçbir tool çalıştırılmaz; `ToolRegistry`/`ToolExecutor`/`AgentRunner`/
  `AgentService` import EDİLMEZ. Council → Agent özyinelemesi yapısal olarak
  imkânsızdır.
- LLM çıktısı VERİDİR: incelemeler `extra="forbid"` şemasıyla ayrıştırılır ve
  ardından deterministik olarak doğrulanır (etiket kümesi, tekrar, kapsam).
  Geçersiz bir inceleme yalnızca KENDİSİ atılır; aşama devam eder.
- Hiçbir aşama istisna sızdırmaz: sağlayıcı hatası, timeout ve bozuk çıktı
  yapılandırılmış duruma çevrilir.

Eşzamanlılık:
    Stage 1 ve Stage 2 üyeleri paraleldir. Eşzamanlılık bir `asyncio.Semaphore`
    ile sınırlanır (yerel bir Ollama örneğinde üç modeli aynı anda koşturmak
    bellek sınırına çarpabilir). Her çağrı ayrıca kendi `wait_for` timeout'una
    sahiptir; bir üyenin donması diğerlerini bekletmez.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.llm.base import LLMProvider, LLMProviderError
from app.council.anonymizer import LabelMap
from app.council.models import (
    CandidateStatus,
    CouncilCandidate,
    CouncilCriticism,
    CouncilMember,
    CouncilRequest,
    CouncilReview,
)
from app.council.prompts import (
    build_candidate_messages,
    build_chairman_messages,
    build_review_messages,
    render_review_payload,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

ERROR_TIMEOUT = "timeout"
ERROR_PROVIDER = "provider_error"
ERROR_EMPTY = "empty_answer"
ERROR_UNPARSABLE = "unparsable_review"
ERROR_INVALID_REVIEW = "invalid_review"


# ---------------------------------------------------------------------------
# LLM çıktısı ayrıştırma (inceleme aşaması)
# ---------------------------------------------------------------------------


class _CriticismPayload(BaseModel):
    """Tek bir eleştiri için katı şema."""

    model_config = ConfigDict(extra="forbid")

    candidate: str = Field(min_length=1, max_length=2)
    issue: str = Field(min_length=1, max_length=500)


class _ReviewPayload(BaseModel):
    """Değerlendirme çıktısı için katı şema.

    `extra="forbid"`: modelin uydurduğu ek alanlar (ör. kendine yetki verme
    denemesi) sessizce kabul edilmez, inceleme tamamen reddedilir.
    """

    model_config = ConfigDict(extra="forbid")

    rankings: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    criticisms: list[_CriticismPayload] = Field(default_factory=list)


def parse_json_object(raw_text: str) -> dict[str, Any] | None:
    """Ham metinden JSON nesnesi çıkarır; başarısızsa None. Hata fırlatmaz."""
    if not raw_text or not raw_text.strip():
        return None
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    parsed: Any
    try:
        parsed = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_review(
    payload: _ReviewPayload, *, allowed_labels: Sequence[str]
) -> str | None:
    """İncelemeyi sunulan aday kümesine karşı deterministik olarak doğrular.

    Geçerliyse None, aksi halde kısa bir hata etiketi döndürür.

    Bu, prompt injection'a karşı ASIL savunmadır: bir aday metnine ne yazarsa
    yazsın, sıralama yalnızca kendisine SUNULAN etiketlerden oluşabilir.
    """
    allowed = set(allowed_labels)

    if set(payload.rankings) != allowed:
        return "rankings_mismatch"
    if len(payload.rankings) != len(allowed):
        return "rankings_duplicate"
    if not set(payload.scores).issubset(allowed):
        return "unknown_score_label"
    if any(criticism.candidate not in allowed for criticism in payload.criticisms):
        return "unknown_criticism_label"
    return None


# ---------------------------------------------------------------------------
# Eşzamanlılık yardımcısı
# ---------------------------------------------------------------------------


async def _guarded(
    factory: Callable[[], Awaitable[T]],
    *,
    semaphore: asyncio.Semaphore,
    timeout: float,
) -> tuple[T | None, str | None]:
    """Bir çağrıyı eşzamanlılık limiti ve timeout altında çalıştırır.

    Returns:
        `(sonuç, None)` veya `(None, hata_etiketi)`. İstisna fırlatmaz —
        `asyncio.CancelledError` dışında; o, dışarıdan gelen bir iptal
        sinyalidir ve yutulmamalıdır.
    """
    try:
        async with semaphore:
            return await asyncio.wait_for(factory(), timeout=timeout), None
    except TimeoutError:
        return None, ERROR_TIMEOUT
    except asyncio.CancelledError:
        raise
    except LLMProviderError as exc:
        logger.warning("council_provider_error", extra={"error": str(exc)})
        return None, ERROR_PROVIDER
    except Exception:  # noqa: BLE001
        logger.exception("council_unexpected_provider_error")
        return None, ERROR_PROVIDER


# ---------------------------------------------------------------------------
# Stage 1 — bağımsız görüşler
# ---------------------------------------------------------------------------


async def run_candidate_stage(
    members: Sequence[CouncilMember],
    request: CouncilRequest,
    *,
    label_map: LabelMap,
    member_timeout_seconds: float,
    max_concurrency: int,
) -> list[CouncilCandidate]:
    """Her üyeye AYNI görevi ve AYNI bağlamı bağımsız olarak çözdürür.

    Üyeler birbirlerinin cevabını göremez: her çağrı yalnızca
    `build_candidate_messages(task, context)` çıktısını alır ve bu fonksiyon
    hiçbir aday cevabı içermez.

    Bir üyenin başarısızlığı diğerlerini etkilemez; sonuç listesi her üye için
    açık bir `status` taşır.
    """
    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    messages = build_candidate_messages(request.task, request.context_block)

    async def _ask(member: CouncilMember) -> CouncilCandidate:
        answer, error = await _guarded(
            lambda: member.provider.generate(messages),
            semaphore=semaphore,
            timeout=member_timeout_seconds,
        )
        label = label_map.label_for(member.member_id)

        if error is not None:
            return CouncilCandidate(
                member_id=member.member_id,
                label=label,
                status=(
                    CandidateStatus.TIMED_OUT
                    if error == ERROR_TIMEOUT
                    else CandidateStatus.FAILED
                ),
                error=error,
            )
        if not (answer or "").strip():
            return CouncilCandidate(
                member_id=member.member_id,
                label=label,
                status=CandidateStatus.FAILED,
                error=ERROR_EMPTY,
            )
        return CouncilCandidate(
            member_id=member.member_id,
            label=label,
            status=CandidateStatus.SUCCESS,
            answer=answer.strip(),
        )

    candidates = await asyncio.gather(*(_ask(member) for member in members))
    logger.info(
        "council_stage1_complete",
        extra={
            "member_count": len(members),
            "success_count": sum(1 for c in candidates if c.succeeded),
            "session_id": request.session_id,
        },
    )
    return list(candidates)


# ---------------------------------------------------------------------------
# Stage 2 — akran değerlendirmesi
# ---------------------------------------------------------------------------


async def run_review_stage(
    members: Sequence[CouncilMember],
    candidates: Sequence[CouncilCandidate],
    request: CouncilRequest,
    *,
    member_timeout_seconds: float,
    max_concurrency: int,
    max_candidate_chars: int,
) -> list[CouncilReview]:
    """Her başarılı üyeye DİĞER adayları anonim olarak değerlendirtir.

    Bir üyenin kendi adayını puanlaması YAPISAL OLARAK İMKÂNSIZDIR: kendi
    adayı, o üyeye gönderilen listeye hiç konmaz.

    İki veya daha az başarılı aday varsa (yani bir değerlendiriciye
    gösterilecek en az iki aday kalmıyorsa) aşama atlanır.
    """
    successful = [candidate for candidate in candidates if candidate.succeeded]
    if len(successful) < 2:
        return []

    by_member = {member.member_id: member for member in members}
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _review(reviewer: CouncilCandidate) -> CouncilReview | None:
        member = by_member.get(reviewer.member_id)
        if member is None:
            return None

        # GÜVENLİK SINIRI: değerlendiricinin kendi adayı listeye hiç girmez.
        others = [(c.label, c.answer) for c in successful if c.member_id != reviewer.member_id]
        if len(others) < 1:
            return None

        messages = build_review_messages(
            request.task, others, max_answer_chars=max_candidate_chars
        )
        raw, error = await _guarded(
            lambda: member.provider.generate(messages),
            semaphore=semaphore,
            timeout=member_timeout_seconds,
        )
        if error is not None:
            logger.warning(
                "council_review_failed",
                extra={"reason": error, "session_id": request.session_id},
            )
            return None

        return _build_review(reviewer.member_id, raw or "", [label for label, _ in others])

    reviews = await asyncio.gather(*(_review(candidate) for candidate in successful))
    valid = [review for review in reviews if review is not None]
    logger.info(
        "council_stage2_complete",
        extra={
            "reviewer_count": len(successful),
            "valid_review_count": len(valid),
            "session_id": request.session_id,
        },
    )
    return valid


def _build_review(
    reviewer_member_id: str, raw: str, allowed_labels: Sequence[str]
) -> CouncilReview | None:
    """Ham inceleme metnini doğrulanmış bir `CouncilReview`'a çevirir.

    Geçersiz bir inceleme sessizce YOK SAYILMAZ: loglanır ve atılır; aşamanın
    kalanı etkilenmez.
    """
    payload = parse_json_object(raw)
    if payload is None:
        logger.warning("council_review_rejected", extra={"reason": ERROR_UNPARSABLE})
        return None

    try:
        parsed = _ReviewPayload.model_validate(payload)
    except ValidationError:
        logger.warning("council_review_rejected", extra={"reason": ERROR_INVALID_REVIEW})
        return None

    problem = validate_review(parsed, allowed_labels=allowed_labels)
    if problem is not None:
        logger.warning("council_review_rejected", extra={"reason": problem})
        return None

    return CouncilReview(
        reviewer_member_id=reviewer_member_id,
        rankings=parsed.rankings,
        scores=parsed.scores,
        criticisms=[
            CouncilCriticism(candidate=item.candidate, issue=item.issue)
            for item in parsed.criticisms
        ],
    )


# ---------------------------------------------------------------------------
# Stage 3 — Chairman
# ---------------------------------------------------------------------------


async def run_chairman_stage(
    chairman: CouncilMember,
    candidates: Sequence[CouncilCandidate],
    reviews: Sequence[CouncilReview],
    request: CouncilRequest,
    *,
    timeout_seconds: float,
    max_candidate_chars: int,
    max_review_chars: int,
) -> tuple[str | None, str | None]:
    """Adayları ve incelemeleri sentezler.

    Chairman gerçek üye kimliklerini görmez; yalnızca anonim etiketler
    taşınır. İnceleme yoksa yalnızca adaylarla çalışır (düşürülmüş mod).

    Returns:
        `(sentez, None)` veya `(None, hata_etiketi)`.
    """
    successful = [candidate for candidate in candidates if candidate.succeeded]
    if not successful:
        return None, ERROR_EMPTY

    messages = build_chairman_messages(
        request.task,
        [(candidate.label, candidate.answer) for candidate in successful],
        [
            render_review_payload(
                review.rankings,
                review.scores,
                [(item.candidate, item.issue) for item in review.criticisms],
            )
            for review in reviews
        ],
        context_block=request.context_block,
        max_answer_chars=max_candidate_chars,
        max_review_chars=max_review_chars,
    )

    semaphore = asyncio.Semaphore(1)
    answer, error = await _guarded(
        lambda: chairman.provider.generate(messages),
        semaphore=semaphore,
        timeout=timeout_seconds,
    )
    if error is not None:
        return None, error
    if not (answer or "").strip():
        return None, ERROR_EMPTY
    return answer.strip(), None
