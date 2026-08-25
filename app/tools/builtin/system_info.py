"""Sadece sistemden okuma yapan tarih, saat ve durum tool'ları."""

from datetime import datetime
from pathlib import Path

import psutil

from app.tools.base import PermissionLevel, Tool, ToolInput


class EmptyInput(ToolInput):
    """Argument kabul etmeyen tool'lar için katı boş input modeli."""


class GetTimeTool(Tool[EmptyInput]):
    """Yerel sistem saatini döndürür."""

    name = "get_time"
    description = "Mevcut yerel sistem saatini döndürür."
    permission = PermissionLevel.READ
    input_model = EmptyInput

    async def execute(self, tool_input: EmptyInput) -> dict[str, str]:
        del tool_input
        now = datetime.now().astimezone()
        return {"time": now.strftime("%H:%M:%S"), "timezone": str(now.tzinfo)}


class GetDateTool(Tool[EmptyInput]):
    """Yerel sistem tarihini döndürür."""

    name = "get_date"
    description = "Mevcut yerel sistem tarihini ISO 8601 formatında döndürür."
    permission = PermissionLevel.READ
    input_model = EmptyInput

    async def execute(self, tool_input: EmptyInput) -> dict[str, str]:
        del tool_input
        now = datetime.now().astimezone()
        return {"date": now.date().isoformat(), "timezone": str(now.tzinfo)}


class SystemStatusTool(Tool[EmptyInput]):
    """CPU, RAM ve çalışma diski kullanımını salt-okunur olarak döndürür."""

    name = "system_status"
    description = "CPU, RAM ve disk kullanımına ait temel sistem durumunu döndürür."
    permission = PermissionLevel.READ
    input_model = EmptyInput

    async def execute(self, tool_input: EmptyInput) -> dict[str, object]:
        del tool_input
        memory = psutil.virtual_memory()
        disk_root = Path.cwd().anchor or "/"
        disk = psutil.disk_usage(disk_root)
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory": {
                "percent": memory.percent,
                "total_bytes": memory.total,
                "available_bytes": memory.available,
            },
            "disk": {
                "path": disk_root,
                "percent": disk.percent,
                "total_bytes": disk.total,
                "free_bytes": disk.free,
            },
        }
