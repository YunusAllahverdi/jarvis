"""Eklenti (plugin) altyapısının testleri.

Kapsar:
1. Eklenti sözleşmesi — varsayılan KAPALI, config bayrağıyla açma
2. PluginRegistry — sıra, tekillik, kapalı eklentilerin atlanması
3. Örnek eklenti — kapalıyken yok, açıkken aracı kayıtlı
4. İzin akışı — eklenti aracı ToolPermissionPolicy + onay akışından geçer
5. Davranış korunması — mevcut araç yüzeyi eklenti arayüzüne taşınırken aynı
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from app.config.settings import Settings
from app.plugins import (
    BUILTIN_PLUGINS,
    DuplicatePluginError,
    FunctionPlugin,
    Plugin,
    PluginContext,
    PluginRegistry,
)
from app.plugins.example import EchoTool, ExamplePlugin
from app.security.permissions import PermissionDecision, ToolPermissionPolicy
from app.tools.base import PermissionLevel, Tool
from app.tools.defaults import (
    build_default_tool_registry,
    register_context_tools,
    register_filesystem_tools,
    register_maps_tools,
    register_note_tools,
    register_research_tool,
    register_terminal_tool,
    register_ui_tool,
)
from app.tools.registry import ToolRegistry


def _settings(**overrides: object) -> Settings:
    return Settings(environment="test", **overrides)


def _context(settings: Settings | None = None, **overrides: object) -> PluginContext:
    return PluginContext(
        registry=ToolRegistry(),
        settings=settings or _settings(),
        **overrides,
    )


# ---------------------------------------------------------------------------
# 1. Sözleşme — varsayılan kapalı
# ---------------------------------------------------------------------------


class _NoopPlugin(Plugin):
    name = "noop"
    description = "test"

    def register(self, context: PluginContext) -> Sequence[str]:
        return []


class TestPluginContract:
    def test_plugin_is_disabled_by_default(self) -> None:
        plugin = _NoopPlugin()

        assert plugin.enabled(_settings()) is False

    def test_plugin_enabled_only_when_listed(self) -> None:
        plugin = _NoopPlugin()

        assert plugin.enabled(_settings(enabled_plugins=["noop"])) is True
        assert plugin.enabled(_settings(enabled_plugins=["other"])) is False

    def test_example_plugin_is_disabled_by_default(self) -> None:
        assert ExamplePlugin().enabled(_settings()) is False

    def test_builtin_plugins_are_disabled_by_default(self) -> None:
        """Hiçbir eklenti, kimse açmadan etkinleşmemeli.

        Dosya/terminal/ağ/harita eklentileri zaten kapalı olan ayarlara bağlı;
        salt-okunur olanlar ise ilgili servis yokken kayıt yapmaz. Bu test,
        yanlışlıkla açık varsayılan eklenmesini yakalar.
        """

        settings = _settings()
        context = _context(settings)
        results = PluginRegistry(BUILTIN_PLUGINS).apply(context)

        # Servisler verilmediği için hiçbir eklenti araç kaydetmemeli.
        assert all(not reg.tools for reg in results)


# ---------------------------------------------------------------------------
# 2. Registry
# ---------------------------------------------------------------------------


class TestPluginRegistry:
    def test_duplicate_plugin_name_is_rejected(self) -> None:
        registry = PluginRegistry([_NoopPlugin()])

        with pytest.raises(DuplicatePluginError):
            registry.add(_NoopPlugin())

    def test_names_preserve_registration_order(self) -> None:
        registry = PluginRegistry([_NoopPlugin()])
        registry.add(
            FunctionPlugin(
                name="second",
                description="",
                register=lambda ctx: [],
                enabled=lambda s: False,
            )
        )

        assert registry.names() == ["noop", "second"]

    def test_disabled_plugins_are_skipped_but_reported(self) -> None:
        class _Registering(Plugin):
            name = "reg"
            description = ""

            def register(self, context: PluginContext) -> Sequence[str]:
                context.registry.register(EchoTool())
                return ["example_echo"]

        context = _context()
        results = PluginRegistry([_Registering()]).apply(context)

        assert results[0].enabled is False
        assert results[0].skipped is True
        assert results[0].tools == ()
        assert context.registry.get("example_echo") is None

    def test_enabled_plugin_registers_its_tools(self) -> None:
        context = _context(_settings(enabled_plugins=["example"]))
        results = PluginRegistry([ExamplePlugin()]).apply(context)

        assert results[0].enabled is True
        assert results[0].tools == ("example_echo",)
        assert context.registry.get("example_echo") is not None


# ---------------------------------------------------------------------------
# 3. Örnek eklenti
# ---------------------------------------------------------------------------


class TestExamplePlugin:
    def test_echo_tool_is_read_only(self) -> None:
        assert EchoTool.permission is PermissionLevel.READ

    def test_echo_tool_executes(self) -> None:
        result = asyncio.run(EchoTool().execute(EchoTool.input_model(message="merhaba")))

        assert result == {"echo": "merhaba"}

    def test_plugin_registers_tool_under_its_name(self) -> None:
        context = _context(_settings(enabled_plugins=["example"]))

        ExamplePlugin().register(context)

        assert context.registry.get("example_echo") is not None


# ---------------------------------------------------------------------------
# 4. İzin akışı — eklenti aracı politika + onay akışından geçer
# ---------------------------------------------------------------------------


class TestPluginToolPermissions:
    def test_plugin_tool_goes_through_permission_policy(self) -> None:
        """Eklentinin READ aracı serbest, uydurma DANGEROUS aracı reddedilir."""

        policy = ToolPermissionPolicy(allowed={PermissionLevel.READ})

        assert policy.decide(EchoTool.permission) is PermissionDecision.ALLOW
        assert policy.decide(PermissionLevel.DANGEROUS) is PermissionDecision.DENY

    def test_plugin_write_tool_requires_approval(self) -> None:
        """WRITE seviyeli bir eklenti aracı, onay olmadan çalışmaz."""

        from app.core.chat import ToolCall
        from app.tools.base import ToolInput
        from app.tools.executor import ToolExecutor

        class _WriteTool(Tool[ToolInput]):
            name = "plugin_write"
            description = "test"
            permission = PermissionLevel.WRITE
            input_model = ToolInput

            async def execute(self, tool_input: ToolInput) -> dict[str, object]:
                return {"ok": True}

        registry = ToolRegistry()
        registry.register(_WriteTool())
        executor = ToolExecutor(
            registry,
            policy=ToolPermissionPolicy(requires_approval={PermissionLevel.WRITE}),
        )

        result = asyncio.run(executor.execute(ToolCall(name="plugin_write", arguments={})))

        assert result.success is False
        assert result.requires_approval is True
        assert result.error_code == "approval_required"

    def test_plugin_tool_runs_after_approval(self) -> None:
        from app.core.chat import ToolCall
        from app.tools.base import ToolInput
        from app.tools.executor import ToolExecutor

        class _WriteTool(Tool[ToolInput]):
            name = "plugin_write"
            description = "test"
            permission = PermissionLevel.WRITE
            input_model = ToolInput

            async def execute(self, tool_input: ToolInput) -> dict[str, object]:
                return {"ok": True}

        registry = ToolRegistry()
        registry.register(_WriteTool())
        executor = ToolExecutor(
            registry,
            policy=ToolPermissionPolicy(requires_approval={PermissionLevel.WRITE}),
        )

        result = asyncio.run(
            executor.execute(ToolCall(name="plugin_write", arguments={}), approved=True)
        )

        assert result.success is True
        assert result.data == {"ok": True}


# ---------------------------------------------------------------------------
# 5. Davranış korunması — eklenti arayüzü eski kayıtla aynı sonucu verir
# ---------------------------------------------------------------------------


class TestBuiltinPluginParity:
    """Yerleşik eklentiler, eski `register_*` çağrılarıyla aynı araçları üretir."""

    def test_filesystem_parity(self, tmp_path) -> None:
        from app.security.paths import PathGuard

        guard = PathGuard(tmp_path)
        legacy = ToolRegistry()
        expected = register_filesystem_tools(legacy, guard=guard, writable=True)

        via_plugin = ToolRegistry()
        context = _context(
            _settings(workspace_root=str(tmp_path), workspace_writable=True),
            workspace_guard=guard,
            workspace_writable=True,
        )
        context.registry = via_plugin
        results = PluginRegistry(BUILTIN_PLUGINS).apply(context)
        plugin_tools = [name for reg in results for name in reg.tools]

        assert sorted(plugin_tools) == sorted(expected)
        assert {t.name for t in via_plugin.list_tools()} == {t.name for t in legacy.list_tools()}

    def test_notes_parity(self, tmp_path) -> None:
        from app.notes.store import NoteStore

        store = NoteStore(str(tmp_path / "notes.db"))
        legacy = ToolRegistry()
        expected = register_note_tools(legacy, store=store, writable=True)

        via_plugin = ToolRegistry()
        context = _context(_settings(), note_store=store, notes_writable=True)
        context.registry = via_plugin
        results = PluginRegistry(BUILTIN_PLUGINS).apply(context)
        plugin_tools = [name for reg in results for name in reg.tools]

        assert sorted(plugin_tools) == sorted(expected)

    def test_terminal_parity(self, tmp_path) -> None:
        from app.security.commands import CommandPolicy
        from app.security.paths import PathGuard

        guard = PathGuard(tmp_path)
        policy = CommandPolicy()
        legacy = ToolRegistry()
        expected = register_terminal_tool(legacy, guard=guard, command_policy=policy, enabled=True)

        from app.plugins.builtin import TerminalToolsPlugin

        via_plugin = ToolRegistry()
        context = _context(
            _settings(terminal_enabled=True, workspace_root=str(tmp_path)),
            workspace_guard=guard,
            command_policy=policy,
            terminal_enabled=True,
        )
        context.registry = via_plugin
        results = PluginRegistry([TerminalToolsPlugin()]).apply(context)
        plugin_tools = [name for reg in results for name in reg.tools]

        assert sorted(plugin_tools) == sorted(expected)

    def test_research_parity(self) -> None:
        from app.security.network import NetworkGuard

        guard = NetworkGuard(allowed_domains=[])
        legacy = ToolRegistry()
        expected = register_research_tool(legacy, guard=guard)

        via_plugin = ToolRegistry()
        context = _context(
            _settings(research_enabled=True),
            network_guard=guard,
        )
        context.registry = via_plugin
        results = PluginRegistry(BUILTIN_PLUGINS).apply(context)
        plugin_tools = [name for reg in results for name in reg.tools]

        assert sorted(plugin_tools) == sorted(expected)

    def test_maps_parity(self) -> None:
        legacy = ToolRegistry()
        expected = register_maps_tools(legacy, api_key="test-key")

        via_plugin = ToolRegistry()
        context = _context(_settings(maps_api_key="test-key"), maps_api_key="test-key")
        context.registry = via_plugin
        results = PluginRegistry(BUILTIN_PLUGINS).apply(context)
        plugin_tools = [name for reg in results for name in reg.tools]

        assert sorted(plugin_tools) == sorted(expected)

    def test_ui_parity(self) -> None:
        from app.ui.actions import UIActionBus

        bus = UIActionBus()
        legacy = ToolRegistry()
        expected = register_ui_tool(legacy, bus=bus)

        via_plugin = ToolRegistry()
        context = _context(_settings(), ui_action_bus=bus)
        context.registry = via_plugin
        results = PluginRegistry(BUILTIN_PLUGINS).apply(context)
        plugin_tools = [name for reg in results for name in reg.tools]

        assert sorted(plugin_tools) == sorted(expected)

    def test_context_tools_parity(self) -> None:
        """Servis yokluğunda ikisi de boş liste döndürür (davranış aynı)."""

        legacy = ToolRegistry()
        assert register_context_tools(legacy) == []

        via_plugin = ToolRegistry()
        context = _context()
        context.registry = via_plugin
        results = PluginRegistry(BUILTIN_PLUGINS).apply(context)
        plugin_tools = [name for reg in results for name in reg.tools]

        assert plugin_tools == []

    def test_default_registry_surface_unchanged(self) -> None:
        """Eklentiler eklenmeden önceki varsayılan araç yüzeyi aynı kalmalı."""

        names = {tool.name for tool in build_default_tool_registry().list_tools()}

        assert names == {"get_time", "get_date", "calculator", "system_status"}
