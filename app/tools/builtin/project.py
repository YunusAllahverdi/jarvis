"""Bir kod tabanının yapısını çıkaran salt-okunur tool.

Amaç, ajanın "önce anla, sonra değiştir" ilkesini uygulayabilmesi için
gereken ilk bakışı sağlamaktır: hangi diller var, hangi paket dosyaları
projeyi tanımlıyor, giriş noktaları nerede, ağaç neye benziyor.

Özet DETERMİNİSTİKTİR — LLM çağrılmaz. Bir modelin kod tabanı hakkında
tahmin yürütmesi yerine, dosya sisteminden okunabilecek olguları toplar.
Yorum yapmak modelin işidir; bu araç ona güvenilir bir zemin verir.

Çıktı her boyutta sınırlıdır. Büyük bir depoda tam ağaç, modelin bağlamını
tek başına doldurabilirdi; kesilen her yer `truncated` ile bildirilir.
"""

from __future__ import annotations

import json
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import Field

from app.security.paths import PathGuard, PathNotAllowedError
from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput
from app.tools.builtin.filesystem import SKIPPED_DIRECTORIES

PROJECT_OVERVIEW_TOOL_NAME = "project_overview"

MAX_SCANNED_FILES = 20_000
MAX_TREE_ENTRIES = 200
MAX_DEPENDENCIES = 60

LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".css": "CSS",
    ".html": "HTML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".md": "Markdown",
}

ENTRY_POINT_NAMES: tuple[str, ...] = (
    "main.py",
    "app.py",
    "__main__.py",
    "manage.py",
    "index.ts",
    "index.js",
    "main.ts",
    "main.tsx",
    "main.go",
    "main.rs",
    "Dockerfile",
    "docker-compose.yml",
)


class ProjectOverviewInput(ToolInput):
    """`project_overview` tool'unun doğrulanmış input'u."""

    path: str = Field(default=".", min_length=1, max_length=1024)


class ProjectOverviewTool(Tool[ProjectOverviewInput]):
    """Kod tabanının dillerini, paket dosyalarını ve yapısını özetler."""

    name = PROJECT_OVERVIEW_TOOL_NAME
    description = (
        "Bir kod tabanının yapısını özetler: diller, paket dosyaları, "
        "bağımlılıklar, giriş noktaları ve üst düzey klasörler."
    )
    permission = PermissionLevel.READ
    input_model = ProjectOverviewInput

    def __init__(self, *, guard: PathGuard) -> None:
        self._guard = guard

    async def execute(self, tool_input: ProjectOverviewInput) -> dict[str, Any]:
        try:
            root = self._guard.resolve(tool_input.path)
        except PathNotAllowedError as exc:
            raise ToolExecutionError(str(exc)) from exc

        if not root.is_dir():
            raise ToolExecutionError("Klasör bulunamadı.")

        files, scan_truncated = self._collect_files(root)

        return {
            "path": root.relative_to(self._guard.root).as_posix() or ".",
            "file_count": len(files),
            "languages": _languages(files),
            "manifests": _manifests(root, files),
            "entry_points": _entry_points(root, files),
            "structure": _structure(root, files),
            "truncated": scan_truncated or len(files) > MAX_TREE_ENTRIES,
        }

    def _collect_files(self, root: Path) -> tuple[list[Path], bool]:
        """Ağacı gezer; kapalı ve gürültülü olanları atlar.

        Bekçinin kapattığı dosyalar sayıma bile girmez: bir özet, okunamayan
        bir dosyanın varlığını duyurmamalıdır.
        """
        collected: list[Path] = []
        for candidate in root.rglob("*"):
            if len(collected) >= MAX_SCANNED_FILES:
                return collected, True
            if not candidate.is_file():
                continue
            relative_parts = set(candidate.relative_to(root).parts)
            if SKIPPED_DIRECTORIES & relative_parts:
                continue
            if not self._guard.is_allowed(candidate):
                continue
            collected.append(candidate)
        return collected, False


def _languages(files: list[Path]) -> list[dict[str, Any]]:
    """Dosya uzantılarından dil dağılımını çıkarır."""

    counts: Counter[str] = Counter()
    for path in files:
        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if language:
            counts[language] += 1

    total = sum(counts.values()) or 1
    return [
        {"name": name, "files": count, "share": round(count / total, 3)}
        for name, count in counts.most_common(10)
    ]


def _manifests(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    """Projeyi tanımlayan paket dosyalarını okur.

    Yalnızca kökteki dosyalara bakılır: alt klasörlerdeki her `package.json`
    genellikle bir bağımlılığın kendi dosyasıdır ve projeyi tanımlamaz.
    """
    found: list[dict[str, Any]] = []

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        found.append(_read_pyproject(pyproject))

    package_json = root / "package.json"
    if package_json.is_file():
        found.append(_read_package_json(package_json))

    for name, kind in (("go.mod", "go"), ("Cargo.toml", "rust"), ("pom.xml", "java")):
        if (root / name).is_file():
            found.append({"file": name, "kind": kind, "name": None, "dependencies": []})

    return found


def _read_pyproject(path: Path) -> dict[str, Any]:
    """pyproject.toml'dan ad ve bağımlılıkları çıkarır; bozuksa boş döner."""

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        # Bozuk bir manifest, özetin tamamını düşürmemeli.
        return {"file": "pyproject.toml", "kind": "python", "name": None, "dependencies": []}

    project = data.get("project", {})
    dependencies = project.get("dependencies", []) or []
    return {
        "file": "pyproject.toml",
        "kind": "python",
        "name": project.get("name"),
        "dependencies": [str(item) for item in dependencies[:MAX_DEPENDENCIES]],
    }


def _read_package_json(path: Path) -> dict[str, Any]:
    """package.json'dan ad ve bağımlılıkları çıkarır; bozuksa boş döner."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"file": "package.json", "kind": "node", "name": None, "dependencies": []}

    dependencies = list((data.get("dependencies") or {}).keys())
    return {
        "file": "package.json",
        "kind": "node",
        "name": data.get("name"),
        "dependencies": dependencies[:MAX_DEPENDENCIES],
    }


def _entry_points(root: Path, files: list[Path]) -> list[str]:
    """Bilinen giriş noktası adlarını köke göreli olarak listeler."""

    return sorted(
        path.relative_to(root).as_posix()
        for path in files
        if path.name in ENTRY_POINT_NAMES
    )[:MAX_TREE_ENTRIES]


def _structure(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    """Üst düzey klasörleri, içerdikleri dosya sayısıyla listeler.

    Tam ağaç yerine bir seviye verilir: modelin nereye bakacağını seçmesi
    için yeter, bağlamı doldurmaz. Derinlik gerektiğinde `list_dir` var.
    """
    counts: Counter[str] = Counter()
    for path in files:
        parts = path.relative_to(root).parts
        counts[parts[0] if len(parts) > 1 else "."] += 1

    return [
        {"path": name, "files": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
            :MAX_TREE_ENTRIES
        ]
    ]
