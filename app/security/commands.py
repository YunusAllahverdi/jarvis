"""Hangi komutun çalıştırılabileceğine karar veren politika.

Buradaki asıl savunma bir liste değil, bir yapı kararıdır: komut **kabuk
olmadan** çalıştırılır. Kabuk yoksa `;`, `&&`, `|`, backtick, yönlendirme ve
glob genişletme diye bir şey de yoktur — zincirleme komut çalıştırmak
engellenen bir şey değil, mümkün olmayan bir şey hâline gelir.

Listeler bunun üstüne gelir: yalnızca adı açıkça tanınan çalıştırılabilirler
kabul edilir. Varsayılan küme inceleme ve test araçlarıyla sınırlıdır;
`git` bilerek dışarıdadır, çünkü sürüm kontrolü kendi araçlarını ve geri
alma mekanizmasını hak eder, ham terminal üzerinden yapılmamalıdır.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Sequence

MAX_COMMAND_LENGTH = 2000
MAX_ARGUMENT_COUNT = 60

SHELL_METACHARACTERS: tuple[str, ...] = (";", "&", "|", "`", ">", "<", "\n", "\r", "$(")
"""Kabuk denetimi anlamına gelen diziler.

Kabuk zaten kullanılmıyor, dolayısıyla bunlar çalışmazdı. Yine de
reddedilirler: böyle bir komut ya yanlış anlaşılmış bir niyettir ya da
kasıtlı bir denemedir; ikisi de sessizce yarım çalıştırılmamalıdır.
"""

DEFAULT_ALLOWED_COMMANDS: tuple[str, ...] = (
    "python",
    "python3",
    "pytest",
    "ruff",
    "mypy",
    "node",
    "npm",
    "npx",
    "tsc",
)
"""Terminal açıldığında tanınan çalıştırılabilirler.

İnceleme ve test araçlarıyla sınırlıdır: ajanın kendi değişikliğini
doğrulaması için gereken en küçük kümedir.
"""


class CommandNotAllowedError(PermissionError):
    """Komut politikadan geçemedi.

    Mesaj gerekçeyi söyler ama tanınan komutların listesini vermez:
    reddedilen bir deneme, izin haritasını çıkarmaya yaramamalıdır.
    """


class CommandPolicy:
    """Bir komut metnini güvenli bir argüman listesine çevirir ya da reddeder."""

    def __init__(
        self,
        *,
        allowed_commands: Iterable[str] = DEFAULT_ALLOWED_COMMANDS,
    ) -> None:
        """
        Args:
            allowed_commands: Çalıştırılmasına izin verilen program adları.
                Boş bırakılırsa hiçbir komut çalışmaz.
        """
        self._allowed = frozenset(name.lower() for name in allowed_commands)

    @property
    def allowed_commands(self) -> frozenset[str]:
        """Tanınan program adları."""

        return self._allowed

    def parse(self, command: str) -> Sequence[str]:
        """Komutu doğrular ve çalıştırılacak argüman listesini döndürür.

        Dönen liste doğrudan `subprocess`'e verilmek üzeredir; çağıran ham
        metni kullanmamalıdır, yoksa doğrulanan ile çalıştırılan ayrışır.

        Raises:
            CommandNotAllowedError: Komut boşsa, çok uzunsa, kabuk denetimi
                içeriyorsa, ayrıştırılamıyorsa veya programı tanınmıyorsa.
        """
        text = command.strip()
        if not text:
            raise CommandNotAllowedError("Komut boş.")
        if len(text) > MAX_COMMAND_LENGTH:
            raise CommandNotAllowedError("Komut çok uzun.")

        for token in SHELL_METACHARACTERS:
            if token in text:
                raise CommandNotAllowedError(
                    "Komut kabuk denetim karakteri içeriyor; tek bir program çalıştırın."
                )

        try:
            argv = shlex.split(text, posix=True)
        except ValueError as exc:
            raise CommandNotAllowedError("Komut ayrıştırılamadı.") from exc

        if not argv:
            raise CommandNotAllowedError("Komut boş.")
        if len(argv) > MAX_ARGUMENT_COUNT:
            raise CommandNotAllowedError("Komut çok fazla argüman içeriyor.")

        program = _program_name(argv[0])
        if program not in self._allowed:
            raise CommandNotAllowedError(f"'{program}' çalıştırılabilir listesinde değil.")

        # Listedeki ad kullanılır, kullanıcının yazdığı yol değil: aksi hâlde
        # ".../bin/python" gibi bir yolla listedeki adı taklit eden başka bir
        # program çalıştırılabilirdi.
        return [program, *argv[1:]]


def _program_name(token: str) -> str:
    """Bir yolun sonundaki program adını, uzantısız ve küçük harfle döndürür."""

    cleaned = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if cleaned.endswith(suffix):
            return cleaned[: -len(suffix)]
    return cleaned
