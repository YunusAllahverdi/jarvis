"""Sadece sistemden okuma yapan tarih, saat ve durum tool'ları.

SAAT DİLİMİ HAKKINDA: Bu araçlar varsayılan olarak SUNUCUNUN saatini
döndürür. Sunucu kullanıcının kendi makinesindeyken bu doğrudur; bulutta
çalışan bir örnekte ise yanlıştır ve kullanıcı "saat kaç?" sorusuna başka
bir kıtanın saatini alır.

Bu yüzden araçlar isteğe bağlı bir saat dilimi kabul eder ve kullandıkları
dilimi SONUÇTA BİLDİRİRLER. Yanlış bir saati sessizce vermek yerine, hangi
dilime göre konuşulduğunu görünür kılmak tercih edildi.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psutil

from app.tools.base import PermissionLevel, Tool, ToolInput


class EmptyInput(ToolInput):
    """Argument kabul etmeyen tool'lar için katı boş input modeli."""


def _now(timezone_name: str | None) -> datetime:
    """Yapılandırılmış dilimde şimdiki zamanı verir; dilim geçersizse yerel.

    Geçersiz bir dilim adı yüzünden araç HATA VERMEZ: kullanıcı yanlış bir
    ayar yazdığında saati hiç öğrenememesindense, sunucunun saatini alıp
    hangi dilimde olduğunu görmesi daha kullanışlıdır. Dönen `timezone`
    alanı zaten gerçekte kullanılanı söyler.
    """
    if timezone_name:
        try:
            return datetime.now(ZoneInfo(timezone_name))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return datetime.now().astimezone()


class GetTimeTool(Tool[EmptyInput]):
    """Yapılandırılmış saat dilimine göre saati döndürür."""

    name = "get_time"
    description = "Mevcut saati döndürür."
    permission = PermissionLevel.READ
    input_model = EmptyInput

    def __init__(self, *, timezone_name: str | None = None) -> None:
        """
        Args:
            timezone_name: IANA saat dilimi adı (ör. "Europe/Istanbul").
                Verilmezse sunucunun yerel dilimi kullanılır.
        """
        self._timezone_name = timezone_name

    async def execute(self, tool_input: EmptyInput) -> dict[str, str]:
        del tool_input
        now = _now(self._timezone_name)
        return {"time": now.strftime("%H:%M:%S"), "timezone": str(now.tzinfo)}


class GetDateTool(Tool[EmptyInput]):
    """Yapılandırılmış saat dilimine göre tarihi döndürür."""

    name = "get_date"
    description = "Mevcut tarihi ISO 8601 formatında döndürür."
    permission = PermissionLevel.READ
    input_model = EmptyInput

    def __init__(self, *, timezone_name: str | None = None) -> None:
        self._timezone_name = timezone_name

    async def execute(self, tool_input: EmptyInput) -> dict[str, str]:
        del tool_input
        now = _now(self._timezone_name)
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
