"""Council — veri modelleri ve anonimleştirme.

Kapsam:
 1. Geçerli aday / geçersiz aday
 2. Fazla alan reddedilir (extra="forbid")
 3. Geçersiz skor reddedilir
 4. Geçersiz sıralama (tekrar) reddedilir
 5. CouncilResult yardımcıları
 6. Anonimleştirme: deterministik, müzakere başına, global durum yok
 7. Modeller saftır (I/O yok, tool/agent bağımlılığı yok)
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from app.council import models as models_module
from app.council.anonymizer import LabelMap
from app.council.models import (
    CandidateStatus,
    CouncilCandidate,
    CouncilCriticism,
    CouncilGateDecision,
    CouncilRequest,
    CouncilResult,
    CouncilReview,
    CouncilStatus,
    CouncilTrigger,
)


def _candidate(**overrides: object) -> CouncilCandidate:
    defaults: dict[str, object] = dict(
        member_id="member-1", label="A", status=CandidateStatus.SUCCESS, answer="Cevap"
    )
    defaults.update(overrides)
    return CouncilCandidate(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1-2. Aday modeli
# ---------------------------------------------------------------------------


class TestCandidate:
    def test_successful_candidate(self) -> None:
        candidate = _candidate()

        assert candidate.succeeded is True
        assert candidate.status is CandidateStatus.SUCCESS

    def test_failed_candidate_is_not_successful(self) -> None:
        assert _candidate(status=CandidateStatus.FAILED, answer="", error="provider_error").succeeded is False

    def test_timed_out_candidate_is_not_successful(self) -> None:
        assert _candidate(status=CandidateStatus.TIMED_OUT, answer="").succeeded is False

    def test_blank_answer_is_not_successful_even_when_marked_success(self) -> None:
        """Boş bir cevap "başarılı" sayılmamalı."""
        assert _candidate(answer="   ").succeeded is False

    def test_label_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            _candidate(label="TOO_LONG")


# ---------------------------------------------------------------------------
# 3-4. İnceleme doğrulaması
# ---------------------------------------------------------------------------


class TestReviewValidation:
    def test_valid_review(self) -> None:
        review = CouncilReview(
            reviewer_member_id="member-1",
            rankings=["B", "C"],
            scores={"B": 0.9, "C": 0.4},
            criticisms=[CouncilCriticism(candidate="C", issue="Eksik")],
        )

        assert review.rankings == ["B", "C"]

    @pytest.mark.parametrize("score", [-0.1, 1.1, 42.0])
    def test_out_of_range_score_is_rejected(self, score: float) -> None:
        with pytest.raises(ValidationError):
            CouncilReview(reviewer_member_id="m", scores={"A": score})

    def test_duplicate_ranking_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CouncilReview(reviewer_member_id="m", rankings=["A", "A"])

    def test_criticism_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            CouncilCriticism(candidate="A", issue="x", severity="high")  # type: ignore[call-arg]

    def test_criticism_issue_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            CouncilCriticism(candidate="A", issue="x" * 501)


# ---------------------------------------------------------------------------
# 5. Sonuç modeli
# ---------------------------------------------------------------------------


class TestCouncilResult:
    def test_ok_requires_completed_status_and_an_answer(self) -> None:
        assert CouncilResult(status=CouncilStatus.COMPLETED, final_answer="Sentez").ok is True
        assert CouncilResult(status=CouncilStatus.COMPLETED, final_answer="  ").ok is False
        assert CouncilResult(status=CouncilStatus.FAILED, final_answer="Sentez").ok is False
        assert CouncilResult(status=CouncilStatus.INSUFFICIENT).ok is False

    def test_successful_candidates_filters(self) -> None:
        result = CouncilResult(
            status=CouncilStatus.COMPLETED,
            final_answer="x",
            candidates=[
                _candidate(label="A"),
                _candidate(member_id="member-2", label="B", status=CandidateStatus.TIMED_OUT, answer=""),
            ],
        )

        assert [c.label for c in result.successful_candidates] == ["A"]

    def test_request_never_carries_agent_structures(self) -> None:
        """Council, agent veri yapılarını değil düz metin bağlam alır."""
        request = CouncilRequest(task="Görev", context_block="bağlam")

        assert request.task == "Görev"
        assert isinstance(request.context_block, str)

    def test_gate_decision_requires_a_reason(self) -> None:
        with pytest.raises(ValidationError):
            CouncilGateDecision(run=False, reason="")

    def test_gate_decision_is_frozen(self) -> None:
        decision = CouncilGateDecision(run=True, reason="x", trigger=CouncilTrigger.EXPLICIT_REQUEST)
        with pytest.raises(ValidationError):
            decision.run = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 6. Anonimleştirme
# ---------------------------------------------------------------------------


class TestLabelMap:
    def test_assigns_sequential_labels(self) -> None:
        mapping = LabelMap(["member-1", "member-2", "member-3"])

        assert mapping.label_for("member-1") == "A"
        assert mapping.label_for("member-2") == "B"
        assert mapping.label_for("member-3") == "C"
        assert mapping.labels == ["A", "B", "C"]

    def test_reverse_lookup(self) -> None:
        mapping = LabelMap(["m1", "m2"])

        assert mapping.member_for("B") == "m2"
        assert mapping.member_for("Z") is None
        assert mapping.knows_label("A") is True
        assert mapping.knows_label("Z") is False

    def test_unknown_member_raises(self) -> None:
        with pytest.raises(KeyError):
            LabelMap(["m1"]).label_for("nope")

    def test_duplicate_member_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="benzersiz"):
            LabelMap(["m1", "m1"])

    def test_too_many_members_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="en fazla"):
            LabelMap([f"m{i}" for i in range(27)])

    def test_each_map_is_independent(self) -> None:
        """Eşleme müzakere başına üretilir; global/statik durum olmamalı."""
        first = LabelMap(["a", "b"])
        second = LabelMap(["x", "y"])

        assert first.member_for("A") == "a"
        assert second.member_for("A") == "x"
        assert len(first) == len(second) == 2

    def test_module_holds_no_global_state(self) -> None:
        import app.council.anonymizer as anonymizer_module

        source = inspect.getsource(anonymizer_module)
        # Modül düzeyinde bir sözlük/küme tutulmamalı.
        assert "\n_MAP" not in source
        assert "global " not in source


# ---------------------------------------------------------------------------
# 7. Saflık ve sınırlar
# ---------------------------------------------------------------------------


class TestPurity:
    def test_models_module_has_no_io_or_agent_dependency(self) -> None:
        source = inspect.getsource(models_module)

        assert "sqlite" not in source.lower()
        assert "httpx" not in source
        assert "ToolExecutor" not in source
        assert "AgentService" not in source
        assert "from app.agent" not in source

    def test_models_only_know_the_provider_protocol(self) -> None:
        source = inspect.getsource(models_module)

        assert "from app.adapters.llm.base import LLMProvider" in source
        assert "OllamaProvider" not in source
