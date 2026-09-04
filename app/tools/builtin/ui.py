"""Ajanın kullanıcının ekranını sürdüğü araç.

Bu, kabuğun "ajan tarafından sürülen paneller" yeteneğinin ajan tarafındaki
yarısıdır; diğer yarısı `app/ui/actions.py` ve kabuğun onu yoklaması.

İZİN SEVİYESİ READ'TİR ve bu tartışıldı: bir panel açmak dosyaya dokunmaz,
komut çalıştırmaz, dışarıya istek yapmaz ve geri alınamaz bir şey yapmaz —
kullanıcı paneli kapatabilir. Onaya tabi olsaydı, "notlarını açayım mı?" diye
sorup beklemek etkileşimi kolaylaştırmak yerine zorlaştırırdı.

ARACIN SÖYLEYEMEDİĞİ ŞEY: serbest metin. Ajan ekrana içerik gönderemez,
yalnızca KAPALI bir kümeden bir panel seçebilir. Serbest içerik gönderilseydi,
bir web sayfasından okunan metin kullanıcının ekranında Jarvis'in sözü gibi
görünebilirdi.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput
from app.ui.actions import UIActionBus, UIPanel

SHOW_PANEL_TOOL_NAME = "show_panel"

_PANEL_DESCRIPTIONS = {
    UIPanel.NOTES: "kalıcı notlar",
    UIPanel.MEMORY: "bellek kayıtları",
    UIPanel.EXPERIENCES: "son etkileşimler",
    UIPanel.TRAITS: "öğrenilmiş kullanıcı örüntüleri",
    UIPanel.USER_MODEL: "kullanıcı modeli özeti",
    UIPanel.SYSTEM: "sistem kaynak kullanımı",
    UIPanel.CODING: "kodlama ajanı",
}


def _panel_catalog() -> str:
    """Araç açıklamasına girecek panel listesini üretir.

    Listeyi elle yazmak yerine enum'dan üretmek bilinçlidir: yeni bir panel
    eklendiğinde açıklama kendiliğinden güncellenir ve modele var olmayan ya
    da eksik bir liste sunulmaz.
    """
    return ", ".join(
        f"{panel.value} ({_PANEL_DESCRIPTIONS.get(panel, panel.value)})"
        for panel in UIPanel
    )


class ShowPanelInput(ToolInput):
    """`show_panel` tool'unun doğrulanmış input'u.

    `panel` bir enum'dur: model buraya yeni bir değer uyduramaz, uydurursa
    şema doğrulaması çağrıyı reddeder.
    """

    panel: UIPanel
    reason: str = Field(default="", max_length=200)


class ShowPanelTool(Tool[ShowPanelInput]):
    """Kullanıcının ekranında bir paneli açar."""

    name = SHOW_PANEL_TOOL_NAME
    description = (
        "Kullanıcının ekranında bir paneli açar. Yalnızca şu paneller "
        f"açılabilir: {_panel_catalog()}. Panel içeriği bu araçla "
        "değiştirilemez; yalnızca açılır."
    )
    permission = PermissionLevel.READ
    input_model = ShowPanelInput

    def __init__(self, *, bus: UIActionBus, session_id: str | None = None) -> None:
        """
        Args:
            bus: Aksiyonun konacağı kanal.
            session_id: Aksiyonun hangi oturuma ait olduğu. Verilmezse
                oturumsuz kuyruğa girer — ajan bir oturum kimliği olmadan da
                çalıştırılabilir ve isteği düşürmek kanalı sessizce çalışmaz
                kılardı.
        """
        self._bus = bus
        self._session_id = session_id

    async def execute(self, tool_input: ShowPanelInput) -> dict[str, Any]:
        try:
            action = self._bus.publish(
                tool_input.panel,
                session_id=self._session_id,
                reason=tool_input.reason,
            )
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError("Panel açılamadı.") from exc

        return {
            "panel": action.panel.value,
            "action_id": action.id,
            # Panelin AÇILDIĞI değil, açılmasının İSTENDİĞİ bildirilir:
            # kabuk açık değilse hiçbir şey açılmayacaktır ve ajanın
            # kullanıcıya "açtım" demesi yanlış olurdu.
            "requested": True,
        }
