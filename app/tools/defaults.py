"""Jarvis başlangıcında kaydedilecek güvenli built-in tool'lar."""

from app.services.memory_retrieval import MemoryRetrievalService
from app.services.user_model_service import UserModelService
from app.tools.builtin import (
    CalculatorTool,
    GetDateTool,
    GetTimeTool,
    MemorySearchTool,
    SystemStatusTool,
    UserProfileTool,
)
from app.tools.registry import ToolRegistry


def build_default_tool_registry() -> ToolRegistry:
    """Sadece READ izinli Step 2 tool'larıyla dolu registry oluşturur."""

    registry = ToolRegistry()
    for tool in (GetTimeTool(), GetDateTool(), CalculatorTool(), SystemStatusTool()):
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
