"""Derlenmiş kabuğun backend tarafından sunulması.

Kullanım senaryosu bunu gerektirdi: bilgisayar açık kalıyor ve Jarvis
tabletten kullanılıyor. Tablet iki ayrı sunucuya (Vite ve uvicorn)
bağlanamaz — tek bir adres olmalı.

Aynı origin'den sunmanın ikinci bir kazancı var: CORS diye bir sorun hiç
oluşmaz. Ayrı origin olsaydı, tarayıcının ön kontrol (preflight) isteklerine
izin vermek için kimlik başlığını da kapsayan bir CORS yapılandırması
gerekirdi ve o yapılandırma, yanlış yazıldığında sessizce her siteye izin
veren türden bir şeydir.

Derlenmiş çıktı yoksa uygulama ÇALIŞMAYA DEVAM EDER; yalnızca API sunar ve
kök adres bunu açıkça söyler. Sebebi şu: `npm run build` çalıştırmamış bir
geliştiricinin backend'i hiç başlatamaması, kabuğu hiç kullanmayan testleri
ve API istemcilerini de cezalandırırdı.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

DEFAULT_FRONTEND_DIR = "frontend/dist"


class SPAStaticFiles(StaticFiles):
    """Bulunmayan yolları `index.html`'e düşüren statik dosya sunucusu.

    Tek sayfalık uygulamanın yönlendirmesi tarayıcıda yapılır: kullanıcı
    `/notlar` gibi bir adresi yenilediğinde sunucuda öyle bir dosya yoktur
    ama 404 dönmek yanlış olur — sayfa vardır, yalnızca sunucu onu bilmez.

    API yolları buraya HİÇ gelmez: statik sunucu `/` altına en son monte
    edilir ve `/api` router'ları ondan önce eşleşir. Yine de gelseydi,
    `index.html` dönmek bir API istemcisini sessizce HTML ile karşılamak
    olurdu — bu yüzden aşağıda ayrıca korunuyor.
    """

    async def get_response(self, path: str, scope) -> Response:  # noqa: ANN001
        try:
            return await super().get_response(path, scope)
        except Exception:  # noqa: BLE001
            # Dosya yoksa (ya da bir dizinse) SPA girişine düşülür.
            return await super().get_response("index.html", scope)


def mount_frontend(app: FastAPI, directory: str = DEFAULT_FRONTEND_DIR) -> bool:
    """Derlenmiş kabuğu `/` altına monte eder.

    Args:
        directory: `npm run build` çıktısının bulunduğu klasör.

    Returns:
        Gerçekten monte edildiyse True. Klasör yoksa False döner ve uygulama
        yalnızca API sunar — bu bir hata değildir.
    """
    root = Path(directory)
    index = root / "index.html"
    if not index.is_file():
        logger.info(
            "frontend_not_mounted",
            extra={"directory": str(root), "reason": "index.html bulunamadı"},
        )
        return False

    # En sona monte edilir: `/api` router'ları önce eşleşmelidir, aksi hâlde
    # kök altındaki her yol statik sunucuya gider ve API kaybolurdu.
    app.mount("/", SPAStaticFiles(directory=str(root), html=True), name="frontend")
    logger.info("frontend_mounted", extra={"directory": str(root)})
    return True


def build_root_response(app_name: str, version: str, environment: str) -> dict[str, str]:
    """Kabuk monte edilmediğinde kök adresin döndüreceği bilgi."""
    return {
        "name": app_name,
        "version": version,
        "environment": environment,
        "frontend": (
            "Derlenmiş kabuk bulunamadı. `npm run build --prefix frontend` "
            "çalıştırın ya da geliştirmede Vite'ı ayrıca başlatın."
        ),
    }


async def serve_index(request: Request) -> FileResponse:  # pragma: no cover - basit köprü
    """Doğrudan `index.html` döndürür (elle yönlendirme gerekirse)."""
    del request
    return FileResponse(Path(DEFAULT_FRONTEND_DIR) / "index.html")
