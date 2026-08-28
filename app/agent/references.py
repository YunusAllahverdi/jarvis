"""Çok adımlı planlarda adımlar arası KONTROLLÜ veri akışı.

Bir adımın argümanı, kendisinden ÖNCEKİ bir adımın sonucundan bir değere
başvurabilir. Başvuru, kod değil VERİDİR:

    {"$from": {"step": 0, "path": "memories.0.content"}}

Güvenlik sınırları (hepsi burada zorlanır):
- Kod çalıştırma YOKTUR. `eval`, format-string, şablon motoru kullanılmaz;
  yalnızca dict anahtarları ve liste indeksleri üzerinde yürünür.
- Yalnızca GERİYE başvurulabilir: adım indeksi mevcut adımdan küçük olmalıdır.
  Böylece döngüsel veya ileriye dönük bağımlılık imkânsızdır.
- Başvurulan adım BAŞARILI olmalıdır. Başarısız bir adımın çıktısı yerine
  bir varsayılan uydurulmaz; bağımlı adım çalıştırılmaz.
- Yol (path) derinliği sınırlıdır; sınırsız derin gezinme yapılamaz.
- Çözülen değer JSON-güvenli olmalıdır (skaler, liste, sözlük).

Çözümlenemeyen bir başvuru SESSİZCE yok sayılmaz: çağıran bir hata kodu alır
ve o adımı çalıştırmaz — yanlış argümanla tool çağırmaktansa adımı
başarısız saymak tercih edilir.
"""

from __future__ import annotations

from typing import Any

REFERENCE_KEY = "$from"
"""Bir argüman değerinin adım başvurusu olduğunu belirten anahtar."""

_STEP_FIELD = "step"
_PATH_FIELD = "path"

MAX_PATH_DEPTH = 8
"""Bir başvuru yolunda izin verilen maksimum segment sayısı."""

MAX_ARGUMENT_DEPTH = 6
"""Argüman ağacında başvuru aranırken inilecek maksimum derinlik."""

ERROR_UNRESOLVED_REFERENCE = "unresolved_reference"
"""Bir başvuru çözülemediğinde üretilen hata kodu."""


class ReferenceError(ValueError):
    """Bir adım başvurusu çözümlenemedi."""


def is_reference(value: Any) -> bool:
    """Bir argüman değerinin adım başvurusu olup olmadığını söyler."""
    return isinstance(value, dict) and set(value.keys()) == {REFERENCE_KEY}


def resolve_arguments(
    arguments: dict[str, Any],
    *,
    previous_results: list[dict[str, Any] | None],
) -> dict[str, Any]:
    """Argümanlardaki adım başvurularını çözer ve yeni bir sözlük döndürür.

    Args:
        arguments: Ham eylem argümanları (başvuru içerebilir).
        previous_results: Bu adımdan ÖNCEKİ adımların sonuç verileri, sırayla.
            Başarısız bir adım için `None` konur. Listenin uzunluğu aynı
            zamanda geriye başvuru sınırıdır — sonraki adımlara erişilemez.

    Returns:
        Başvuruları çözülmüş yeni argüman sözlüğü. Girdi değiştirilmez.

    Raises:
        ReferenceError: Başvuru biçimsiz, ileriye dönük, başarısız bir adıma
            işaret ediyor veya yol bulunamıyorsa.
    """
    return _resolve_value(arguments, previous_results, depth=0)


def _resolve_value(value: Any, previous: list[dict[str, Any] | None], *, depth: int) -> Any:
    if depth > MAX_ARGUMENT_DEPTH:
        raise ReferenceError("argüman ağacı çok derin")

    if is_reference(value):
        return _resolve_reference(value[REFERENCE_KEY], previous)

    if isinstance(value, dict):
        return {key: _resolve_value(item, previous, depth=depth + 1) for key, item in value.items()}

    if isinstance(value, list):
        return [_resolve_value(item, previous, depth=depth + 1) for item in value]

    return value


def _resolve_reference(spec: Any, previous: list[dict[str, Any] | None]) -> Any:
    if not isinstance(spec, dict):
        raise ReferenceError("başvuru bir nesne olmalı")

    unexpected = set(spec.keys()) - {_STEP_FIELD, _PATH_FIELD}
    if unexpected:
        raise ReferenceError(f"başvuruda beklenmeyen alan: {sorted(unexpected)}")

    step = spec.get(_STEP_FIELD)
    if not isinstance(step, int) or isinstance(step, bool):
        raise ReferenceError("başvuru adımı tam sayı olmalı")
    if step < 0 or step >= len(previous):
        # Sınır: yalnızca daha ÖNCE çalışmış adımlara başvurulabilir.
        raise ReferenceError(f"başvurulan adım geçerli değil: {step}")

    source = previous[step]
    if source is None:
        raise ReferenceError(f"başvurulan adım başarılı değil: {step}")

    path = spec.get(_PATH_FIELD, "")
    if not isinstance(path, str):
        raise ReferenceError("başvuru yolu metin olmalı")

    return _walk(source, path)


def _walk(source: dict[str, Any], path: str) -> Any:
    """Yol boyunca yalnızca sözlük anahtarları ve liste indeksleri üzerinde yürür."""
    if not path.strip():
        return source

    segments = [segment for segment in path.split(".") if segment]
    if len(segments) > MAX_PATH_DEPTH:
        raise ReferenceError("başvuru yolu çok derin")

    current: Any = source
    for segment in segments:
        if isinstance(current, dict):
            if segment not in current:
                raise ReferenceError(f"başvuru yolu bulunamadı: {path}")
            current = current[segment]
        elif isinstance(current, list):
            if not segment.lstrip("-").isdigit():
                raise ReferenceError(f"liste indeksi sayısal olmalı: {segment}")
            index = int(segment)
            if index < 0 or index >= len(current):
                raise ReferenceError(f"liste indeksi aralık dışı: {segment}")
            current = current[index]
        else:
            raise ReferenceError(f"başvuru yolu bir değerin içine giremez: {path}")

    if not _is_json_safe(current):
        raise ReferenceError("çözülen değer JSON-güvenli değil")
    return current


def _is_json_safe(value: Any) -> bool:
    """Yalnızca JSON'a serileştirilebilir tiplere izin verilir."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_json_safe(v) for k, v in value.items())
    return False
