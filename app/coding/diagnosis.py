"""Doğrulama çıktısının DETERMİNİSTİK teşhisi.

Bu modül hiçbir LLM çağırmaz ve çağırmamalıdır. Sebebi maliyet değil,
güvenilirliktir: "test geçti mi?" sorusunun cevabı çıkış kodudur, bir modelin
yorumu değil. Modelin işi hatayı DÜZELTMEKTİR, hatanın olup olmadığına karar
vermek değil — bu ikisi karıştırıldığında model, geçmeyen bir testi geçmiş
ilan edebilir ve döngü kendi kendini kandırır.

Çıktı GÜVENİLMEZ VERİDİR: bir test adı, bir dosya yolu veya bir hata metni
model tarafından okunacaksa çitlenerek okunmalıdır (bkz. `app.coding.prompts`).
Burada yalnızca ayrıştırma yapılır, biçimlendirme değil.

Tanınan örüntüler bilinçli olarak DAR tutulmuştur: pytest, Python geri izi
(traceback) ve komut politikası retleri. Tanınmayan her çıktı `UNKNOWN`
kategorisine düşer ve ham kesitiyle birlikte taşınır — uydurulmuş bir
kategori, yanlış bir düzeltmeye yol açar.
"""

from __future__ import annotations

import re

from app.coding.models import Diagnosis, DiagnosisCategory

MAX_EXCERPT_CHARS = 4000
"""Teşhisle birlikte taşınacak en fazla karakter.

`Diagnosis.excerpt` alanının sınırıyla aynıdır; kırpma burada yapılır ki
model doğrulamasına hiç geçersiz veri gitmesin.
"""

_MAX_ITEMS = 10
"""Bir listede taşınacak en fazla test/dosya. Sınırsız liste, sınırsız prompt."""

# pytest'in özet satırı: "FAILED tests/test_x.py::test_y - AssertionError: ..."
_PYTEST_FAILED = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?::\S+)", re.MULTILINE)

# pytest'in sayaç satırı: "=== 3 failed, 12 passed in 1.2s ==="
_PYTEST_COUNTS = re.compile(r"\b(\d+)\s+(failed|error|errors)\b", re.IGNORECASE)

# Python geri izi dosya satırı: '  File "app/x.py", line 12, in f'
_TRACEBACK_FILE = re.compile(r'File "([^"]+)", line (\d+)')

# Toplanma hatası: "ERROR tests/test_x.py" (::test yok)
_PYTEST_COLLECT_ERROR = re.compile(r"^ERROR\s+(\S+\.py)\s*$", re.MULTILINE)

_SYNTAX_MARKERS = ("SyntaxError:", "IndentationError:", "TabError:")
_IMPORT_MARKERS = ("ModuleNotFoundError:", "ImportError:")
_TYPE_MARKERS = ("TypeError:", "AttributeError:", "NameError:")

# Komut politikası ve izin katmanının retleri. Bunlar KOD hatası değildir.
_REJECTION_MARKERS = (
    "izin verilen program",
    "izni bu oturumda etkin değil",
    "onayı gerekiyor",
    "bulunamadı.",
    "Komut başlatılamadı.",
)


def _clip(text: str) -> str:
    """Kesiti sınıra kırpar; sondan kırpar çünkü hata çoğunlukla sondadır."""
    if len(text) <= MAX_EXCERPT_CHARS:
        return text
    return text[-MAX_EXCERPT_CHARS:]


def _unique(values: list[str]) -> list[str]:
    """Sırayı koruyarak tekilleştirir ve sayıyı sınırlar."""
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= _MAX_ITEMS:
            break
    return seen


def _first_error_line(text: str) -> str:
    """Çıktıdaki ilk anlamlı hata satırını bulur; yoksa son dolu satırı.

    Özet cümlesi buradan üretilir. Bir modele yazdırılmamasının sebebi
    yine dürüstlüktür: özet, çıktıda GERÇEKTEN yazan bir şey olmalıdır.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        # pytest hata satırlarını "E   " ile önekler.
        if line.startswith("E ") or line.startswith("E\t"):
            return line[1:].strip()
        for marker in (*_SYNTAX_MARKERS, *_IMPORT_MARKERS, *_TYPE_MARKERS):
            if marker in line:
                return line
    return lines[-1] if lines else ""


def _categorize(text: str, *, timed_out: bool, rejected: bool) -> DiagnosisCategory:
    """Çıktıyı bilinen bir kategoriye eşler.

    Sıralama önemlidir ve en spesifikten en genele gider: zaman aşımı ve ret
    çıktının içeriğinden BAĞIMSIZ olgulardır, bu yüzden önce gelirler.
    """
    if rejected:
        return DiagnosisCategory.COMMAND_REJECTED
    if timed_out:
        return DiagnosisCategory.TIMEOUT
    if any(marker in text for marker in _SYNTAX_MARKERS):
        return DiagnosisCategory.SYNTAX_ERROR
    if any(marker in text for marker in _IMPORT_MARKERS):
        return DiagnosisCategory.IMPORT_ERROR
    if _PYTEST_FAILED.search(text) or _PYTEST_COUNTS.search(text):
        return DiagnosisCategory.TEST_FAILURE
    if any(marker in text for marker in _TYPE_MARKERS):
        return DiagnosisCategory.TYPE_ERROR
    return DiagnosisCategory.UNKNOWN


def diagnose(
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = None,
    timed_out: bool = False,
    rejection_message: str | None = None,
) -> Diagnosis:
    """Doğrulama çıktısını yapılandırılmış bir teşhise çevirir.

    Hiçbir zaman istisna fırlatmaz ve her zaman bir teşhis döndürür:
    tanınmayan çıktı `UNKNOWN` kategorisiyle, ham kesitiyle birlikte taşınır.

    Args:
        stdout: Komutun standart çıktısı.
        stderr: Komutun hata çıktısı.
        exit_code: Çıkış kodu; bilinmiyorsa None.
        timed_out: Komut zaman aşımına uğradıysa True.
        rejection_message: Komut hiç çalıştırılamadıysa (politika reddi,
            izin reddi, program bulunamadı) o katmanın mesajı. Verildiğinde
            teşhis KOD hatası olarak değil, ret olarak sınıflandırılır.
    """
    if rejection_message:
        return Diagnosis(
            category=DiagnosisCategory.COMMAND_REJECTED,
            summary=rejection_message[:300],
            excerpt=_clip(rejection_message),
        )

    combined = "\n".join(part for part in (stdout, stderr) if part)
    rejected = any(marker in combined for marker in _REJECTION_MARKERS)
    category = _categorize(combined, timed_out=timed_out, rejected=rejected)

    failing_tests = _unique(
        _PYTEST_FAILED.findall(combined) + _PYTEST_COLLECT_ERROR.findall(combined)
    )
    file_hints = _unique(
        [path for path, _line in _TRACEBACK_FILE.findall(combined)]
        # Test kimliğinin dosya kısmı da bir ipucudur: geri iz olmasa bile
        # hangi dosyanın testi patladığını biliriz.
        + [test.split("::", 1)[0] for test in failing_tests]
    )

    return Diagnosis(
        category=category,
        summary=_summarize(category, combined, exit_code=exit_code, timed_out=timed_out),
        failing_tests=failing_tests,
        file_hints=file_hints,
        excerpt=_clip(combined),
    )


def _summarize(
    category: DiagnosisCategory,
    text: str,
    *,
    exit_code: int | None,
    timed_out: bool,
) -> str:
    """Teşhis için kısa, OLGUSAL bir özet cümlesi üretir.

    Cümle çıktıdan türetilir; yorum eklenmez. "Muhtemelen şu olmuş olabilir"
    türü tahminler bilinçli olarak yoktur: yanlış bir tahmin, düzeltme turunu
    yanlış dosyaya yönlendirir.
    """
    if timed_out:
        return "Doğrulama komutu zaman aşımına uğradı."
    if category is DiagnosisCategory.COMMAND_REJECTED:
        return "Doğrulama komutu çalıştırılamadı; izin veya politika engeli."

    detail = _first_error_line(text)
    counts = _PYTEST_COUNTS.search(text)
    if counts:
        prefix = f"{counts.group(1)} test başarısız."
        return (f"{prefix} {detail}" if detail else prefix)[:300]
    if detail:
        return detail[:300]
    if exit_code is not None:
        return f"Doğrulama komutu {exit_code} çıkış koduyla sonlandı."
    return "Doğrulama başarısız oldu; çıktıdan ayrıntı çıkarılamadı."
