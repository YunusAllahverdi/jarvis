"""Eklenti (plugin) altyapısı.

Yeni araç ve entegrasyonların tek bir yerden eklenmesini sağlar. Bir eklenti
`Plugin` sözleşmesini uygular ve `BUILTIN_PLUGINS` listesine eklenir; her
eklenti varsayılan KAPALI'dır ve kaydettiği araçlar mevcut
`ToolPermissionPolicy` + onay akışından geçer.
"""

from app.plugins.base import (
    FunctionPlugin,
    Plugin,
    PluginContext,
    PluginRegistration,
)
from app.plugins.builtin import BUILTIN_PLUGINS
from app.plugins.registry import (
    DuplicatePluginError,
    PluginRegistry,
    apply_plugins,
)

__all__ = [
    "BUILTIN_PLUGINS",
    "DuplicatePluginError",
    "FunctionPlugin",
    "Plugin",
    "PluginContext",
    "PluginRegistration",
    "PluginRegistry",
    "apply_plugins",
]
