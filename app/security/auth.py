"""Uygulamanın kimlik doğrulama katmanı.

Bu, projenin en uzun süre açık kalan borcuydu: bütün uçlar herkese açıktı ve
tek koruma, sunucunun yalnızca `127.0.0.1`'i dinlemesiydi. Bir kişisel asistan
kullanıcının belleğini, dosyalarını ve terminalini taşıdığı için bu yeterli
değildir.

KURAL TEK CÜMLEYLE: Sunucu yerel adres dışına bağlıysa bir anahtar ZORUNLUDUR.

    ┌──────────────┬───────────────┬─────────────────────────────────┐
    │ Bağlı adres  │ Anahtar var mı│ Sonuç                            │
    ├──────────────┼───────────────┼─────────────────────────────────┤
    │ 127.0.0.1    │ hayır         │ Serbest (tek kullanıcılı makine) │
    │ 127.0.0.1    │ evet          │ Anahtar istenir                  │
    │ 0.0.0.0 vb.  │ hayır         │ HER İSTEK REDDEDİLİR             │
    │ 0.0.0.0 vb.  │ evet          │ Anahtar istenir                  │
    └──────────────┴───────────────┴─────────────────────────────────┘

Üçüncü satır bilinçlidir ve bu modülün asıl varlık sebebidir: sunucuyu ağa
açmak tek bir ayar değişikliğidir ve o değişikliği yapan kişi, kimlik
katmanının da gerektiğini fark etmeyebilir. Uygulamayı açılışta reddettirmek
yerine her isteği reddetmek tercih edildi — böylece sebep, sunucu loglarında
değil isteği yapanın elinde görünür.

Anahtar karşılaştırması SABİT ZAMANLIDIR: uzunluk veya ilk farklı karakter
üzerinden anahtar tahmin edilememelidir.

Sağlık ucu bilinçli olarak muaftır: bir yük dengeleyici ya da container
sağlık kontrolü, uygulamanın ayakta olup olmadığını anahtarsız sorabilmelidir
ve o uç hiçbir kullanıcı verisi döndürmez.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Iterable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

API_TOKEN_HEADER = "X-Jarvis-Token"
"""Anahtarın taşındığı başlık.

`Authorization: Bearer` de kabul edilir; tarayıcıdan çağıran bir istemci için
özel bir başlık daha az sürprizlidir, komut satırından çağıran için Bearer
daha tanıdıktır.
"""

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

PROTECTED_PREFIX = "/api"
"""Korunan yolların öneki.

KORUNAN ŞEY API'DİR, SAYFA DEĞİL. Bu ayrım zorunludur: backend derlenmiş
kabuğu da sunar ve sayfanın kendisi anahtarla korunsaydı, kullanıcı anahtarı
gireceği ekranı hiç göremezdi — tabletten bağlanmak imkânsız olurdu.

Sayfayı açık bırakmak bir taviz değildir: derlenmiş kabuk herkese açık
HTML ve JavaScript'tir, hiçbir sır taşımaz. Korunması gereken, onun
konuştuğu uçlardır ve `/api` öneki tam olarak onları kapsar.
"""

DEFAULT_EXEMPT_PATHS: tuple[str, ...] = ("/api/v1/health",)
"""`/api` altında olduğu hâlde anahtarsız erişilebilen yollar.

Yalnızca sağlık ucu. Liste bilinçli olarak KISA tutulur: her muafiyet,
kimlik katmanında açılmış bir delik demektir ve buraya eklenen her yol
"bu uç hiçbir kullanıcı verisi döndürmüyor mu?" sorusunu geçmelidir.
"""


def is_local_host(host: str) -> bool:
    """Verilen bağlanma adresi yerel makineyle mi sınırlı?"""
    return host.strip().lower() in LOCAL_HOSTS


def _provided_token(request: Request) -> str:
    """İstekten anahtarı çıkarır; yoksa boş dize.

    İki biçim de kabul edilir. Boş dize dönmesi "anahtar yok" demektir ve
    sabit zamanlı karşılaştırmada yine de reddedilir.
    """
    header = request.headers.get(API_TOKEN_HEADER)
    if header:
        return header

    authorization = request.headers.get("Authorization", "")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value:
        return value.strip()
    return ""


class ApiTokenMiddleware(BaseHTTPMiddleware):
    """Her isteği kimlik kuralından geçirir.

    Yönlendirmeden ÖNCE çalışır: kural, uçların tek tek hatırlaması gereken
    bir şey değildir. Yeni bir router eklendiğinde onu korumak için ayrıca
    bir şey yapılması gerekmez — muaf tutmak için yapılması gerekir.
    """

    def __init__(
        self,
        app,  # noqa: ANN001 - Starlette ASGI uygulaması
        *,
        token: str,
        host: str,
        exempt_paths: Iterable[str] = DEFAULT_EXEMPT_PATHS,
    ) -> None:
        """
        Args:
            token: Beklenen anahtar. Boşsa yalnızca yerel erişime izin verilir.
            host: Sunucunun bağlandığı adres.
            exempt_paths: Anahtarsız erişilebilen yollar.
        """
        super().__init__(app)
        self._token = token.strip()
        self._local = is_local_host(host)
        self._exempt = frozenset(exempt_paths)

        if not self._token and not self._local:
            # Açılışta bir kez uyarılır; her istekte tekrar loglamak, saldırı
            # altında log dosyasını dolduran bir mekanizma olurdu.
            logger.warning(
                "api_token_required_but_missing",
                extra={"host": host},
            )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        decision = self._reject_reason(request)
        if decision is not None:
            code, message, status_code = decision
            logger.info(
                "request_rejected_by_auth",
                extra={"code": code, "path": request.url.path},
            )
            return JSONResponse(
                status_code=status_code,
                content={"detail": {"code": code, "message": message}},
            )
        return await call_next(request)

    def _reject_reason(self, request: Request) -> tuple[str, str, int] | None:
        """İstek reddedilecekse `(kod, mesaj, http_durumu)`, aksi hâlde None."""
        path = request.url.path

        # Sayfa ve varlıkları serbesttir; korunan API'dir. Aksi hâlde
        # kullanıcı anahtarı gireceği ekranı hiç göremezdi.
        if not path.startswith(PROTECTED_PREFIX):
            return None

        if path in self._exempt:
            return None

        if self._token:
            if secrets.compare_digest(_provided_token(request), self._token):
                return None
            return (
                "unauthorized",
                f"Geçerli bir anahtar gerekiyor ({API_TOKEN_HEADER} başlığı).",
                401,
            )

        if self._local:
            return None

        return (
            "api_token_required",
            (
                "Sunucu yerel adres dışına bağlı. Kimlik doğrulama olmadan "
                "çalışamaz; JARVIS_API_TOKEN tanımlayın."
            ),
            403,
        )
