"""Güvenlik katmanı — dosya yolu bekçisi.

Kapsam:
 1. Kök içindeki sıradan dosya kabul edilir
 2. Kökün kendisi kabul edilir
 3. Henüz var olmayan yazma hedefi kabul edilir
 4. `..` ile dizin dışına çıkış reddedilir
 5. Kök dışındaki mutlak yol reddedilir
 6. Dışarıyı gösteren sembolik bağ reddedilir
 7. `.env` reddedilir
 8. `.env.local` gibi türevler reddedilir
 9. `.env.example` KABUL EDİLİR — içinde gerçek değer yoktur
10. Büyük/küçük harf koruma atlatılamaz
11. Anahtar ve sertifika dosyaları reddedilir
12. Kapalı dizinlerin içi reddedilir
13. is_allowed hata fırlatmaz
14. Var olmayan kök reddedilir
15. Hata mesajı tam yolu sızdırmaz
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.security.paths import PathGuard, PathNotAllowedError


@pytest.fixture()
def guard(tmp_path: Path) -> PathGuard:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("x", encoding="utf-8")
    return PathGuard(tmp_path)


# ---------------------------------------------------------------------------
# 1-3. İzin verilen durumlar
# ---------------------------------------------------------------------------

def test_ordinary_file_inside_root_is_allowed(guard: PathGuard) -> None:
    """Kök içindeki normal dosya kabul edilmeli."""
    resolved = guard.resolve("app/main.py")

    assert resolved.name == "main.py"
    assert guard.root in resolved.parents


def test_root_itself_is_allowed(guard: PathGuard) -> None:
    """Kökün kendisi listelenebilmeli."""
    assert guard.resolve(".") == guard.root


def test_missing_write_target_is_allowed(guard: PathGuard) -> None:
    """Henüz var olmayan dosyaya yazmak engellenmemeli."""
    resolved = guard.resolve("app/yeni.py")

    assert resolved.name == "yeni.py"
    assert not resolved.exists()


# ---------------------------------------------------------------------------
# 4-6. Kaçış denemeleri
# ---------------------------------------------------------------------------

def test_parent_traversal_is_refused(guard: PathGuard) -> None:
    """`..` ile yukarı çıkmak engellenmeli."""
    with pytest.raises(PathNotAllowedError):
        guard.resolve("../../etc/passwd")


def test_absolute_path_outside_root_is_refused(guard: PathGuard, tmp_path: Path) -> None:
    """Kök dışındaki mutlak yol engellenmeli."""
    outsider = tmp_path.parent / "disarida.txt"

    with pytest.raises(PathNotAllowedError):
        guard.resolve(outsider)


def test_symlink_pointing_outside_is_refused(guard: PathGuard, tmp_path: Path) -> None:
    """Kök içinde durup dışarıyı gösteren bağ engellenmeli.

    Kontrol bağlar çözüldükten sonra yapılmasaydı, bu bağ kökün içinde
    göründüğü için kabul edilirdi.
    """
    outside = tmp_path.parent / "gizli.txt"
    outside.write_text("sır", encoding="utf-8")
    link = tmp_path / "kisayol.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("Bu ortamda sembolik bağ oluşturulamıyor.")

    with pytest.raises(PathNotAllowedError):
        guard.resolve("kisayol.txt")


def test_returned_path_is_normalised_not_the_raw_input() -> None:
    """Kontrol edilen ile döndürülen aynı, normalleştirilmiş yol olmalı.

    Sembolik bağ testi her ortamda koşamıyor (Windows'ta yetki ister); bu
    test aynı altta yatan özelliği ortamdan bağımsız olarak sınar: bekçi
    ham girdiyi değil, çözülmüş yolu döndürür ve kontrolünü onun üzerinde
    yapar.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "app").mkdir()
        (root / "app" / "main.py").write_text("x", encoding="utf-8")
        guard = PathGuard(root)

        resolved = guard.resolve("app/../app/main.py")

        assert ".." not in resolved.parts
        assert resolved == (root.resolve() / "app" / "main.py")


# ---------------------------------------------------------------------------
# 7-12. Hassas dosyalar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    [".env", ".env.local", ".env.production", "prod.env", ".git-credentials", ".netrc"],
)
def test_secret_config_files_are_refused(guard: PathGuard, name: str) -> None:
    """Gizli değer taşıyan ayar dosyaları okunamamalı."""
    with pytest.raises(PathNotAllowedError):
        guard.resolve(name)


def test_env_example_is_allowed(guard: PathGuard) -> None:
    """`.env.example` şablondur; gerçek değer taşımaz ve okunabilmeli."""
    assert guard.is_allowed(".env.example") is True


@pytest.mark.parametrize("name", [".ENV", ".Env", "ID_RSA"])
def test_case_does_not_bypass_the_rule(guard: PathGuard, name: str) -> None:
    """Büyük harfle yazmak korumayı atlatmamalı."""
    with pytest.raises(PathNotAllowedError):
        guard.resolve(name)


@pytest.mark.parametrize("name", ["sunucu.pem", "ozel.key", "id_rsa", "sertifika.p12"])
def test_keys_and_certificates_are_refused(guard: PathGuard, name: str) -> None:
    """Anahtar ve sertifika dosyaları kapalı olmalı."""
    with pytest.raises(PathNotAllowedError):
        guard.resolve(name)


def test_closed_directories_are_refused(guard: PathGuard, tmp_path: Path) -> None:
    """Kapalı bir dizinin içindeki her şey kapalı olmalı."""
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("x", encoding="utf-8")

    with pytest.raises(PathNotAllowedError):
        guard.resolve(".ssh/config")


# ---------------------------------------------------------------------------
# 13-15. Arayüz davranışı
# ---------------------------------------------------------------------------

def test_is_allowed_does_not_raise(guard: PathGuard) -> None:
    """Sorgulama biçimi hata fırlatmamalı."""
    assert guard.is_allowed("app/main.py") is True
    assert guard.is_allowed("../disarida.txt") is False


def test_missing_root_is_refused(tmp_path: Path) -> None:
    """Var olmayan köke hapsetmek, hapsetmemekle aynı şey olurdu."""
    with pytest.raises(ValueError):
        PathGuard(tmp_path / "olmayan")


def test_error_message_does_not_leak_the_resolved_path(guard: PathGuard) -> None:
    """Reddedilen istek dosya sistemi haritası çıkarmaya yaramamalı."""
    with pytest.raises(PathNotAllowedError) as exc:
        guard.resolve("../../etc/passwd")

    assert "etc" not in str(exc.value)
    assert str(guard.root) not in str(exc.value)
