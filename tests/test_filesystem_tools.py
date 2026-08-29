"""Dosya sistemi tool'ları — okuma tarafı.

Kapsam:
 1. read_file kök içindeki dosyayı okur
 2. read_file satır aralığı verilebilir ve kesilme bildirilir
 3. read_file `.env` dosyasını REDDEDER
 4. read_file kök dışını reddeder
 5. read_file ikili dosyayı reddeder
 6. list_dir içeriği listeler ve göreli yol döndürür
 7. list_dir kapalı dosyaları HİÇ göstermez
 8. grep eşleşmeleri göreli yolla döndürür
 9. grep kapalı dosyaların içinde arama YAPMAZ
10. grep gürültülü dizinleri atlar
11. grep geçersiz düzenli ifadeyi bildirir
12. Üç araç da READ izinlidir
13. Bekçi yoksa hiçbir araç kaydedilmez
14. Varsayılan registry değişmedi — sohbetin tool yüzeyi korunur
15. Hata mesajları mutlak yol sızdırmaz
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.security.paths import PathGuard
from app.tools.base import PermissionLevel, ToolExecutionError
from app.tools.builtin.filesystem import GrepTool, ListDirTool, ReadFileTool
from app.tools.defaults import build_default_tool_registry, register_filesystem_tools
from app.tools.registry import ToolRegistry


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "def merhaba():\n    return 'selam'\n", encoding="utf-8"
    )
    (tmp_path / "notlar.txt").write_text("\n".join(f"satır {i}" for i in range(1, 51)), encoding="utf-8")
    (tmp_path / ".env").write_text("JARVIS_API_KEY=cok-gizli-deger\n", encoding="utf-8")
    (tmp_path / "resim.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00gizli")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "paket.js").write_text("merhaba dunya", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def guard(workspace: Path) -> PathGuard:
    return PathGuard(workspace)


# ---------------------------------------------------------------------------
# 1-5. read_file
# ---------------------------------------------------------------------------

def test_read_file_reads_a_file_inside_the_root(guard: PathGuard) -> None:
    """Kök içindeki dosya okunabilmeli."""
    result = _run(ReadFileTool(guard=guard).execute(ReadFileTool.input_model(path="app/main.py")))

    assert "def merhaba" in result["content"]
    assert result["path"] == "app/main.py"
    assert result["truncated"] is False


def test_read_file_windows_lines_and_reports_truncation(guard: PathGuard) -> None:
    """Aralık verilebilmeli ve eksik okuma sessiz kalmamalı."""
    result = _run(
        ReadFileTool(guard=guard).execute(
            ReadFileTool.input_model(path="notlar.txt", offset=10, limit=5)
        )
    )

    assert result["returned_lines"] == 5
    assert result["content"].startswith("satır 11")
    assert result["truncated"] is True, "geri kalan satırlar var, model tam sanmamalı"


def test_read_file_refuses_dotenv(guard: PathGuard) -> None:
    """Ajan `.env` okuyamamalı — API anahtarları oradadır."""
    with pytest.raises(ToolExecutionError):
        _run(ReadFileTool(guard=guard).execute(ReadFileTool.input_model(path=".env")))


def test_read_file_refuses_outside_the_root(guard: PathGuard) -> None:
    """Çalışma dizininin dışı kapalı olmalı."""
    with pytest.raises(ToolExecutionError):
        _run(ReadFileTool(guard=guard).execute(ReadFileTool.input_model(path="../../etc/passwd")))


def test_read_file_refuses_binary(guard: PathGuard) -> None:
    """İkili dosya metin gibi sunulmamalı."""
    with pytest.raises(ToolExecutionError) as exc:
        _run(ReadFileTool(guard=guard).execute(ReadFileTool.input_model(path="resim.png")))

    assert "ikili" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# 6-7. list_dir
# ---------------------------------------------------------------------------

def test_list_dir_lists_entries_with_relative_paths(guard: PathGuard) -> None:
    """Listeleme göreli yol döndürmeli."""
    result = _run(ListDirTool(guard=guard).execute(ListDirTool.input_model(path=".")))

    names = {entry["name"] for entry in result["entries"]}
    assert "notlar.txt" in names
    assert "app" in names
    assert result["path"] == "."


def test_list_dir_hides_closed_files_entirely(guard: PathGuard) -> None:
    """Kapalı dosya listede GÖRÜNMEMELİ.

    Adını gösterip okumayı reddetmek, okunamayan bir dosyanın varlığını
    duyurmak olurdu.
    """
    result = _run(ListDirTool(guard=guard).execute(ListDirTool.input_model(path=".")))

    names = {entry["name"] for entry in result["entries"]}
    assert ".env" not in names


# ---------------------------------------------------------------------------
# 8-11. grep
# ---------------------------------------------------------------------------

def test_grep_returns_matches_with_relative_paths(guard: PathGuard) -> None:
    """Arama sonucu göreli yol ve satır numarası taşımalı."""
    result = _run(GrepTool(guard=guard).execute(GrepTool.input_model(pattern="merhaba")))

    paths = {match["path"] for match in result["matches"]}
    assert "app/main.py" in paths
    assert all(not Path(p).is_absolute() for p in paths)


def test_grep_does_not_search_inside_closed_files(guard: PathGuard) -> None:
    """`.env` içindeki değer aramayla da elde edilememeli.

    Okuma engellenip arama açık kalsaydı, anahtar tek tek sorgularla
    sızdırılabilirdi.
    """
    result = _run(GrepTool(guard=guard).execute(GrepTool.input_model(pattern="cok-gizli-deger")))

    assert result["count"] == 0


def test_grep_skips_noisy_directories(guard: PathGuard) -> None:
    """node_modules gibi dizinler sonuçları boğmamalı."""
    result = _run(GrepTool(guard=guard).execute(GrepTool.input_model(pattern="dunya")))

    assert result["count"] == 0


def test_grep_reports_an_invalid_expression(guard: PathGuard) -> None:
    """Bozuk düzenli ifade anlaşılır bir hata vermeli."""
    with pytest.raises(ToolExecutionError):
        _run(GrepTool(guard=guard).execute(GrepTool.input_model(pattern="[bozuk")))


# ---------------------------------------------------------------------------
# 12-15. Sözleşme
# ---------------------------------------------------------------------------

def test_all_read_tools_are_read_permission(guard: PathGuard) -> None:
    """Üçü de salt okunur olmalı."""
    for tool in (ReadFileTool(guard=guard), ListDirTool(guard=guard), GrepTool(guard=guard)):
        assert tool.permission is PermissionLevel.READ


def test_no_guard_means_no_filesystem_tools() -> None:
    """Çalışma kökü yoksa dosya okuma yeteneği hiç var olmamalı."""
    registry = ToolRegistry()

    registered = register_filesystem_tools(registry, guard=None)

    assert registered == []
    assert registry.list_tools() == []


def test_default_registry_is_unchanged(guard: PathGuard) -> None:
    """Sohbetin gördüğü tool yüzeyi kendiliğinden değişmemeli."""
    names = {tool.name for tool in build_default_tool_registry().list_tools()}

    assert names == {"get_time", "get_date", "calculator", "system_status"}


def test_errors_do_not_leak_absolute_paths(guard: PathGuard, workspace: Path) -> None:
    """Reddedilen istek dosya sisteminin haritasını vermemeli."""
    with pytest.raises(ToolExecutionError) as exc:
        _run(ReadFileTool(guard=guard).execute(ReadFileTool.input_model(path=".env")))

    assert str(workspace) not in str(exc.value)


# ---------------------------------------------------------------------------
# 16-18. Uygulama bağlantısı
# ---------------------------------------------------------------------------

def _app_settings(tmp_path: Path, **kwargs: object):
    from app.config.settings import Settings

    defaults = dict(
        app_name="Test",
        app_version="t",
        environment="test",
        ollama_model="x",
        memory_db_path=str(tmp_path / "memory.db"),
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _agent_tool_names(app) -> set[str]:  # type: ignore[no-untyped-def]
    return {tool.name for tool in app.state.agent_service._context_builder._tool_registry.list_tools()}


def test_app_registers_file_tools_when_a_workspace_is_configured(
    tmp_path: Path, workspace: Path
) -> None:
    """Çalışma kökü verilince ajan dosya araçlarını almalı."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings=_app_settings(tmp_path, workspace_root=str(workspace)))

    with TestClient(app):
        assert {"read_file", "list_dir", "grep"} <= _agent_tool_names(app)


def test_app_grants_no_file_access_without_a_workspace(tmp_path: Path) -> None:
    """Kök verilmezse dosya yeteneği hiç oluşmamalı."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings=_app_settings(tmp_path))

    with TestClient(app):
        assert not ({"read_file", "list_dir", "grep"} & _agent_tool_names(app))


def test_invalid_workspace_disables_the_tools_without_crashing(tmp_path: Path) -> None:
    """Bozuk ayar uygulamayı düşürmemeli, yeteneği kapalı bırakmalı."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(
        settings=_app_settings(tmp_path, workspace_root=str(tmp_path / "olmayan-klasor"))
    )

    with TestClient(app):
        assert not ({"read_file", "list_dir", "grep"} & _agent_tool_names(app))
