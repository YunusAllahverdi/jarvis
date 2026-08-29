"""Ajanın çalışma dizinini okumasını sağlayan tool'lar.

Üçü de salt okunurdur ve üçü de aynı `PathGuard`'dan geçer. Bekçi tek bir
örnek olarak enjekte edilir: üç araç aynı sınırı paylaşmalıdır, yoksa biri
sıkılaştırıldığında diğerleri açık kalabilirdi.

Dönen yollar her zaman köke GÖRELİDİR. Mutlak yol döndürmek, reddedilmiş
bir isteğin bile dosya sisteminin yapısını sızdırmasına yol açardı.

Bu araçlar varsayılan registry'ye otomatik eklenmez; yalnızca bir çalışma
kökü yapılandırıldığında kaydedilirler. Kök tanımlanmadan ajanın dosya
okuması diye bir şey yoktur.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import Field

from app.security.paths import PathGuard, PathNotAllowedError
from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput

READ_FILE_TOOL_NAME = "read_file"
LIST_DIR_TOOL_NAME = "list_dir"
GREP_TOOL_NAME = "grep"

MAX_READ_BYTES = 256 * 1024
"""Tek seferde okunacak en fazla bayt.

Bir dosya bundan büyükse tamamı okunmaz. Amaç belleği korumak değil,
modelin bağlamını tek bir dosyayla doldurmamaktır.
"""

MAX_LINES = 2000
MAX_DIR_ENTRIES = 500
MAX_GREP_MATCHES = 200
MAX_GREP_FILE_BYTES = 1024 * 1024

SKIPPED_DIRECTORIES: frozenset[str] = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".pytest_cache"}
)
"""Aramada atlanacak dizinler.

Güvenlik değil, kullanılabilirlik gerekçesi: gerçek bir depoda bunlar
sonuçları boğar ve aramayı işe yaramaz hâle getirir.
"""


def _relative(path: Path, guard: PathGuard) -> str:
    """Yolu köke göre göreli, platformdan bağımsız bir metne çevirir."""

    return path.relative_to(guard.root).as_posix() or "."


def _looks_binary(chunk: bytes) -> bool:
    """İçerikte NUL baytı varsa metin değildir."""

    return b"\x00" in chunk


class ReadFileInput(ToolInput):
    """`read_file` tool'unun doğrulanmış input'u."""

    path: str = Field(min_length=1, max_length=1024)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=MAX_LINES, ge=1, le=MAX_LINES)


class ReadFileTool(Tool[ReadFileInput]):
    """Çalışma dizinindeki bir metin dosyasını okur."""

    name = READ_FILE_TOOL_NAME
    description = (
        "Çalışma dizinindeki bir metin dosyasını okur. Satır aralığı verilebilir."
    )
    permission = PermissionLevel.READ
    input_model = ReadFileInput

    def __init__(self, *, guard: PathGuard) -> None:
        self._guard = guard

    async def execute(self, tool_input: ReadFileInput) -> dict[str, Any]:
        target = _resolve_or_fail(self._guard, tool_input.path)

        if not target.is_file():
            raise ToolExecutionError("Dosya bulunamadı.")

        try:
            raw = target.read_bytes()[: MAX_READ_BYTES + 1]
        except OSError as exc:
            raise ToolExecutionError("Dosya okunamadı.") from exc

        if _looks_binary(raw[:8192]):
            raise ToolExecutionError("Dosya metin değil (ikili içerik).")

        truncated_bytes = len(raw) > MAX_READ_BYTES
        text = raw[:MAX_READ_BYTES].decode("utf-8", errors="replace")

        lines = text.splitlines()
        window = lines[tool_input.offset : tool_input.offset + tool_input.limit]

        return {
            "path": _relative(target, self._guard),
            "content": "\n".join(window),
            "line_count": len(lines),
            "offset": tool_input.offset,
            "returned_lines": len(window),
            # Kesilme sessizce olmaz: model eksik veriyle tam sanarak
            # akıl yürütmesin.
            "truncated": truncated_bytes or (tool_input.offset + len(window)) < len(lines),
        }


class ListDirInput(ToolInput):
    """`list_dir` tool'unun doğrulanmış input'u."""

    path: str = Field(default=".", min_length=1, max_length=1024)


class ListDirTool(Tool[ListDirInput]):
    """Çalışma dizinindeki bir klasörün içeriğini listeler."""

    name = LIST_DIR_TOOL_NAME
    description = "Çalışma dizinindeki bir klasörün dosya ve alt klasörlerini listeler."
    permission = PermissionLevel.READ
    input_model = ListDirInput

    def __init__(self, *, guard: PathGuard) -> None:
        self._guard = guard

    async def execute(self, tool_input: ListDirInput) -> dict[str, Any]:
        target = _resolve_or_fail(self._guard, tool_input.path)

        if not target.is_dir():
            raise ToolExecutionError("Klasör bulunamadı.")

        entries: list[dict[str, Any]] = []
        try:
            children = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError as exc:
            raise ToolExecutionError("Klasör okunamadı.") from exc

        for child in children:
            # Bekçinin kapattığı girdi listede hiç görünmez. Adını göstermek,
            # okunamayan bir dosyanın varlığını duyurmak olurdu.
            if not self._guard.is_allowed(child):
                continue
            if len(entries) >= MAX_DIR_ENTRIES:
                break
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )

        return {
            "path": _relative(target, self._guard),
            "count": len(entries),
            "entries": entries,
            "truncated": len(children) > MAX_DIR_ENTRIES,
        }


class GrepInput(ToolInput):
    """`grep` tool'unun doğrulanmış input'u."""

    pattern: str = Field(min_length=1, max_length=500)
    path: str = Field(default=".", min_length=1, max_length=1024)
    glob: str = Field(default="*", min_length=1, max_length=100)
    limit: int = Field(default=50, ge=1, le=MAX_GREP_MATCHES)


class GrepTool(Tool[GrepInput]):
    """Çalışma dizininde düzenli ifadeyle arama yapar."""

    name = GREP_TOOL_NAME
    description = "Çalışma dizinindeki metin dosyalarında düzenli ifadeyle arama yapar."
    permission = PermissionLevel.READ
    input_model = GrepInput

    def __init__(self, *, guard: PathGuard) -> None:
        self._guard = guard

    async def execute(self, tool_input: GrepInput) -> dict[str, Any]:
        root = _resolve_or_fail(self._guard, tool_input.path)

        try:
            expression = re.compile(tool_input.pattern)
        except re.error as exc:
            raise ToolExecutionError("Düzenli ifade geçersiz.") from exc

        matches: list[dict[str, Any]] = []
        for candidate in self._candidates(root, tool_input.glob):
            if len(matches) >= tool_input.limit:
                break
            matches.extend(self._search(candidate, expression, tool_input.limit - len(matches)))

        return {
            "pattern": tool_input.pattern,
            "count": len(matches),
            "matches": matches,
            "truncated": len(matches) >= tool_input.limit,
        }

    def _candidates(self, root: Path, glob: str):
        """Aranacak dosyaları üretir; kapalı ve gürültülü olanları atlar."""

        if root.is_file():
            yield root
            return
        for candidate in sorted(root.rglob(glob)):
            if not candidate.is_file():
                continue
            if SKIPPED_DIRECTORIES & set(candidate.relative_to(root).parts):
                continue
            if not self._guard.is_allowed(candidate):
                continue
            yield candidate

    def _search(self, path: Path, expression: re.Pattern[str], remaining: int) -> list[dict[str, Any]]:
        """Tek bir dosyada eşleşmeleri toplar; okunamayan dosya sessizce atlanır."""

        try:
            raw = path.read_bytes()[:MAX_GREP_FILE_BYTES]
        except OSError:
            return []
        if _looks_binary(raw[:8192]):
            return []

        found: list[dict[str, Any]] = []
        for number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), start=1):
            if len(found) >= remaining:
                break
            if expression.search(line):
                found.append(
                    {
                        "path": _relative(path, self._guard),
                        "line": number,
                        # Uzun satır bağlamı doldurmasın; eşleşmeyi göstermek yeter.
                        "text": line[:300],
                    }
                )
        return found


def _resolve_or_fail(guard: PathGuard, path: str) -> Path:
    """Yolu bekçiden geçirir ve reddi araç hatasına çevirir.

    Bekçinin mesajı olduğu gibi taşınır: hangi kurala takıldığını söyler,
    çözülmüş yolu söylemez.
    """
    try:
        return guard.resolve(path)
    except PathNotAllowedError as exc:
        raise ToolExecutionError(str(exc)) from exc
