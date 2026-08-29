"""Güvenlik katmanı — komut politikası.

Kapsam:
 1. Tanınan komut argüman listesine çevrilir
 2. Tırnaklı argümanlar korunur
 3. Boş komut reddedilir
 4. Kabuk denetim karakterleri reddedilir (zincirleme, boru, yönlendirme)
 5. Ayrıştırılamayan komut reddedilir
 6. Tanınmayan program reddedilir
 7. Yol öneki atılır; listedeki ad kullanılır
 8. Yerel bir programın listedeki adı taklit etmesi engellenir
 9. Windows uzantıları ve büyük/küçük harf korumayı atlatmaz
10. Boş liste hiçbir komuta izin vermez
11. Aşırı uzun ve aşırı argümanlı komutlar reddedilir
12. Hata mesajı izin listesini sızdırmaz
"""

from __future__ import annotations

import pytest

from app.security.commands import (
    CommandNotAllowedError,
    CommandPolicy,
    MAX_ARGUMENT_COUNT,
    MAX_COMMAND_LENGTH,
)


@pytest.fixture()
def policy() -> CommandPolicy:
    return CommandPolicy()


# ---------------------------------------------------------------------------
# 1-2. Kabul edilen komutlar
# ---------------------------------------------------------------------------

def test_allowed_command_becomes_an_argument_list(policy: CommandPolicy) -> None:
    """Tanınan komut, kabuk olmadan çalıştırılabilecek listeye çevrilmeli."""
    assert list(policy.parse("pytest -q tests")) == ["pytest", "-q", "tests"]


def test_quoted_arguments_are_preserved(policy: CommandPolicy) -> None:
    """Tırnak içindeki boşluk tek bir argüman olarak kalmalı."""
    argv = policy.parse('python -c "print(1 + 1)"')

    assert argv[-1] == "print(1 + 1)"


# ---------------------------------------------------------------------------
# 3-5. Biçim reddi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", ["", "   ", "\t"])
def test_empty_command_is_refused(policy: CommandPolicy, command: str) -> None:
    """Boş komut çalıştırılmamalı."""
    with pytest.raises(CommandNotAllowedError):
        policy.parse(command)


@pytest.mark.parametrize(
    "command",
    [
        "pytest; rm -rf /",
        "pytest && curl kotu.example",
        "pytest | tee cikti.txt",
        "pytest > cikti.txt",
        "pytest < girdi.txt",
        "pytest `whoami`",
        "pytest $(whoami)",
        "pytest\nrm -rf /",
    ],
)
def test_shell_control_is_refused(policy: CommandPolicy, command: str) -> None:
    """Zincirleme, boru ve yönlendirme denemesi reddedilmeli.

    Kabuk zaten kullanılmıyor, dolayısıyla bunlar çalışmazdı; yine de
    sessizce yarım çalıştırmak yerine açıkça reddedilirler.
    """
    with pytest.raises(CommandNotAllowedError):
        policy.parse(command)


def test_unparseable_command_is_refused(policy: CommandPolicy) -> None:
    """Kapanmamış tırnak tahminle tamamlanmamalı."""
    with pytest.raises(CommandNotAllowedError):
        policy.parse('python -c "kapanmadi')


# ---------------------------------------------------------------------------
# 6-9. Program tanıma
# ---------------------------------------------------------------------------

def test_unknown_program_is_refused(policy: CommandPolicy) -> None:
    """Listede olmayan program çalıştırılmamalı."""
    with pytest.raises(CommandNotAllowedError):
        policy.parse("rm -rf /")


def test_path_prefix_is_stripped(policy: CommandPolicy) -> None:
    """Tam yolla çağrılan tanınan program kabul edilmeli."""
    assert list(policy.parse("/usr/bin/python --version"))[0] == "python"


def test_a_local_program_cannot_impersonate_an_allowed_name(policy: CommandPolicy) -> None:
    """Kullanıcının yazdığı yol değil, listedeki ad çalıştırılmalı.

    Aksi hâlde çalışma dizinine konan `./sahte/python` gibi bir dosya,
    listedeki adı taşıdığı için çalıştırılabilirdi.
    """
    argv = policy.parse("./sahte/python --version")

    assert argv[0] == "python"
    assert "sahte" not in argv[0]


@pytest.mark.parametrize("command", ["PYTHON --version", "Python.exe --version"])
def test_case_and_extension_do_not_bypass_the_rule(
    policy: CommandPolicy, command: str
) -> None:
    """Büyük harf ya da .exe yazmak tanımayı değiştirmemeli."""
    assert policy.parse(command)[0] == "python"


# ---------------------------------------------------------------------------
# 10-12. Sınırlar
# ---------------------------------------------------------------------------

def test_an_empty_allow_list_permits_nothing() -> None:
    """Liste boşsa hiçbir komut çalışmamalı."""
    with pytest.raises(CommandNotAllowedError):
        CommandPolicy(allowed_commands=()).parse("python --version")


def test_oversized_commands_are_refused(policy: CommandPolicy) -> None:
    """Aşırı uzun ve aşırı argümanlı komutlar reddedilmeli."""
    with pytest.raises(CommandNotAllowedError):
        policy.parse("python " + "a" * MAX_COMMAND_LENGTH)

    with pytest.raises(CommandNotAllowedError):
        policy.parse("python " + " ".join(["x"] * (MAX_ARGUMENT_COUNT + 1)))


def test_refusal_does_not_disclose_the_allow_list(policy: CommandPolicy) -> None:
    """Reddedilen deneme izin haritasını çıkarmaya yaramamalı."""
    with pytest.raises(CommandNotAllowedError) as exc:
        policy.parse("rm -rf /")

    message = str(exc.value)
    assert "pytest" not in message
    assert "python" not in message
