"""API'nin tek ve tutarlı hata yanıtı biçimi.

Tüm hatalar aynı zarfı kullanır::

    {"detail": {"code": "...", "message": "..."}}

`code` makine tarafından eşleştirilebilir kararlı bir simgedir; `message`
kullanıcıya gösterilebilecek Türkçe metindir. İstek kimliği gövdeye değil
`X-Request-ID` başlığına yazılır (bkz. `app.core.request_context`): gövde
sözleşmesi sabit kalır, korelasyon için standart yer kullanılır.

Bu biçim zaten uçların çoğunda kullanılıyordu; buradaki iş onu TEK bir
yerden üretmek ve çerçevenin kendi ürettiği hataları (doğrulama, 404, 500)
da aynı zarfa sokmaktır. Aksi hâlde istemci iki farklı hata şeklini
tanımak zorunda kalırdı.
"""

from __future__ import annotations

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def error_body(code: str, message: str) -> dict[str, object]:
    """Tutarlı hata gövdesini üretir."""

    return {"detail": {"code": code, "message": message}}


# Durum kodu -> (kararlı hata simgesi, Türkçe kullanıcı mesajı).
# Çerçevenin ürettiği hatalar İngilizce gelir ("Not Found"); arayüz tamamen
# Türkçe olduğu için burada çevrilir. Uçların kendi mesajları varsa onlara
# dokunulmaz.
_STATUS_MAP: dict[int, tuple[str, str]] = {
    status.HTTP_400_BAD_REQUEST: ("bad_request", "İstek geçersiz."),
    status.HTTP_401_UNAUTHORIZED: ("unauthorized", "Kimlik doğrulama gerekiyor."),
    status.HTTP_403_FORBIDDEN: ("forbidden", "Bu işlem için yetkiniz yok."),
    status.HTTP_404_NOT_FOUND: ("not_found", "Kaynak bulunamadı."),
    status.HTTP_405_METHOD_NOT_ALLOWED: ("method_not_allowed", "Bu yöntem desteklenmiyor."),
    status.HTTP_409_CONFLICT: ("conflict", "İstek mevcut durumla çakışıyor."),
    # 422: `status.HTTP_422_UNPROCESSABLE_ENTITY` Starlette'te kullanımdan
    # kaldırıldı; sabit sayı, uyarıyı tetiklemeden aynı kodu taşır.
    422: ("validation_error", "İstek gövdesi veya parametreleri geçersiz."),
    status.HTTP_429_TOO_MANY_REQUESTS: ("too_many_requests", "Çok fazla istek gönderildi."),
    status.HTTP_503_SERVICE_UNAVAILABLE: ("service_unavailable", "Servis şu an kullanılamıyor."),
}


def _default_phrase(status_code: int) -> str:
    """Durum kodunun çerçevenin kullandığı İngilizce ifadesi."""

    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return ""


def _describe(status_code: int) -> tuple[str, str]:
    """Durum kodunu kararlı bir simge ve Türkçe mesaja eşler."""

    return _STATUS_MAP.get(status_code, ("http_error", "İstek işlenemedi."))


def register_exception_handlers(app: FastAPI) -> None:
    """Çerçeve hatalarını tutarlı zarfa bağlar.

    Uçların kendi `HTTPException(detail={...})` çağrıları KORUNUR: onlar
    zaten zarflıdır ve burada yalnızca dokunulmadan geçirilir.
    """

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Uç kendi kodunu verdiyse ona dokunulmaz; yalnızca çıplak bir
        # `detail` metni ya da eksik zarf tutarlı hâle getirilir.
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=error_body(
                    str(exc.detail.get("code")),
                    str(exc.detail.get("message", "")),
                ),
                headers=getattr(exc, "headers", None),
            )
        code, default_message = _describe(exc.status_code)
        # Çerçeve, kendi ürettiği hatalarda `detail` olarak İngilizce durum
        # ifadesini koyar ("Not Found"). Onu Türkçe karşılığıyla değiştiririz;
        # yalnızca uç özel bir metin verdiyse o metin korunur.
        message = default_message
        if (
            isinstance(exc.detail, str)
            and exc.detail
            and exc.detail != _default_phrase(exc.status_code)
        ):
            message = exc.detail
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "İstek gövdesi veya parametreleri geçersiz.",
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        # Beklenmeyen hata: ayrıntı LOG'A yazılır, istemciye ASLA sızdırılmaz.
        # Bir yığın izi veya iç yol, saldırgana keşif bilgisi verirdi.
        logger.exception("unhandled_error", extra={"path": request.url.path})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("internal_error", "Beklenmeyen bir sunucu hatası oluştu."),
        )
