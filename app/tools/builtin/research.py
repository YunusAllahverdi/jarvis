"""Araştırma aracı — ajanın bir şeye BAKABİLMESİ.

Coding Agent V1'in 14 kriterinden 5'incisi ("araştırma yapabilmeli") bu araç
gelene kadar tamamen boştu: ajan bir kütüphanenin belgesine, bir hata
mesajının anlamına ya da bir API'nin sözleşmesine bakamıyordu.

İZİN SEVİYESİ NEDEN READ DEĞİL: Bir sayfa getirmek yerel bir dosya okumak
gibi görünür ama değildir. Dışarıya çıkan her istek bir İZ bırakır ve
istenen adres, ajanın bağlamındaki bir metinden gelmiş olabilir — yani
kullanıcının belleğinde duran bir bilgi, bir URL'nin sorgu dizesine
konarak dışarı sızdırılabilir. Bu yüzden araç WRITE izinlidir ve her
çağrısı kullanıcı onayından geçer. "Okuma" sayılsaydı sessizce çalışırdı.

Getirilen içerik GÜVENİLMEZ VERİDİR ve öyle işaretlenir: bir web sayfası,
modele talimat gibi okunacak metin yazmak için en kolay yerdir.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from pydantic import Field

from app.security.fencing import fence
from app.security.network import NetworkGuard, UrlNotAllowedError
from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput

logger = logging.getLogger(__name__)

FETCH_URL_TOOL_NAME = "fetch_url"

MAX_CONTENT_CHARS = 12_000
"""Modele taşınacak en fazla karakter.

Bir web sayfası megabaytlarca olabilir; sınırsız içerik tek bir çağrıyla
bağlam penceresini doldururdu.
"""

MAX_RESPONSE_BYTES = 3_000_000
"""İndirilecek en fazla bayt.

Kırpma metne çevrildikten SONRA değil, indirme sırasında uygulanır: 500 MB'lık
bir dosyayı indirip sonra kırpmak, sınırın hiç olmaması demekti.
"""

DEFAULT_TIMEOUT_SECONDS = 20.0

_ALLOWED_CONTENT_PREFIXES = ("text/", "application/json", "application/xml")
"""Getirilebilen içerik türleri.

İkili içerik (görsel, arşiv, çalıştırılabilir) bilinçli olarak dışarıdadır:
modele verilemez ve indirilmesi yalnızca risk taşır.
"""

_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    """HTML'i kaba ama öngörülebilir biçimde düz metne çevirir.

    Tam bir HTML ayrıştırıcısı kullanılmaz ve bu bilinçlidir: amaç sayfayı
    yeniden üretmek değil, modelin okuyabileceği metni çıkarmaktır. Script ve
    style içeriği ÖNCE atılır — aksi hâlde JavaScript kaynağı metne karışır
    ve hem bağlamı doldurur hem de içine talimat gömmek için ideal bir yer
    olurdu.
    """
    without_code = _SCRIPT_STYLE.sub(" ", html)
    without_tags = _TAG.sub(" ", without_code)

    # Yaygın HTML varlıkları; tam bir çözümleme yerine en sık görülenler.
    for entity, replacement in (
        ("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"),
    ):
        without_tags = without_tags.replace(entity, replacement)

    collapsed = _WHITESPACE.sub(" ", without_tags)
    lines = [line.strip() for line in collapsed.splitlines()]
    return _BLANK_LINES.sub("\n\n", "\n".join(line for line in lines if line)).strip()


class FetchUrlInput(ToolInput):
    """`fetch_url` tool'unun doğrulanmış input'u."""

    url: str = Field(min_length=1, max_length=2048)


class FetchUrlTool(Tool[FetchUrlInput]):
    """Bir web sayfasını getirir ve metnini döndürür."""

    name = FETCH_URL_TOOL_NAME
    description = (
        "Bir web adresinin içeriğini getirir ve düz metne çevirir. "
        "Belgelere, hata açıklamalarına ve API sözleşmelerine bakmak için."
    )
    permission = PermissionLevel.WRITE
    input_model = FetchUrlInput

    def __init__(
        self,
        *,
        guard: NetworkGuard,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_content_chars: int = MAX_CONTENT_CHARS,
    ) -> None:
        """
        Args:
            guard: URL'nin getirilip getirilemeyeceğine karar veren bekçi.
            timeout_seconds: Tek bir isteğin en uzun süresi.
            max_content_chars: Modele taşınacak en fazla karakter.
        """
        self._guard = guard
        self._timeout = timeout_seconds
        self._max_chars = max_content_chars

    async def execute(self, tool_input: FetchUrlInput) -> dict[str, Any]:
        try:
            url = self._guard.validate(tool_input.url)
        except UrlNotAllowedError as exc:
            raise ToolExecutionError(str(exc)) from exc

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                # Yönlendirmeler İZLENMEZ. Bir yönlendirme, bekçiden geçmiş
                # bir adresi geçmemiş bir adrese çevirebilir; kontrol edilen
                # ile getirilen ayrışırdı. Yeni adres dönerse ajan onu ayrı
                # bir çağrıyla — yani yeniden onaydan geçerek — isteyebilir.
                follow_redirects=False,
            ) as client:
                response = await client.get(url, headers={"User-Agent": "Jarvis/0.1"})
        except httpx.TimeoutException as exc:
            raise ToolExecutionError("İstek zaman aşımına uğradı.") from exc
        except httpx.HTTPError as exc:
            raise ToolExecutionError("Adrese ulaşılamadı.") from exc

        if response.is_redirect:
            location = response.headers.get("location", "")
            return {
                "url": url,
                "status_code": response.status_code,
                "redirected_to": location[:2048],
                "content": "",
                "truncated": False,
                "note": (
                    "Adres başka bir yere yönlendiriyor. Yönlendirme izlenmedi; "
                    "gerekiyorsa yeni adresi ayrıca isteyin."
                ),
            }

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith(_ALLOWED_CONTENT_PREFIXES):
            raise ToolExecutionError(f"Desteklenmeyen içerik türü: {content_type}")

        raw = response.content[:MAX_RESPONSE_BYTES]
        text = raw.decode(response.encoding or "utf-8", errors="replace")
        body = html_to_text(text) if "html" in content_type else text.strip()

        truncated = len(body) > self._max_chars
        logger.info(
            "url_fetched",
            extra={
                "status_code": response.status_code,
                "content_type": content_type,
                "truncated": truncated,
            },
        )

        return {
            "url": url,
            "status_code": response.status_code,
            "content_type": content_type,
            # İçerik ÇİTLENEREK döner: bir web sayfası, modele talimat gibi
            # okunacak metin yazmak için en kolay yerdir.
            "content": fence("web_page", body[: self._max_chars]),
            "truncated": truncated,
        }
