"""Council'ın yapılandırılmış veri modelleri.

Bu modül saf veri modelidir: hiçbir LLM çağırmaz, hiçbir depoya erişmez,
hiçbir I/O yapmaz.

Tasarım ilkeleri:
- Aşamalar arası her şey YAPILANDIRILMIŞTIR; serbest metin yalnızca aday
  cevabı, eleştiri ve nihai sentez metnindedir.
- Model/sağlayıcı kimliği ile anonim etiket AYRI alanlardır. Prompt'lara
  yalnızca etiket verilir (bkz. `app.council.prompts`).
- Bir üyenin başarısızlığı veri modelinde açıkça temsil edilir
  (`CandidateStatus`), sessizce yok sayılmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.adapters.llm.base import LLMProvider

MAX_LABEL_COUNT = 26
"""Anonim etiket sayısı üst sınırı (A..Z)."""


class CandidateStatus(StrEnum):
    """Bir Council üyesinin Stage 1'deki sonucu."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class CouncilStatus(StrEnum):
    """Bir müzakerenin toplu sonucu."""

    COMPLETED = "completed"
    """Chairman bir sentez üretti."""

    INSUFFICIENT = "insufficient"
    """Yeterli sayıda başarılı aday oluşmadı; sentez denenmedi."""

    FAILED = "failed"
    """Chairman başarısız oldu veya müzakere tamamlanamadı."""


class CouncilTrigger(StrEnum):
    """Council'ın hangi deterministik koşulla tetiklendiği."""

    EXPLICIT_REQUEST = "explicit_request"
    """Kullanıcı açıkça birden fazla modelin görüşünü istedi."""

    INTENT = "intent"
    """Kararın amacı yapılandırılmış tetikleyici kümesinde."""


@dataclass(frozen=True)
class CouncilMember:
    """Bir Council üyesi: opaque kimlik + hazır bir LLM sağlayıcısı.

    Model ADI bilinçli olarak burada YOKTUR. Üyeler `main.py`'de model
    başına bir sağlayıcı kurularak oluşturulur; Council çekirdeği yalnızca
    `member_id` görür. Bu, hem sağlayıcı bağımsızlığını hem de model
    isimlerinin prompt'lara sızmamasını yapısal olarak sağlar.
    """

    member_id: str
    provider: LLMProvider


class CouncilRequest(BaseModel):
    """Council'a verilen görev.

    `AgentContext` BİLİNÇLİ OLARAK taşınmaz: Council, agent katmanının
    veri yapılarını hiç bilmez. Bağlam, çağıran tarafından önceden
    sınırlandırılmış (bounded) düz metin bloğuna çevrilerek verilir.
    """

    model_config = ConfigDict(frozen=True)

    task: str = Field(min_length=1)
    """Kullanıcının ham isteği. ASLA kısaltılmaz."""

    context_block: str | None = None
    """Sınırlandırılmış bağlam ve varsa tool sonuçları (hazır metin)."""

    session_id: str | None = None
    """Yalnızca gözlemlenebilirlik için; prompt'lara girmez."""


class CouncilCandidate(BaseModel):
    """Stage 1'de tek bir üyenin ürettiği aday cevap."""

    member_id: str
    """Gerçek üye kimliği. Prompt'lara ASLA girmez."""

    label: str = Field(min_length=1, max_length=2)
    """Bu müzakereye özgü anonim etiket ("A", "B", ...)."""

    status: CandidateStatus
    answer: str = ""
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is CandidateStatus.SUCCESS and bool(self.answer.strip())


class CouncilCriticism(BaseModel):
    """Bir aday hakkında yapılandırılmış tek bir eleştiri."""

    model_config = ConfigDict(extra="forbid")

    candidate: str = Field(min_length=1, max_length=2)
    issue: str = Field(min_length=1, max_length=500)


class CouncilReview(BaseModel):
    """Bir üyenin diğer adaylar hakkındaki yapılandırılmış değerlendirmesi."""

    reviewer_member_id: str
    """Değerlendirmeyi yapan üye. Prompt'lara ASLA girmez."""

    rankings: list[str] = Field(default_factory=list)
    """En iyiden en kötüye anonim etiketler."""

    scores: dict[str, float] = Field(default_factory=dict)
    criticisms: list[CouncilCriticism] = Field(default_factory=list)

    @field_validator("scores")
    @classmethod
    def scores_must_be_in_range(cls, value: dict[str, float]) -> dict[str, float]:
        for label, score in value.items():
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"{label} için skor 0.0–1.0 aralığında olmalı: {score}")
        return value

    @field_validator("rankings")
    @classmethod
    def rankings_must_not_repeat(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("sıralamada aynı aday birden fazla kez yer alamaz")
        return value


class CouncilResult(BaseModel):
    """Bir müzakerenin tam, yapılandırılmış sonucu."""

    status: CouncilStatus
    final_answer: str | None = None
    """Chairman'ın sentezi. Kullanıcıya DOĞRUDAN gösterilmez — normal cevap
    üretimine sınırlanmış veri olarak aktarılır."""

    candidates: list[CouncilCandidate] = Field(default_factory=list)
    reviews: list[CouncilReview] = Field(default_factory=list)

    trigger: CouncilTrigger | None = None
    failure_reason: str | None = None
    """Makine tarafından okunabilir kısa hata etiketi (gizli bilgi içermez)."""

    @property
    def successful_candidates(self) -> list[CouncilCandidate]:
        return [candidate for candidate in self.candidates if candidate.succeeded]

    @property
    def ok(self) -> bool:
        return self.status is CouncilStatus.COMPLETED and bool(
            (self.final_answer or "").strip()
        )


class CouncilGateDecision(BaseModel):
    """Council'ın çalışıp çalışmayacağına dair deterministik karar."""

    model_config = ConfigDict(frozen=True)

    run: bool
    reason: str = Field(min_length=1, max_length=200)
    trigger: CouncilTrigger | None = None
