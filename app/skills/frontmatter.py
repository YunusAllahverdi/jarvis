"""SKILL.md YAML ön yüzünü (frontmatter) ayrıştırma.

Bir skill dosyası `---` ile çevrili bir YAML bloğuyla başlar ve gövdesi bu
bloğun ardından gelir. Bu modül yalnızca AYRIŞTIRIR: dosyayı okumaz, klasör
taraması yapmaz, doğrulama kararı vermez. Ayrıştırma ile keşfin ayrılması
bilinçlidir — bozuk bir ön yüz bir dosyanın sorunudur, taramanın değil.

`yaml.safe_load` kullanılır: `yaml.load` keyfi Python nesnesi kurma izni
verir ve güvenilmez bir dosya için bu kabul edilemez.
"""

from __future__ import annotations

from typing import Any

import yaml

DELIMITER = "---"
"""Ön yüz bloğunu açan ve kapatan ayraç."""


class FrontmatterError(ValueError):
    """Ön yüz okunamadı: ayraç yok, YAML bozuk ya da blok bir eşleme değil.

    Bu bir `ValueError`'dır çünkü hata dosyanın İÇERİĞİYLE ilgilidir, bir
    kaynak tükenmesiyle değil. Çağıran (keşif) bunu yakalar, o skill'i
    atlar ve loglar; uygulama çökmez.
    """


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Metni (ön yüz, gövde) ikilisine ayırır.

    Args:
        text: Dosyanın tam içeriği.

    Returns:
        `(metadata, body)`: ön yüz alanları ve kalan gövde (kırpılmamış).

    Raises:
        FrontmatterError: Metin `---` ile başlamıyorsa, kapanış ayracı
            yoksa, YAML bozuksa ya da blok bir eşleme (mapping) değilse.
    """
    # UTF-8 BOM bazı editörlerce eklenir; ayracı tanımak için önce atılır.
    normalized = text.lstrip("\ufeff")
    if not normalized.startswith(DELIMITER):
        raise FrontmatterError("Dosya '---' ön yüz ayracıyla başlamıyor.")

    # İlk satırı (açılış ayracı) atla, sonra kapanış ayracını ara.
    lines = normalized.splitlines()
    if lines and lines[0].strip() == DELIMITER:
        rest = lines[1:]
    else:
        # "---" sonrasında aynı satırda içerik varsa (ör. "--- foo") geçersiz
        # sayılır: spec bloğun kendi satırında başlamasını bekler.
        raise FrontmatterError("Ön yüz ayracı kendi satırında olmalıdır.")

    closing = _find_closing_delimiter(rest)
    if closing is None:
        raise FrontmatterError("Ön yüzün kapanış '---' ayracı yok.")

    yaml_block = "\n".join(rest[:closing])
    body = "\n".join(rest[closing + 1 :])

    try:
        loaded = yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"Ön yüz YAML'i çözümlenemedi: {exc}") from exc

    if loaded is None:
        # Boş ön yüz: bir eşleme değil, eksik veridir.
        raise FrontmatterError("Ön yüz boş; 'name' ve 'description' zorunludur.")

    if not isinstance(loaded, dict):
        raise FrontmatterError("Ön yüz bir eşleme (anahtar: değer) olmalıdır.")

    return loaded, body


def _find_closing_delimiter(lines: list[str]) -> int | None:
    """Kapanış ayracının satır indeksini bulur; yoksa None."""

    for index, line in enumerate(lines):
        if line.strip() == DELIMITER:
            return index
    return None
