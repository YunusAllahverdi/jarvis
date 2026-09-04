"""Jarvis başlangıcında kaydedilecek güvenli built-in tool'lar."""

from app.notes.store import NoteStore
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.user_model_service import UserModelService
from app.security.checkpoints import ChangeJournal
from app.security.commands import CommandPolicy
from app.security.network import NetworkGuard
from app.security.paths import PathGuard
from app.tools.builtin.notes import NoteSearchTool, NoteWriteTool
from app.tools.builtin.research import FetchUrlTool
from app.tools.builtin.ui import ShowPanelTool
from app.ui.actions import UIActionBus
from app.tools.builtin import (
    CalculatorTool,
    GetDateTool,
    EditFileTool,
    GetTimeTool,
    GitDiffTool,
    GitStatusTool,
    GrepTool,
    ListDirTool,
    ProjectOverviewTool,
    MemorySearchTool,
    ReadFileTool,
    RunCommandTool,
    WriteFileTool,
    SystemStatusTool,
    UserProfileTool,
)
from app.tools.registry import ToolRegistry


def build_default_tool_registry(*, timezone_name: str | None = None) -> ToolRegistry:
    """Sadece READ izinli temel tool'larla dolu registry oluşturur.

    Args:
        timezone_name: Saat/tarih araçlarının kullanacağı IANA dilim adı.
            Verilmezse sunucunun yerel dilimi kullanılır.
    """

    registry = ToolRegistry()
    for tool in (
        GetTimeTool(timezone_name=timezone_name),
        GetDateTool(timezone_name=timezone_name),
        CalculatorTool(),
        SystemStatusTool(),
    ):
        registry.register(tool)
    return registry


def register_context_tools(
    registry: ToolRegistry,
    *,
    memory_retrieval: MemoryRetrievalService | None = None,
    user_model: UserModelService | None = None,
) -> list[str]:
    """Jarvis'in kendi bilgi katmanlarını okuyan tool'ları kaydeder.

    Bu tool'lar `build_default_tool_registry()`'ye BİLİNÇLİ OLARAK dahil
    değildir: kurucularında birer servis gerektirirler ve bu servisler
    yalnızca uygulama başlatıldığında mevcut olur. Ayrıca sohbet akışının
    LLM'e sunduğu tool yüzeyini değiştirmemek için ayrı tutulurlar.

    Servisi verilmeyen tool sessizce atlanır — eksik bir kaynak hata değildir.

    Returns:
        Gerçekten kaydedilen tool adları.
    """
    registered: list[str] = []
    if memory_retrieval is not None:
        registry.register(MemorySearchTool(retrieval=memory_retrieval))
        registered.append(MemorySearchTool.name)
    if user_model is not None:
        registry.register(UserProfileTool(user_model=user_model))
        registered.append(UserProfileTool.name)
    return registered


def register_filesystem_tools(
    registry: ToolRegistry,
    *,
    guard: PathGuard | None = None,
    writable: bool = False,
    journal: ChangeJournal | None = None,
) -> list[str]:
    """Çalışma dizinini okuyan tool'ları kaydeder.

    Bekçi verilmezse HİÇBİRİ kaydedilmez ve ajanın dosya okuma yeteneği hiç
    var olmaz. Varsayılanın kapalı olması bilinçlidir: dosya erişimi,
    kullanıcının bir çalışma kökü belirlemesiyle açılmalıdır, uygulamanın
    kendiliğinden verdiği bir yetki olmamalıdır.

    Yazma araçları AYRICA `writable` gerektirir. Okumak ve yazmak iki ayrı
    karardır: kullanıcı ajanın deposunu incelemesini isteyip değiştirmesini
    istemeyebilir ve tek bir ayar bunu ifade edemezdi.

    Tüm araçlar AYNI bekçi örneğini paylaşır; ayrı ayrı kurulsalardı biri
    sıkılaştırıldığında diğerleri geride kalabilirdi.

    Returns:
        Gerçekten kaydedilen tool adları.
    """
    if guard is None:
        return []

    tools: list = [
        ReadFileTool(guard=guard),
        ListDirTool(guard=guard),
        GrepTool(guard=guard),
        # Değişiklikleri görünür kılan salt-okunur git araçları okuma
        # yeteneğinin parçasıdır: ne değiştiğini görmek için yazabilmek
        # gerekmez.
        GitStatusTool(guard=guard),
        GitDiffTool(guard=guard),
        # Yapıyı çıkarmak da okumaktır: ajanın değiştirmeden önce
        # anlaması için gereken ilk bakış.
        ProjectOverviewTool(guard=guard),
    ]
    if writable:
        tools += [
            WriteFileTool(guard=guard, journal=journal),
            EditFileTool(guard=guard, journal=journal),
        ]
    for tool in tools:
        registry.register(tool)
    return [tool.name for tool in tools]


def register_note_tools(
    registry: ToolRegistry,
    *,
    store: NoteStore | None = None,
    writable: bool = True,
) -> list[str]:
    """Not araçlarını kaydeder.

    Depo verilmezse HİÇBİRİ kaydedilmez. `writable` kapatılırsa yalnızca
    arama kaydedilir: kullanıcı, ajanın notlarını okumasını isteyip
    yazmasını istemeyebilir ve tek bir ayar bunu ifade edemezdi — dosya
    araçlarındaki ayrımın aynısı.

    Returns:
        Gerçekten kaydedilen tool adları.
    """
    if store is None:
        return []

    tools: list = [NoteSearchTool(store=store)]
    if writable:
        tools.append(NoteWriteTool(store=store))
    for tool in tools:
        registry.register(tool)
    return [tool.name for tool in tools]


def register_ui_tool(
    registry: ToolRegistry, *, bus: UIActionBus | None = None
) -> list[str]:
    """Panel açma aracını kaydeder.

    Kanal verilmezse araç hiç var olmaz. Panel açmak READ seviyesindedir:
    dosyaya dokunmaz, komut çalıştırmaz ve geri alınamaz bir şey yapmaz —
    kullanıcı paneli kapatabilir.

    Returns:
        Gerçekten kaydedilen tool adları.
    """
    if bus is None:
        return []
    registry.register(ShowPanelTool(bus=bus))
    return [ShowPanelTool.name]


def register_research_tool(
    registry: ToolRegistry,
    *,
    guard: NetworkGuard | None = None,
    timeout_seconds: float = 20.0,
) -> list[str]:
    """Web getirme aracını kaydeder.

    Bekçi verilmezse araç hiç var olmaz. Ağ erişimi, dosya erişimi ve
    terminal gibi AYRI bir karardır: ajanın internete çıkması, kullanıcının
    açıkça vermesi gereken bir yetkidir.

    Returns:
        Gerçekten kaydedilen tool adları.
    """
    if guard is None:
        return []
    registry.register(FetchUrlTool(guard=guard, timeout_seconds=timeout_seconds))
    return [FetchUrlTool.name]


def register_terminal_tool(
    registry: ToolRegistry,
    *,
    guard: PathGuard | None = None,
    command_policy: CommandPolicy | None = None,
    enabled: bool = False,
    max_timeout_seconds: float = 60.0,
) -> list[str]:
    """Komut çalıştırma tool'unu kaydeder.

    Üç şart birden gerekir: bir çalışma kökü, bir komut politikası ve açık
    bir etkinleştirme. Herhangi biri eksikse araç hiç var olmaz.

    Etkinleştirme dosya izinlerinden AYRI bir karardır: dosya okumak ile
    program çalıştırmak aynı büyüklükte riskler değildir ve tek bir ayarla
    ifade edilmemelidirler.

    Returns:
        Gerçekten kaydedilen tool adları.
    """
    if not enabled or guard is None or command_policy is None:
        return []

    registry.register(
        RunCommandTool(
            guard=guard,
            command_policy=command_policy,
            max_timeout_seconds=max_timeout_seconds,
        )
    )
    return [RunCommandTool.name]
