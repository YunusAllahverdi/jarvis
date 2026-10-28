"""Skill klasörlerini tarama — bozuk girdileri atlar, uygulamayı çökertmez.

Keşif, `roots` altındaki her ALT KLASÖRÜ tarar ve içinde `SKILL.md` olanları
bir yetenek olarak kabul eder. Tek bir bozuk dosya (ayraçsız, bozuk YAML,
eksik `name`/`description`) TÜM taramayı düşürmez: o skill atlanır, nedeni
loglanır ve diğerleri keşfedilmeye devam eder.

Provenans (kaynak repo, lisans, commit SHA) iki yerden okunur:

1. Ön yüzdeki `license` alanı (varsa),
2. Klasördeki isteğe bağlı `.skill-source.json` yan dosyası.

Yan dosya, vendorlanan skill'lerin izlenebilirliği içindir; elle eklenen
yerel skill'lerde bulunmaz ve bu bir hata değildir.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.skills.frontmatter import FrontmatterError, parse_frontmatter
from app.skills.models import Skill, SkillInfo

logger = logging.getLogger(__name__)

SKILL_FILE_NAME = "SKILL.md"
SOURCE_SIDECAR_NAME = ".skill-source.json"

_DEFAULT_SOURCE_FIELDS = ("source", "source_sha", "license")


class SkillDiscoveryError(RuntimeError):
    """Keşif yapılandırması bozuk (ör. kök bir dizin değil)."""


def discover_skills(roots: list[str | Path]) -> list[Skill]:
    """Verilen köklerdeki tüm geçerli skill'leri keşfeder.

    Args:
        roots: Taranacak kök klasörler. Var olmayan bir kök sessizce atlanır
            (bir yeteneğin kurulmamış olması hata değildir).

    Returns:
        Ada göre sıralı skill listesi. Bozuk girdiler listeye GİRMEZ.

    Raises:
        SkillDiscoveryError: Bir kök var ama bir dizin değilse. Var olmayan
            kök hata DEĞİLDİR; var olup yanlış türde olan kök bir
            yapılandırma hatasıdır ve sessizce yutulmamalıdır.
    """
    skills: list[Skill] = []
    seen: set[str] = set()

    for raw_root in roots:
        root = Path(raw_root).expanduser()
        if not root.exists():
            logger.debug("skill_root_missing", extra={"root": str(root)})
            continue
        if not root.is_dir():
            raise SkillDiscoveryError(f"Skill kökü bir dizin olmalıdır: {root}")

        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            skill = _load_skill_dir(child)
            if skill is None:
                continue
            if skill.slug in seen:
                # İki kök aynı adlı skill sağlarsa ilki kazanır; ikincisi
                # sessizce ezilmez, loglanır.
                logger.warning("skill_name_conflict", extra={"skill": skill.name})
                continue
            seen.add(skill.slug)
            skills.append(skill)

    skills.sort(key=lambda item: item.name)
    return skills


def _load_skill_dir(directory: Path) -> Skill | None:
    """Tek bir klasörü skill olarak yüklemeyi dener; başarısızsa None."""

    skill_file = directory / SKILL_FILE_NAME
    if not skill_file.is_file():
        return None

    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("skill_unreadable", extra={"skill_dir": str(directory), "error": str(exc)})
        return None

    try:
        metadata, body = parse_frontmatter(text)
    except FrontmatterError as exc:
        logger.warning(
            "skill_frontmatter_invalid",
            extra={"skill_dir": str(directory), "error": str(exc)},
        )
        return None

    name = _clean_str(metadata.get("name"))
    description = _clean_str(metadata.get("description"))
    if not name or not description:
        logger.warning(
            "skill_frontmatter_incomplete",
            extra={"skill_dir": str(directory), "skill_name": name or ""},
        )
        return None

    slug = _slugify(name)
    sidecar = _read_sidecar(directory)

    try:
        info = SkillInfo(
            name=name,
            description=description,
            slug=slug,
            license=_clean_str(metadata.get("license")) or _clean_str(sidecar.get("license")),
            source=_clean_str(sidecar.get("source")),
            source_sha=_clean_str(sidecar.get("source_sha")),
            root=directory.resolve(),
            metadata=_extra_metadata(metadata),
        )
    except ValidationError as exc:
        logger.warning(
            "skill_invalid",
            extra={"skill_dir": str(directory), "error": str(exc)},
        )
        return None

    return Skill(info=info, body=body)


def _read_sidecar(directory: Path) -> dict[str, Any]:
    """İsteğe bağlı `.skill-source.json` yan dosyasını okur (yoksa boş)."""

    sidecar_path = directory / SOURCE_SIDECAR_NAME
    if not sidecar_path.is_file():
        return {}
    try:
        loaded = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "skill_source_sidecar_invalid",
            extra={"skill_dir": str(directory), "error": str(exc)},
        )
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _extra_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Bilinen alanlar dışındaki ön yüz alanlarını toplar."""

    known = {"name", "description", "license"}
    return {key: value for key, value in metadata.items() if key not in known}


def _clean_str(value: Any) -> str:
    """Bir ön yüz değerini kırpılmış dizeye çevirir; geçersizse boş."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        # `True`/`False` metne çevrilir; YAML'da tırnaksız yazılmış bir
        # boolean'ı sessizce atmak yerine görünür kılarız.
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    # İç içe yapılar (liste/sözlük) metin alanlarına konmaz.
    return ""


def _slugify(name: str) -> str:
    """Skill adını dosya/override anahtarı için normalize eder."""

    cleaned = name.strip().lower()
    out = []
    for ch in cleaned:
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        else:
            out.append("-")
    return "".join(out).strip("-_") or "skill"
