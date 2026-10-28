"""Agent Skills (SKILL.md) desteği — keşif, ön yüz (frontmatter) ve araçlar.

Bir "skill", agentskills.io spesifikasyonuna göre YAML ön yüzü taşıyan bir
`SKILL.md` dosyası ve yanındaki referans/script dosyalarından oluşan bir
klasördür. Bu paket onu Jarvis'in yetenek kaydına BAĞLAR:

- `discovery` klasörleri tarar ve bozuk olanları atlar,
- `SkillProvider` üç aracı (`load_skill`, `read_skill_file`,
  `run_skill_script`) yetenek kaydına sunar,
- ilerici açıklama (progressive disclosure) sistem prompt'una yalnızca ad ve
  açıklama koyar; gövde yalnızca `load_skill` çağrıldığında modele gelir.

GÜVENLİK: bir skill'in gövdesi ve referans dosyaları GÜVENİLMEZ veridir.
Araçlar çıktılarını `untrusted_output` olarak işaretler ve script çalıştırma
YALNIZCA mevcut onay gerektiren terminal yolundan geçer — bu paket yeni bir
izin yolu AÇMAZ.
"""

from app.skills.discovery import SkillDiscoveryError, discover_skills
from app.skills.frontmatter import FrontmatterError, parse_frontmatter
from app.skills.models import Skill, SkillInfo
from app.skills.provider import SKILLS_PROVIDER_ID, SkillProvider
from app.skills.tools import (
    LoadSkillTool,
    ReadSkillFileTool,
    RunSkillScriptTool,
    SkillCatalog,
)

__all__ = [
    "SKILLS_PROVIDER_ID",
    "FrontmatterError",
    "LoadSkillTool",
    "ReadSkillFileTool",
    "RunSkillScriptTool",
    "Skill",
    "SkillCatalog",
    "SkillDiscoveryError",
    "SkillInfo",
    "SkillProvider",
    "discover_skills",
    "parse_frontmatter",
]
