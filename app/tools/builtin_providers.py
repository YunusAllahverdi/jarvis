"""Yerleşik araç setlerini `ToolProvider` sözleşmesine saran sağlayıcılar.

Buradaki her sağlayıcı, daha önce `app/plugins/builtin.py` içindeki bir
eklentinin (ve dolayısıyla `app/tools/defaults.py` içindeki bir `register_*`
fonksiyonunun) yaptığı işi yapar. Araçların KENDİSİ ve davranışı değişmedi;
yalnızca kayıt noktası `CapabilityRegistry`'ye taşındı.

Nasıl çalışır: bir eklenti, araçlarını KENDİSİ bir registry'ye kaydeder.
Sağlayıcı sözleşmesi ise araçları üretmeyi ister. İkisini uzlaştırmak için
eklenti, GEÇİCİ bir registry'ye kaydettirilir ve ürettiği araçlar alınır;
gerçek kayıt `CapabilityRegistry`'de yapılır. Böylece eklenti kodu ve mevcut
`register_*` fonksiyonları HİÇ değişmez — davranış bit düzeyinde korunur.

İki sistem PARALEL BIRAKILMAZ: uygulama artık yetenekleri yalnızca
`CapabilityRegistry` üzerinden kurar. `Plugin`/`PluginRegistry` sözleşmesi
korunur (mevcut testler ve eklenti yazım kılavuzu ona dayanır), ama uygulama
başlangıcında tek yol vardır.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable

from app.plugins.base import Plugin, PluginContext
from app.plugins.builtin import BUILTIN_PLUGINS
from app.plugins.example import ExamplePlugin
from app.tools.base import Tool
from app.tools.defaults import build_default_tool_registry
from app.tools.providers import FunctionToolProvider, ToolProvider
from app.tools.registry import ToolRegistry

DEFAULT_PROVIDER_ID = "builtin"
"""Temel (her zaman açık) yerleşik araçların sağlayıcı kimliği."""


def _produce_via_plugin(plugin: Plugin, context: PluginContext) -> list[Tool]:
    """Bir eklentinin araçlarını geçici bir registry üzerinden üretir.

    Eklenti, kendi `register()`'ını değiştirmeden çalıştırılır; sonuç araç
    nesneleri toplanır ve gerçek kayıt çağırana bırakılır.
    """

    scratch = ToolRegistry()
    plugin.register(dataclasses.replace(context, registry=scratch))
    return list(scratch.list_tools())


def plugin_provider(plugin: Plugin, context: PluginContext) -> ToolProvider:
    """Bir `Plugin`'i `ToolProvider` sözleşmesine sarar."""

    return FunctionToolProvider(
        provider_id=plugin.name,
        description=plugin.description,
        produce=lambda: _produce_via_plugin(plugin, context),
        is_enabled=plugin.enabled,
    )


def default_provider(*, timezone_name: str | None = None) -> ToolProvider:
    """Temel READ araçlarını (saat, tarih, hesap, sistem durumu) sağlar."""

    return FunctionToolProvider(
        provider_id=DEFAULT_PROVIDER_ID,
        description="Temel yerleşik araçlar (saat, tarih, hesap makinesi, sistem durumu).",
        produce=lambda: list(build_default_tool_registry(timezone_name=timezone_name).list_tools()),
    )


def build_builtin_providers(
    context: PluginContext,
    *,
    timezone_name: str | None = None,
    plugins: Iterable[Plugin] | None = None,
) -> list[ToolProvider]:
    """Yerleşik sağlayıcıları kurar (temel araçlar + eklentiler).

    Args:
        context: Eklentilerin kaydolmak için ihtiyaç duyduğu bağlam. Kayıt
            sırasında registry alanı geçici bir registry ile değiştirilir.
        timezone_name: Temel saat/tarih araçlarının kullanacağı IANA dilim adı.
        plugins: Kullanılacak eklentiler. Verilmezse `BUILTIN_PLUGINS` +
            `ExamplePlugin`. Sıra korunur.

    Returns:
        Sağlayıcı listesi. Temel araçlar EN BAŞTA gelir: eklentiler aynı isimli
        bir araç sağlarsa çakışma deterministik olarak raporlanır.
    """

    active_plugins: tuple[Plugin, ...] = (
        tuple(plugins) if plugins is not None else (*BUILTIN_PLUGINS, ExamplePlugin())
    )
    return [
        default_provider(timezone_name=timezone_name),
        *(plugin_provider(plugin, context) for plugin in active_plugins),
    ]
