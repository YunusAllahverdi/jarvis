"""Değişikliklerin görünür olmasını sağlayan salt-okunur git tool'ları.

Bu araçlar `run_command`'dan geçmez ve `git` komut listesinde yer almaz.
Sebebi bilinçli: ham terminale git vermek, `git push` ile `git status`
arasında hiçbir ayrım bırakmaz. Buradaki araçlar argüman listesini kendileri
kurar; kullanıcıdan gelen tek şey bekçiden geçmiş bir yoldur ve o da ayrı
bir argüman olarak eklenir, komut metnine gömülmez.

İkisi de READ izinlidir: depoyu okurlar, değiştirmezler.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import Field

from app.security.paths import PathGuard, PathNotAllowedError
from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput

GIT_STATUS_TOOL_NAME = "git_status"
GIT_DIFF_TOOL_NAME = "git_diff"

MAX_GIT_OUTPUT_CHARS = 40_000
GIT_TIMEOUT_SECONDS = 30.0


async def _run_git(root: Path, arguments: list[str]) -> tuple[str, str, int]:
    """Sabit bir git argüman listesini çalıştırır.

    Argümanlar çağıranın metninden ayrıştırılmaz; her biri ayrı bir öğedir.
    Kabuk kullanılmaz, dolayısıyla bir yol adındaki boşluk ya da noktalı
    virgül komutu bölemez.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *arguments,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise ToolExecutionError("git bulunamadı.") from exc
    except OSError as exc:
        raise ToolExecutionError("git çalıştırılamadı.") from exc

    try:
        raw_out, raw_err = await asyncio.wait_for(
            process.communicate(), timeout=GIT_TIMEOUT_SECONDS
        )
    except TimeoutError:
        process.kill()
        raise ToolExecutionError("git zaman aşımına uğradı.") from None

    return (
        raw_out.decode("utf-8", errors="replace"),
        raw_err.decode("utf-8", errors="replace"),
        process.returncode or 0,
    )


def _require_repository(stderr: str, code: int) -> None:
    """Depo değilse anlaşılır bir hata verir."""

    if code != 0 and "not a git repository" in stderr.lower():
        raise ToolExecutionError("Çalışma dizini bir git deposu değil.")


def _clip(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_GIT_OUTPUT_CHARS:
        return text, False
    return text[:MAX_GIT_OUTPUT_CHARS], True


class GitStatusInput(ToolInput):
    """`git_status` tool'unun input'u — argüman almaz."""


class GitStatusTool(Tool[GitStatusInput]):
    """Çalışma dizinindeki değişiklikleri listeler."""

    name = GIT_STATUS_TOOL_NAME
    description = "Çalışma dizinindeki değiştirilmiş, eklenmiş ve silinmiş dosyaları listeler."
    permission = PermissionLevel.READ
    input_model = GitStatusInput

    def __init__(self, *, guard: PathGuard) -> None:
        self._guard = guard

    async def execute(self, tool_input: GitStatusInput) -> dict[str, Any]:
        stdout, stderr, code = await _run_git(
            self._guard.root, ["status", "--porcelain=v1", "--untracked-files=normal"]
        )
        _require_repository(stderr, code)
        if code != 0:
            raise ToolExecutionError("git status başarısız oldu.")

        entries: list[dict[str, str]] = []
        for line in stdout.splitlines():
            if len(line) < 4:
                continue
            entries.append({"state": line[:2].strip(), "path": line[3:]})

        return {"count": len(entries), "changes": entries, "clean": not entries}


class GitDiffInput(ToolInput):
    """`git_diff` tool'unun doğrulanmış input'u."""

    path: str | None = Field(default=None, max_length=1024)
    staged: bool = False


class GitDiffTool(Tool[GitDiffInput]):
    """Yapılmış değişikliklerin içeriğini gösterir."""

    name = GIT_DIFF_TOOL_NAME
    description = "Çalışma dizinindeki değişikliklerin satır satır farkını döndürür."
    permission = PermissionLevel.READ
    input_model = GitDiffInput

    def __init__(self, *, guard: PathGuard) -> None:
        self._guard = guard

    async def execute(self, tool_input: GitDiffInput) -> dict[str, Any]:
        arguments = ["diff"]
        if tool_input.staged:
            arguments.append("--staged")

        if tool_input.path:
            try:
                target = self._guard.resolve(tool_input.path)
            except PathNotAllowedError as exc:
                raise ToolExecutionError(str(exc)) from exc
            # `--` ayırıcısı olmadan, tire ile başlayan bir yol adı git
            # tarafından seçenek sanılabilirdi.
            arguments.extend(["--", str(target.relative_to(self._guard.root))])

        stdout, stderr, code = await _run_git(self._guard.root, arguments)
        _require_repository(stderr, code)
        if code not in (0, 1):
            raise ToolExecutionError("git diff başarısız oldu.")

        diff, truncated = _clip(stdout)
        return {
            "diff": diff,
            "has_changes": bool(stdout.strip()),
            "staged": tool_input.staged,
            "truncated": truncated,
        }
