"""İstek başına korelasyon kimliği (request-id) taşıyan bağlam.

Her isteğe bir kimlik atanır; bu kimlik hem yanıt başlığına eklenir hem de
o istek sırasında üretilen TÜM log kayıtlarına otomatik olarak iliştirilir.
Böylece tek bir kullanıcı isteğinin ardındaki onlarca log satırı, başka
isteklerin satırlarıyla karışmadan bir arada görülebilir.

Kimlik bir `contextvars.ContextVar`'da tutulur: her istek kendi async
bağlamında çalıştığı için değerler birbirine sızmaz. Global bir sözlük
kullanılsaydı, eşzamanlı istekler birbirinin kimliğini görürdü.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
"""İstemcinin gönderebileceği ve yanıtta her zaman dönen başlık.

İstemci kendi kimliğini gönderirse (ör. bir üst servisin izleme kimliği)
korunur; göndermezse yenisi üretilir. Kimliği her zaman yeniden üretmek,
dağıtık izlemeyi (distributed tracing) imkânsız kılardı.
"""

_request_id: ContextVar[str | None] = ContextVar("jarvis_request_id", default=None)


def current_request_id() -> str | None:
    """Şu an işlenen isteğin kimliği; bağlam dışındaysa None."""

    return _request_id.get()


def _sanitize(value: str) -> str:
    """İstemciden gelen kimliği güvenli bir uzunluk ve karakter kümesine indirger.

    Kimlik log satırlarına ve yanıt başlığına girer. Doğrulanmadan
    geçirilseydi, satır sonu veya kontrol karakterleri içeren bir değer log
    dosyasını bozabilir ya da sahte satırlar üretebilirdi.
    """

    cleaned = value.strip()
    if not cleaned or len(cleaned) > 128:
        return uuid.uuid4().hex
    if not all(char.isalnum() or char in "-_." for char in cleaned):
        return uuid.uuid4().hex
    return cleaned


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Her isteğe bir kimlik atar ve onu yanıt başlığına yazar."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = _sanitize(incoming) if incoming else uuid.uuid4().hex

        token = _request_id.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            _request_id.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
