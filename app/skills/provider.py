"""Skill sağlayıcısı — keşfedilen skill'leri yetenek kaydına bağlar.

Bu sağlayıcı, Parça 1'deki `ToolProvider` sözleşmesini uygular: araçları
KENDİSİ bir registry'ye kaydetmez, yalnızca üretir. Kayıt ve çakışma denetimi
`CapabilityRegistry`'nin işidir.

İki katmanlı yetenek sunar:

1. **Üç araç** (`load_skill`, `read_skill_file`, `run_skill_script`) her zaman
   üretilir; skill'lerin kendisi bu araçların ARGÜMANI olarak seçilir.
2. **Skill kataloğu** (`skills()`) arayüzde ayrı bir grup olarak listelenir ve
   tek tek açılıp kapatılabilir.

Skill başına aç/kapa, mevcut `ToolOverrideStore` mekanizmasıyla yapılır:
anahtar `skill_<slug>` biçimindedir ve `enabled=False` olan skill'ler
katalogdan DÜŞER (araçlar yine var olur; katalog `get` çağrısı onları
çözemez).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from app.config.settings import Settings
from app.security.commands import CommandPolicy
from app.security.tool_overrides import ToolOverrideStore
from app.skills.discovery import discover_skills
from app.skills.models import (
    SKILL_OVERRIDE_PREFIX,
    Skill,
    SkillInfo,
    skill_override_key,
)
from app.skills.tools import (
    LoadSkillTool,
    ReadSkillFileTool,
    RunSkillScriptTool,
    SkillCatalog,
)
from app.tools.base import Tool
from app.tools.builtin.terminal import DEFAULT_TIMEOUT_SECONDS
from app.tools.providers import ProviderHealth

logger = logging.getLogger(__name__)

SKILLS_PROVIDER_ID = "skills"

__all__ = ["SKILLS_PROVIDER_ID", "SKILL_OVERRIDE_PREFIX", "SkillProvider", "skill_override_key"]


class SkillProvider:
    """`skills/` klasörlerindeki yetenekleri sağlayan `ToolProvider`."""

    id = SKILLS_PROVIDER_ID
    description = "Agent Skills (SKILL.md): keşfedilen yetenekler ve erişim araçları."

    def __init__(
        self,
        *,
        settings: Settings,
        command_policy: CommandPolicy,
        override_store: ToolOverrideStore | None = None,
        discover: Callable[[list[str | Path]], list[Skill]] | None = None,
        max_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """
        Args:
            settings: Etkinlik ve klasör yapılandırmasının kaynağı.
            command_policy: Script çalıştırmada kullanılacak komut politikası.
                Terminal ile AYNI politika verilmelidir; ayrı bir politika
                skill'ler için daha gevşek bir izin yolu açardı.
            override_store: Skill başına aç/kapa kararlarının deposu.
            discover: Keşif fonksiyonu (test için enjekte edilebilir).
            max_timeout_seconds: Script'lerin çalışabileceği en uzun süre.
        """
        self._settings = settings
        self._command_policy = command_policy
        self._override_store = override_store
        self._discover = discover or discover_skills
        self._max_timeout = max_timeout_seconds
        self._skills: list[Skill] = []

    def enabled(self, settings: Settings) -> bool:
        """Skill yeteneği bu yapılandırmada etkin mi?"""

        return settings.skills_enabled

    def _catalog(self) -> SkillCatalog:
        """Etkin skill'lerden bir katalog üretir."""

        return SkillCatalog(self.active_skills())

    def active_skills(self) -> list[Skill]:
        """Override'lara göre ETKİN skill'leri döndürür (kapatılanlar hariç)."""

        if not self._settings.skills_enabled:
            return []
        skills = self._discover(list(self._settings.skills_dirs))
        if self._override_store is None:
            return skills
        active: list[Skill] = []
        for skill in skills:
            override = self._override_store.get(skill_override_key(skill.slug))
            if override is not None and not override.enabled:
                continue
            active.append(skill)
        return active

    def skills(self) -> list[SkillInfo]:
        """Arayüze sunulacak skill görünümlerini döndürür.

        Kapalı skill'ler de `enabled=False` işaretiyle listelenir: kullanıcı
        neyin kapatıldığını görebilmelidir. Katalog (araçların çözdüğü küme)
        ise yalnızca ETKİN skill'leri içerir.
        """

        if not self._settings.skills_enabled:
            return []
        skills = self._discover(list(self._settings.skills_dirs))
        infos: list[SkillInfo] = []
        for skill in skills:
            enabled = True
            if self._override_store is not None:
                override = self._override_store.get(skill_override_key(skill.slug))
                if override is not None:
                    enabled = override.enabled
            infos.append(skill.info.model_copy(update={"enabled": enabled}))
        return infos

    async def tools(self) -> list[Tool]:
        """Üç skill aracını üretir (katalog her çağrıda tazelenir)."""

        return self._build_tools()

    def _build_tools(self) -> list[Tool]:
        """Skill araçlarını güncel katalogla üretir."""

        catalog = self._catalog()
        return [
            LoadSkillTool(catalog=catalog),
            ReadSkillFileTool(catalog=catalog),
            RunSkillScriptTool(
                catalog=catalog,
                command_policy=self._command_policy,
                max_timeout_seconds=self._max_timeout,
            ),
        ]

    def tools_sync(self) -> list[Tool]:
        """`tools()`'un senkron eşdeğeri — yalnızca uygulama başlangıcı için."""

        return self._build_tools()

    async def health(self) -> ProviderHealth:
        """Kaç skill keşfedildiğini bildirir; istisna fırlatmaz."""

        try:
            infos = self.skills()
        except Exception as exc:  # pragma: no cover - savunma katmanı
            return ProviderHealth(ok=False, detail=f"Skill'ler keşfedilemedi: {exc}")
        active = sum(1 for info in infos if info.enabled)
        return ProviderHealth(
            ok=True,
            detail=f"{active}/{len(infos)} skill etkin.",
            tool_count=active,
        )

    async def aclose(self) -> None:
        """Skill sağlayıcısı hiçbir kaynak tutmaz."""

        return None
