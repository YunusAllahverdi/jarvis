"""Proje özeti tool'u — project_overview.

Kapsam:
 1. Dil dağılımı dosya uzantılarından çıkarılır
 2. pyproject.toml adı ve bağımlılıkları okunur
 3. package.json adı ve bağımlılıkları okunur
 4. Giriş noktaları bulunur
 5. Üst düzey yapı dosya sayılarıyla verilir
 6. Gürültülü dizinler sayıma girmez
 7. Kapalı dosyalar özette HİÇ görünmez
 8. Bozuk manifest özeti düşürmez
 9. Kök dışı reddedilir
10. Araç READ izinlidir ve okuma kümesinde kayıtlıdır
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.security.paths import PathGuard
from app.tools.base import PermissionLevel, ToolExecutionError
from app.tools.builtin.project import ProjectOverviewTool


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / "app" / "servis.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.ts").write_text("export {}\n", encoding="utf-8")

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "jarvis-test"\ndependencies = ["fastapi>=0.115", "httpx"]\n',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"name": "web", "dependencies": {"react": "^19.0.0"}}', encoding="utf-8"
    )
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (tmp_path / ".env").write_text("JARVIS_API_KEY=gizli\n", encoding="utf-8")

    noisy = tmp_path / "node_modules" / "paket"
    noisy.mkdir(parents=True)
    (noisy / "index.js").write_text("module.exports = {}\n", encoding="utf-8")

    return tmp_path


@pytest.fixture()
def tool(project: Path) -> ProjectOverviewTool:
    return ProjectOverviewTool(guard=PathGuard(project))


def _overview(tool: ProjectOverviewTool) -> dict:
    return _run(tool.execute(tool.input_model()))


# ---------------------------------------------------------------------------
# 1-5. Özetin içeriği
# ---------------------------------------------------------------------------

def test_languages_are_derived_from_the_files(tool: ProjectOverviewTool) -> None:
    """Dil dağılımı dosyalardan çıkarılmalı."""
    languages = {entry["name"]: entry["files"] for entry in _overview(tool)["languages"]}

    assert languages["Python"] == 2
    assert languages["TypeScript"] == 1


def test_python_manifest_is_read(tool: ProjectOverviewTool) -> None:
    """pyproject.toml adı ve bağımlılıkları taşımalı."""
    manifests = {entry["file"]: entry for entry in _overview(tool)["manifests"]}

    assert manifests["pyproject.toml"]["name"] == "jarvis-test"
    assert "httpx" in manifests["pyproject.toml"]["dependencies"]


def test_node_manifest_is_read(tool: ProjectOverviewTool) -> None:
    """package.json adı ve bağımlılıkları taşımalı."""
    manifests = {entry["file"]: entry for entry in _overview(tool)["manifests"]}

    assert manifests["package.json"]["name"] == "web"
    assert manifests["package.json"]["dependencies"] == ["react"]


def test_entry_points_are_found(tool: ProjectOverviewTool) -> None:
    """Bilinen giriş noktaları listelenmeli."""
    entry_points = _overview(tool)["entry_points"]

    assert "app/main.py" in entry_points
    assert "Dockerfile" in entry_points


def test_structure_reports_top_level_folders(tool: ProjectOverviewTool) -> None:
    """Üst düzey klasörler dosya sayılarıyla verilmeli."""
    structure = {entry["path"]: entry["files"] for entry in _overview(tool)["structure"]}

    assert structure["app"] == 2
    assert structure["web"] == 1


# ---------------------------------------------------------------------------
# 6-9. Sınırlar ve dayanıklılık
# ---------------------------------------------------------------------------

def test_noisy_directories_are_not_counted(tool: ProjectOverviewTool) -> None:
    """node_modules özeti bozmamalı."""
    overview = _overview(tool)

    assert "node_modules" not in {entry["path"] for entry in overview["structure"]}
    languages = {entry["name"] for entry in overview["languages"]}
    assert "JavaScript" not in languages


def test_closed_files_are_invisible(tool: ProjectOverviewTool) -> None:
    """`.env` özette hiç görünmemeli.

    Bir özet, okunamayan bir dosyanın varlığını duyurmamalıdır.
    """
    overview = _overview(tool)

    assert ".env" not in overview["entry_points"]
    assert overview["file_count"] == 6, "gizli dosya sayıma girmemeliydi"


def test_a_broken_manifest_does_not_break_the_overview(project: Path) -> None:
    """Bozuk bir paket dosyası özetin tamamını düşürmemeli."""
    (project / "pyproject.toml").write_text("bu geçerli toml değil [[[", encoding="utf-8")
    tool = ProjectOverviewTool(guard=PathGuard(project))

    overview = _overview(tool)

    manifests = {entry["file"]: entry for entry in overview["manifests"]}
    assert manifests["pyproject.toml"]["name"] is None
    assert overview["languages"], "geri kalan özet üretilmeliydi"


def test_outside_the_root_is_refused(tool: ProjectOverviewTool) -> None:
    """Çalışma dizininin dışı özetlenememeli."""
    with pytest.raises(ToolExecutionError):
        _run(tool.execute(tool.input_model(path="../..")))


# ---------------------------------------------------------------------------
# 10. Sözleşme
# ---------------------------------------------------------------------------

def test_tool_is_read_only_and_registered(project: Path) -> None:
    """Okuma yeteneğinin parçası olmalı; yazma izni gerektirmemeli."""
    from app.tools.defaults import register_filesystem_tools
    from app.tools.registry import ToolRegistry

    assert ProjectOverviewTool(guard=PathGuard(project)).permission is PermissionLevel.READ

    registry = ToolRegistry()
    registered = register_filesystem_tools(registry, guard=PathGuard(project))
    assert "project_overview" in registered
