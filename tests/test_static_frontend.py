"""Derlenmiş kabuğun backend tarafından sunulması.

Senaryo: bilgisayar açık kalıyor, Jarvis tabletten kullanılıyor. Tablet iki
ayrı sunucuya bağlanamaz; tek bir adres olmalı.

Kapsam:
 1. Derlenmiş çıktı varsa kök adres kabuğu döndürür
 2. Varlıklar sunulur
 3. Bilinmeyen yol `index.html`'e düşer (SPA yönlendirmesi)
 4. Derlenmiş çıktı YOKSA uygulama çalışmaya devam eder ve API sunar
 5. Çıktı yoksa kök adres durumu açıkça söyler
 6. Kabuk monte edilse bile API yolları kaybolmaz
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.static import mount_frontend

_INDEX = "<!doctype html><html><body><div id='root'></div></body></html>"


def _built_frontend(tmp_path: Path) -> str:
    """`npm run build` çıktısını taklit eden bir klasör kurar."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(_INDEX, encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('jarvis');", encoding="utf-8")
    return str(dist)


def _app(directory: str) -> tuple[FastAPI, bool]:
    app = FastAPI()

    @app.get("/api/ping")
    async def _ping() -> dict[str, str]:
        return {"pong": "yes"}

    mounted = mount_frontend(app, directory)
    return app, mounted


def test_root_serves_the_shell(tmp_path: Path) -> None:
    app, mounted = _app(_built_frontend(tmp_path))

    assert mounted is True
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "<div id='root'>" in response.text


def test_assets_are_served(tmp_path: Path) -> None:
    app, _ = _app(_built_frontend(tmp_path))

    response = TestClient(app).get("/assets/app.js")

    assert response.status_code == 200
    assert "jarvis" in response.text


def test_unknown_path_falls_back_to_the_shell(tmp_path: Path) -> None:
    """Kullanıcı bir alt adresi yenilediğinde sayfa VARDIR; sunucu bilmez."""
    app, _ = _app(_built_frontend(tmp_path))

    response = TestClient(app).get("/notlar")

    assert response.status_code == 200
    assert "<div id='root'>" in response.text


def test_api_still_wins_over_the_shell(tmp_path: Path) -> None:
    """Statik sunucu `/` altına monte edilir; API yolları önce eşleşmelidir."""
    app, _ = _app(_built_frontend(tmp_path))

    response = TestClient(app).get("/api/ping")

    assert response.status_code == 200
    assert response.json() == {"pong": "yes"}


def test_missing_build_does_not_break_the_app(tmp_path: Path) -> None:
    """`npm run build` çalıştırmamış biri backend'i yine de başlatabilmeli."""
    app, mounted = _app(str(tmp_path / "hic-olmayan"))

    assert mounted is False
    assert TestClient(app).get("/api/ping").status_code == 200


def test_directory_without_index_is_not_mounted(tmp_path: Path) -> None:
    """Klasör var ama derleme yarım kalmışsa monte edilmemeli."""
    empty = tmp_path / "dist"
    empty.mkdir()

    _app_instance, mounted = _app(str(empty))

    assert mounted is False
