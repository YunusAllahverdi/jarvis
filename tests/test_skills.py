"""Agent Skills (SKILL.md) — ön yüz, keşif, araçlar ve güvenlik sınırları.

Kapsam:
 1.  Geçerli ön yüz ayrıştırılır (name/description/opsiyonel alanlar)
 2.  Bozuk ön yüz (ayraçsız, bozuk YAML, eksik alan, eşleme değil) reddedilir
 3.  Keşif bozuk klasörü atlar, diğerlerini korur
 4.  Aynı adlı skill ikinci kökte sessizce ezilmez
 5.  load_skill gövdeyi döndürür; bilinmeyen ad hata verir
 6.  read_skill_file referans dosyayı okur
 7.  Path traversal (../, mutlak yol, bağlantı) engellenir
 8.  Skill başına enable/disable override kataloğu değiştirir
 9.  run_skill_script onay olmadan ÇALIŞMAZ (onay ister)
10.  run_skill_script onaylandığında skill klasöründe çalışır
11.  Skill çıktısı untrusted olarak işaretlenir
12.  İlerici açıklama: prompt'a yalnızca ad + açıklama girer, gövde girmez
13.  Vendorlanan skill'ler (parça 2'de 4, bu turda 43 daha) keşfedilir ve
     yüklenebilir; her birinin lisansı, kaynağı ve SHA'sı doğrulanır
14.  Sağlayıcı sağlık kontrolü istisna fırlatmaz
15.  Uçlar: skill listesi ve override (enable/disable)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.config.settings import Settings
from app.core.chat import ToolCall
from app.security.audit import AuditAction, InMemoryAuditLog
from app.security.commands import CommandPolicy
from app.security.permissions import (
    PermissionDecision,
    ToolOverride,
    ToolPermissionPolicy,
)
from app.security.tool_overrides import ToolOverrideStore
from app.skills.discovery import SkillDiscoveryError, discover_skills
from app.skills.frontmatter import FrontmatterError, parse_frontmatter
from app.skills.models import skill_override_key
from app.skills.prompt import build_skills_section
from app.skills.provider import SKILLS_PROVIDER_ID, SkillProvider
from app.skills.tools import (
    LoadSkillTool,
    ReadSkillFileTool,
    RunSkillScriptTool,
    SkillCatalog,
    SkillNotFoundError,
    SkillPathError,
)
from app.tools.base import PermissionLevel, Tool
from app.tools.capabilities import CapabilityRegistry
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

# Parça 2'de vendorlanan ilk dört skill (tek klasörlük).
VENDORED_SKILLS = ("anatomy", "answer-me-with-html", "geo-sleuth", "holmes")

# "Daha fazla skill" turunda vendorlanan paketler. Paketler tek tek skill
# klasörlerine DÜZLEŞTİRİLEREK eklendi; oil-ui ise kendi kök-göreli
# referansları olduğu için bütün klasör olarak korundu.
VENDORED_PACK_SKILLS = (
    # t3dotgg/tstack
    "babysit-pr",
    "council",
    "file-pr",
    "full-send",
    "full-stop",
    "leaving-pr-comments",
    "modernize",
    "sol-loop",
    "takeover",
    # Jakeschincariol/founder-skill
    "founder-board",
    "founder-brand",
    "founder-cfo",
    "founder-competitors",
    "founder-consumer",
    "founder-launch",
    "founder-marketing",
    "founder-offer",
    "founder-ops",
    "founder-plan",
    "founder-pricing",
    # Jakeschincariol/replica-skill
    "replica-architect",
    "replica-backend",
    "replica-brand",
    "replica-build",
    "replica-deploy",
    "replica-design",
    "replica-diff",
    "replica-entrepreneur",
    "replica-launch",
    "replica-recon",
    "replica-test",
    # Jakeschincariol/youtube-agent-skill
    "yt-audit",
    "yt-chapters",
    "yt-comment",
    "yt-edit",
    "yt-package",
    "yt-plan",
    "yt-retention",
    "yt-script",
    "yt-seo",
    "yt-shorts",
    "yt-viral",
    # oil-oil/oil-ui
    "oil-ui",
)

ALL_VENDORED_SKILLS = VENDORED_SKILLS + VENDORED_PACK_SKILLS

# Her vendorlanan paketin beklenen kaynak deposu ve commit SHA'sı.
VENDORED_SOURCES = {
    "t3dotgg/tstack": "1085050f3baed1ac724caa4a8166145fb2ac88af",
    "Jakeschincariol/founder-skill": "fd9385b0cfe1b96bebce3898fbd506d73eff5a9d",
    "Jakeschincariol/replica-skill": "77c9436fb3d18c3d58169efb8caf4fe906b0dc51",
    "Jakeschincariol/youtube-agent-skill": "a2feb2104981a375ffd4f87ee04f4f5344ac43c6",
    "oil-oil/oil-ui": "e3334bd5f6e700d21ac275b169ceee6495db9391",
}


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _settings(**kwargs: object) -> Settings:
    defaults: dict[str, object] = dict(
        app_name="T", app_version="t", environment="test", ollama_model="x"
    )
    defaults.update(kwargs)
    return Settings(**defaults)  # type: ignore[arg-type]


def _write_skill(
    root: Path,
    name: str,
    *,
    frontmatter: str | None = None,
    body: str = "# Gövde\n\nTalimatlar.",
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Bir skill klasörü kurar. `frontmatter=None` geçilirse geçerli bir blok yazılır."""

    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    if frontmatter is None:
        frontmatter = f"---\nname: {name}\ndescription: {name} açıklaması\n---\n"
    (directory / "SKILL.md").write_text(frontmatter + body, encoding="utf-8")
    for relative, content in (extra_files or {}).items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return directory


# ---------------------------------------------------------------------------
# 1-2. Ön yüz ayrıştırma
# ---------------------------------------------------------------------------


class TestFrontmatterParsing:
    def test_valid_frontmatter_is_split(self) -> None:
        text = "---\nname: ornek\ndescription: Bir örnek\nlicense: MIT\n---\nGövde burada.\n"
        metadata, body = parse_frontmatter(text)

        assert metadata["name"] == "ornek"
        assert metadata["description"] == "Bir örnek"
        assert metadata["license"] == "MIT"
        assert body.strip() == "Gövde burada."

    def test_bom_and_crlf_are_tolerated(self) -> None:
        text = "\ufeff---\r\nname: ornek\r\ndescription: x\r\n---\r\nGövde"
        metadata, body = parse_frontmatter(text)

        assert metadata["name"] == "ornek"
        assert "Gövde" in body

    @pytest.mark.parametrize(
        "text",
        [
            "name: ornek\ndescription: x\n",  # ayraç yok
            "---\nname: ornek\ndescription: x\n",  # kapanış ayracı yok
            "---\nname: [a, b\ndescription: x\n---\n",  # bozuk YAML
            "---\n---\n",  # boş ön yüz
            "---\n- a\n- b\n---\n",  # eşleme değil, liste
            "--- foo\nname: x\n---\n",  # ayraç kendi satırında değil
        ],
    )
    def test_broken_frontmatter_raises(self, text: str) -> None:
        with pytest.raises(FrontmatterError):
            parse_frontmatter(text)


# ---------------------------------------------------------------------------
# 3-4. Keşif
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_valid_skills_are_discovered(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "bir")
        _write_skill(tmp_path, "iki")

        names = {skill.name for skill in discover_skills([tmp_path])}
        assert names == {"bir", "iki"}

    def test_broken_skill_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "saglam")
        _write_skill(tmp_path, "bozuk", frontmatter="name: bozuk\n")  # ayraçsız
        _write_skill(tmp_path, "eksik", frontmatter="---\nname: eksik\n---\n")  # description yok

        skills = discover_skills([tmp_path])

        assert {skill.name for skill in skills} == {"saglam"}

    def test_missing_root_is_not_an_error(self, tmp_path: Path) -> None:
        assert discover_skills([tmp_path / "yok"]) == []

    def test_non_directory_root_is_an_error(self, tmp_path: Path) -> None:
        file_path = tmp_path / "dosya"
        file_path.write_text("x", encoding="utf-8")
        with pytest.raises(SkillDiscoveryError):
            discover_skills([file_path])

    def test_duplicate_name_keeps_first(self, tmp_path: Path) -> None:
        first = tmp_path / "a"
        second = tmp_path / "b"
        _write_skill(first, "ayni")
        _write_skill(second, "ayni")

        skills = discover_skills([first, second])

        assert len(skills) == 1
        assert skills[0].root == (first / "ayni").resolve()

    def test_provenance_sidecar_is_read(self, tmp_path: Path) -> None:
        directory = _write_skill(tmp_path, "vendor")
        (directory / ".skill-source.json").write_text(
            '{"source": "https://example.com/x", "source_sha": "abc123", "license": "MIT"}',
            encoding="utf-8",
        )

        skill = discover_skills([tmp_path])[0]

        assert skill.info.source == "https://example.com/x"
        assert skill.info.source_sha == "abc123"
        assert skill.info.license == "MIT"

    def test_invalid_sidecar_is_ignored(self, tmp_path: Path) -> None:
        directory = _write_skill(tmp_path, "vendor")
        (directory / ".skill-source.json").write_text("{bozuk json", encoding="utf-8")

        skill = discover_skills([tmp_path])[0]
        assert skill.info.source == ""


# ---------------------------------------------------------------------------
# 5-7. Araçlar
# ---------------------------------------------------------------------------


def _catalog_from(tmp_path: Path) -> SkillCatalog:
    return SkillCatalog(discover_skills([tmp_path]))


class TestLoadSkillTool:
    def test_returns_body(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "ornek", body="# Talimat\nAdım 1.")
        tool = LoadSkillTool(catalog=_catalog_from(tmp_path))

        result = _run(tool.execute(tool.input_model(name="ornek")))

        assert result["skill"] == "ornek"
        assert "Adım 1." in result["content"]

    def test_unknown_skill_raises(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "ornek")
        tool = LoadSkillTool(catalog=_catalog_from(tmp_path))

        with pytest.raises(SkillNotFoundError):
            _run(tool.execute(tool.input_model(name="yok")))

    def test_tool_is_read_permission_and_untrusted(self, tmp_path: Path) -> None:
        tool = LoadSkillTool(catalog=_catalog_from(tmp_path))
        assert tool.permission is PermissionLevel.READ
        assert tool.untrusted_output is True


class TestReadSkillFileTool:
    def test_reads_reference_file(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "ornek", extra_files={"references/not.md": "içerik"})
        tool = ReadSkillFileTool(catalog=_catalog_from(tmp_path))

        result = _run(tool.execute(tool.input_model(name="ornek", path="references/not.md")))

        assert result["content"] == "içerik"
        assert result["path"] == "references/not.md"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "ornek")
        tool = ReadSkillFileTool(catalog=_catalog_from(tmp_path))

        with pytest.raises(SkillPathError):
            _run(tool.execute(tool.input_model(name="ornek", path="yok.md")))


class TestPathTraversal:
    @pytest.mark.parametrize(
        "path",
        [
            "../gizli.txt",
            "../../etc/passwd",
            "references/../../SKILL.md",
            "/etc/passwd",
            "references/../../../gizli",
        ],
    )
    def test_traversal_is_blocked(self, tmp_path: Path, path: str) -> None:
        _write_skill(tmp_path, "ornek", extra_files={"references/ok.md": "x"})
        (tmp_path / "gizli.txt").write_text("sır", encoding="utf-8")
        tool = ReadSkillFileTool(catalog=_catalog_from(tmp_path))

        with pytest.raises(SkillPathError):
            _run(tool.execute(tool.input_model(name="ornek", path=path)))

    def test_symlink_out_of_root_is_blocked(self, tmp_path: Path) -> None:
        directory = _write_skill(tmp_path, "ornek")
        secret = tmp_path / "gizli.txt"
        secret.write_text("sır", encoding="utf-8")
        link = directory / "kacis.txt"
        try:
            link.symlink_to(secret)
        except OSError:
            pytest.skip("Sembolik bağlantı bu platformda kurulamadı.")

        tool = ReadSkillFileTool(catalog=_catalog_from(tmp_path))
        with pytest.raises(SkillPathError):
            _run(tool.execute(tool.input_model(name="ornek", path="kacis.txt")))


# ---------------------------------------------------------------------------
# 8. Sağlayıcı + override
# ---------------------------------------------------------------------------


def _provider(tmp_path: Path, **kwargs: Any) -> SkillProvider:
    return SkillProvider(
        settings=kwargs.pop("settings", _settings(skills_dirs=[str(tmp_path)])),
        command_policy=kwargs.pop("command_policy", CommandPolicy(allowed_commands=("python",))),
        **kwargs,
    )


class TestSkillProviderOverride:
    def test_provider_id_and_tools(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "ornek")
        provider = _provider(tmp_path)

        assert provider.id == SKILLS_PROVIDER_ID
        tools = _run(provider.tools())
        assert {tool.name for tool in tools} == {
            "load_skill",
            "read_skill_file",
            "run_skill_script",
        }

    def test_skills_are_listed(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "bir")
        _write_skill(tmp_path, "iki")
        provider = _provider(tmp_path)

        assert {info.name for info in provider.skills()} == {"bir", "iki"}

    def test_disabled_skill_leaves_the_catalog(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "bir")
        _write_skill(tmp_path, "iki")
        store = ToolOverrideStore(":memory:")
        provider = _provider(tmp_path, override_store=store)

        store.set(ToolOverride(tool_name=skill_override_key("bir"), enabled=False))

        # Katalog (araçların gördüğü küme) kapalı skill'i içermez...
        catalog = SkillCatalog(provider.active_skills())
        assert {skill.name for skill in catalog.skills} == {"iki"}
        # ...ama arayüz listesi kapalı olarak gösterir.
        listed = {info.name: info.enabled for info in provider.skills()}
        assert listed == {"bir": False, "iki": True}

    def test_disabled_skill_cannot_be_loaded(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "bir")
        store = ToolOverrideStore(":memory:")
        provider = _provider(tmp_path, override_store=store)
        store.set(ToolOverride(tool_name=skill_override_key("bir"), enabled=False))

        catalog = SkillCatalog(provider.active_skills())
        with pytest.raises(SkillNotFoundError):
            catalog.get("bir")

    def test_skills_can_be_disabled_globally(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "bir")
        provider = _provider(tmp_path, settings=_settings(skills_enabled=False))

        assert provider.skills() == []
        assert provider.active_skills() == []

    def test_health_never_raises(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "bir")
        provider = _provider(tmp_path)

        health = _run(provider.health())
        assert health.ok is True
        assert health.tool_count == 1


# ---------------------------------------------------------------------------
# 9-11. Script çalıştırma — onay ve untrusted çıktı
# ---------------------------------------------------------------------------


def _script_provider(tmp_path: Path) -> tuple[SkillProvider, SkillCatalog]:
    _write_skill(
        tmp_path,
        "calistir",
        extra_files={"scripts/merhaba.py": "print('merhaba')\n"},
    )
    provider = _provider(tmp_path)
    catalog = SkillCatalog(provider.active_skills())
    return provider, catalog


class TestRunSkillScriptApproval:
    def test_script_does_not_run_without_approval(self, tmp_path: Path) -> None:
        _, catalog = _script_provider(tmp_path)
        tool = RunSkillScriptTool(
            catalog=catalog,
            command_policy=CommandPolicy(allowed_commands=("python",)),
        )
        # Terminal kapalıyken DANGEROUS onaya tabi DEĞİL, reddedilir.
        policy = ToolPermissionPolicy(
            allowed={PermissionLevel.READ},
            requires_approval={PermissionLevel.WRITE},
        )
        registry = ToolRegistry()
        registry.register(tool)
        executor = ToolExecutor(registry, policy=policy)

        result = _run(
            executor.execute(
                ToolCall(
                    name=tool.name, arguments={"name": "calistir", "path": "scripts/merhaba.py"}
                )
            )
        )

        assert result.success is False
        assert result.error_code == "permission_denied"

    def test_script_requires_approval_when_terminal_enabled(self, tmp_path: Path) -> None:
        _, catalog = _script_provider(tmp_path)
        tool = RunSkillScriptTool(
            catalog=catalog,
            command_policy=CommandPolicy(allowed_commands=("python",)),
        )
        policy = ToolPermissionPolicy(
            allowed={PermissionLevel.READ},
            requires_approval={PermissionLevel.WRITE, PermissionLevel.DANGEROUS},
        )
        registry = ToolRegistry()
        registry.register(tool)
        executor = ToolExecutor(registry, policy=policy)

        result = _run(
            executor.execute(
                ToolCall(
                    name=tool.name, arguments={"name": "calistir", "path": "scripts/merhaba.py"}
                )
            )
        )

        assert result.success is False
        assert result.requires_approval is True
        assert result.error_code == "approval_required"

    def test_approved_script_runs_in_skill_directory(self, tmp_path: Path) -> None:
        _, catalog = _script_provider(tmp_path)
        tool = RunSkillScriptTool(
            catalog=catalog,
            command_policy=CommandPolicy(allowed_commands=("python",)),
        )

        result = _run(tool.execute(tool.input_model(name="calistir", path="scripts/merhaba.py")))

        assert result["exit_code"] == 0
        assert "merhaba" in result["stdout"]

    def test_unsupported_script_type_is_refused(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "calistir", extra_files={"scripts/x.sh": "echo hi\n"})
        provider = _provider(tmp_path)
        catalog = SkillCatalog(provider.active_skills())
        tool = RunSkillScriptTool(
            catalog=catalog, command_policy=CommandPolicy(allowed_commands=("python",))
        )

        with pytest.raises(SkillPathError):
            _run(tool.execute(tool.input_model(name="calistir", path="scripts/x.sh")))

    def test_script_outside_skill_dir_is_refused(self, tmp_path: Path) -> None:
        _, catalog = _script_provider(tmp_path)
        tool = RunSkillScriptTool(
            catalog=catalog, command_policy=CommandPolicy(allowed_commands=("python",))
        )

        with pytest.raises(SkillPathError):
            _run(tool.execute(tool.input_model(name="calistir", path="../../evil.py")))

    def test_skill_tool_output_is_untrusted(self, tmp_path: Path) -> None:
        _, catalog = _script_provider(tmp_path)
        load = LoadSkillTool(catalog=catalog)
        registry = ToolRegistry()
        registry.register(load)
        executor = ToolExecutor(
            registry, policy=ToolPermissionPolicy(allowed={PermissionLevel.READ})
        )

        result = _run(executor.execute(ToolCall(name=load.name, arguments={"name": "calistir"})))

        assert result.success is True
        assert result.data is not None
        assert result.data.get("untrusted") is True


# ---------------------------------------------------------------------------
# 12. İlerici açıklama
# ---------------------------------------------------------------------------


class TestProgressiveDisclosure:
    def test_section_contains_names_and_descriptions_only(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "ornek", body="# GİZLİ GÖVDE\nÇok gizli talimat.")
        provider = _provider(tmp_path)

        section = build_skills_section(provider.skills())

        assert section is not None
        assert "ornek" in section
        assert "GİZLİ GÖVDE" not in section
        assert "Çok gizli talimat" not in section

    def test_section_is_none_when_no_active_skill(self, tmp_path: Path) -> None:
        provider = _provider(tmp_path)
        assert build_skills_section(provider.skills()) is None

    def test_disabled_skill_is_not_in_the_prompt(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "bir")
        store = ToolOverrideStore(":memory:")
        provider = _provider(tmp_path, override_store=store)
        store.set(ToolOverride(tool_name=skill_override_key("bir"), enabled=False))

        assert build_skills_section(provider.skills()) is None


# ---------------------------------------------------------------------------
# 13. Vendorlanan skill'ler
# ---------------------------------------------------------------------------


class TestVendoredSkills:
    @pytest.mark.skipif(not SKILLS_DIR.is_dir(), reason="skills/ klasörü yok")
    def test_all_vendored_skills_are_discovered(self) -> None:
        discovered = {skill.name for skill in discover_skills([SKILLS_DIR])}
        assert set(VENDORED_SKILLS) <= discovered

    @pytest.mark.skipif(not SKILLS_DIR.is_dir(), reason="skills/ klasörü yok")
    @pytest.mark.parametrize("name", VENDORED_SKILLS)
    def test_vendored_skill_is_loadable_and_licensed(self, name: str) -> None:
        catalog = SkillCatalog(discover_skills([SKILLS_DIR]))
        tool = LoadSkillTool(catalog=catalog)

        result = _run(tool.execute(tool.input_model(name=name)))

        assert result["skill"] == name
        assert result["content"].strip()
        # Lisans ve kaynak SHA vendorlama sözleşmesinin parçasıdır.
        assert result["license"]
        skill = catalog.get(name)
        assert skill.info.source.startswith("https://github.com/")
        assert len(skill.info.source_sha) == 40
        assert (skill.root / "LICENSE").is_file()

    @pytest.mark.skipif(not SKILLS_DIR.is_dir(), reason="skills/ klasörü yok")
    def test_vendored_licenses_are_permissive(self) -> None:
        catalog = SkillCatalog(discover_skills([SKILLS_DIR]))
        for name in VENDORED_SKILLS:
            skill = catalog.get(name)
            assert skill.info.license.upper() in {
                "MIT",
                "APACHE-2.0",
                "BSD-3-CLAUSE",
                "BSD-2-CLAUSE",
            }

    @pytest.mark.skipif(not SKILLS_DIR.is_dir(), reason="skills/ klasörü yok")
    def test_all_pack_skills_are_discovered(self) -> None:
        """Paketlerden düzleştirilerek eklenen tüm skill'ler keşfedilmeli."""

        discovered = {skill.name for skill in discover_skills([SKILLS_DIR])}
        assert set(VENDORED_PACK_SKILLS) <= discovered

    @pytest.mark.skipif(not SKILLS_DIR.is_dir(), reason="skills/ klasörü yok")
    @pytest.mark.parametrize("name", VENDORED_PACK_SKILLS)
    def test_pack_skill_is_loadable_and_licensed(self, name: str) -> None:
        """Her yeni skill yüklenebilmeli; lisans + kaynak + SHA + LICENSE olmalı."""

        catalog = SkillCatalog(discover_skills([SKILLS_DIR]))
        tool = LoadSkillTool(catalog=catalog)

        result = _run(tool.execute(tool.input_model(name=name)))

        assert result["skill"] == name
        assert result["content"].strip()
        skill = catalog.get(name)
        assert skill.info.license.upper() in {"MIT", "APACHE-2.0", "BSD-3-CLAUSE", "BSD-2-CLAUSE"}
        assert skill.info.source.startswith("https://github.com/")
        assert len(skill.info.source_sha) == 40
        assert (skill.root / "LICENSE").is_file()

    @pytest.mark.skipif(not SKILLS_DIR.is_dir(), reason="skills/ klasörü yok")
    def test_pack_skill_provenance_matches_upstream(self) -> None:
        """Her yeni skill doğru kaynak depoya ve commit SHA'sına işaret etmeli."""

        catalog = SkillCatalog(discover_skills([SKILLS_DIR]))
        for name in VENDORED_PACK_SKILLS:
            skill = catalog.get(name)
            source = skill.info.source.removeprefix("https://github.com/")
            assert source in VENDORED_SOURCES, (name, source)
            assert skill.info.source_sha == VENDORED_SOURCES[source], name

    @pytest.mark.skipif(not SKILLS_DIR.is_dir(), reason="skills/ klasörü yok")
    def test_all_vendored_skills_have_unique_slugs(self) -> None:
        """Düzleştirme sonrası hiçbir iki skill aynı slug'ı paylaşmamalı."""

        skills = discover_skills([SKILLS_DIR])
        slugs = [skill.slug for skill in skills]
        assert len(slugs) == len(set(slugs))

    @pytest.mark.skipif(not SKILLS_DIR.is_dir(), reason="skills/ klasörü yok")
    def test_pack_skill_scripts_are_approved_only_types(self) -> None:
        """Vendorlanan skill script'leri yalnızca onaylı yorumlayıcı türlerinde olmalı.

        `run_skill_script` yalnızca `.py`, `.mjs`, `.js` çalıştırır. Paketlerde
        başka türde (ör. POSIX shell) bir script bulunursa bu bir GÜVENLİK
        değil, işlevsellik notudur: çalıştırılamaz. Bu test hangi türlerin
        geldiğini görünür kılar ve sessiz bir "çalışmıyor" durumunu engeller.
        """

        catalog = SkillCatalog(discover_skills([SKILLS_DIR]))
        supported = {".py", ".mjs", ".js"}
        unexpected: list[str] = []
        for name in VENDORED_PACK_SKILLS:
            root = catalog.get(name).root
            scripts_dir = root / "scripts"
            if not scripts_dir.is_dir():
                continue
            unexpected.extend(
                f"{name}/{path.relative_to(root)}"
                for path in scripts_dir.rglob("*")
                if path.is_file() and path.suffix.lower() not in supported
            )
        # Bilinen istisnalar: tstack/babysit-pr'deki POSIX shell script'i ve
        # oil-ui'nin kendi `check_update.sh` yardımcısı. İkisi de `run_skill_script`
        # ile ÇALIŞTIRILAMAZ; bu bilinçli bir işlevsellik sınırıdır.
        assert set(unexpected) <= {
            "babysit-pr/scripts/pr-wait",
            "oil-ui/scripts/check_update.sh",
        }, unexpected

    @pytest.mark.skipif(not SKILLS_DIR.is_dir(), reason="skills/ klasörü yok")
    def test_pack_skill_reference_files_are_readable(self) -> None:
        """Bir paket skill'inin referans dosyası read_skill_file ile okunabilmeli."""

        catalog = SkillCatalog(discover_skills([SKILLS_DIR]))
        # founder-board'un referans dosyası vardır (lenses.md).
        tool = ReadSkillFileTool(catalog=catalog)
        registry = ToolRegistry()
        registry.register(tool)
        executor = ToolExecutor(
            registry, policy=ToolPermissionPolicy(allowed={PermissionLevel.READ})
        )

        result = _run(
            executor.execute(
                ToolCall(
                    name=tool.name,
                    arguments={"name": "founder-board", "path": "lenses.md"},
                )
            )
        )

        assert result.success is True
        assert result.data is not None
        assert str(result.data["content"]).strip()
        assert result.data.get("untrusted") is True


# ---------------------------------------------------------------------------
# 15. Uçlar
# ---------------------------------------------------------------------------


def _registry_with_skills(tmp_path: Path, store: ToolOverrideStore) -> CapabilityRegistry:
    _write_skill(tmp_path, "bir")
    _write_skill(tmp_path, "iki")
    settings = _settings(skills_dirs=[str(tmp_path)])
    provider = SkillProvider(
        settings=settings,
        command_policy=CommandPolicy(allowed_commands=("python",)),
        override_store=store,
    )
    registry = CapabilityRegistry(
        registry=ToolRegistry(),
        providers=[provider],
        settings=settings,
        override_store=store,
        policy=ToolPermissionPolicy(allowed={PermissionLevel.READ}),
    )
    registry.rebuild_sync()
    return registry


def _client(registry: CapabilityRegistry, store: ToolOverrideStore) -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes.capabilities import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.settings = _settings()
    app.state.capability_registry = registry
    app.state.tool_override_store = store
    app.state.audit_log = InMemoryAuditLog()
    return TestClient(app)


class TestSkillEndpoints:
    def test_admin_lists_skills_in_a_separate_group(self, tmp_path: Path) -> None:
        store = ToolOverrideStore(":memory:")
        client = _client(_registry_with_skills(tmp_path, store), store)

        body = client.get("/api/admin/capabilities").json()

        assert {s["name"] for s in body["skills"]} == {"bir", "iki"}
        # Skill'ler ayrı bir gruptadır; araç listesi skill KAYITLARINI değil,
        # yalnızca skill'leri kullanan üç aracı taşır.
        assert {t["name"] for t in body["tools"]} == {
            "load_skill",
            "read_skill_file",
            "run_skill_script",
        }

    def test_admin_can_disable_a_skill(self, tmp_path: Path) -> None:
        store = ToolOverrideStore(":memory:")
        client = _client(_registry_with_skills(tmp_path, store), store)

        response = client.put("/api/admin/capabilities/skills/bir", json={"enabled": False})

        assert response.status_code == 200
        assert response.json()["accepted"] is True
        after = client.get("/api/admin/capabilities").json()["skills"]
        state = {s["name"]: s["enabled"] for s in after}
        assert state == {"bir": False, "iki": True}

    def test_unknown_skill_override_is_404(self, tmp_path: Path) -> None:
        store = ToolOverrideStore(":memory:")
        client = _client(_registry_with_skills(tmp_path, store), store)

        response = client.put("/api/admin/capabilities/skills/yok", json={"enabled": False})

        assert response.status_code == 404

    def test_skill_override_is_audited(self, tmp_path: Path) -> None:
        store = ToolOverrideStore(":memory:")
        audit = InMemoryAuditLog()
        registry = _registry_with_skills(tmp_path, store)
        client = _client(registry, store)
        client.app.state.audit_log = audit

        client.put("/api/admin/capabilities/skills/bir", json={"enabled": False})

        assert audit.recent()[0].action is AuditAction.TOOL_OVERRIDE


# ---------------------------------------------------------------------------
# Sağlayıcı sözleşmesi (registry ile bütünleşme)
# ---------------------------------------------------------------------------


class TestProviderContract:
    def test_provider_skills_are_registered_as_tools(self, tmp_path: Path) -> None:
        store = ToolOverrideStore(":memory:")
        registry = _registry_with_skills(tmp_path, store)

        tool_names = {tool.name for tool in registry.registry.list_tools()}
        assert {"load_skill", "read_skill_file", "run_skill_script"} <= tool_names

    def test_snapshot_skills_match_provider(self, tmp_path: Path) -> None:
        store = ToolOverrideStore(":memory:")
        registry = _registry_with_skills(tmp_path, store)

        snapshot = _run(registry.describe())
        assert {s.slug for s in snapshot.skills} == {"bir", "iki"}
        assert all(s.override_key.startswith("skill_") for s in snapshot.skills)

    def test_skills_enabled_false_hides_skills(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "bir")
        store = ToolOverrideStore(":memory:")
        settings = _settings(skills_enabled=False, skills_dirs=[str(tmp_path)])
        provider = SkillProvider(
            settings=settings,
            command_policy=CommandPolicy(allowed_commands=("python",)),
            override_store=store,
        )
        registry = CapabilityRegistry(
            registry=ToolRegistry(),
            providers=[provider],
            settings=settings,
            override_store=store,
            policy=ToolPermissionPolicy(allowed={PermissionLevel.READ}),
        )
        registry.rebuild_sync()

        snapshot = _run(registry.describe())
        assert snapshot.skills == []


def test_skill_permission_decision_is_read_only(tmp_path: Path) -> None:
    """Skill araçlarının izin seviyeleri sabittir: okuma serbest, script onaylı."""

    catalog = SkillCatalog([])
    load: Tool[Any] = LoadSkillTool(catalog=catalog)
    run_tool: Tool[Any] = RunSkillScriptTool(
        catalog=catalog, command_policy=CommandPolicy(allowed_commands=("python",))
    )

    policy = ToolPermissionPolicy(allowed={PermissionLevel.READ}, requires_approval=set())
    assert policy.decide(load.permission) is PermissionDecision.ALLOW
    assert policy.decide(run_tool.permission) is PermissionDecision.DENY


class TestEdgeCases:
    def test_empty_path_is_refused(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "ornek")
        tool = ReadSkillFileTool(catalog=_catalog_from(tmp_path))

        with pytest.raises(SkillPathError):
            _run(tool.execute(tool.input_model(name="ornek", path="   ")))

    def test_backslash_path_is_normalized(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "ornek", extra_files={"references/not.md": "içerik"})
        tool = ReadSkillFileTool(catalog=_catalog_from(tmp_path))

        result = _run(tool.execute(tool.input_model(name="ornek", path="references\\not.md")))

        assert result["content"] == "içerik"

    def test_unreadable_reference_is_an_error(self, tmp_path: Path) -> None:
        import os

        if os.geteuid() == 0:  # pragma: no cover - root izinleri yok sayar
            pytest.skip("root kullanıcısı chmod ile okumayı engelleyemez.")
        directory = _write_skill(tmp_path, "ornek", extra_files={"references/x.md": "x"})
        target = directory / "references" / "x.md"
        target.chmod(0o000)
        tool = ReadSkillFileTool(catalog=_catalog_from(tmp_path))
        try:
            with pytest.raises(SkillPathError):
                _run(tool.execute(tool.input_model(name="ornek", path="references/x.md")))
        finally:
            target.chmod(0o644)

    def test_missing_script_is_an_error(self, tmp_path: Path) -> None:
        provider = _provider(tmp_path)
        _write_skill(tmp_path, "calistir")
        catalog = SkillCatalog(provider.active_skills())
        tool = RunSkillScriptTool(
            catalog=catalog, command_policy=CommandPolicy(allowed_commands=("python",))
        )

        with pytest.raises(SkillPathError):
            _run(tool.execute(tool.input_model(name="calistir", path="scripts/yok.py")))

    def test_catalog_len_and_bool(self, tmp_path: Path) -> None:
        empty = SkillCatalog([])
        assert not empty
        assert len(empty) == 0

        _write_skill(tmp_path, "bir")
        full = _catalog_from(tmp_path)
        assert full
        assert len(full) == 1

    def test_catalog_accepts_slug(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "ornek")
        catalog = _catalog_from(tmp_path)

        # Slug ve ad aynı skill'e çözülür.
        assert catalog.get("ornek").name == catalog.get("ornek").slug

    def test_non_mapping_sidecar_is_ignored(self, tmp_path: Path) -> None:
        directory = _write_skill(tmp_path, "vendor")
        (directory / ".skill-source.json").write_text("[1, 2, 3]", encoding="utf-8")

        skill = discover_skills([tmp_path])[0]
        assert skill.info.source == ""

    def test_non_string_frontmatter_value_is_dropped(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "sayili",
            frontmatter="---\nname: sayili\ndescription: 42\nlicense:\n  - MIT\n---\n",
        )

        skill = discover_skills([tmp_path])[0]

        # Sayısal `description` stringe çevrilir; sözlük/liste lisans boş kalır.
        assert skill.info.description == "42"
        assert skill.info.license == ""

    def test_extra_frontmatter_fields_are_kept_as_metadata(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "meta",
            frontmatter="---\nname: meta\ndescription: x\ncompatibility: Claude Code\n---\n",
        )

        skill = discover_skills([tmp_path])[0]
        assert skill.info.metadata.get("compatibility") == "Claude Code"

    def test_slugify_falls_back_for_symbolic_names(self) -> None:
        from app.skills.discovery import _slugify

        assert _slugify("...") == "skill"
        assert _slugify("A B") == "a-b"

    def test_script_policy_error_is_wrapped_as_execution_error(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "calistir", extra_files={"scripts/x.py": "print(1)\n"})
        provider = _provider(tmp_path)
        catalog = SkillCatalog(provider.active_skills())
        # `python` tanınmıyor: politika reddeder, araç bunu yapılandırılmış
        # hataya çevirir (çıplak istisna sızmaz).
        tool = RunSkillScriptTool(
            catalog=catalog, command_policy=CommandPolicy(allowed_commands=("node",))
        )

        with pytest.raises(Exception) as excinfo:
            _run(tool.execute(tool.input_model(name="calistir", path="scripts/x.py")))

        assert type(excinfo.value).__name__ in {"ToolExecutionError", "CommandNotAllowedError"}
