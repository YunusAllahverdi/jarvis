"""Sadece açıkça kayıtlı araçlara erişim sağlayan tool registry."""

from threading import RLock

from app.core.chat import ToolDefinition
from app.tools.base import Tool


class ToolRegistryError(RuntimeError):
    """Tool registry hatalarının temel sınıfı."""


class DuplicateToolError(ToolRegistryError):
    """Bir isim ikinci kez kaydedilmek istendiğinde oluşur."""


class ToolRegistry:
    """Tool'ları ada göre saklayan ve listeleyen merkezî registry."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._lock = RLock()

    def register(self, tool: Tool) -> None:
        """Yeni bir tool kaydeder; aynı isimli ikinci kaydı reddeder."""

        with self._lock:
            if tool.name in self._tools:
                raise DuplicateToolError(f"'{tool.name}' adlı tool zaten kayıtlı.")
            self._tools[tool.name] = tool

    def unregister(self, name: str) -> Tool | None:
        """Bir tool'u kayıtlı listeden kaldırır ve varsa döndürür."""

        with self._lock:
            return self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Yalnızca kayıtlı bir tool'u döndürür."""

        with self._lock:
            return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """Kayıtlı tüm tool'ların kararlı bir kopyasını döndürür."""

        with self._lock:
            return list(self._tools.values())

    def list_definitions(self) -> list[ToolDefinition]:
        """Kayıtlı tool'ların LLM'e sunulacak şemalarını döndürür."""

        return [tool.definition for tool in self.list_tools()]
