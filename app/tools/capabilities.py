"""Yetenek kaydı — çok kaynaklı araçların tek kurulum noktası.

Bu modül, `ToolProvider`'ları toplar, etkin olanların araçlarını ister ve
PAYLAŞILAN `ToolRegistry`'yi yerinde yeniden kurar. "Yerinde" olması şarttır:
registry örneği yürütücüler (chat ve agent `ToolExecutor`'ları) tarafından
tutulur; yeni bir örnek üretilseydi onlar eski ve artık güncellenmeyen kopyaya
bakmaya devam ederdi ve iki paralel araç yüzeyi doğardı.

`rebuild()` çalışma zamanında çağrılabilir: bir sağlayıcı açıldığında,
kapatıldığında ya da izin override'ı değiştiğinde uygulamayı yeniden
başlatmak gerekmez.

İKİNCİ YÜRÜTME YOLU YOKTUR: bu kayıt yalnızca hangi araçların VAR olduğunu
belirler. Çalıştırma, izin kararı ve denetim yine tek `ToolExecutor` sınırından
geçer.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.config.settings import Settings
from app.security.permissions import PermissionDecision, ToolPermissionPolicy
from app.security.tool_overrides import ToolOverrideStore
from app.tools.base import PermissionLevel, Tool
from app.tools.providers import ProviderHealth, ToolProvider
from app.tools.registry import DuplicateToolError, ToolRegistry

logger = logging.getLogger(__name__)


class CapabilityError(RuntimeError):
    """Yetenek kaydı kurulurken oluşan kontrollü hataların tabanı."""


class ToolView(BaseModel):
    """Bir aracın arayüze ve denetime sunulan salt-okunur görünümü."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    source: str
    category: str = ""
    risk_tags: tuple[str, ...] = ()

    permission: PermissionLevel
    """Fiilen geçerli izin seviyesi (override uygulanmış hâli)."""

    declared_permission: PermissionLevel
    """Aracın KENDİ beyan ettiği seviye — override'dan bağımsız.

    İkisi birlikte gösterilir: kullanıcı "bu araç ne istiyordu, ben ne yaptım"
    sorusunu tek bakışta cevaplayabilmelidir.
    """

    enabled: bool = True
    requires_approval: bool = False
    untrusted_output: bool = False
    timeout_seconds: float | None = None
    max_output_chars: int | None = None


class ProviderView(BaseModel):
    """Bir sağlayıcının arayüze sunulan görünümü."""

    model_config = ConfigDict(frozen=True)

    id: str
    description: str = ""
    enabled: bool
    tool_count: int = Field(default=0, ge=0)
    ok: bool = True
    detail: str = ""


class CapabilitySnapshot(BaseModel):
    """Yetenek kaydının tam, salt-okunur anlık görüntüsü."""

    model_config = ConfigDict(frozen=True)

    providers: list[ProviderView] = Field(default_factory=list)
    tools: list[ToolView] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    """Kayıt sırasında oluşan yapılandırılmış sorunlar (ör. isim çakışması).

    Boş olmaması bir istisna değildir: çakışan araç kaydedilmez ve burada
    raporlanır — sessizce biri diğerini ezmez.
    """


class CapabilityRegistry:
    """Sağlayıcıları toplayan ve paylaşılan registry'yi kuran kayıt."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        providers: Iterable[ToolProvider],
        settings: Settings,
        override_store: ToolOverrideStore | None = None,
        policy: ToolPermissionPolicy | None = None,
    ) -> None:
        """
        Args:
            registry: Paylaşılan ve YERİNDE güncellenecek araç kaydı.
            providers: Araç üreten sağlayıcılar (kayıt sırası korunur).
            settings: Etkinlik kararı için okunan yapılandırma.
            override_store: Kalıcı kullanıcı override'ları. Verilmezse yoktur.
            policy: Onay gereksinimini hesaplamak için izin politikası. Yalnızca
                görünüm (`ToolView.requires_approval`) için kullanılır; karar
                mercii değildir.
        """
        self._registry = registry
        self._providers: list[ToolProvider] = list(providers)
        self._settings = settings
        self._override_store = override_store
        self._policy = policy
        self._errors: list[str] = []
        self._tool_sources: dict[str, str] = {}

    @property
    def registry(self) -> ToolRegistry:
        """Yerinde kurulan paylaşılan araç kaydı."""

        return self._registry

    @property
    def override_store(self) -> ToolOverrideStore | None:
        """Kalıcı kullanıcı override'larının deposu (yoksa None)."""

        return self._override_store

    def set_override_store(self, store: ToolOverrideStore | None) -> None:
        """Kalıcı override deposunu sonradan bağlar.

        Depo bir dosya açar; bu yüzden import anında değil, uygulama fiilen
        başlarken kurulur ve kayda geç bağlanır — diğer kalıcı depolarla aynı
        kalıp.
        """

        self._override_store = store

    def set_policy(self, policy: ToolPermissionPolicy | None) -> None:
        """Onay gereksinimini hesaplamak için kullanılan politikayı bağlar."""

        self._policy = policy

    @property
    def provider_ids(self) -> list[str]:
        """Kayıtlı sağlayıcı kimlikleri (kayıt sırasıyla)."""

        return [provider.id for provider in self._providers]

    def add_provider(self, provider: ToolProvider) -> None:
        """Çalışma zamanında yeni bir sağlayıcı ekler.

        Aynı kimlikli ikinci kayıt reddedilir: iki sağlayıcı aynı kimliği
        taşısaydı, etkinlik bayrağı hangisini açtığını belirsizleştirirdi.
        """

        if provider.id in self.provider_ids:
            raise CapabilityError(f"'{provider.id}' kimlikli sağlayıcı zaten kayıtlı.")
        self._providers.append(provider)

    def remove_provider(self, provider_id: str) -> bool:
        """Bir sağlayıcıyı kayıttan çıkarır."""

        for index, provider in enumerate(self._providers):
            if provider.id == provider_id:
                del self._providers[index]
                return True
        return False

    async def rebuild(self) -> CapabilitySnapshot:
        """Paylaşılan registry'yi sağlayıcılardan yeniden kurar.

        Hiçbir zaman istisna fırlatmaz: bir sağlayıcı araç üretemezse o
        sağlayıcı atlanır, hata `errors` içinde raporlanır ve diğerleri
        kaydedilmeye devam eder. Tek bir bozuk sağlayıcı, çalışan tüm
        yetenekleri düşürmemelidir.
        """

        self._errors = []
        self._tool_sources = {}
        # Yerinde boşaltma: executor'lar AYNI örneği tutar.
        self._registry.clear()

        for provider in self._providers:
            if not provider.enabled(self._settings):
                continue
            try:
                tools = await provider.tools()
            except Exception:
                logger.exception("capability_provider_failed", extra={"provider": provider.id})
                self._errors.append(f"'{provider.id}' sağlayıcısı araçlarını üretemedi.")
                continue
            self._register_provider_tools(provider.id, tools)

        snapshot = await self.describe()
        logger.info(
            "capabilities_rebuilt",
            extra={
                "providers": len(self._providers),
                "tool_count": len(self._registry.list_tools()),
                "error_count": len(snapshot.errors),
            },
        )
        return snapshot

    def rebuild_sync(self) -> list[str]:
        """`rebuild()`'in senkron eşdeğeri — yalnızca uygulama başlangıcı için.

        Uygulama `create_app` içinde, henüz bir olay döngüsü yokken kurulur.
        Senkron yetenekli sağlayıcılar (`FunctionToolProvider`) bu yoldan
        çalışır; `tools_sync()` sunmayan bir sağlayıcı varsa o sağlayıcı
        atlanır ve bu durum `errors` içinde görünür — başlangıçta asenkron bir
        sağlayıcıyı zorla çalıştırmak, olay döngüsü olmadan sessizce
        başarısız olurdu.

        Returns:
            Kaydedilen araç adları (kayıt sırasıyla).
        """

        self._errors = []
        self._tool_sources = {}
        self._registry.clear()

        for provider in self._providers:
            if not provider.enabled(self._settings):
                continue
            tools_sync = getattr(provider, "tools_sync", None)
            if tools_sync is None:
                self._errors.append(f"'{provider.id}' sağlayıcısı senkron kurulumu desteklemiyor.")
                continue
            try:
                tools = tools_sync()
            except Exception:
                logger.exception("capability_provider_failed", extra={"provider": provider.id})
                self._errors.append(f"'{provider.id}' sağlayıcısı araçlarını üretemedi.")
                continue
            self._register_provider_tools(provider.id, tools)

        logger.info(
            "capabilities_rebuilt_sync",
            extra={
                "providers": len(self._providers),
                "tool_count": len(self._registry.list_tools()),
                "error_count": len(self._errors),
            },
        )
        return [tool.name for tool in self._registry.list_tools()]

    def _register_provider_tools(self, provider_id: str, tools: Iterable[Tool[Any]]) -> None:
        """Bir sağlayıcının araçlarını override uygulayarak kaydeder."""

        for tool in tools:
            override = (
                self._override_store.get(tool.name) if self._override_store is not None else None
            )
            if override is not None and not override.enabled:
                # Kapalı araç HİÇ kaydedilmez: yok olması, kayıtlı ama
                # reddedilen bir araçtan daha dürüsttür.
                continue
            if override is not None and override.permission is not None:
                tool.with_permission_override(override.permission)

            if tool.name in self._tool_sources:
                # İsim çakışması: ikinci kayıt reddedilir ve raporlanır.
                message = (
                    f"'{tool.name}' aracı hem '{self._tool_sources[tool.name]}' hem de "
                    f"'{provider_id}' sağlayıcısından geliyor; ikinci kayıt reddedildi."
                )
                self._errors.append(message)
                logger.warning("capability_tool_name_conflict", extra={"tool_name": tool.name})
                continue

            try:
                self._registry.register(tool)
            except DuplicateToolError:
                self._errors.append(f"'{tool.name}' aracı zaten kayıtlı; ikinci kayıt reddedildi.")
                continue
            self._tool_sources[tool.name] = provider_id

    async def describe(self) -> CapabilitySnapshot:
        """Sağlayıcıları, araçları ve sağlık durumunu birlikte döndürür."""

        providers: list[ProviderView] = []
        for provider in self._providers:
            enabled = provider.enabled(self._settings)
            health = ProviderHealth()
            if enabled:
                health = await provider.health()
            providers.append(
                ProviderView(
                    id=provider.id,
                    description=getattr(provider, "description", ""),
                    enabled=enabled,
                    tool_count=health.tool_count,
                    ok=health.ok,
                    detail=health.detail,
                )
            )

        tools = [
            self._tool_view(tool)
            for tool in sorted(self._registry.list_tools(), key=lambda t: t.name)
        ]
        return CapabilitySnapshot(providers=providers, tools=tools, errors=list(self._errors))

    def tool_views(self) -> list[ToolView]:
        """Kayıtlı araçların görünümlerini döndürür (senkron; sağlık içermez)."""

        return [
            self._tool_view(tool)
            for tool in sorted(self._registry.list_tools(), key=lambda t: t.name)
        ]

    def _tool_view(self, tool: Tool[Any]) -> ToolView:
        declared = tool.permission
        effective = tool.effective_permission
        return ToolView(
            name=tool.name,
            description=tool.description,
            source=tool.source,
            category=tool.category,
            risk_tags=tuple(sorted(tool.risk_tags)),
            permission=effective,
            declared_permission=declared,
            enabled=True,
            requires_approval=(
                self._policy is not None
                and self._policy.decide(effective) is not PermissionDecision.ALLOW
            ),
            untrusted_output=tool.untrusted_output,
            timeout_seconds=tool.timeout_seconds,
            max_output_chars=tool.max_output_chars,
        )

    async def aclose(self) -> None:
        """Tüm sağlayıcıların kaynaklarını serbest bırakır.

        Bir kapanışın başarısız olması diğerlerini engellemez: aksi hâlde tek
        bir bozuk sağlayıcı, geri kalanların bağlantılarını sızdırırdı.
        """

        for provider in self._providers:
            try:
                await provider.aclose()
            except Exception:
                logger.exception(
                    "capability_provider_close_failed", extra={"provider": provider.id}
                )
