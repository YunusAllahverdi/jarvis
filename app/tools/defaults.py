"""Jarvis başlangıcında kaydedilecek güvenli built-in tool'lar."""

from app.tools.builtin import CalculatorTool, GetDateTool, GetTimeTool, SystemStatusTool
from app.tools.registry import ToolRegistry


def build_default_tool_registry() -> ToolRegistry:
    """Sadece READ izinli Step 2 tool'larıyla dolu registry oluşturur."""

    registry = ToolRegistry()
    for tool in (GetTimeTool(), GetDateTool(), CalculatorTool(), SystemStatusTool()):
        registry.register(tool)
    return registry
