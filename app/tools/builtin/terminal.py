"""Ajanın komut çalıştırmasını sağlayan tool.

`DANGEROUS` izinlidir ve uygulama politikasında yalnızca terminal açıkça
etkinleştirildiğinde onaya tabi olur; aksi hâlde reddedilir. Yani bu araç
kayıtlı olsa bile, kullanıcı hem terminali açmadan hem de her çağrıyı tek
tek onaylamadan hiçbir şey çalıştıramaz.

İki karar, listelerden daha önemlidir:

1. **Kabuk yoktur.** Komut argüman listesine ayrıştırılıp doğrudan
   çalıştırılır. Zincirleme ve yönlendirme engellenen değil, var olmayan
   şeylerdir.
2. **Ortam devralınmaz.** Alt sürece yalnızca çalışması için gereken birkaç
   değişken verilir. `os.environ` aktarılsaydı, `.env` okumasını
   engellemenin anlamı kalmazdı: çalışan program anahtarları ortamdan
   okurdu.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic import Field

from app.security.commands import CommandNotAllowedError, CommandPolicy
from app.security.paths import PathGuard
from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput

RUN_COMMAND_TOOL_NAME = "run_command"

MAX_OUTPUT_CHARS = 20_000
"""Çıktının modele taşınacak en fazla karakteri (akış başına)."""

DEFAULT_TIMEOUT_SECONDS = 60.0

_INHERITED_ENVIRONMENT_KEYS: tuple[str, ...] = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
)
"""Alt sürece geçirilen değişkenler.

Program bulunabilsin ve düzgün çalışabilsin diye gereken en küçük küme.
Anahtar taşıyan hiçbir değişken listede yoktur ve olmamalıdır.
"""


def _child_environment() -> dict[str, str]:
    """Alt süreç için asgari ortamı kurar."""

    environment = {
        key: os.environ[key] for key in _INHERITED_ENVIRONMENT_KEYS if key in os.environ
    }
    # Alt süreç Python ise çıktısı tamponlanmasın; zaman aşımında yarım
    # kalan bir çalıştırmadan da bir şey öğrenebilelim.
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def _clip(text: str) -> tuple[str, bool]:
    """Çıktıyı sınıra kırpar ve kırpılıp kırpılmadığını bildirir."""

    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS], True


class RunCommandInput(ToolInput):
    """`run_command` tool'unun doğrulanmış input'u."""

    command: str = Field(min_length=1, max_length=2000)
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0, le=600)


class RunCommandTool(Tool[RunCommandInput]):
    """Çalışma dizininde tanınan bir komutu çalıştırır."""

    name = RUN_COMMAND_TOOL_NAME
    description = (
        "Çalışma dizininde izin verilen bir programı çalıştırır ve çıktısını döndürür. "
        "Kabuk kullanılmaz; tek bir program çalıştırılabilir."
    )
    permission = PermissionLevel.DANGEROUS
    input_model = RunCommandInput

    def __init__(
        self,
        *,
        guard: PathGuard,
        command_policy: CommandPolicy,
        max_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """
        Args:
            guard: Çalışma dizinini belirleyen bekçi; komut orada çalışır.
            command_policy: Komutu doğrulayıp argüman listesine çeviren politika.
            max_timeout_seconds: Çağıranın isteyebileceği en uzun süre. Model
                kendi sınırını yükseltememelidir.
        """
        self._guard = guard
        self._command_policy = command_policy
        self._max_timeout = max_timeout_seconds

    async def execute(self, tool_input: RunCommandInput) -> dict[str, Any]:
        try:
            argv = self._command_policy.parse(tool_input.command)
        except CommandNotAllowedError as exc:
            raise ToolExecutionError(str(exc)) from exc

        timeout = min(tool_input.timeout_seconds, self._max_timeout)

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self._guard.root),
                env=_child_environment(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Girdi kapalı: etkileşim bekleyen bir program, kimse
                # cevaplamayacağı için süresiz beklerdi.
                stdin=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ToolExecutionError(f"'{argv[0]}' bulunamadı.") from exc
        except OSError as exc:
            raise ToolExecutionError("Komut başlatılamadı.") from exc

        timed_out = False
        try:
            raw_out, raw_err = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            timed_out = True
            raw_out, raw_err = await _terminate(process)

        stdout, out_clipped = _clip(raw_out.decode("utf-8", errors="replace"))
        stderr, err_clipped = _clip(raw_err.decode("utf-8", errors="replace"))

        return {
            "command": " ".join(argv),
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": out_clipped or err_clipped,
        }


async def _terminate(process: asyncio.subprocess.Process) -> tuple[bytes, bytes]:
    """Süresi dolan süreci sonlandırır ve o ana kadarki çıktısını toplar.

    Önce nazikçe sonlandırılır; kısa sürede kapanmazsa öldürülür. Zaman
    aşımına uğrayan bir sürecin arkada çalışmaya devam etmesi, zaman
    aşımının bir anlamının kalmaması demek olurdu.
    """
    process.terminate()
    try:
        return await asyncio.wait_for(process.communicate(), timeout=5)
    except TimeoutError:
        process.kill()
        try:
            return await process.communicate()
        except Exception:  # noqa: BLE001
            return b"", b""
