"""Kodlama döngüsü — doğrulama çıktısının deterministik teşhisi.

Kapsam:
 1. pytest başarısızlığı TEST_FAILURE olarak sınıflandırılır
 2. Başarısız test kimlikleri çıktıdan çıkarılır
 3. Geri izdeki dosya yolları ipucu olarak toplanır
 4. Sözdizimi hatası kendi kategorisine düşer
 5. İçe aktarma hatası kendi kategorisine düşer
 6. Zaman aşımı çıktıdan bağımsız olarak TIMEOUT'tur
 7. Politika reddi KOD hatası olarak sınıflandırılmaz
 8. Reddedilen komut düzeltilebilir sayılmaz
 9. Tanınmayan çıktı UNKNOWN'a düşer ve ham kesitini korur
10. Kesit sınırı aşılmaz
11. Teşhis hiçbir girdide istisna fırlatmaz
"""

from __future__ import annotations

from app.coding.diagnosis import MAX_EXCERPT_CHARS, diagnose
from app.coding.models import DiagnosisCategory

_PYTEST_OUTPUT = """
============================= test session starts =============================
collected 12 items

tests/test_math.py::test_add PASSED
tests/test_math.py::test_divide FAILED

================================== FAILURES ===================================
____________________________ test_divide ______________________________________
    def test_divide():
>       assert divide(1, 0) == 0
E       ZeroDivisionError: division by zero

app/math_utils.py:14: ZeroDivisionError
=========================== short test summary info ===========================
FAILED tests/test_math.py::test_divide - ZeroDivisionError: division by zero
========================= 1 failed, 11 passed in 0.42s ========================
"""

_TRACEBACK_OUTPUT = """
Traceback (most recent call last):
  File "app/service.py", line 42, in handle
    return self._parse(payload)
  File "app/parser.py", line 8, in _parse
    raise TypeError("bad payload")
TypeError: bad payload
"""


def test_pytest_failure_is_categorised_as_test_failure() -> None:
    diagnosis = diagnose(stdout=_PYTEST_OUTPUT, exit_code=1)

    assert diagnosis.category is DiagnosisCategory.TEST_FAILURE


def test_failing_test_ids_are_extracted() -> None:
    diagnosis = diagnose(stdout=_PYTEST_OUTPUT, exit_code=1)

    assert "tests/test_math.py::test_divide" in diagnosis.failing_tests


def test_traceback_files_become_hints() -> None:
    diagnosis = diagnose(stderr=_TRACEBACK_OUTPUT, exit_code=1)

    assert "app/service.py" in diagnosis.file_hints
    assert "app/parser.py" in diagnosis.file_hints


def test_syntax_error_has_its_own_category() -> None:
    output = 'File "app/x.py", line 3\n    def f(\n         ^\nSyntaxError: invalid syntax'

    assert diagnose(stderr=output, exit_code=1).category is DiagnosisCategory.SYNTAX_ERROR


def test_import_error_has_its_own_category() -> None:
    output = "ModuleNotFoundError: No module named 'missing_package'"

    assert diagnose(stderr=output, exit_code=1).category is DiagnosisCategory.IMPORT_ERROR


def test_timeout_wins_over_output_content() -> None:
    """Zaman aşımı, çıktının ne dediğinden bağımsız bir olgudur."""
    diagnosis = diagnose(stdout=_PYTEST_OUTPUT, timed_out=True, exit_code=None)

    assert diagnosis.category is DiagnosisCategory.TIMEOUT
    assert "zaman aşımı" in diagnosis.summary.lower()


def test_policy_rejection_is_not_a_code_failure() -> None:
    """Reddedilen komutta düzeltilecek kod yoktur; ayrı kategoriye düşer."""
    diagnosis = diagnose(rejection_message="'rm' izin verilen program listesinde değil.")

    assert diagnosis.category is DiagnosisCategory.COMMAND_REJECTED


def test_rejected_command_is_not_actionable() -> None:
    """Döngü, reddedilen bir komut için düzeltme turu harcamamalıdır."""
    diagnosis = diagnose(rejection_message="Komut başlatılamadı.")

    assert diagnosis.is_actionable is False


def test_unrecognised_output_falls_back_to_unknown() -> None:
    diagnosis = diagnose(stdout="something went sideways", exit_code=3)

    assert diagnosis.category is DiagnosisCategory.UNKNOWN
    assert "something went sideways" in diagnosis.excerpt


def test_excerpt_respects_the_limit() -> None:
    diagnosis = diagnose(stdout="x" * (MAX_EXCERPT_CHARS * 3), exit_code=1)

    assert len(diagnosis.excerpt) <= MAX_EXCERPT_CHARS


def test_diagnose_never_raises_on_odd_input() -> None:
    """Teşhis bir savunma katmanıdır; kendisi bir hata kaynağı olamaz."""
    for stdout, stderr in (("", ""), ("\x00\x01", "ünïcödé"), ("<script>", "\n\n\n")):
        assert diagnose(stdout=stdout, stderr=stderr, exit_code=1) is not None
