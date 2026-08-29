"""Git okuma araçları ve geri alma noktaları.

Kapsam:
 1. git_status değişiklikleri listeler
 2. Temiz depo temiz raporlanır
 3. Depo olmayan dizin anlaşılır hata verir
 4. git_diff değişikliğin içeriğini gösterir
 5. git_diff kapalı bir yolu reddeder
 6. Git araçları READ izinlidir
 7. Checkpoint mevcut içeriği kaydeder
 8. Var olmayan dosya "yoktu" olarak kaydedilir
 9. Geri alma içeriği eski hâline döndürür
10. Var olmayan dosyanın geri alınması onu siler
11. Bilinmeyen kimlik hata verir
12. Çok büyük dosya geri alınamaz olarak işaretlenir
13. Kayıtlar yeniden başlatmayı atlatır
14. write_file bir geri alma noktası üretir ve geri alınabilir
15. edit_file için de aynısı geçerli
16. API bekleyen noktaları listeler ve geri alır
17. Geri alınamayan nokta 409 verir
18. Geri alma bir AJAN aracı değildir
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.checkpoints import router as checkpoints_router
from app.security.checkpoints import (
    CheckpointNotFoundError,
    CheckpointNotRestorableError,
    MAX_SNAPSHOT_BYTES,
    SQLiteCheckpointStore,
)
from app.security.paths import PathGuard
from app.tools.base import PermissionLevel, ToolExecutionError
from app.tools.builtin.filesystem import EditFileTool, WriteFileTool
from app.tools.builtin.git_tools import GitDiffTool, GitStatusTool
from app.tools.defaults import register_filesystem_tools
from app.tools.registry import ToolRegistry

_HAS_GIT = shutil.which("git") is not None
_needs_git = pytest.mark.skipif(not _HAS_GIT, reason="git bu ortamda yok")


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "rapor.txt").write_text("özgün\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def guard(workspace: Path) -> PathGuard:
    return PathGuard(workspace)


@pytest.fixture()
def store(workspace: Path) -> SQLiteCheckpointStore:
    return SQLiteCheckpointStore(str(workspace / ".jarvis.db"), root=workspace)


def _git_repo(path: Path) -> None:
    """Testler için küçük bir depo kurar."""
    env = {"GIT_CONFIG_GLOBAL": str(path / "gitconfig"), "PATH": ""}
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "ilk"], cwd=path, check=True)


# ---------------------------------------------------------------------------
# 1-6. Git araçları
# ---------------------------------------------------------------------------

@_needs_git
def test_git_status_lists_changes(guard: PathGuard, workspace: Path) -> None:
    """Değiştirilen dosya durumda görünmeli."""
    _git_repo(workspace)
    (workspace / "rapor.txt").write_text("değişti\n", encoding="utf-8")

    result = _run(GitStatusTool(guard=guard).execute(GitStatusTool.input_model()))

    assert result["clean"] is False
    assert any(change["path"] == "rapor.txt" for change in result["changes"])


@_needs_git
def test_clean_repository_is_reported_clean(guard: PathGuard, workspace: Path) -> None:
    """Değişiklik yoksa temiz denmeli."""
    _git_repo(workspace)

    result = _run(GitStatusTool(guard=guard).execute(GitStatusTool.input_model()))

    assert result["clean"] is True
    assert result["count"] == 0


@_needs_git
def test_a_non_repository_reports_clearly(guard: PathGuard) -> None:
    """Depo olmayan dizinde anlaşılır bir hata verilmeli."""
    with pytest.raises(ToolExecutionError) as exc:
        _run(GitStatusTool(guard=guard).execute(GitStatusTool.input_model()))

    assert "depo" in str(exc.value).lower()


@_needs_git
def test_git_diff_shows_the_change(guard: PathGuard, workspace: Path) -> None:
    """Fark, değişen satırı içermeli."""
    _git_repo(workspace)
    (workspace / "rapor.txt").write_text("değişti\n", encoding="utf-8")

    result = _run(GitDiffTool(guard=guard).execute(GitDiffTool.input_model()))

    assert result["has_changes"] is True
    assert "değişti" in result["diff"]


@_needs_git
def test_git_diff_refuses_a_closed_path(guard: PathGuard, workspace: Path) -> None:
    """Bekçinin kapattığı yol için fark istenememeli."""
    _git_repo(workspace)

    with pytest.raises(ToolExecutionError):
        _run(GitDiffTool(guard=guard).execute(GitDiffTool.input_model(path="../disarida")))


def test_git_tools_are_read_permission(guard: PathGuard) -> None:
    """İkisi de yalnızca okur."""
    assert GitStatusTool(guard=guard).permission is PermissionLevel.READ
    assert GitDiffTool(guard=guard).permission is PermissionLevel.READ


# ---------------------------------------------------------------------------
# 7-13. Checkpoint deposu
# ---------------------------------------------------------------------------

def test_existing_content_is_captured(store: SQLiteCheckpointStore, workspace: Path) -> None:
    """Değişiklikten önceki içerik kaydedilmeli."""
    record = store.record(workspace / "rapor.txt")

    assert record is not None
    assert record.existed is True
    assert record.content == "özgün\n"
    assert record.restorable is True


def test_a_missing_file_is_recorded_as_absent(
    store: SQLiteCheckpointStore, workspace: Path
) -> None:
    """Var olmayan dosya da kaydedilmeli; geri alma onu silmelidir."""
    record = store.record(workspace / "yeni.txt")

    assert record is not None
    assert record.existed is False


def test_restore_puts_the_old_content_back(
    store: SQLiteCheckpointStore, workspace: Path
) -> None:
    """Geri alma dosyayı eski hâline döndürmeli."""
    record = store.record(workspace / "rapor.txt")
    (workspace / "rapor.txt").write_text("bozuldu", encoding="utf-8")

    store.restore(record.checkpoint_id)

    assert (workspace / "rapor.txt").read_text(encoding="utf-8") == "özgün\n"


def test_restoring_an_absent_file_removes_it(
    store: SQLiteCheckpointStore, workspace: Path
) -> None:
    """Değişiklikten önce yoktuysa geri alma onu kaldırmalı."""
    target = workspace / "yeni.txt"
    record = store.record(target)
    target.write_text("sonradan", encoding="utf-8")

    store.restore(record.checkpoint_id)

    assert not target.exists()


def test_unknown_checkpoint_is_reported(store: SQLiteCheckpointStore) -> None:
    """Var olmayan kimlik açıkça bulunamadı demeli."""
    with pytest.raises(CheckpointNotFoundError):
        store.restore("olmayan")


def test_a_large_file_is_marked_unrestorable(
    store: SQLiteCheckpointStore, workspace: Path
) -> None:
    """Kaydedilemeyen bir değişiklik geri alınabilir gibi görünmemeli."""
    big = workspace / "buyuk.txt"
    big.write_text("a" * (MAX_SNAPSHOT_BYTES + 10), encoding="utf-8")

    record = store.record(big)

    assert record is not None
    assert record.restorable is False
    with pytest.raises(CheckpointNotRestorableError):
        store.restore(record.checkpoint_id)


def test_checkpoints_survive_a_new_store(workspace: Path) -> None:
    """Geri alma imkânı yeniden başlatmayı atlatmalı."""
    db = str(workspace / ".jarvis.db")
    record = SQLiteCheckpointStore(db, root=workspace).record(workspace / "rapor.txt")
    (workspace / "rapor.txt").write_text("bozuldu", encoding="utf-8")

    SQLiteCheckpointStore(db, root=workspace).restore(record.checkpoint_id)

    assert (workspace / "rapor.txt").read_text(encoding="utf-8") == "özgün\n"


# ---------------------------------------------------------------------------
# 14-15. Araçlarla birlikte
# ---------------------------------------------------------------------------

def test_write_file_produces_an_undoable_checkpoint(
    guard: PathGuard, store: SQLiteCheckpointStore, workspace: Path
) -> None:
    """Yazma geri alınabilir olmalı ve kimliği sonuçta görünmeli."""
    tool = WriteFileTool(guard=guard, journal=store)

    result = _run(tool.execute(tool.input_model(path="rapor.txt", content="yeni")))

    assert result["checkpoint_id"] is not None
    store.restore(result["checkpoint_id"])
    assert (workspace / "rapor.txt").read_text(encoding="utf-8") == "özgün\n"


def test_edit_file_produces_an_undoable_checkpoint(
    guard: PathGuard, store: SQLiteCheckpointStore, workspace: Path
) -> None:
    """Düzenleme de geri alınabilir olmalı."""
    tool = EditFileTool(guard=guard, journal=store)

    result = _run(
        tool.execute(tool.input_model(path="rapor.txt", old_string="özgün", new_string="yeni"))
    )

    store.restore(result["checkpoint_id"])
    assert (workspace / "rapor.txt").read_text(encoding="utf-8") == "özgün\n"


def test_without_a_journal_the_change_is_marked_unrecoverable(
    guard: PathGuard, workspace: Path
) -> None:
    """Günlük yoksa geri alınamazlık sessiz kalmamalı."""
    tool = WriteFileTool(guard=guard)

    result = _run(tool.execute(tool.input_model(path="rapor.txt", content="yeni")))

    assert result["checkpoint_id"] is None


# ---------------------------------------------------------------------------
# 16-18. API ve sınırlar
# ---------------------------------------------------------------------------

def _client(store: SQLiteCheckpointStore | None) -> TestClient:
    app = FastAPI()
    app.include_router(checkpoints_router, prefix="/api")
    app.state.checkpoint_store = store
    return TestClient(app)


def test_api_lists_and_restores(
    guard: PathGuard, store: SQLiteCheckpointStore, workspace: Path
) -> None:
    """Kullanıcı noktaları görebilmeli ve geri alabilmeli."""
    tool = WriteFileTool(guard=guard, journal=store)
    _run(tool.execute(tool.input_model(path="rapor.txt", content="yeni")))
    client = _client(store)

    listed = client.get("/api/checkpoints").json()["checkpoints"]
    assert len(listed) == 1
    assert listed[0]["path"] == "rapor.txt"

    response = client.post(f"/api/checkpoints/{listed[0]['checkpoint_id']}/restore")

    assert response.status_code == 200
    assert response.json()["status"] == "restored"
    assert (workspace / "rapor.txt").read_text(encoding="utf-8") == "özgün\n"


def test_api_reports_an_unrestorable_point(
    store: SQLiteCheckpointStore, workspace: Path
) -> None:
    """Geri alınamayan nokta bulunamadıdan ayrı bir durum vermeli."""
    big = workspace / "buyuk.txt"
    big.write_text("a" * (MAX_SNAPSHOT_BYTES + 10), encoding="utf-8")
    record = store.record(big)
    client = _client(store)

    response = client.post(f"/api/checkpoints/{record.checkpoint_id}/restore")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "checkpoint_not_restorable"


def test_restore_is_not_an_agent_tool(guard: PathGuard, store: SQLiteCheckpointStore) -> None:
    """Ajan kendi değişikliğini geri alan bir araca sahip olmamalı.

    Geri alma insanın kararıdır; ajanın elinde olsaydı yaptığının izini
    kendi silebilirdi.
    """
    registry = ToolRegistry()
    register_filesystem_tools(registry, guard=guard, writable=True, journal=store)

    names = {tool.name for tool in registry.list_tools()}
    assert not any("restore" in name or "rollback" in name for name in names)
