"""Kimlik doğrulama, kalıcı konuşma ve saat dilimi borçlarının kapanışı.

Kapsam:
 1. Yerel adres + anahtarsız: erişim serbest
 2. Yerel adres + anahtar: anahtar zorunlu
 3. YEREL OLMAYAN adres + anahtarsız: her istek reddedilir
 4. Yerel olmayan adres + anahtar: doğru anahtarla geçilir
 5. Yanlış anahtar reddedilir
 6. Bearer biçimi de kabul edilir
 7. Sağlık ucu her koşulda anahtarsız erişilebilir
 8. Konuşma yeniden başlatmayı atlatır
 9. Tool alanları da kalıcıdır
10. Bozuk satır konuşmayı erişilemez kılmaz
11. Geçmiş sınırı en YENİ mesajları tutar
12. Saat dilimi yapılandırılabilir ve sonuçta bildirilir
13. Geçersiz saat dilimi araçları çökertmez
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.chat import ChatMessage, ToolCall
from app.security.auth import API_TOKEN_HEADER, ApiTokenMiddleware
from app.services.sqlite_conversation import SQLiteConversationStore
from app.tools.builtin.system_info import EmptyInput, GetDateTool, GetTimeTool

_TOKEN = "cok-gizli-api-anahtari"


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Kimlik doğrulama
# ---------------------------------------------------------------------------


def _client(*, token: str = "", host: str = "127.0.0.1") -> TestClient:
    app = FastAPI()
    app.add_middleware(ApiTokenMiddleware, token=token, host=host)

    @app.get("/api/chat")
    async def _protected() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/api/v1/health")
    async def _health() -> dict[str, str]:
        return {"status": "ok"}

    # Kabuğu temsil eden, `/api` DIŞINDA yollar.
    @app.get("/")
    async def _page() -> dict[str, str]:
        return {"page": "shell"}

    @app.get("/assets/app.js")
    async def _asset() -> dict[str, str]:
        return {"asset": "js"}

    return TestClient(app)


def test_local_without_token_is_open() -> None:
    """Tek kullanıcılı bir makinede anahtar zorunlu tutmak gereksiz sürtünmedir."""
    assert _client().get("/api/chat").status_code == 200


def test_local_with_token_requires_it() -> None:
    client = _client(token=_TOKEN)

    assert client.get("/api/chat").status_code == 401
    assert (
        client.get("/api/chat", headers={API_TOKEN_HEADER: _TOKEN}).status_code == 200
    )


def test_non_local_without_token_rejects_everything() -> None:
    """Sunucuyu ağa açmak tek bir ayardır; kimlik katmanı unutulmamalıdır."""
    response = _client(host="0.0.0.0").get("/api/chat")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "api_token_required"


def test_non_local_with_token_is_allowed() -> None:
    client = _client(token=_TOKEN, host="0.0.0.0")

    assert (
        client.get("/api/chat", headers={API_TOKEN_HEADER: _TOKEN}).status_code == 200
    )


def test_wrong_token_is_rejected() -> None:
    client = _client(token=_TOKEN)

    response = client.get("/api/chat", headers={API_TOKEN_HEADER: "yanlis"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"


def test_bearer_scheme_is_accepted() -> None:
    client = _client(token=_TOKEN)

    response = client.get("/api/chat", headers={"Authorization": f"Bearer {_TOKEN}"})

    assert response.status_code == 200


def test_health_is_always_reachable() -> None:
    """Bir sağlık kontrolü anahtarsız sorabilmeli; o uç veri döndürmez."""
    for client in (_client(), _client(token=_TOKEN), _client(host="0.0.0.0")):
        assert client.get("/api/v1/health").status_code == 200


def test_the_page_is_reachable_without_a_token() -> None:
    """Korunan API'dir, sayfa değil.

    Sayfa da korunsaydı kullanıcı anahtarı GİRECEĞİ ekranı hiç göremezdi ve
    tabletten bağlanmak imkânsız olurdu. Derlenmiş kabuk herkese açık HTML ve
    JavaScript'tir; sır taşımaz.
    """
    for client in (_client(token=_TOKEN), _client(host="0.0.0.0")):
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200


def test_api_stays_protected_while_the_page_is_open() -> None:
    """Sayfanın açık olması API'yi açmaz."""
    client = _client(token=_TOKEN, host="0.0.0.0")

    assert client.get("/").status_code == 200
    assert client.get("/api/chat").status_code == 401


# ---------------------------------------------------------------------------
# Kalıcı konuşma
# ---------------------------------------------------------------------------


def test_conversation_survives_a_restart(tmp_path: Path) -> None:
    """Açık sohbetlerin yeniden başlatmada sıfırlanması kapanan borçtu."""
    db = str(tmp_path / "jarvis.db")

    first = SQLiteConversationStore(db)
    first.append_messages(
        "sess-1",
        [
            ChatMessage(role="user", content="merhaba"),
            ChatMessage(role="assistant", content="selam"),
        ],
    )

    # Yeni bir örnek = yeniden başlatılmış uygulama.
    second = SQLiteConversationStore(db)
    conversation = second.get_or_create("sess-1")

    assert [m.content for m in conversation.messages] == ["merhaba", "selam"]


def test_tool_metadata_is_persisted(tmp_path: Path) -> None:
    """Yalnızca metin saklansaydı, bir tool turu yeniden başlatmada yarım kalırdı."""
    store = SQLiteConversationStore(str(tmp_path / "jarvis.db"))
    store.append_messages(
        "sess-1",
        [
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall(name="get_time", arguments={})],
            ),
            ChatMessage(role="tool", tool_name="get_time", content='{"ok": true}'),
        ],
    )

    messages = store.get_or_create("sess-1").messages

    assert messages[0].tool_calls[0].name == "get_time"
    assert messages[1].tool_name == "get_time"


def test_a_corrupt_row_does_not_hide_the_conversation(tmp_path: Path) -> None:
    """Tek bir bozuk kayıt bütün geçmişi erişilemez kılmamalı."""
    db = str(tmp_path / "jarvis.db")
    store = SQLiteConversationStore(db)
    store.append_messages("sess-1", [ChatMessage(role="user", content="saglam")])

    # Geçersiz bir rol ile elle bozuk bir satır yazılır.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO conversation_messages (session_id, role, content) VALUES (?, ?, ?)",
            ("sess-1", "gecersiz-rol", "bozuk"),
        )

    messages = store.get_or_create("sess-1").messages

    assert [m.content for m in messages] == ["saglam"]


def test_history_limit_keeps_the_newest(tmp_path: Path) -> None:
    store = SQLiteConversationStore(str(tmp_path / "jarvis.db"), history_limit=2)
    store.append_messages(
        "sess-1",
        [ChatMessage(role="user", content=str(index)) for index in range(5)],
    )

    messages = store.get_or_create("sess-1").messages

    assert [m.content for m in messages] == ["3", "4"]


def test_unknown_session_starts_empty(tmp_path: Path) -> None:
    store = SQLiteConversationStore(str(tmp_path / "jarvis.db"))

    conversation = store.get_or_create("hic-olmayan")

    assert conversation.messages == []
    assert conversation.session_id == "hic-olmayan"


# ---------------------------------------------------------------------------
# Saat dilimi
# ---------------------------------------------------------------------------


def test_timezone_is_configurable_and_reported() -> None:
    """Bulutta sunucu saatini sessizce vermek yanlış cevaptır."""
    result = _run(GetTimeTool(timezone_name="Europe/Istanbul").execute(EmptyInput()))

    assert "Istanbul" in result["timezone"]


def test_date_uses_the_configured_timezone() -> None:
    result = _run(GetDateTool(timezone_name="Pacific/Kiritimati").execute(EmptyInput()))

    assert "Kiritimati" in result["timezone"]


def test_invalid_timezone_falls_back_instead_of_failing() -> None:
    """Yanlış bir ayar yüzünden saati hiç öğrenememek, kullanışsız bir katılıktır."""
    result = _run(GetTimeTool(timezone_name="Yok/Boyle").execute(EmptyInput()))

    assert result["time"]
    assert result["timezone"]
