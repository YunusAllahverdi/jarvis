"""Kodlama döngüsü — üretilen diff'in Council tarafından incelenmesi.

Kapsam:
 1. Diff varsa inceleme çalışır ve bulguları taşır
 2. Diff yoksa inceleme çalışmaz
 3. Council başarısız olursa sonuç incelenmemiş kalır, iş kaybolmaz
 4. Council patlarsa istisna sızmaz
 5. Diff ÇİTLENEREK gönderilir (incelenen kod talimat yazamaz)
 6. Hedef de çitlenir
 7. Kırpma gizlenmez, incelemeciye söylenir
 8. İNCELEME BİR KAPI DEĞİLDİR: bulgular durumu değiştirmez
 9. Özet, inceleme yapılmadığında bunu açıkça söyler
10. Özet bulguları raporlar
11. İnceleyici bağlı değilse döngü normal çalışır
"""

from __future__ import annotations

import asyncio

from app.coding.models import CodingResult, CodingStatus, TaskSpec
from app.coding.review import CodeReview, CodeReviewer
from app.coding.summary import build_summary
from app.council.models import (
    CouncilCandidate,
    CandidateStatus,
    CouncilRequest,
    CouncilResult,
    CouncilStatus,
)
from app.security.fencing import UNTRUSTED_OPEN


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class _FakeCouncil:
    """Sabit bir sonuç döndüren ve isteği kaydeden sahte Council."""

    def __init__(
        self,
        *,
        answer: str | None = "app/x.py: eklenen API anahtarı koda gömülmüş.",
        ok: bool = True,
        explode: bool = False,
    ) -> None:
        self._answer = answer
        self._ok = ok
        self._explode = explode
        self.request: CouncilRequest | None = None

    async def deliberate(self, request, *, trigger=None):  # type: ignore[no-untyped-def]
        if self._explode:
            raise RuntimeError("council patladı")
        self.request = request
        return CouncilResult(
            status=CouncilStatus.COMPLETED if self._ok else CouncilStatus.FAILED,
            final_answer=self._answer,
            candidates=[
                CouncilCandidate(
                    member_id="member-1", label="A", status=CandidateStatus.SUCCESS, answer="x"
                )
            ],
        )


def _result(diff: str | None = "--- a/app/x.py\n+++ b/app/x.py\n+API_KEY = 'sk-123'") -> CodingResult:
    return CodingResult(
        request="anahtarı ekle",
        status=CodingStatus.COMPLETED,
        task=TaskSpec(goal="Bir yapılandırma ekle.", verification_command="pytest -q"),
        diff=diff,
    )


def test_review_runs_and_carries_findings() -> None:
    council = _FakeCouncil()

    review = _run(CodeReviewer(council_service=council).review(_result()))  # type: ignore[arg-type]

    assert review.ran is True
    assert "API anahtarı" in review.findings
    assert review.reviewer_count == 1


def test_no_diff_means_no_review() -> None:
    review = _run(CodeReviewer(council_service=_FakeCouncil()).review(_result(diff=None)))  # type: ignore[arg-type]

    assert review.ran is False
    assert review.skipped_reason is not None


def test_failed_council_leaves_the_work_unreviewed_not_lost() -> None:
    council = _FakeCouncil(ok=False, answer=None)

    review = _run(CodeReviewer(council_service=council).review(_result()))  # type: ignore[arg-type]

    assert review.ran is False
    assert review.findings == ""


def test_exploding_council_does_not_leak() -> None:
    council = _FakeCouncil(explode=True)

    review = _run(CodeReviewer(council_service=council).review(_result()))  # type: ignore[arg-type]

    assert review.ran is False


def test_diff_is_fenced() -> None:
    """İncelenen kod, incelemeciye talimat yazmak için ideal bir yerdir."""
    council = _FakeCouncil()
    _run(CodeReviewer(council_service=council).review(_result()))  # type: ignore[arg-type]

    block = council.request.context_block or ""
    assert UNTRUSTED_OPEN in block
    assert 'type="diff"' in block


def test_goal_is_also_fenced() -> None:
    """Hedef kullanıcı isteğinden türer; o da güvenilmezdir."""
    council = _FakeCouncil()
    _run(CodeReviewer(council_service=council).review(_result()))  # type: ignore[arg-type]

    assert 'type="stated_goal"' in (council.request.context_block or "")


def test_truncation_is_disclosed_to_the_reviewer() -> None:
    """Görmediği bir parça olduğunu bilmeyen bir incelemeci, bulgusuzluğu güvence sanar."""
    council = _FakeCouncil()
    long_diff = "+" + ("x" * 500)
    reviewer = CodeReviewer(council_service=council, max_diff_chars=100)  # type: ignore[arg-type]

    review = _run(reviewer.review(_result(diff=long_diff)))

    assert review.diff_truncated is True
    assert "truncated" in (council.request.context_block or "").lower()


def test_review_is_a_report_not_a_gate() -> None:
    """İnceleyen de bir modeldir ve yanılabilir; doğru bir işi geri alamamalı."""
    result = _result()
    original_status = result.status

    result.review = _run(CodeReviewer(council_service=_FakeCouncil()).review(result))  # type: ignore[arg-type]

    assert result.status is original_status
    assert result.diff is not None


def test_summary_states_when_review_did_not_run() -> None:
    result = _result()
    result.review = CodeReview(ran=False, skipped_reason="Council kurulu değil.")

    assert "Kod incelemesi yapılmadı" in build_summary(result)


def test_summary_reports_findings() -> None:
    result = _result()
    result.review = CodeReview(ran=True, findings="app/x.py: gömülü anahtar.", reviewer_count=2)

    summary = build_summary(result)

    assert "2 inceleyici" in summary
    assert "gömülü anahtar" in summary


def test_summary_warns_when_the_diff_was_truncated() -> None:
    result = _result()
    result.review = CodeReview(
        ran=True, findings="sorun yok", reviewer_count=1, diff_truncated=True
    )

    assert "kırpıldı" in build_summary(result)
