"""Eklentilerin tek yerden kaydedildiği kayıt (registry).

`PluginRegistry` eklentileri sırayla uygular: her eklentiye "bu
yapılandırmada etkin misin?" diye sorar, etkinse araçlarını hedef
`ToolRegistry`'ye kaydeder. Uygulama kodu yalnızca bu kaydı kurar; yeni bir
yetenek eklemek, buraya bir eklenti eklemekten ibarettir.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence

from app.plugins.base import Plugin, PluginContext, PluginRegistration
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class DuplicatePluginError(RuntimeError):
    """Aynı ada sahip ikinci bir eklenti kaydedilmek istendiğinde oluşur."""


class PluginRegistry:
    """Eklentileri sırayla tutar ve uygular."""

    def __init__(self, plugins: Iterable[Plugin] = ()) -> None:
        self._plugins: list[Plugin] = []
        self._names: set[str] = set()
        for plugin in plugins:
            self.add(plugin)

    def add(self, plugin: Plugin) -> None:
        """Bir eklentiyi kaydeder; aynı adlı ikinci kaydı reddeder.

        Ad tekilliği zorunludur: aynı ad iki eklentiye verilseydi
        `enabled_plugins` bayrağı hangisini açtığını belirsizleştirirdi.
        """

        if plugin.name in self._names:
            raise DuplicatePluginError(f"'{plugin.name}' adlı eklenti zaten kayıtlı.")
        self._plugins.append(plugin)
        self._names.add(plugin.name)

    def __iter__(self) -> Iterator[Plugin]:
        return iter(self._plugins)

    def __len__(self) -> int:
        return len(self._plugins)

    def names(self) -> list[str]:
        """Kayıtlı eklenti adları (kayıt sırasıyla)."""

        return [plugin.name for plugin in self._plugins]

    def apply(self, context: PluginContext) -> list[PluginRegistration]:
        """Tüm eklentileri uygular ve sonuçlarını döndürür.

        Kapalı eklentiler ATLANIR ve sonuç listesinde `enabled=False` olarak
        görünür — böylece "yok" ile "kapalı" ayırt edilebilir.
        """

        results: list[PluginRegistration] = []
        for plugin in self._plugins:
            if not plugin.enabled(context.settings):
                results.append(PluginRegistration(plugin=plugin.name, enabled=False))
                continue
            tools: Sequence[str] = plugin.register(context)
            results.append(
                PluginRegistration(
                    plugin=plugin.name,
                    enabled=True,
                    tools=tuple(tools),
                )
            )
        logger.info(
            "plugins_applied",
            extra={
                "enabled": [r.plugin for r in results if r.enabled],
                "tools": [name for r in results for name in r.tools],
                "tool_count": len(context.registry.list_tools()),
            },
        )
        return results


def apply_plugins(
    plugins: Iterable[Plugin],
    registry: ToolRegistry,
    context: PluginContext,
) -> list[PluginRegistration]:
    """Yardımcı: verilen eklentileri bir registry üzerinde uygular."""

    return PluginRegistry(plugins).apply(context)
