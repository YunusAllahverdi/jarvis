"""Örnek eklenti — yeni bir yeteneğin nasıl ekleneceğini gösterir.

Bu eklenti BİLİNÇLİ OLARAK işe yaramaz bir araç (`echo`) kaydeder: amacı
davranış eklemek değil, sözleşmeyi çalışan bir örnekle göstermektir. Yeni
bir yetenek (MCP, ses, Home Assistant, tarayıcı ajanı, bilgisayar kontrolü)
eklerken bu dosyayı kopyalayıp `register()` içine gerçek araçlarınızı koyun
ve `BUILTIN_PLUGINS` listesine ekleyin.

Etkinleştirmek için:

    JARVIS_ENABLED_PLUGINS=["example"]

Adı listede geçmediği sürece KAPALIDIR — bu, eklenti sözleşmesinin
varsayılanıdır.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import Field

from app.plugins.base import Plugin, PluginContext
from app.tools.base import PermissionLevel, Tool, ToolInput


class EchoInput(ToolInput):
    """Örnek aracın doğrulanmış girdisi."""

    message: str = Field(min_length=1, max_length=200)


class EchoTool(Tool[EchoInput]):
    """Girdiyi olduğu gibi geri döndüren zararsız örnek araç."""

    name = "example_echo"
    description = "Örnek eklenti: verilen mesajı geri döndürür."
    permission = PermissionLevel.READ
    input_model = EchoInput

    async def execute(self, tool_input: EchoInput) -> dict[str, Any]:
        return {"echo": tool_input.message}


class ExamplePlugin(Plugin):
    """Yeni eklentiler için şablon."""

    name = "example"
    description = "Örnek eklenti (varsayılan kapalı); example_echo aracını ekler."

    def register(self, context: PluginContext) -> Sequence[str]:
        # `enabled()` taban sınıftan gelir: ad `enabled_plugins` listesinde
        # olmalı. Kaydettiğimiz araç READ seviyesindedir, dolayısıyla
        # ToolPermissionPolicy onu serbest bırakır; WRITE/DANGEROUS bir araç
        # kaydetseydik onay akışına girer ve eklenti bunu atlayamazdı.
        tool = EchoTool()
        context.registry.register(tool)
        return [tool.name]
