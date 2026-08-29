"""Gizli bilginin tanınması ve maskelenmesi.

"Gizli bilgi neye benzer?" sorusunun tek cevabı burada durur. İki farklı
kullanıcısı var ve ikisi de aynı tanımı kullanmalıdır:

- Bellek çıkarıcı, gizli bilgi içeren adayı **reddeder**.
- Denetim kaydı, argümanları **maskeleyerek** yazar.

Kalıplar bilerek geniştir. Bir denetim kaydında fazladan maskelenmiş bir
alan yalnızca okunabilirliği düşürür; kaçan bir anahtar ise kalıcı bir
sızıntıdır. Şüphede kalınca maskelemekten yanayız.
"""

import re
from typing import Any

REDACTED = "[REDACTED]"
"""Maskelenmiş bir değerin yerine yazılan işaret."""

MAX_VALUE_LENGTH = 512
"""Denetim kaydına yazılacak tek bir değerin üst sınırı.

Bir dosya yazma çağrısının argümanı tüm dosya içeriği olabilir. Denetim
kaydı ne yapıldığını göstermelidir, verinin kendisini saklamak zorunda
değildir.
"""

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
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

_SECRET_KEY_NAMES = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|auth)",
    re.IGNORECASE,
)
"""Adı tek başına içeriğini gizli kılan argüman anahtarları.

Değer kalıba uymasa bile — kısa bir parola gibi — anahtar adı yeterlidir.
"""


def contains_secret(text: str) -> bool:
    """Metnin gizli bilgi barındırıp barındırmadığını söyler.

    Deterministik kural tabanlı denetim — LLM çıkışına güvenilmez.
    """
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def redact_text(text: str) -> str:
    """Metindeki gizli görünen parçaları maskeler ve uzunluğu sınırlar."""

    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)

    if len(redacted) > MAX_VALUE_LENGTH:
        return redacted[:MAX_VALUE_LENGTH] + f"…[{len(redacted) - MAX_VALUE_LENGTH} karakter kırpıldı]"
    return redacted


def redact_value(key: str | None, value: Any) -> Any:
    """Tek bir değeri, anahtar adını da dikkate alarak maskeler.

    Yapı korunur: sözlük ve listeler gezilerek içleri maskelenir, böylece
    denetim kaydı "ne yapıldı" sorusunu hâlâ cevaplayabilir.
    """
    if key is not None and _SECRET_KEY_NAMES.search(key):
        return REDACTED

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(None, item) for item in value]
    return value


def redact_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Bir araç çağrısının argümanlarını denetim kaydına yazılabilir hâle getirir."""

    return {key: redact_value(str(key), value) for key, value in arguments.items()}
