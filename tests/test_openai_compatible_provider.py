"""OpenAI uyumlu sağlayıcı adaptörü.

Kapsam:
 1. Metin cevabı çözülür
 2. Model adı ve mesajlar isteğe doğru konur
 3. API anahtarı Authorization başlığında gider
 4. Anahtar yoksa başlık hiç eklenmez (yerel sunucular)
 5. Araç tanımları sözleşmenin biçimine çevrilir
 6. Araç çağrısının JSON METNİ argümanları sözlüğe çevrilir
 7. Nesne olarak gelen argümanlar da kabul edilir
 8. Bozuk argüman metni sessizce boş sözlüğe düşürülmez
 9. Araç sonucu mesajı tool_call_id taşır
10. Asistan araç çağrısı argümanları metin olarak serileştirilir
11. Model yapılandırılmamışsa açık hata verilir
12. Ulaşılamayan sağlayıcı LLMUnavailableError verir
13. Hata gövdesindeki mesaj kullanıcıya taşınır
14. Hata mesajı API anahtarını sızdırmaz
15. Beklenmeyen yanıt biçimi LLMResponseError verir
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.adapters.llm.base import (
    LLMConfigurationError,
    LLMProviderError,
    LLMResponseError,
    LLMUnavailableError,
)
from app.adapters.llm.openai_compatible import OpenAICompatibleProvider
from app.core.chat import ChatMessage, ToolCall, ToolDefinition

_KEY = "sk-cok-gizli-anahtar-123456"


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _provider(handler, *, api_key: str | None = _KEY, model: str | None = "test-model"):
    """Ağa çıkmadan gerçek serileştirmeyi sınayan bir sağlayıcı kurar."""

    return OpenAICompatibleProvider(
        base_url="https://saglayici.example/v1",
        model=model,
        api_key=api_key,
        transport=httpx.MockTransport(handler),
    )


def _text_reply(content: str = "selam") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _capture() -> tuple[list[httpx.Request], Any]:
    """İsteği kaydeden ve sabit bir metin cevabı dönen bir işleyici."""

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _text_reply()

    return seen, handler


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content.decode("utf-8"))


_HELLO = [ChatMessage(role="user", content="merhaba")]


# ---------------------------------------------------------------------------
# 1-4. İstek biçimi ve kimlik
# ---------------------------------------------------------------------------

def test_text_reply_is_parsed() -> None:
    """Düz metin cevabı çözülmeli."""
    assert _run(_provider(lambda r: _text_reply("selam")).generate(_HELLO)) == "selam"


def test_model_and_messages_are_sent() -> None:
    """Model adı ve mesajlar isteğe doğru yerleştirilmeli."""
    seen, handler = _capture()

    _run(_provider(handler).generate(_HELLO))

    body = _body(seen[0])
    assert body["model"] == "test-model"
    assert body["messages"] == [{"role": "user", "content": "merhaba"}]
    assert seen[0].url.path.endswith("/chat/completions")


def test_api_key_travels_in_the_authorization_header() -> None:
    """Anahtar başlıkta gitmeli, gövdede değil."""
    seen, handler = _capture()

    _run(_provider(handler).generate(_HELLO))

    assert seen[0].headers["Authorization"] == f"Bearer {_KEY}"
    assert _KEY not in seen[0].content.decode("utf-8")


def test_no_key_means_no_header() -> None:
    """Anahtar gerekmeyen yerel sunucular için başlık hiç eklenmemeli."""
    seen, handler = _capture()

    _run(_provider(handler, api_key=None).generate(_HELLO))

    assert "Authorization" not in seen[0].headers


# ---------------------------------------------------------------------------
# 5-10. Araç sözleşmesi
# ---------------------------------------------------------------------------

def test_tool_definitions_are_translated() -> None:
    """Araç tanımı sözleşmenin function biçimine çevrilmeli."""
    seen, handler = _capture()
    tool = ToolDefinition(
        name="okuyucu", description="Dosya okur.", input_schema={"type": "object"}
    )

    _run(_provider(handler).generate_with_tools(_HELLO, tools=[tool]))

    sent = _body(seen[0])["tools"][0]
    assert sent["type"] == "function"
    assert sent["function"]["name"] == "okuyucu"
    assert sent["function"]["parameters"] == {"type": "object"}


def test_tool_call_arguments_arrive_as_json_text_and_are_decoded() -> None:
    """Argümanlar METİN olarak gelir; sözlüğe çevrilmeli.

    Çevrilmezse araç şeması boş bir sözlük görür ve çağrı sessizce
    argümansız çalışırdı.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "okuyucu",
                                        "arguments": '{"path": "rapor.txt"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    response = _run(_provider(handler).generate_with_tools(_HELLO, tools=()))

    assert response.tool_calls[0].arguments == {"path": "rapor.txt"}
    assert response.tool_calls[0].call_id == "call_1"


def test_object_arguments_are_also_accepted() -> None:
    """Bazı sağlayıcılar nesne döndürüyor; o da kabul edilmeli."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "okuyucu",
                                        "arguments": {"path": "a.txt"},
                                    }
                                }
                            ],
                        }
                    }
                ]
            },
        )

    response = _run(_provider(handler).generate_with_tools(_HELLO, tools=()))

    assert response.tool_calls[0].arguments == {"path": "a.txt"}


def test_broken_arguments_are_reported_not_swallowed() -> None:
    """Ayrıştırılamayan argüman metni hata vermeli.

    Sessizce boş sözlüğe düşürmek, aracın argümanları hiç verilmemiş gibi
    çalışması demek olurdu.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"function": {"name": "okuyucu", "arguments": "{bozuk"}}
                            ],
                        }
                    }
                ]
            },
        )

    with pytest.raises(LLMResponseError):
        _run(_provider(handler).generate_with_tools(_HELLO, tools=()))


def test_tool_result_message_carries_the_call_id() -> None:
    """Araç sonucu, ait olduğu çağrıya bağlanmalı."""
    seen, handler = _capture()
    messages = [
        ChatMessage(role="user", content="oku"),
        ChatMessage(role="tool", tool_name="call_1", content='{"ok": true}'),
    ]

    _run(_provider(handler).generate_with_tools(messages, tools=()))

    tool_message = _body(seen[0])["messages"][1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_1"


def test_assistant_tool_calls_are_serialised_as_text() -> None:
    """Giden araç çağrısının argümanları da metin olmalı."""
    seen, handler = _capture()
    messages = [
        ChatMessage(role="user", content="oku"),
        ChatMessage(
            role="assistant",
            tool_calls=[ToolCall(name="okuyucu", arguments={"path": "a.txt"}, call_id="c1")],
        ),
    ]

    _run(_provider(handler).generate_with_tools(messages, tools=()))

    call = _body(seen[0])["messages"][1]["tool_calls"][0]
    assert call["id"] == "c1"
    assert json.loads(call["function"]["arguments"]) == {"path": "a.txt"}


# ---------------------------------------------------------------------------
# 11-15. Hata yolları
# ---------------------------------------------------------------------------

def test_missing_model_is_reported_clearly() -> None:
    """Model seçilmemişse anlaşılır bir yapılandırma hatası verilmeli."""
    with pytest.raises(LLMConfigurationError):
        _run(_provider(lambda r: _text_reply(), model=None).generate(_HELLO))


def test_unreachable_provider_is_reported() -> None:
    """Bağlantı kurulamıyorsa kullanılamaz denmeli."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("bağlanamadı", request=request)

    with pytest.raises(LLMUnavailableError):
        _run(_provider(handler).generate(_HELLO))


def test_error_body_message_is_surfaced() -> None:
    """Sağlayıcının açıklaması kullanıcıya taşınmalı."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "kota doldu"}})

    with pytest.raises(LLMProviderError) as exc:
        _run(_provider(handler).generate(_HELLO))

    assert "kota doldu" in str(exc.value)


def test_error_message_does_not_leak_the_key() -> None:
    """Hata mesajı anahtarı sızdırmamalı."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(LLMProviderError) as exc:
        _run(_provider(handler).generate(_HELLO))

    assert _KEY not in str(exc.value)


def test_unexpected_shape_is_reported() -> None:
    """Beklenmeyen yanıt biçimi açık bir hata vermeli."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"beklenmeyen": True})

    with pytest.raises(LLMResponseError):
        _run(_provider(handler).generate(_HELLO))
