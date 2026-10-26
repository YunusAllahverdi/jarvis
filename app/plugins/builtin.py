"""Yerleşik araç setlerinin eklenti sarmalayıcıları.

Buradaki her eklenti, daha önce `app/tools/defaults.py` içindeki bir
`register_*` fonksiyonunun yaptığı işi yapar. Araçların KENDİSİ ve
davranışı değişmedi; yalnızca kayıt noktası tek bir arayüze taşındı.

Etkinlik ölçütü, geriye dönük uyumluluk için mevcut ayar bayraklarıdır:
tehlikeli yetenekler (dosya, terminal, ağ, haritalar) zaten VARSAYILAN
KAPALI'ydı ve öyle kalır. Salt-okunur ve güvenli olanlar (bağlam, notlar,
arayüz) ise önceden açıktı ve açık kalır — onları kapatmak davranışı
değiştirirdi. Yeni eklentiler ise `Plugin.enabled()` varsayılanını kullanır:
`enabled_plugins` listesinde adı geçmedikçe KAPALIDIR.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.config.settings import Settings
from app.plugins.base import Plugin, PluginContext
from app.tools.defaults import (
    register_context_tools,
    register_filesystem_tools,
    register_maps_tools,
    register_note_tools,
    register_research_tool,
    register_terminal_tool,
    register_ui_tool,
)


class ContextToolsPlugin(Plugin):
    """Bellek ve kullanıcı modelini okuyan araçlar."""

    name = "context_tools"
    description = "memory_search ve user_profile araçları (salt okunur)."

    def enabled(self, settings: Settings) -> bool:
        # Bu araçlar yalnızca ilgili servis varsa anlamlıdır; servis yokluğu
        # `register()` içinde sessizce boş listeye dönüşür.
        return True

    def register(self, context: PluginContext) -> Sequence[str]:
        return register_context_tools(
            context.registry,
            memory_retrieval=context.memory_retrieval,
            user_model=context.user_model,
        )


class FilesystemToolsPlugin(Plugin):
    """Çalışma kökünü okuyan/yazan dosya araçları (varsayılan KAPALI)."""

    name = "filesystem"
    description = "Dosya okuma/yazma/arama araçları; çalışma kökü gerekir."

    def enabled(self, settings: Settings) -> bool:
        # Çalışma kökü boşsa kayıt zaten olmaz; bayrağı burada da yansıtırız.
        return bool(settings.workspace_root.strip())

    def register(self, context: PluginContext) -> Sequence[str]:
        return register_filesystem_tools(
            context.registry,
            guard=context.workspace_guard,
            writable=context.workspace_writable,
            journal=context.change_journal,
        )


class NotesToolsPlugin(Plugin):
    """Kalıcı not araçları."""

    name = "notes"
    description = "note_search ve note_write araçları."

    def enabled(self, settings: Settings) -> bool:
        return settings.notes_enabled

    def register(self, context: PluginContext) -> Sequence[str]:
        return register_note_tools(
            context.registry,
            store=context.note_store,
            writable=context.notes_writable,
        )


class UiToolsPlugin(Plugin):
    """Arayüz paneli açan araç."""

    name = "ui_actions"
    description = "show_panel aracı (salt okunur arayüz kanalı)."

    def enabled(self, settings: Settings) -> bool:
        return True

    def register(self, context: PluginContext) -> Sequence[str]:
        return register_ui_tool(context.registry, bus=context.ui_action_bus)


class ResearchToolsPlugin(Plugin):
    """Web getirme aracı (varsayılan KAPALI)."""

    name = "research"
    description = "fetch_url aracı; ağ erişimi açıkça verilmelidir."

    def enabled(self, settings: Settings) -> bool:
        return settings.research_enabled

    def register(self, context: PluginContext) -> Sequence[str]:
        return register_research_tool(
            context.registry,
            guard=context.network_guard,
            timeout_seconds=context.research_timeout_seconds,
        )


class TerminalToolsPlugin(Plugin):
    """Komut çalıştırma aracı (varsayılan KAPALI)."""

    name = "terminal"
    description = "run_command aracı; terminal açıkça etkinleştirilmelidir."

    def enabled(self, settings: Settings) -> bool:
        return settings.terminal_enabled

    def register(self, context: PluginContext) -> Sequence[str]:
        return register_terminal_tool(
            context.registry,
            guard=context.workspace_guard,
            command_policy=context.command_policy,
            enabled=context.terminal_enabled,
            max_timeout_seconds=context.terminal_timeout_seconds,
        )


class MapsToolsPlugin(Plugin):
    """Google Maps araçları (anahtar yoksa KAPALI)."""

    name = "maps"
    description = "geocode, yol tarifi ve yer arama araçları; API anahtarı gerekir."

    def enabled(self, settings: Settings) -> bool:
        return bool(settings.maps_api_key.strip())

    def register(self, context: PluginContext) -> Sequence[str]:
        return register_maps_tools(context.registry, api_key=context.maps_api_key)


BUILTIN_PLUGINS: tuple[Plugin, ...] = (
    ContextToolsPlugin(),
    FilesystemToolsPlugin(),
    NotesToolsPlugin(),
    UiToolsPlugin(),
    ResearchToolsPlugin(),
    TerminalToolsPlugin(),
    MapsToolsPlugin(),
)
"""Agent yığınında uygulanan yerleşik eklentiler (kayıt sırası korunur)."""
