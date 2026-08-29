"""Güvenlik katmanı — gizli bilgi tanıma ve maskeleme.

Kapsam:
 1. Bilinen gizli bilgi kalıpları tanınır
 2. Zararsız metin maskelenmeden geçer
 3. Anahtar ADI gizliyse değer maskelenir (değer masum görünse bile)
 4. Değerin kendisi gizliye benziyorsa maskelenir
 5. İç içe sözlük ve listeler gezilir, yapı korunur
 6. Çok uzun değerler kırpılır
 7. Metin olmayan değerler olduğu gibi kalır
 8. Bellek çıkarıcı ile denetim kaydı AYNI kalıp tanımını kullanır
"""

from __future__ import annotations

import pytest

from app.memory.extractor import _SECRET_PATTERNS
from app.security.redaction import (
    MAX_VALUE_LENGTH,
    REDACTED,
    SECRET_PATTERNS,
    contains_secret,
    redact_arguments,
    redact_text,
)


# ---------------------------------------------------------------------------
# 1-2. Tanıma
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "The user's password is hunter2",
        "API key is sk-abc123",
        "auth_token: Bearer eyJhbGciOiJIUzI1NiJ9",
        "Private key: -----BEGIN RSA PRIVATE KEY-----",
        "access_token: xoxb-abc-def",
        "deadbeefdeadbeefdeadbeefdeadbeef",
    ],
)
def test_known_secrets_are_detected(text: str) -> None:
    """Gizli bilgi kalıpları tanınmalı."""
    assert contains_secret(text) is True


@pytest.mark.parametrize(
    "text",
    ["merhaba dünya", "rapor.txt dosyasını oku", "25 * 17 kaç eder"],
)
def test_harmless_text_is_untouched(text: str) -> None:
    """Zararsız metin ne gizli sayılmalı ne de değiştirilmeli."""
    assert contains_secret(text) is False
    assert redact_text(text) == text


# ---------------------------------------------------------------------------
# 3-4. Maskeleme kararı
# ---------------------------------------------------------------------------

def test_secret_key_name_masks_even_an_innocent_value() -> None:
    """Anahtar adı gizliyse değer okunmadan maskelenmeli.

    Kısa bir parola hiçbir kalıba uymaz; onu yakalayan tek şey adıdır.
    """
    result = redact_arguments({"password": "abc", "api_key": "1", "path": "rapor.txt"})

    assert result["password"] == REDACTED
    assert result["api_key"] == REDACTED
    assert result["path"] == "rapor.txt", "masum alan maskelenmemeliydi"


def test_secret_looking_value_is_masked() -> None:
    """Anahtar adı masum olsa da değer gizliye benziyorsa maskelenmeli."""
    result = redact_arguments({"note": "auth_token: Bearer eyJhbGciOiJIUzI1NiJ9"})

    assert REDACTED in result["note"]
    assert "eyJhbGciOiJIUzI1NiJ9" not in result["note"]


# ---------------------------------------------------------------------------
# 5-7. Yapı ve sınırlar
# ---------------------------------------------------------------------------

def test_nested_structures_are_walked_and_preserved() -> None:
    """İç içe yapılar gezilmeli ama biçimleri bozulmamalı."""
    result = redact_arguments(
        {
            "config": {"password": "x", "host": "127.0.0.1"},
            "files": ["a.txt", "b.txt"],
        }
    )

    assert result["config"] == {"password": REDACTED, "host": "127.0.0.1"}
    assert result["files"] == ["a.txt", "b.txt"]


def test_long_values_are_truncated() -> None:
    """Denetim kaydı dosya içeriğini saklamak zorunda değil.

    Metin bilerek boşluklu seçildi: bitişik uzun bir dizi zaten token
    kalıbına uyar ve kırpılmadan önce tamamen maskelenirdi.
    """
    long_text = "kelime " * ((MAX_VALUE_LENGTH // 7) + 40)
    assert len(long_text) > MAX_VALUE_LENGTH

    result = redact_text(long_text)

    assert len(result) < len(long_text)
    assert "kırpıldı" in result


def test_a_long_unbroken_string_is_masked_not_merely_trimmed() -> None:
    """Bitişik uzun dizi token'a benzer; kırpmak yerine tamamen maskelenmeli.

    Fazladan maskeleme kabul edilebilir bir maliyettir — kaçan bir anahtar
    değildir.
    """
    assert redact_text("a" * (MAX_VALUE_LENGTH + 200)) == REDACTED


def test_non_string_values_pass_through() -> None:
    """Sayı ve bayraklar olduğu gibi kalmalı — okunabilirlik için."""
    result = redact_arguments({"count": 3, "force": True, "ratio": 1.5, "none": None})

    assert result == {"count": 3, "force": True, "ratio": 1.5, "none": None}


# ---------------------------------------------------------------------------
# 8. Tek tanım
# ---------------------------------------------------------------------------

def test_extractor_and_redaction_share_one_definition() -> None:
    """İki kullanıcı da aynı kalıp listesini kullanmalı; ayrışamasınlar."""
    assert _SECRET_PATTERNS is SECRET_PATTERNS
