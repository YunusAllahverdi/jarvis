"""Eklenti (plugin) sözleşmesi.

Bir eklenti, uygulamaya yeni araç ve/veya entegrasyon katan, TEK bir yerden
kaydedilen bir birimdir. Sözleşme iki şeyi garanti eder:

1. **Varsayılan KAPALI.** Hiçbir eklenti, kullanıcı açıkça açmadan
   çalışmaz. Yeni bir yeteneğin sessizce etkinleşmesi, güvenlik modelinin
   en kolay delinme yoludur.
2. **Aynı izin akışı.** Eklentinin kaydettiği her araç, tıpkı yerleşik
   araçlar gibi `ToolPermissionPolicy`'den geçer ve gerekirse onay akışına
   girer. Eklenti bu akışı ATLAYAMAZ — kaydettiği aracın izin seviyesi ne
   gerektiriyorsa o uygulanır.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from app.tools.registry import ToolRegistry

if TYPE_CHECKING:  # pragma: no cover - yalnızca tip denetimi
    from app.config.settings import Settings


@dataclass
class PluginContext:
    """Bir eklentinin kaydolmak için ihtiyaç duyabileceği bağımlılıklar.

    Tek bir taşıyıcı nesne kullanılır çünkü eklenti sayısı arttıkça konum
    argümanları hızla okunamaz hâle gelir; eklenti yalnızca İHTİYACI OLAN
    alanları okur. Kaynak servisler isteğe bağlıdır: verilmeyen kaynak,
    ilgili eklentinin kendini kaydetmemesi anlamına gelir — eksik bir
    kaynak hata değildir.
    """

    registry: ToolRegistry
    settings: Settings

    timezone_name: str | None = None

    # Bağlam/öğrenme servisleri
    memory_retrieval: Any = None
    user_model: Any = None

    # Dosya ve terminal
    workspace_guard: Any = None
    workspace_writable: bool = False
    change_journal: Any = None
    command_policy: Any = None
    terminal_enabled: bool = False
    terminal_timeout_seconds: float = 60.0

    # Notlar
    note_store: Any = None
    notes_writable: bool = True

    # Ağ
    network_guard: Any = None
    research_timeout_seconds: float = 20.0

    # Arayüz
    ui_action_bus: Any = None

    # Harici API anahtarları
    maps_api_key: str = ""

    extras: dict[str, Any] = field(default_factory=dict)
    """Eklentiye özel ek bağımlılıklar (anahtar → değer)."""


@dataclass(frozen=True)
class PluginRegistration:
    """Tek bir eklentinin uygulanma sonucu."""

    plugin: str
    enabled: bool
    tools: tuple[str, ...] = ()

    @property
    def skipped(self) -> bool:
        """Eklenti kapalı olduğu için atlandı mı?"""

        return not self.enabled


class Plugin(ABC):
    """Uygulamaya araç/entegrasyon katan birim.

    Alt sınıflar `name`, `description` ve `register()` sağlar; `enabled()`
    varsayılan olarak ``name``in `settings.enabled_plugins` içinde olmasını
    bekler — yani VARSAYILAN KAPALI. Kendi ön koşulu olan (ör. bir API
    anahtarı gerektiren) eklentiler `enabled()`'ı geçersiz kılabilir, ama
    kapalılık varsayılanı korunmalıdır.
    """

    name: ClassVar[str]
    description: ClassVar[str] = ""

    def enabled(self, settings: Settings) -> bool:
        """Eklenti bu yapılandırmada çalışacak mı?

        Varsayılan kural: adı `enabled_plugins` listesinde olmalı. Liste
        varsayılan olarak BOŞTUR, dolayısıyla yeni bir eklenti kimse
        açmadan asla etkinleşmez.
        """

        return self.name in settings.enabled_plugins

    @abstractmethod
    def register(self, context: PluginContext) -> Sequence[str]:
        """Eklentinin araçlarını kaydeder ve adlarını döndürür.

        Kaydedilecek bir şey yoksa (ör. gerekli kaynak verilmemişse) boş
        liste döndürülür.
        """


class FunctionPlugin(Plugin):
    """Basit bir kayıt fonksiyonunu eklentiye saran yardımcı.

    Mevcut `register_*` fonksiyonlarını tek tek sınıf yazmadan bu arayüze
    taşımak için kullanılır.
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        register: Callable[[PluginContext], Sequence[str]],
        enabled: Callable[[Settings], bool],
    ) -> None:
        """
        Args:
            name: Eklenti adı (config bayrağı bu adı kullanır).
            description: İnsan okunur açıklama.
            register: `PluginContext -> Sequence[str]` imzalı kayıt fonksiyonu.
            enabled: `Settings -> bool` imzalı etkinlik yüklemi.
        """
        self._name = name
        self._description = description
        self._register = register
        self._enabled = enabled

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def description(self) -> str:  # type: ignore[override]
        return self._description

    def enabled(self, settings: Settings) -> bool:
        return bool(self._enabled(settings))

    def register(self, context: PluginContext) -> Sequence[str]:
        return list(self._register(context))
