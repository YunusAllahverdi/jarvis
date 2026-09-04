"""UI aksiyon kanalı — ajanın kullanıcının ekranını sürmesi.

Kapsam:
 1. Aksiyon kuyruğa girer ve okunur
 2. Okuma TÜKETİR: ikinci okuma boş döner
 3. Aksiyonlar oturuma bağlıdır; başka oturumda görünmez
 4. Oturumsuz aksiyonlar düşürülmez
 5. Kuyruk sınırı aşılınca EN ESKİ atılır
 6. Oturum sayısı sınırlıdır (sızıntı yok)
 7. Ajan panel adı UYDURAMAZ — kapalı küme
 8. Ajan ekrana SERBEST METİN gönderemez
 9. Araç READ izinlidir (onay kapısına takılmaz)
10. Araç "açıldı" değil "istendi" der
11. Kanal yoksa araç hiç kaydedilmez
12. API ucu aksiyonları döndürür ve tüketir
13. Kanal bağlı değilse uç 503 döner
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.ui import router as ui_router
from app.tools.base import PermissionLevel
from app.tools.builtin.ui import ShowPanelInput, ShowPanelTool
from app.tools.defaults import register_ui_tool
from app.tools.registry import ToolRegistry
from app.ui.actions import MAX_ACTIONS_PER_SESSION, UIActionBus, UIPanel


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Kanal
# ---------------------------------------------------------------------------


def test_action_is_queued_and_read() -> None:
    bus = UIActionBus()
    bus.publish(UIPanel.NOTES, session_id="s1", reason="notlara bakılıyor")

    actions = bus.consume(session_id="s1")

    assert len(actions) == 1
    assert actions[0].panel is UIPanel.NOTES
    assert actions[0].reason == "notlara bakılıyor"


def test_reading_consumes() -> None:
    """Kalsalardı kullanıcının kapattığı pencere her yoklamada geri gelirdi."""
    bus = UIActionBus()
    bus.publish(UIPanel.SYSTEM, session_id="s1")

    assert len(bus.consume(session_id="s1")) == 1
    assert bus.consume(session_id="s1") == []


def test_actions_are_scoped_to_a_session() -> None:
    """İki sekme açık olan kullanıcı, diğerinin panelini görmemelidir."""
    bus = UIActionBus()
    bus.publish(UIPanel.NOTES, session_id="s1")

    assert bus.consume(session_id="s2") == []
    assert len(bus.consume(session_id="s1")) == 1


def test_sessionless_actions_are_not_dropped() -> None:
    """Ajan oturum kimliği olmadan da çalıştırılabilir; isteği düşürmek kanalı sessizce çalışmaz kılardı."""
    bus = UIActionBus()
    bus.publish(UIPanel.CODING)

    assert len(bus.consume()) == 1


def test_queue_limit_drops_the_oldest() -> None:
    """Aksiyonlar geçici niyetlerdir; en yeni, kullanıcının konuştuğu şeye en yakındır."""
    bus = UIActionBus(max_per_session=2)
    bus.publish(UIPanel.NOTES, session_id="s1")
    bus.publish(UIPanel.MEMORY, session_id="s1")
    bus.publish(UIPanel.SYSTEM, session_id="s1")

    panels = [action.panel for action in bus.consume(session_id="s1")]

    assert panels == [UIPanel.MEMORY, UIPanel.SYSTEM]


def test_session_count_is_bounded() -> None:
    """Kimlikler istemciden gelir; sınırsız sözlük bir sızıntıdır."""
    bus = UIActionBus(max_sessions=3)
    for index in range(10):
        bus.publish(UIPanel.NOTES, session_id=f"s{index}")

    live = sum(1 for index in range(10) if bus.pending_count(session_id=f"s{index}"))
    assert live <= 3


def test_default_queue_limit_is_small() -> None:
    """Kabuk açıldığında beş pencerenin birden açılması yardımcı olmaz."""
    assert MAX_ACTIONS_PER_SESSION <= 5


# ---------------------------------------------------------------------------
# Araç
# ---------------------------------------------------------------------------


def test_agent_cannot_invent_a_panel_name() -> None:
    """Kapalı küme: uydurulan değer şema doğrulamasında reddedilir."""
    with pytest.raises(ValidationError):
        ShowPanelInput(panel="kullanicinin_banka_hesabi")  # type: ignore[arg-type]


def test_agent_cannot_send_free_text_to_the_screen() -> None:
    """Serbest içerik gönderilseydi, bir web sayfasından okunan metin
    kullanıcının ekranında Jarvis'in sözü gibi görünebilirdi."""
    with pytest.raises(ValidationError):
        ShowPanelInput(panel=UIPanel.NOTES, content="<h1>zararlı</h1>")  # type: ignore[call-arg]


def test_show_panel_is_read_level() -> None:
    """Panel açmak dosyaya dokunmaz, komut çalıştırmaz ve geri alınabilir."""
    assert ShowPanelTool(bus=UIActionBus()).permission is PermissionLevel.READ


def test_tool_reports_requested_not_opened() -> None:
    """Kabuk açık değilse hiçbir şey açılmaz; "açtım" demek yanlış olurdu."""
    bus = UIActionBus()
    result = _run(ShowPanelTool(bus=bus).execute(ShowPanelInput(panel=UIPanel.NOTES)))

    assert result["requested"] is True
    assert result["panel"] == "notes"
    assert "opened" not in result


def test_tool_queues_into_its_session() -> None:
    bus = UIActionBus()
    tool = ShowPanelTool(bus=bus, session_id="s1")

    _run(tool.execute(ShowPanelInput(panel=UIPanel.MEMORY)))

    assert bus.pending_count(session_id="s1") == 1


def test_no_bus_means_no_tool() -> None:
    registry = ToolRegistry()

    assert register_ui_tool(registry, bus=None) == []


def test_every_panel_is_described_for_the_model() -> None:
    """Katalog enum'dan üretilir; yeni panel eklendiğinde açıklama eksik kalmaz."""
    description = ShowPanelTool(bus=UIActionBus()).description

    for panel in UIPanel:
        assert panel.value in description


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _client(bus: UIActionBus | None) -> TestClient:
    app = FastAPI()
    app.state.ui_action_bus = bus
    app.include_router(ui_router, prefix="/api")
    return TestClient(app)


def test_endpoint_returns_and_consumes() -> None:
    bus = UIActionBus()
    bus.publish(UIPanel.NOTES, session_id="s1")
    client = _client(bus)

    first = client.get("/api/ui/actions", params={"session_id": "s1"}).json()
    second = client.get("/api/ui/actions", params={"session_id": "s1"}).json()

    assert first["count"] == 1
    assert first["actions"][0]["panel"] == "notes"
    assert second["count"] == 0


def test_endpoint_reports_missing_bus() -> None:
    response = _client(None).get("/api/ui/actions")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ui_actions_unavailable"
