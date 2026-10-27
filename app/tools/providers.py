"""Çok kaynaklı araçlar için tek tip sağlayıcı sözleşmesi.

Sonraki parçalar MCP sunucuları, Home Assistant, tarayıcı ve bilgisayar
kontrolü araç ekleyecek. Hepsi aynı soruları yanıtlamak zorunda:

- "Bu yapılandırmada etkin misin?"  → `enabled(settings)`
- "Hangi araçları sağlıyorsun?"     → `tools()`
- "Şu an sağlıklı mısın?"           → `health()`
- "Kaynaklarını serbest bırak."     → `aclose()`

Bu sorular tek bir `ToolProvider` sözleşmesinde toplanır. Sağlayıcı, araçları
KENDİSİ bir registry'ye kaydetmez; yalnızca üretir. Kayıt ve çakışma denetimi
`CapabilityRegistry`'nin işidir — böylece iki sağlayıcı aynı aracı sağlasa bile
sessizce biri diğerini ezmez.

Sözleşme `async`'tir çünkü ileride MCP sunucuları araç listesini bir ağ
çağrısıyla alacaktır. Bugünkü yerleşik sağlayıcılar senkron bir fonksiyonu
sarmalar; sarmalayıcı (`FunctionToolProvider`) bu farkı tek yerde kapatır.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Tool

if TYPE_CHECKING:  # pragma: no cover - yalnızca tip denetimi
    from app.config.settings import Settings


class ProviderHealth(BaseModel):
    """Bir sağlayıcının sağlık durumu — yapılandırılmış, istisnasız.

    Sağlık kontrolü hiçbir zaman istisna fırlatmaz: erişilemeyen bir MCP
    sunucusu bir HATA değil, `ok=False` taşıyan bir durumdur. Çağıran
    (yönetim ucu) bunu olduğu gibi raporlar.
    """

    model_config = ConfigDict(frozen=True)

    ok: bool = True
    detail: str = ""
    """İnsan tarafından okunabilir kısa durum (ör. "3 araç sağlıyor")."""

    tool_count: int = Field(default=0, ge=0)
    """Sağlayıcının sağladığı araç sayısı (kapalıyken 0)."""


@runtime_checkable
class ToolProvider(Protocol):
    """Çok kaynaklı araç sağlayan birimlerin sözleşmesi."""

    id: str
    """Sağlayıcının kararlı kimliği (ör. "builtin", "mcp").

    Araç İSMİ değildir: aynı sağlayıcı birden çok araç sağlar ve kimlik
    yalnızca sağlayıcıyı tanımlar.
    """

    def enabled(self, settings: Settings) -> bool:
        """Sağlayıcı bu yapılandırmada etkin mi?

        Kapalı bir sağlayıcının araçları HİÇ üretilmez ve kaydedilmez.
        """
        ...

    async def tools(self) -> list[Tool[Any]]:
        """Sağlayıcının sunduğu araçları üretir.

        Araçları registry'ye KAYDETMEZ; yalnızca döndürür. Çakışma denetimi
        çağıranındır.
        """
        ...

    async def health(self) -> ProviderHealth:
        """Sağlayıcının şu anki durumunu döndürür; istisna fırlatmaz."""
        ...

    async def aclose(self) -> None:
        """Sağlayıcının tuttuğu kaynakları serbest bırakır.

        Yerleşik sağlayıcılar için bu bir no-op'tur; ağ bağlantısı tutan
        sağlayıcılar (MCP) için gerçek bir kapanıştır.
        """
        ...


class FunctionToolProvider:
    """Senkron bir araç üreticisini `ToolProvider` sözleşmesine saran yardımcı.

    Mevcut `register_*` fonksiyonlarını yeniden yazmadan bu arayüze taşımak
    için kullanılır: kayıt fonksiyonu, kaydettiği araçları döndürecek biçimde
    çağrılır ve üretilenler sağlayıcının araçları olur. Araçların KENDİSİ ve
    davranışı değişmez.
    """

    def __init__(
        self,
        *,
        provider_id: str,
        description: str,
        produce: Callable[[], Iterable[Tool[Any]]],
        is_enabled: Callable[[Settings], bool] | None = None,
    ) -> None:
        """
        Args:
            provider_id: Sağlayıcı kimliği.
            description: İnsan tarafından okunabilir açıklama.
            produce: Araçları üreten senkron fonksiyon. Etkinlik kararı
                VERMEZ; yalnızca mevcut kaynaklardan araç üretir.
            is_enabled: Etkinlik yüklemi. Verilmezse sağlayıcı her zaman
                etkindir — yerleşik araçların mevcut davranışını korur.
        """
        self.id = provider_id
        self.description = description
        self._produce = produce
        self._is_enabled = is_enabled

    def enabled(self, settings: Settings) -> bool:
        """Etkinlik yüklemi yoksa her zaman etkin (yerleşik davranış)."""

        if self._is_enabled is None:
            return True
        return bool(self._is_enabled(settings))

    async def tools(self) -> list[Tool[Any]]:
        """Senkron üreticiyi çalıştırıp araçları döndürür."""

        return list(self._produce())

    def tools_sync(self) -> list[Tool[Any]]:
        """`tools()`'un senkron eşdeğeri.

        Uygulama başlangıcı senkron bir bağlamda (`create_app`) çalışır ve
        yerleşik üreticiler hiçbir `await` içermez. Bu kısayol, başlangıçta
        gereksiz bir olay döngüsü kurmadan aynı araçları üretmeyi sağlar.
        Ağ çağrısı yapan sağlayıcılar (MCP) bu yolu KULLANMAZ; onlar yalnızca
        `tools()` üzerinden, olay döngüsü içinde çalışır.
        """

        return list(self._produce())

    async def health(self) -> ProviderHealth:
        """Üretilebilen araç sayısına göre basit bir sağlık durumu."""

        try:
            count = len(list(self._produce()))
        except Exception as exc:  # pragma: no cover - savunma katmanı
            return ProviderHealth(ok=False, detail=f"Araçlar üretilemedi: {exc}")
        return ProviderHealth(ok=True, detail=f"{count} araç sağlıyor.", tool_count=count)

    async def aclose(self) -> None:
        """Yerleşik sağlayıcı hiçbir kaynak tutmaz."""

        return None
