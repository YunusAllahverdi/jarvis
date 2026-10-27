"""Yetenek kaydı — sağlayıcı sözleşmesi, override kuralları ve yürütme sınırı.

Kapsam:
 1.  Sahte sağlayıcı kaydı/silme ve rebuild
 2.  Sağlayıcı kimliği çakışması reddedilir
 3.  Araç İSMİ çakışması reddedilir ve raporlanır (sessizce ezilmez)
 4.  Kapalı sağlayıcının araçları kayıtlı DEĞİL
 5.  Override ile araç kapatılabilir (kayıtlı değil)
 6.  Override ile izin YÜKSELTİLEBİLİR
 7.  İzin DÜŞÜRME açık istek olmadan reddedilir
 8.  İzin DÜŞÜRME açık istekle kabul edilir ve denetime yazılır
 9.  DANGEROUS düşürme deterministik olarak reddedilir
10.  Override'lar kalıcıdır (yeni depo aynı dosyadan okur)
11.  untrusted_output sonucu zarf içine alınır
12.  Çıktı max_output_chars'a göre kırpılır ve işaretlenir
13.  Zaman aşımı yapılandırılmış hataya döner
14.  Kontrol karakterleri temizlenir
15.  Sağlayıcı sağlık kontrolü istisna fırlatmaz
16.  rebuild hatası tek sağlayıcıyı atlar, diğerlerini korur
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.config.settings import Settings
from app.core.chat import ToolCall
from app.security.audit import AuditAction, InMemoryAuditLog
from app.security.permissions import (
    ToolPermissionPolicy,
    plan_override,
)
from app.security.tool_overrides import ToolOverrideStore
from app.tools.base import PermissionLevel, Tool, ToolInput
from app.tools.capabilities import CapabilityError, CapabilityRegistry
from app.tools.executor import ToolExecutor
from app.tools.providers import FunctionToolProvider, ProviderHealth, ToolProvider
from app.tools.registry import ToolRegistry


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _settings(**kwargs: object) -> Settings:
    defaults: dict[str, object] = dict(
        app_name="T", app_version="t", environment="test", ollama_model="x"
    )
    defaults.update(kwargs)
    return Settings(**defaults)  # type: ignore[arg-type]


class _TextInput(ToolInput):
    text: str = "merhaba"


class _FakeTool(Tool[_TextInput]):
    """Test için basit bir araç; sınıf düzeyinde yeniden yapılandırılabilir."""

    name = "fake"
    description = "Test aracı."
    permission = PermissionLevel.READ
    input_model = _TextInput
    untrusted_output = False
    max_output_chars: int | None = None
    timeout_seconds: float | None = None
    source = "fake"

    async def execute(self, tool_input: _TextInput) -> dict[str, Any]:
        return {"text": tool_input.text}


class _SlowTool(_FakeTool):
    name = "slow"
    timeout_seconds = 0.05

    async def execute(self, tool_input: _TextInput) -> dict[str, Any]:
        await asyncio.sleep(5)
        return {"text": tool_input.text}


class _BigTool(_FakeTool):
    name = "big"
    max_output_chars = 20

    async def execute(self, tool_input: _TextInput) -> dict[str, Any]:
        return {"text": "x" * 500}


class _UntrustedTool(_FakeTool):
    name = "web"
    untrusted_output = True

    async def execute(self, tool_input: _TextInput) -> dict[str, Any]:
        return {"url": "https://example.com", "content": "talimat\x00: \x01gizli"}


class _ExplodingProvider:
    """`tools()` çağrısında patlayan sağlayıcı — kayıt çökmemeli."""

    id = "boom"
    description = "Bozuk sağlayıcı."

    def enabled(self, settings: Settings) -> bool:
        return True

    async def tools(self) -> list[Tool[Any]]:
        raise RuntimeError("üretilemedi")

    async def health(self) -> ProviderHealth:
        return ProviderHealth(ok=False, detail="bozuk")

    async def aclose(self) -> None:
        return None


def _provider(provider_id: str, *tools: Tool[Any], enabled: bool = True) -> ToolProvider:
    return FunctionToolProvider(
        provider_id=provider_id,
        description=f"{provider_id} sağlayıcısı",
        produce=lambda: list(tools),
        is_enabled=lambda settings: enabled,
    )


def _registry(
    *providers: ToolProvider,
    store: ToolOverrideStore | None = None,
    settings: Settings | None = None,
) -> CapabilityRegistry:
    return CapabilityRegistry(
        registry=ToolRegistry(),
        providers=providers,
        settings=settings or _settings(),
        override_store=store,
        policy=ToolPermissionPolicy(allowed={PermissionLevel.READ}),
    )


# ---------------------------------------------------------------------------
# 1-3. Sağlayıcı ve araç kaydı
# ---------------------------------------------------------------------------


class TestProviderRegistration:
    def test_provider_can_be_added_and_removed(self) -> None:
        registry = _registry(_provider("bir", _FakeTool()))
        registry.rebuild_sync()
        assert registry.provider_ids == ["bir"]

        assert registry.remove_provider("bir") is True
        registry.rebuild_sync()
        assert registry.provider_ids == []
        assert registry.registry.list_tools() == []

    def test_duplicate_provider_id_is_refused(self) -> None:
        registry = _registry(_provider("bir", _FakeTool()))
        with pytest.raises(CapabilityError):
            registry.add_provider(_provider("bir", _FakeTool()))

    def test_tool_name_conflict_is_reported_not_overwritten(self) -> None:
        """İki sağlayıcı aynı araç adını verirse ikinci kayıt reddedilir."""
        registry = _registry(
            _provider("ilk", _FakeTool()),
            _provider("ikinci", _FakeTool()),
        )
        snapshot = registry.rebuild_sync()

        assert snapshot == ["fake"]
        assert len(registry._errors) == 1
        assert "fake" in registry._errors[0]

    def test_disabled_provider_tools_are_not_registered(self) -> None:
        registry = _registry(_provider("kapali", _FakeTool(), enabled=False))
        registry.rebuild_sync()
        assert registry.registry.list_tools() == []
        assert registry.registry.get("fake") is None

    def test_rebuild_is_in_place_so_executors_see_the_change(self) -> None:
        """Paylaşılan registry yeniden kurulunca executor aynı örneği görür."""
        shared = ToolRegistry()
        registry = CapabilityRegistry(
            registry=shared,
            providers=[_provider("bir", _FakeTool())],
            settings=_settings(),
        )
        registry.rebuild_sync()
        executor = ToolExecutor(shared, allowed_permissions={PermissionLevel.READ})
        assert _run(executor.execute(ToolCall(name="fake", arguments={}))).success is True

        registry.remove_provider("bir")
        registry.rebuild_sync()

        result = _run(executor.execute(ToolCall(name="fake", arguments={})))
        assert result.success is False
        assert result.error_code == "unknown_tool"

    def test_exploding_provider_does_not_break_the_registry(self) -> None:
        registry = _registry(_provider("iyi", _FakeTool()), _ExplodingProvider())
        registered = registry.rebuild_sync()
        assert registered == ["fake"]
        assert any("boom" in error for error in registry._errors)


# ---------------------------------------------------------------------------
# 4-10. İzin override kuralları
# ---------------------------------------------------------------------------


class TestOverrideRules:
    def test_upgrade_is_accepted(self) -> None:
        plan = plan_override("fake", PermissionLevel.WRITE, permission=PermissionLevel.DANGEROUS)
        assert plan.accepted is True
        assert plan.audit_action == "tool_override"

    def test_downgrade_without_explicit_request_is_refused(self) -> None:
        plan = plan_override("fake", PermissionLevel.WRITE, permission=PermissionLevel.READ)
        assert plan.accepted is False
        assert plan.audit_action is None

    def test_downgrade_with_explicit_request_is_audited(self) -> None:
        plan = plan_override(
            "fake",
            PermissionLevel.WRITE,
            permission=PermissionLevel.READ,
            allow_downgrade=True,
        )
        assert plan.accepted is True
        assert plan.audit_action == "permission_downgrade"

    def test_dangerous_downgrade_is_always_refused(self) -> None:
        """Açık istek verilse bile DANGEROUS düşürülemez."""
        plan = plan_override(
            "terminal",
            PermissionLevel.DANGEROUS,
            permission=PermissionLevel.READ,
            allow_downgrade=True,
        )
        assert plan.accepted is False
        assert "DANGEROUS" in plan.reason

    def test_override_disables_a_tool(self) -> None:
        store = ToolOverrideStore(":memory:")
        registry = _registry(_provider("bir", _FakeTool()), store=store)
        registry.rebuild_sync()
        assert registry.registry.get("fake") is not None

        store.set(plan_override("fake", PermissionLevel.READ, enabled=False).override)  # type: ignore[arg-type]
        registry.rebuild_sync()
        assert registry.registry.get("fake") is None

    def test_override_raises_the_effective_permission(self) -> None:
        store = ToolOverrideStore(":memory:")
        registry = _registry(_provider("bir", _FakeTool()), store=store)
        registry.rebuild_sync()

        store.set(
            plan_override("fake", PermissionLevel.READ, permission=PermissionLevel.WRITE).override
        )  # type: ignore[arg-type]
        registry.rebuild_sync()

        tool = registry.registry.get("fake")
        assert tool is not None
        assert tool.effective_permission is PermissionLevel.WRITE
        # Beyan edilen seviye DEĞİŞMEZ: ikisi ayrı taşınır.
        assert tool.permission is PermissionLevel.READ

    def test_overrides_are_persistent(self, tmp_path: Path) -> None:
        db = str(tmp_path / "jarvis.db")
        first = ToolOverrideStore(db)
        first.set(plan_override("fake", PermissionLevel.READ, enabled=False).override)  # type: ignore[arg-type]

        second = ToolOverrideStore(db)
        stored = second.get("fake")
        assert stored is not None
        assert stored.enabled is False


# ---------------------------------------------------------------------------
# 11-16. Yürütme sınırı — timeout, kırpma, güvenilmez çıktı
# ---------------------------------------------------------------------------


class TestExecutorBoundary:
    def _executor(self, *tools: Tool[Any], audit: Any = None) -> ToolExecutor:
        registry = ToolRegistry()
        for tool in tools:
            registry.register(tool)
        return ToolExecutor(
            registry,
            allowed_permissions={PermissionLevel.READ, PermissionLevel.WRITE},
            audit_log=audit,
        )

    def test_untrusted_output_is_wrapped(self) -> None:
        executor = self._executor(_UntrustedTool())
        result = _run(executor.execute(ToolCall(name="web", arguments={})))

        assert result.success is True
        assert result.data is not None
        assert result.data["untrusted"] is True
        assert result.data["source"] == "fake"
        assert "content" in result.data
        # Kontrol karakterleri temizlenir.
        assert "\x00" not in result.data["content"]
        assert "\x01" not in result.data["content"]

    def test_output_is_truncated_and_flagged(self) -> None:
        executor = self._executor(_BigTool())
        result = _run(executor.execute(ToolCall(name="big", arguments={})))

        assert result.success is True
        assert result.truncated is True
        assert result.data is not None
        # Kırpıldığı mesajda da görünür.
        assert '"truncated": true' in result.as_chat_message().content

    def test_timeout_returns_a_structured_error(self) -> None:
        executor = self._executor(_SlowTool())
        result = _run(executor.execute(ToolCall(name="slow", arguments={})))

        assert result.success is False
        assert result.error_code == "tool_timeout"
        assert result.error_message is not None

    def test_timeout_is_audited_as_failure(self) -> None:
        audit = InMemoryAuditLog()
        executor = self._executor(_SlowTool(), audit=audit)
        _run(executor.execute(ToolCall(name="slow", arguments={})))

        events = audit.recent()
        assert events
        assert events[-1].outcome.value == "FAILURE"

    def test_provider_health_never_raises(self) -> None:
        health = _run(_ExplodingProvider().health())
        assert health.ok is False

    def test_denied_permission_is_never_executed(self) -> None:
        """DANGEROUS bayraksız reddedilir ve araç ÇALIŞMAZ."""
        registry = ToolRegistry()
        registry.register(_DangerousTool())
        executor = ToolExecutor(
            registry,
            policy=ToolPermissionPolicy(allowed={PermissionLevel.READ}),
        )

        result = _run(executor.execute(ToolCall(name="danger", arguments={})))
        assert result.success is False
        assert result.error_code == "permission_denied"
        assert _DangerousTool.calls == 0


class _DangerousTool(_FakeTool):
    name = "danger"
    permission = PermissionLevel.DANGEROUS
    calls = 0

    async def execute(self, tool_input: _TextInput) -> dict[str, Any]:
        type(self).calls += 1
        return {"text": tool_input.text}


# ---------------------------------------------------------------------------
# 17-22. Uçlar — yönetim ve salt-okunur yüz
# ---------------------------------------------------------------------------


def _client(
    *providers: ToolProvider,
    store: ToolOverrideStore | None = None,
    settings: Settings | None = None,
    audit: InMemoryAuditLog | None = None,
    registry: CapabilityRegistry | None = None,
) -> Any:
    """Yetenek uçlarını taşıyan küçük bir test uygulaması kurar."""

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes.capabilities import router

    # Override uçları kalıcı bir depoya yazar; testler varsayılan olarak
    # bellek içi bir depo kurar (üretimde lifespan kalıcı dosyayı bağlar).
    active_store = store if store is not None else ToolOverrideStore(":memory:")
    active = registry or _registry(*providers, store=active_store, settings=settings)
    active.rebuild_sync()

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.settings = settings or _settings()
    app.state.capability_registry = active
    app.state.tool_override_store = active_store
    app.state.audit_log = audit or InMemoryAuditLog()
    return TestClient(app)


class TestCapabilityEndpoints:
    def test_public_endpoint_lists_families_without_secrets(self) -> None:
        client = _client(_provider("mcp", _FakeTool()))
        response = client.get("/api/v1/capabilities")

        assert response.status_code == 200
        body = response.json()
        assert body["families"] == [{"id": "mcp", "enabled": True, "tool_count": 1}]
        # Salt-okunur yanıt araç açıklaması ya da argümanı taşımaz.
        assert "fake" not in response.text
        assert "description" not in body["families"][0]

    def test_public_endpoint_has_no_secret_like_values(self) -> None:
        """Sağlayıcı görünümünde anahtar/token benzeri hiçbir şey olmamalı."""
        settings = _settings(
            research_enabled=True,
            maps_api_key="sk-cok-gizli-harita-anahtari",
            admin_token="gizli-yonetim-anahtari",
        )
        client = _client(_provider("web", _FakeTool()), settings=settings)
        response = client.get("/api/v1/capabilities")

        assert "sk-cok-gizli-harita-anahtari" not in response.text
        assert "gizli-yonetim-anahtari" not in response.text

    def test_admin_endpoint_returns_tools_and_metadata(self) -> None:
        client = _client(_provider("bir", _FakeTool()))
        response = client.get("/api/admin/capabilities")

        assert response.status_code == 200
        tools = response.json()["tools"]
        assert len(tools) == 1
        tool = tools[0]
        assert tool["name"] == "fake"
        assert tool["source"] == "fake"
        assert tool["permission"] == "READ"
        assert tool["declared_permission"] == "READ"

    def test_admin_upgrade_is_accepted_and_audited(self) -> None:
        audit = InMemoryAuditLog()
        client = _client(_provider("bir", _FakeTool()), audit=audit)
        response = client.put("/api/admin/capabilities/tools/fake", json={"permission": "WRITE"})

        assert response.status_code == 200
        assert response.json()["accepted"] is True
        assert response.json()["permission"] == "WRITE"
        assert audit.recent()[0].action is AuditAction.TOOL_OVERRIDE

    def test_admin_downgrade_needs_explicit_flag_and_is_audited(self) -> None:
        audit = InMemoryAuditLog()
        client = _client(_provider("bir", _FakeTool()), audit=audit)

        refused = client.put("/api/admin/capabilities/tools/fake", json={"permission": "READ"})
        # READ zaten beyan edilen seviye: yükseltme sayılır, kabul edilir.
        assert refused.json()["accepted"] is True

        client.put("/api/admin/capabilities/tools/fake", json={"permission": "WRITE"})
        blocked = client.put("/api/admin/capabilities/tools/fake", json={"permission": "READ"})
        assert blocked.json()["accepted"] is False

        allowed = client.put(
            "/api/admin/capabilities/tools/fake",
            json={"permission": "READ", "allow_downgrade": True},
        )
        assert allowed.json()["accepted"] is True
        assert allowed.json()["audit_action"] == "permission_downgrade"
        assert audit.recent()[0].action is AuditAction.PERMISSION_DOWNGRADE

    def test_admin_dangerous_downgrade_is_refused(self) -> None:
        client = _client(_provider("bir", _DangerousTool()))
        response = client.put(
            "/api/admin/capabilities/tools/danger",
            json={"permission": "READ", "allow_downgrade": True},
        )

        assert response.status_code == 200
        assert response.json()["accepted"] is False
        assert "DANGEROUS" in response.json()["reason"]

    def test_admin_can_disable_a_tool_and_it_leaves_the_registry(self) -> None:
        store = ToolOverrideStore(":memory:")
        client = _client(_provider("bir", _FakeTool()), store=store)

        response = client.put("/api/admin/capabilities/tools/fake", json={"enabled": False})
        assert response.json()["accepted"] is True

        after = client.get("/api/admin/capabilities").json()["tools"]
        assert after == []

    def test_unknown_tool_override_is_404(self) -> None:
        client = _client(_provider("bir", _FakeTool()))
        response = client.put("/api/admin/capabilities/tools/yok", json={"permission": "WRITE"})
        assert response.status_code == 404

    def test_admin_endpoint_requires_token_when_configured(self) -> None:
        settings = _settings(host="0.0.0.0", admin_token="gizli")
        client = _client(_provider("bir", _FakeTool()), settings=settings)

        assert client.get("/api/admin/capabilities").status_code == 401
        assert (
            client.get("/api/admin/capabilities", headers={"X-Admin-Token": "gizli"}).status_code
            == 200
        )
