"""Kodlama döngüsü — açıklama deterministiktir ve yalnızca olanı yazar.

Kapsam:
 1. Her durum için bir başlık üretilir
 2. Değiştirilen dosyalar listelenir
 3. Değişiklik yoksa bu açıkça söylenir
 4. Başarısız adımlar gizlenmez
 5. Doğrulama sonucu ve teşhis raporlanır
 6. Çalışmayan doğrulamanın sebebi yazılır
 7. Onay bekleyen istek sayısı yazılır
 8. Özet hiçbir bilgi uydurmaz
"""

from __future__ import annotations

from app.agent.models import ActionOutcome, AgentAction
from app.coding.models import (
    CodingPlan,
    CodingResult,
    CodingStatus,
    Diagnosis,
    DiagnosisCategory,
    Iteration,
    TaskSpec,
    Verification,
)
from app.coding.summary import build_summary


def _iteration(*outcomes: ActionOutcome, verification: Verification | None = None) -> Iteration:
    return Iteration(
        index=0,
        plan=CodingPlan(
            steps=[
                AgentAction(tool_name=outcome.tool_name, purpose="adım")
                for outcome in outcomes
            ]
        ),
        outcomes=list(outcomes),
        verification=verification,
    )


def _result(status: CodingStatus, *iterations: Iteration, **kwargs) -> CodingResult:
    return CodingResult(
        request="bir şey yap",
        status=status,
        task=TaskSpec(goal="Hatayı düzelt.", verification_command="pytest -q"),
        iterations=list(iterations),
        **kwargs,
    )


def test_every_status_gets_a_headline() -> None:
    for status in CodingStatus:
        summary = build_summary(_result(status))
        assert summary.splitlines()[0]
        assert "Sonuç belirsiz" not in summary


def test_changed_files_are_listed() -> None:
    outcome = ActionOutcome(
        tool_name="edit_file", success=True, arguments={"path": "app/x.py"}
    )
    summary = build_summary(_result(CodingStatus.COMPLETED, _iteration(outcome)))

    assert "app/x.py" in summary


def test_absence_of_changes_is_stated_explicitly() -> None:
    """Doğrulama geçmiş ama hiçbir dosya değişmemişse bu bilinmelidir."""
    outcome = ActionOutcome(
        tool_name="read_file", success=True, arguments={"path": "app/x.py"}
    )
    summary = build_summary(_result(CodingStatus.COMPLETED, _iteration(outcome)))

    assert "Hiçbir dosya değiştirilmedi." in summary


def test_failed_steps_are_not_hidden() -> None:
    """Yalnızca başarılı adımları göstermek, gerçekte ne olduğunu gizlemektir."""
    summary = build_summary(
        _result(
            CodingStatus.VERIFICATION_FAILED,
            _iteration(
                ActionOutcome(tool_name="read_file", success=True, arguments={"path": "a.py"}),
                ActionOutcome(
                    tool_name="edit_file", success=False, error_code="invalid_arguments"
                ),
            ),
        )
    )

    assert "başarısız" in summary
    assert "invalid_arguments" in summary


def test_verification_failure_reports_the_diagnosis() -> None:
    verification = Verification(
        ran=True,
        passed=False,
        command="pytest -q",
        exit_code=1,
        diagnosis=Diagnosis(
            category=DiagnosisCategory.TEST_FAILURE,
            summary="1 test başarısız.",
            failing_tests=["tests/test_a.py::test_b"],
        ),
    )
    summary = build_summary(
        _result(
            CodingStatus.VERIFICATION_FAILED,
            _iteration(
                ActionOutcome(tool_name="edit_file", success=True, arguments={"path": "a.py"}),
                verification=verification,
            ),
        )
    )

    assert "pytest -q" in summary
    assert "1 test başarısız." in summary
    assert "tests/test_a.py::test_b" in summary


def test_skipped_verification_explains_itself() -> None:
    verification = Verification(ran=False, skipped_reason="Terminal kapalı.")
    summary = build_summary(
        _result(
            CodingStatus.APPLIED_UNVERIFIED,
            _iteration(
                ActionOutcome(tool_name="edit_file", success=True, arguments={"path": "a.py"}),
                verification=verification,
            ),
        )
    )

    assert "Terminal kapalı." in summary


def test_pending_approvals_are_counted() -> None:
    summary = build_summary(
        _result(
            CodingStatus.PENDING_APPROVAL,
            _iteration(ActionOutcome(tool_name="edit_file", requires_approval=True)),
            pending_approval_ids=["abc", "def"],
        )
    )

    assert "2" in summary


def test_summary_invents_nothing() -> None:
    """Özet yalnızca sonuçtaki verilerden üretilir."""
    summary = build_summary(_result(CodingStatus.NO_PLAN))

    assert "pytest" not in summary or "Doğrulama komutu" not in summary
    assert "Hedef: Hatayı düzelt." in summary
