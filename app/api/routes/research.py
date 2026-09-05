"""Masadaki Web penceresinin okuduğu uç.

Tarayıcı bir sayfayı kendisi de getirebilirdi; bu uç iki şey için var:

1. **CORS.** Bir `<iframe>` ya da tarayıcıdan yapılan `fetch`, sayfaların
   çoğunda çalışmaz. Sunucu üzerinden geçmek pencereyi gerçekten kullanılır
   yapan tek yol.
2. **Aynı bekçi.** Adres, ajanın `fetch_url` aracıyla AYNI `NetworkGuard`
   üzerinden geçer. İkinci bir kural kümesi yazmak, zamanla ajanın
   giremediği bir yere pencerenin girebilmesi demek olurdu.

Ajanın aracından bir fark vardır ve bilinçlidir: dönen metin **çitlenmez**.
Çit, metnin modele talimat gibi okunmasını engellemek içindir; buradaki
okuyucu modeldir değil kullanıcıdır ve ona çit işaretleri yalnızca gürültü
olarak görünürdü. Metin arayüze veri olarak gider, hiçbir istem'e
eklenmez.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.security.network import NetworkGuard, UrlNotAllowedError
from app.tools.builtin.research import (
    MAX_RESPONSE_BYTES,
    html_to_text,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["research"], prefix="/research")

MAX_PAGE_CHARS = 40_000
"""Pencereye taşınacak en fazla karakter.

Ajanınkinden (12k) daha cömert: oradaki sınır bağlam penceresini korur,
buradaki yalnızca tarayıcının boğulmasını engeller.
"""

_UNAVAILABLE_DETAIL = {
    "code": "research_unavailable",
    "message": "Web erişimi kapalı. Ayarlardan araştırmayı açın.",
}

_ALLOWED_CONTENT_PREFIXES = ("text/", "application/json", "application/xml")


class FetchRequest(BaseModel):
    """Getirilecek adres."""

    url: str = Field(min_length=1, max_length=2048)


class FetchResponse(BaseModel):
    """Getirilen sayfanın okunabilir hâli."""

    url: str
    status_code: int
    title: str = ""
    content: str = ""
    truncated: bool = False
    redirected_to: str | None = None
    """Yönlendirme İZLENMEZ; hedef yalnızca bildirilir.

    Kontrol edilen adresle getirilen adresin ayrışmaması için: bekçiden
    geçen bir adres, geçmeyen bir adrese yönlendirebilirdi.
    """


def _guard(request: Request) -> NetworkGuard:
    guard = getattr(request.app.state, "network_guard", None)
    if guard is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE_DETAIL
        )
    return guard


def _title_of(html: str) -> str:
    """`<title>` içeriğini kaba biçimde çıkarır; yoksa boş dize."""
    lowered = html.lower()
    start = lowered.find("<title")
    if start == -1:
        return ""
    open_end = lowered.find(">", start)
    close = lowered.find("</title>", open_end)
    if open_end == -1 or close == -1:
        return ""
    return html[open_end + 1 : close].strip()[:200]


@router.post("/fetch", response_model=FetchResponse)
async def fetch_page(body: FetchRequest, request: Request) -> FetchResponse:
    """Bir adresi sunucu üzerinden getirir ve metnini döndürür."""
    guard = _guard(request)
    timeout = float(
        getattr(request.app.state.settings, "research_timeout_seconds", 20.0)
    )

    try:
        url = guard.validate(body.url)
    except UrlNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "url_not_allowed", "message": str(exc)},
        ) from exc

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(url, headers={"User-Agent": "Jarvis/0.1"})
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"code": "fetch_timeout", "message": "İstek zaman aşımına uğradı."},
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "fetch_failed", "message": "Adrese ulaşılamadı."},
        ) from exc

    if response.is_redirect:
        return FetchResponse(
            url=url,
            status_code=response.status_code,
            redirected_to=response.headers.get("location", "")[:2048],
        )

    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type and not content_type.startswith(_ALLOWED_CONTENT_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "unsupported_content_type",
                "message": f"Bu içerik türü gösterilemiyor: {content_type}",
            },
        )

    raw = response.content[:MAX_RESPONSE_BYTES]
    text = raw.decode(response.encoding or "utf-8", errors="replace")
    is_html = "html" in content_type
    body_text = html_to_text(text) if is_html else text.strip()

    logger.info(
        "desk_page_fetched",
        extra={"status_code": response.status_code, "content_type": content_type},
    )

    return FetchResponse(
        url=url,
        status_code=response.status_code,
        title=_title_of(text) if is_html else "",
        content=body_text[:MAX_PAGE_CHARS],
        truncated=len(body_text) > MAX_PAGE_CHARS,
    )
