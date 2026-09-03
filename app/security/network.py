"""Ağ erişiminin bekçisi — dosya bekçisinin (`PathGuard`) ağ karşılığı.

Ajana internet vermek, dosya vermekten daha az tehlikeli DEĞİLDİR ve tehlike
farklı bir yerden gelir: bir URL yalnızca dışarıyı değil, İÇERİYİ de
gösterebilir. `http://169.254.169.254/` bulut sağlayıcısının kimlik
sunucusudur; `http://127.0.0.1:8000/api/admin/llm` uygulamanın kendi yönetim
ucudur. Bir modelin "şu adresi getir" demesi yeterliyse, ajan kendi
güvenlik sınırını dışarıdan dolaşabilir.

Bu yüzden bekçi üç şeyi birden uygular:

1. **Şema kısıtı.** Yalnızca `http` ve `https`. `file://` bir dosya
   okuyucusudur ve dosya erişimi ayrı bir karardır.
2. **Özel ağ yasağı.** Çözümlenen ADRES özel, geri döngü, bağlantı-yerel
   veya ayrılmış bir aralıktaysa reddedilir. Ad üzerinden değil ADRES
   üzerinden bakılır: `localtest.me` gibi bir ad 127.0.0.1'e çözülür ve
   yalnızca ada bakan bir kontrol bunu kaçırırdı.
3. **İsteğe bağlı alan adı beyaz listesi.** Verilirse yalnızca listedeki
   alan adları (ve alt alanları) getirilebilir.

DNS yeniden bağlama (rebinding) hakkında dürüst olmak gerekir: burada adres
istek ANINDA çözülür, sonra istemci aynı adı yeniden çözer. Aradaki kısa
pencerede bir saldırgan adı özel bir adrese döndürebilir. Bunu tamamen
kapatmak, çözülmüş IP'ye doğrudan bağlanıp `Host` başlığını elle kurmayı
gerektirir; mevcut tehdit modelinde (kullanıcının kendi makinesinde çalışan,
kullanıcının kendi isteklerini yürüten bir ajan) bu maliyet kazanca değmez.
Sınır burada belgelenmiştir ki gelecekte bilerek karar verilebilsin.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Iterable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})

MAX_URL_LENGTH = 2048


class UrlNotAllowedError(PermissionError):
    """URL ağ politikasından geçemedi.

    Mesaj gerekçeyi söyler ama beyaz listeyi VERMEZ: reddedilen bir deneme,
    izin haritasını çıkarmaya yaramamalıdır — komut politikasıyla aynı ilke.
    """


class NetworkGuard:
    """Bir URL'nin getirilip getirilemeyeceğine karar verir."""

    def __init__(self, *, allowed_domains: Iterable[str] = ()) -> None:
        """
        Args:
            allowed_domains: İzin verilen alan adları. Boş bırakılırsa özel
                ağ dışındaki her adres getirilebilir. Bir ad verildiğinde
                alt alanları da kapsanır ("example.com" → "api.example.com").
        """
        self._allowed_domains = frozenset(
            domain.strip().lower().lstrip(".") for domain in allowed_domains if domain.strip()
        )

    @property
    def allowed_domains(self) -> frozenset[str]:
        return self._allowed_domains

    def validate(self, url: str) -> str:
        """URL'yi doğrular ve normalize edilmiş hâlini döndürür.

        Raises:
            UrlNotAllowedError: URL politikadan geçemezse.
        """
        candidate = url.strip()
        if not candidate or len(candidate) > MAX_URL_LENGTH:
            raise UrlNotAllowedError("URL boş veya fazla uzun.")

        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            raise UrlNotAllowedError("Yalnızca http ve https adresleri getirilebilir.")

        hostname = parsed.hostname
        if not hostname:
            raise UrlNotAllowedError("URL bir sunucu adı içermiyor.")

        if self._allowed_domains and not self._domain_allowed(hostname):
            raise UrlNotAllowedError("Bu alan adı izinli değil.")

        for address in self._resolve(hostname):
            if _is_private(address):
                # Adres üzerinden bakılır: bir ad özel bir adrese çözülüyorsa
                # adın kendisi masum görünse de erişim reddedilir.
                raise UrlNotAllowedError(
                    "Adres özel veya yerel bir ağa çözülüyor; getirilemez."
                )

        return candidate

    def _domain_allowed(self, hostname: str) -> bool:
        host = hostname.lower().rstrip(".")
        return any(
            host == domain or host.endswith(f".{domain}")
            for domain in self._allowed_domains
        )

    def _resolve(self, hostname: str) -> list[ipaddress._BaseAddress]:
        """Adı IP adreslerine çözer.

        Çözümleme başarısızsa BOŞ liste döner ve URL reddedilmez: var olmayan
        bir adı reddetmek gerekmez, istemci zaten bağlanamayacaktır. Asıl
        korunmak istenen şey, çözülebilen ve ÖZEL olan adreslerdir.
        """
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            logger.debug("network_guard_resolve_failed", extra={"hostname": hostname[:64]})
            return []

        addresses: list[ipaddress._BaseAddress] = []
        for info in infos:
            raw = info[4][0]
            try:
                addresses.append(ipaddress.ip_address(raw))
            except ValueError:
                continue
        return addresses


def _is_private(address: ipaddress._BaseAddress) -> bool:
    """Adres, dışarıya çıkmayan bir aralıkta mı?

    Tek tek sayılması bilinçlidir: `is_private` tek başına bağlantı-yerel
    (169.254.0.0/16) adresleri kapsar ama okuyanın bunu bilmesi gerekir.
    Bulut kimlik uçları tam olarak orada durduğu için ayrıca yazıldı.
    """
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )
