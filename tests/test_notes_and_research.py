"""Notlar ve araştırma yeteneği.

Kapsam — notlar:
 1. Not eklenir ve en yeni önce listelenir
 2. Arama başlık ve içerikte çalışır
 3. Güncelleme içeriği değiştirir, kimliği korur
 4. Silme KALICIDIR
 5. Not sınırı sessizce eskiyi silmez, hata verir
 6. Ajanın yazdığı not işaretlenir
 7. Ajanın SİLME aracı yoktur
 8. Yazma aracı WRITE, arama aracı READ izinlidir
 9. API uçları çalışır ve depo yoksa 503 döner

Kapsam — araştırma (ağ bekçisi):
10. Yalnızca http/https
11. Geri döngü adresi reddedilir
12. Özel ağ adresi reddedilir
13. Bulut kimlik ucu (169.254.169.254) reddedilir
14. Beyaz liste alt alanları kapsar, dışındakini reddeder
15. Getirilen içerik ÇİTLENİR
16. HTML'den script ve style atılır
17. Getirme aracı WRITE izinlidir (sessiz çalışmaz)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.notes import router as notes_router
from app.notes.store import MAX_NOTES, NoteStore
from app.security.fencing import UNTRUSTED_OPEN
from app.security.network import NetworkGuard, UrlNotAllowedError
from app.tools.base import PermissionLevel
from app.tools.builtin.notes import NoteSearchTool, NoteWriteTool
from app.tools.builtin.research import FetchUrlTool, html_to_text
from app.tools.defaults import register_note_tools, register_research_tool
from app.tools.registry import ToolRegistry


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _store(tmp_path: Path) -> NoteStore:
    return NoteStore(str(tmp_path / "jarvis.db"))


# ---------------------------------------------------------------------------
# Not deposu
# ---------------------------------------------------------------------------


def test_notes_are_listed_newest_first(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(content="ilk")
    store.add(content="ikinci")

    assert [note.content for note in store.list()] == ["ikinci", "ilk"]


def test_search_matches_title_and_content(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(title="Alışveriş", content="süt ve ekmek")
    store.add(title="Proje", content="jarvis planı")

    assert len(store.list(query="ekmek")) == 1
    assert len(store.list(query="Proje")) == 1
    assert store.list(query="hicbiryerde") == []


def test_update_changes_content_and_keeps_the_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    note = store.add(content="eski")

    updated = store.update(note.id, content="yeni")

    assert updated is not None
    assert updated.id == note.id
    assert store.get(note.id).content == "yeni"  # type: ignore[union-attr]


def test_delete_is_permanent(tmp_path: Path) -> None:
    """Kullanıcı bir notu sildiğinde gitmesini bekler; mantıksal silme yok."""
    store = _store(tmp_path)
    note = store.add(content="gidecek")

    assert store.delete(note.id) is True
    assert store.get(note.id) is None
    assert store.delete(note.id) is False


def test_note_limit_raises_instead_of_dropping_the_oldest(tmp_path: Path) -> None:
    """Sessizce en eskiyi silmek, kullanıcının yazdığını habersiz yok etmektir."""
    store = _store(tmp_path)
    for index in range(MAX_NOTES):
        store.add(content=f"not-{index}")

    with pytest.raises(ValueError):
        store.add(content="bir fazla")


def test_agent_written_notes_are_marked(tmp_path: Path) -> None:
    """Kullanıcı kendi yazdığıyla ajanınkini ayırt edebilmelidir."""
    store = _store(tmp_path)
    _run(NoteWriteTool(store=store).execute(
        NoteWriteTool.input_model(content="ajan notu")
    ))

    assert store.list()[0].created_by == "agent"


# ---------------------------------------------------------------------------
# Not araçları
# ---------------------------------------------------------------------------


def test_agent_has_no_delete_tool(tmp_path: Path) -> None:
    """Ajanın yanlış anlamayla kalıcı bir metni yok edebilmesi kabul edilmedi."""
    registry = ToolRegistry()
    register_note_tools(registry, store=_store(tmp_path))

    names = {tool.name for tool in registry.list_tools()}
    assert names == {"note_search", "note_write"}
    assert not any("delete" in name for name in names)


def test_note_permissions_separate_reading_from_writing(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert NoteSearchTool(store=store).permission is PermissionLevel.READ
    assert NoteWriteTool(store=store).permission is PermissionLevel.WRITE


def test_read_only_mode_registers_search_alone(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_note_tools(registry, store=_store(tmp_path), writable=False)

    assert [tool.name for tool in registry.list_tools()] == ["note_search"]


def test_no_store_means_no_note_tools() -> None:
    registry = ToolRegistry()

    assert register_note_tools(registry, store=None) == []


def test_search_tool_returns_notes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(title="Plan", content="jarvis bitirilecek")

    result = _run(NoteSearchTool(store=store).execute(
        NoteSearchTool.input_model(query="jarvis")
    ))

    assert result["count"] == 1
    assert result["notes"][0]["title"] == "Plan"


# ---------------------------------------------------------------------------
# Notlar API
# ---------------------------------------------------------------------------


def _client(store: NoteStore | None) -> TestClient:
    app = FastAPI()
    app.state.note_store = store
    app.include_router(notes_router, prefix="/api")
    return TestClient(app)


def test_note_endpoints_round_trip(tmp_path: Path) -> None:
    client = _client(_store(tmp_path))

    created = client.post("/api/notes", json={"content": "deneme", "title": "T"})
    assert created.status_code == 201
    note_id = created.json()["id"]

    assert client.get("/api/notes").json()["count"] == 1
    assert client.put(f"/api/notes/{note_id}", json={"content": "yeni"}).status_code == 200
    assert client.delete(f"/api/notes/{note_id}").status_code == 204
    assert client.get("/api/notes").json()["count"] == 0


def test_note_endpoints_report_missing_store() -> None:
    response = _client(None).get("/api/notes")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "notes_unavailable"


# ---------------------------------------------------------------------------
# Ağ bekçisi
# ---------------------------------------------------------------------------


def test_only_http_schemes_are_allowed() -> None:
    guard = NetworkGuard()

    for url in ("file:///etc/passwd", "ftp://example.com", "javascript:alert(1)"):
        with pytest.raises(UrlNotAllowedError):
            guard.validate(url)


def test_loopback_is_rejected() -> None:
    """Ajan kendi yönetim uçlarına dışarıdan ulaşamamalıdır."""
    with pytest.raises(UrlNotAllowedError):
        NetworkGuard().validate("http://127.0.0.1:8000/api/admin/llm")


def test_private_network_is_rejected() -> None:
    with pytest.raises(UrlNotAllowedError):
        NetworkGuard().validate("http://192.168.1.1/router")


def test_cloud_metadata_endpoint_is_rejected() -> None:
    """169.254.169.254 bulut sağlayıcısının kimlik sunucusudur."""
    with pytest.raises(UrlNotAllowedError):
        NetworkGuard().validate("http://169.254.169.254/latest/meta-data/")


def test_allowlist_covers_subdomains_and_blocks_others() -> None:
    guard = NetworkGuard(allowed_domains=["example.com"])

    assert guard.validate("https://example.com/a")
    assert guard.validate("https://api.example.com/b")
    with pytest.raises(UrlNotAllowedError):
        guard.validate("https://baska-site.com/c")


def test_no_guard_means_no_research_tool() -> None:
    registry = ToolRegistry()

    assert register_research_tool(registry, guard=None) == []


def test_fetch_tool_requires_approval() -> None:
    """Dışarı çıkan bir istek iz bırakır ve veri sızdırabilir; sessiz olmamalı."""
    assert FetchUrlTool(guard=NetworkGuard()).permission is PermissionLevel.WRITE


# ---------------------------------------------------------------------------
# HTML metne çevirme
# ---------------------------------------------------------------------------


def test_script_and_style_are_stripped() -> None:
    """Script içeriği hem bağlamı doldurur hem talimat gömmek için idealdir."""
    html = (
        "<html><head><style>body{color:red}</style></head>"
        "<body><script>alert('gizli talimat')</script>"
        "<p>Gerçek içerik</p></body></html>"
    )

    text = html_to_text(html)

    assert "Gerçek içerik" in text
    assert "gizli talimat" not in text
    assert "color:red" not in text


def test_entities_are_decoded() -> None:
    assert "a & b" in html_to_text("<p>a &amp; b</p>")


def test_fetched_content_is_fenced() -> None:
    """Bir web sayfası, modele talimat gibi okunacak metin yazmak için en kolay yerdir."""
    import inspect

    source = inspect.getsource(FetchUrlTool.execute)
    assert 'fence("web_page"' in source
    assert UNTRUSTED_OPEN
