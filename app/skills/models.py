"""Skill veri modelleri — keşfedilen bir yeteneğin güvenli görünümü.

`SkillInfo` arayüze ve denetime giden salt-okunur görünümdür: gövde, script
içeriği veya dosya sistemi ayrıntısı TAŞIMAZ. `Skill` ise çalışma zamanında
gövdeyi de yanında tutar; yalnızca `load_skill` çağrıldığında kullanılır.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SKILL_NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
"""agentskills.io ad kuralı: küçük harf, rakam, tire ve alt çizgi."""

SKILL_OVERRIDE_PREFIX = "skill_"
"""Skill başına aç/kapa override anahtarının öneki.

Araç adlarıyla çakışmaması için ayrı bir önek kullanılır; bir skill'in adı
`run_command` olsa bile anahtarı `skill_run_command` olur ve terminal
aracının override'ıyla karışmaz.

Bu tanım bilerek `models` içindedir: hem sağlayıcı hem yetenek kaydı aynı
öneki kullanır, ama `capabilities` modülünün `provider`'ı import etmesi
döngüsel bir import üretirdi. `models` yalnızca pydantic'e bağlıdır.
"""


def skill_override_key(slug: str) -> str:
    """Bir skill slug'ının override anahtarını döndürür."""

    return f"{SKILL_OVERRIDE_PREFIX}{slug}"


class SkillInfo(BaseModel):
    """Bir skill'in keşif sonrası, LLM'e ve arayüze sunulan görünümü."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str = Field(pattern=SKILL_NAME_PATTERN)
    """Skill'in ön yüzdeki adı (kararlı kimlik)."""

    description: str
    """Ne zaman ve ne için kullanılacağını anlatan kısa metin."""

    slug: str
    """Dosya sistemi ve override anahtarı için normalize edilmiş ad."""

    license: str = ""
    """SPDX kimliği ya da serbest lisans notu (ör. "MIT"). Boş olabilir."""

    source: str = ""
    """Skill'in geldiği depo (ör. "https://github.com/..."). Vendorlanan
    skill'lerde doludur; yerel skill'lerde boş kalır."""

    source_sha: str = ""
    """Vendorlanan skill'in kaynak commit SHA'sı (izlenebilirlik için)."""

    root: Path
    """Skill klasörünün çözülmüş mutlak yolu. Arayüze GİTMEZ."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Ön yüzdeki diğer alanlar (ör. `compatibility`, `metadata`)."""

    enabled: bool = True
    """Kullanıcı override'ına göre skill etkin mi."""


class Skill(BaseModel):
    """Çalışma zamanı skill nesnesi: görünüm + gövde + kök klasör."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    info: SkillInfo
    body: str
    """SKILL.md'nin ön yüzden sonraki gövdesi (Markdown)."""

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def slug(self) -> str:
        return self.info.slug

    @property
    def root(self) -> Path:
        return self.info.root
