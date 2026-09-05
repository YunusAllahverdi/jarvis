"""Masadaki Dosyalar ve Web pencerelerinin okuduğu uçlar.

Bu uçlar bir TARAYICI penceresinden çağrılır; testlerin ağırlığı bu yüzden
"doğru veriyi döndürüyor mu"dan çok "kapalı olması gereken kapı kapalı mı"
üzerinde.

Kapsam — dosyalar:
 1. Kök listelenir, klasörler önce gelir
 2. Alt klasöre inilir ve üst klasör bildirilir
 3. Kökten yukarı çıkılamaz (parent kökte None)
 4. Kökün DIŞI 403
 5. Hassas dosyalar (.env) listede HİÇ görünmez
 6. Bekçi kurulu değilse 503 — "her yeri listele"ye düşmez
 7. Olmayan klasör 404
 8. Dönen yollar göreli ve ileri eğik çizgili (platformdan bağımsız)

Kapsam — web:
 9. Sayfa metne çevrilir ve ÇİTLENMEDEN döner (okuyucu kullanıcıdır)
10. Bekçiden geçmeyen adres 403
11. Yönlendirme İZLENMEZ, yalnızca bildirilir
12. Desteklenmeyen içerik türü 415
13. Bekçi kurulu değilse 503
14. Script ve style içeriği metne karışmaz
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.files import router as files_router
from app.api.routes.research import router as research_router
from app.config.settings import Settings
from app.security.network import NetworkGuard
from app.security.paths import PathGuard

# ---------------------------------------------------------------------------
# Dosyalar
# ---------------------------------------------------------------------------


def _files_client(root: Path | None) -> TestClient:
    app = FastAPI()
    app.state.workspace_guard = PathGuard(root) if root is not None else None
    app.include_router(files_router, prefix="/api")
    return TestClient(app)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """İçinde bir klasör, bir dosya ve bir de hassas dosya olan kök."""
    (tmp_path / "belgeler").mkdir()
    (tmp_path / "belgeler" / "plan.md").write_text("plan", encoding="utf-8")
    (tmp_path / "notlar.txt").write_text("merhaba", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    return tmp_path


def test_root_lists_directories_before_files(workspace: Path) -> None:
    """Klasörler önce gelmeli; karışık sıra gezinmeyi zorlaştırırdı."""
    body = _files_client(workspace).get("/api/files").json()

    names = [entry["name"] for entry in body["entries"]]
    assert names[0] == "belgeler"
    assert "notlar.txt" in names


def test_subdirectory_reports_its_parent(workspace: Path) -> None:
    """Alt klasörde "üst klasör" bilinmeli, yoksa geri dönülemezdi."""
    body = _files_client(workspace).get("/api/files", params={"path": "belgeler"}).json()

    assert body["path"] == "belgeler"
    assert body["parent"] == ""
    assert [entry["name"] for entry in body["entries"]] == ["plan.md"]


def test_root_has_no_parent(workspace: Path) -> None:
    """Kökten yukarı çıkılamaz."""
    assert _files_client(workspace).get("/api/files").json()["parent"] is None


def test_outside_the_root_is_forbidden(workspace: Path) -> None:
    """Kökün dışı kapalıdır; `..` ile çıkılamaz."""
    response = _files_client(workspace).get("/api/files", params={"path": "../.."})

    assert response.status_code == 403


def test_sensitive_files_are_not_even_listed(workspace: Path) -> None:
    """`.env` listede GÖRÜNMEZ.

    Görünüp açılamaması, var olduğunu söylemek olurdu — dosya adının
    kendisi de bir bilgidir.
    """
    body = _files_client(workspace).get("/api/files").json()

    assert all(entry["name"] != ".env" for entry in body["entries"])


def test_paths_are_relative_and_forward_slashed(workspace: Path) -> None:
    """Yollar istemcide URL'ye konur; biçim platformdan bağımsız olmalı."""
    body = _files_client(workspace).get("/api/files", params={"path": "belgeler"}).json()

    assert body["entries"][0]["path"] == "belgeler/plan.md"


def test_missing_directory_is_not_found(workspace: Path) -> None:
    response = _files_client(workspace).get("/api/files", params={"path": "yok"})

    assert response.status_code == 404


def test_files_endpoint_is_closed_without_a_guard() -> None:
    """Bekçi yoksa uç kapalıdır; "her yeri listele"ye DÜŞMEZ."""
    response = _files_client(None).get("/api/files")

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------


def _research_client(
    handler=None, *, guard: NetworkGuard | None = None
) -> TestClient:
    """Ağa çıkmadan uç davranışını sınayan istemci.

    `httpx.AsyncClient` uç içinde kurulduğu için taşıma katmanı monkeypatch
    ile değil, gerçek bir yerel sunucu gibi davranan bir yakalayıcıyla
    değiştirilir (aşağıdaki fixture).
    """
    app = FastAPI()
    app.state.network_guard = guard
    app.state.settings = Settings(research_timeout_seconds=5.0)
    app.include_router(research_router, prefix="/api")
    return TestClient(app)


@pytest.fixture()
def transport(monkeypatch: pytest.MonkeyPatch):
    """`httpx.AsyncClient`'ı sahte bir taşıma katmanıyla kurar."""

    def install(handler) -> None:
        original = httpx.AsyncClient.__init__

        def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            kwargs["transport"] = httpx.MockTransport(handler)
            original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)

    return install


def test_page_is_returned_as_readable_text(transport) -> None:
    """İçerik ÇİTLENMEDEN döner: buradaki okuyucu model değil, kullanıcıdır."""
    transport(lambda request: httpx.Response(
        200,
        html="<html><head><title>Başlık</title></head><body><p>Merhaba</p></body></html>",
    ))
    client = _research_client(guard=NetworkGuard())

    body = client.post("/api/research/fetch", json={"url": "https://ornek.test/a"}).json()

    assert body["title"] == "Başlık"
    assert "Merhaba" in body["content"]
    assert "UNTRUSTED" not in body["content"]


def test_script_and_style_do_not_leak_into_the_text(transport) -> None:
    """JavaScript kaynağı metne karışmamalı."""
    transport(lambda request: httpx.Response(
        200,
        html="<html><body><script>var gizli=1;</script><p>Görünen</p></body></html>",
    ))
    client = _research_client(guard=NetworkGuard())

    content = client.post(
        "/api/research/fetch", json={"url": "https://ornek.test/a"}
    ).json()["content"]

    assert "Görünen" in content
    assert "gizli" not in content


def test_blocked_address_is_forbidden() -> None:
    """Geri döngü adresi bekçiden geçmez."""
    client = _research_client(guard=NetworkGuard())

    response = client.post("/api/research/fetch", json={"url": "http://127.0.0.1/a"})

    assert response.status_code == 403


def test_redirect_is_reported_but_not_followed(transport) -> None:
    """Yönlendirme izlenseydi, denetlenen adresle getirilen ayrışırdı."""
    transport(lambda request: httpx.Response(
        302, headers={"location": "https://baska.test/b"}
    ))
    client = _research_client(guard=NetworkGuard())

    body = client.post("/api/research/fetch", json={"url": "https://ornek.test/a"}).json()

    assert body["redirected_to"] == "https://baska.test/b"
    assert body["content"] == ""


def test_binary_content_type_is_rejected(transport) -> None:
    """İkili içerik gösterilemez; indirilmesi yalnızca risk taşırdı."""
    transport(lambda request: httpx.Response(
        200, content=b"\x89PNG", headers={"content-type": "image/png"}
    ))
    client = _research_client(guard=NetworkGuard())

    response = client.post("/api/research/fetch", json={"url": "https://ornek.test/a.png"})

    assert response.status_code == 415


def test_research_endpoint_is_closed_without_a_guard() -> None:
    """Araştırma kapalıyken uç da kapalıdır."""
    response = _research_client(guard=None).post(
        "/api/research/fetch", json={"url": "https://ornek.test/a"}
    )

    assert response.status_code == 503
