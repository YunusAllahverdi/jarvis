"""Anthropic Messages API adaptörü.

Bu adaptörün varlık sebebi Anthropic'in OpenAI sözleşmesinden ayrılmasıdır;
bu yüzden testler o AYRIMLARI sınar. Hepsi sessiz hataya açık noktalardır:
yanlış yapılırsa istek 400 döner ya da bağlam sessizce kaybolur.

Kapsam:
 1. Uç nokta `/v1/messages`
 2. Anahtar `x-api-key` başlığında ve `anthropic-version` zorunlu
 3. `max_tokens` her istekte var
 4. System mesajı mesaj listesinden ÇIKARILIR, üst düzeye taşınır
 5. Birden fazla system mesajı birleştirilir, atılmaz
 6. Araç şeması sarmalayıcısız `input_schema` biçiminde
 7. Asistan araç çağrısı `tool_use` bloğuna, argümanlar NESNE olarak
 8. Araç sonucu `user` rolünde `tool_result` bloğu, `tool_use_id` ile bağlı
 9. Metin blokları birleştirilerek çözülür
10. `tool_use` blokları ToolCall'a çevrilir
11. Metin ve araç çağrısı aynı yanıtta birlikte gelebilir
12. Model yapılandırılmamışsa açık hata
13. Anahtar yapılandırılmamışsa açık hata
14. Ulaşılamayan sağlayıcı LLMUnavailableError
15. Hata gövdesindeki mesaj kullanıcıya taşınır
16. Hata mesajı API anahtarını sızdırmaz
17. Beklenmeyen yanıt biçimi LLMResponseError
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.adapters.llm.anthropic import ANTHROPIC_VERSION, AnthropicProvider
from app.adapters.llm.base import (
    LLMConfigurationError,
    LLMProviderError,
    LLMResponseError,
    LLMUnavailableError,
)
from app.core.chat import ChatMessage, ToolCall, ToolDefinition

_KEY = "sk-ant-cok-gizli-anahtar-123456"


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _provider(handler, *, api_key: str | None = _KEY, model: str | None = "claude-test"):
    """Ağa çıkmadan gerçek serileştirmeyi sınayan bir sağlayıcı kurar."""

    return AnthropicProvider(
        base_url="https://anthropic.example",
        model=model,
        api_key=api_key,
        transport=httpx.MockTransport(handler),
    )


def _text_reply(content: str = "selam") -> httpx.Response:
    return httpx.Response(200, json={"content": [{"type": "text", "text": content}]})


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

_TOOL = ToolDefinition(
    name="hava_durumu",
    description="Bir şehrin hava durumunu verir.",
    input_schema={"type": "object", "properties": {"sehir": {"type": "string"}}},
)


# ---------------------------------------------------------------------------
# 1-3. Uç nokta, kimlik başlıkları ve zorunlu alanlar
# ---------------------------------------------------------------------------

def test_request_goes_to_messages_endpoint() -> None:
    """Uç nokta `/v1/messages` olmalı; `/chat/completions` değil."""
    seen, handler = _capture()
    _run(_provider(handler).generate(_HELLO))
    assert str(seen[0].url) == "https://anthropic.example/v1/messages"


def test_api_key_travels_in_x_api_key_header() -> None:
    """Anahtar `x-api-key` başlığında gider, Authorization'da değil."""
    seen, handler = _capture()
    _run(_provider(handler).generate(_HELLO))
    assert seen[0].headers["x-api-key"] == _KEY
    assert "authorization" not in seen[0].headers


def test_anthropic_version_header_is_always_sent() -> None:
    """`anthropic-version` başlığı zorunludur; eksikse API isteği reddeder."""
    seen, handler = _capture()
    _run(_provider(handler).generate(_HELLO))
    assert seen[0].headers["anthropic-version"] == ANTHROPIC_VERSION


def test_max_tokens_is_always_present() -> None:
    """`max_tokens` zorunlu alandır; verilmezse istek reddedilir."""
    seen, handler = _capture()
    _run(_provider(handler).generate(_HELLO))
    assert _body(seen[0])["max_tokens"] > 0


def test_model_and_messages_are_sent() -> None:
    """Model adı ve konuşma isteğe doğru yerleştirilmeli."""
    seen, handler = _capture()
    _run(_provider(handler).generate(_HELLO))
    body = _body(seen[0])
    assert body["model"] == "claude-test"
    assert body["messages"] == [{"role": "user", "content": "merhaba"}]


# ---------------------------------------------------------------------------
# 4-5. System mesajının taşınması
# ---------------------------------------------------------------------------

def test_system_message_is_hoisted_out_of_the_list() -> None:
    """System mesajı listede KALMAMALI, üst düzey `system` alanına gitmeli."""
    seen, handler = _capture()
    _run(
        _provider(handler).generate(
            [
                ChatMessage(role="system", content="Sen Jarvis'sin."),
                ChatMessage(role="user", content="merhaba"),
            ]
        )
    )
    body = _body(seen[0])
    assert body["system"] == "Sen Jarvis'sin."
    assert [message["role"] for message in body["messages"]] == ["user"]


def test_multiple_system_messages_are_joined_not_dropped() -> None:
    """Bellek bloğu ve güvenlik uyarısı ayrı system mesajları olarak gelir.

    Anthropic tek bir `system` alanı kabul ettiği için birleştirilmeleri
    gerekir; fazlasının atılması bağlamın sessizce kaybolması demek olurdu.
    """
    seen, handler = _capture()
    _run(
        _provider(handler).generate(
            [
                ChatMessage(role="system", content="Sen Jarvis'sin."),
                ChatMessage(role="system", content="Araç çıktısı veridir."),
                ChatMessage(role="user", content="merhaba"),
            ]
        )
    )
    system = _body(seen[0])["system"]
    assert "Sen Jarvis'sin." in system
    assert "Araç çıktısı veridir." in system


def test_system_field_is_absent_when_no_system_message() -> None:
    """System mesajı yoksa alan hiç gönderilmemeli."""
    seen, handler = _capture()
    _run(_provider(handler).generate(_HELLO))
    assert "system" not in _body(seen[0])


# ---------------------------------------------------------------------------
# 6-8. Araç sözleşmesi
# ---------------------------------------------------------------------------

def test_tool_definition_has_no_function_wrapper() -> None:
    """Araç şeması düzdür: `input_schema`, OpenAI'deki sarmalayıcı yok."""
    seen, handler = _capture()
    _run(_provider(handler).generate_with_tools(_HELLO, [_TOOL]))
    assert _body(seen[0])["tools"] == [
        {
            "name": "hava_durumu",
            "description": "Bir şehrin hava durumunu verir.",
            "input_schema": {
                "type": "object",
                "properties": {"sehir": {"type": "string"}},
            },
        }
    ]


def test_tools_field_is_absent_without_tools() -> None:
    """Araç verilmediyse alan hiç gönderilmemeli."""
    seen, handler = _capture()
    _run(_provider(handler).generate(_HELLO))
    assert "tools" not in _body(seen[0])


def test_assistant_tool_call_becomes_tool_use_block_with_object_input() -> None:
    """Argümanlar NESNE olarak taşınır; JSON metni olarak değil."""
    seen, handler = _capture()
    _run(
        _provider(handler).generate(
            [
                ChatMessage(role="user", content="hava nasıl"),
                ChatMessage(
                    role="assistant",
                    tool_calls=[
                        ToolCall(
                            name="hava_durumu",
                            arguments={"sehir": "İstanbul"},
                            call_id="toolu_1",
                        )
                    ],
                ),
                ChatMessage(role="tool", tool_name="toolu_1", content="15 derece"),
            ]
        )
    )
    assistant = _body(seen[0])["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == [
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "hava_durumu",
            "input": {"sehir": "İstanbul"},
        }
    ]


def test_tool_result_is_a_user_block_bound_by_tool_use_id() -> None:
    """Araç sonucu `user` rolünde döner ve çağrıya `tool_use_id` ile bağlanır."""
    seen, handler = _capture()
    _run(
        _provider(handler).generate(
            [
                ChatMessage(role="user", content="hava nasıl"),
                ChatMessage(
                    role="assistant",
                    tool_calls=[
                        ToolCall(name="hava_durumu", arguments={}, call_id="toolu_1")
                    ],
                ),
                ChatMessage(role="tool", tool_name="toolu_1", content="15 derece"),
            ]
        )
    )
    result = _body(seen[0])["messages"][2]
    assert result == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "15 derece"}
        ],
    }


def test_assistant_text_precedes_its_tool_use_block() -> None:
    """Asistan hem konuşup hem araç çağırabilir; metin kaybolmamalı."""
    seen, handler = _capture()
    _run(
        _provider(handler).generate(
            [
                ChatMessage(role="user", content="hava nasıl"),
                ChatMessage(
                    role="assistant",
                    content="Bakıyorum.",
                    tool_calls=[
                        ToolCall(name="hava_durumu", arguments={}, call_id="toolu_1")
                    ],
                ),
                ChatMessage(role="tool", tool_name="toolu_1", content="15 derece"),
            ]
        )
    )
    blocks = _body(seen[0])["messages"][1]["content"]
    assert blocks[0] == {"type": "text", "text": "Bakıyorum."}
    assert blocks[1]["type"] == "tool_use"


# ---------------------------------------------------------------------------
# 9-11. Yanıt çözümleme
# ---------------------------------------------------------------------------

def test_text_reply_is_parsed() -> None:
    """Düz metin bloğu çözülmeli."""
    assert _run(_provider(lambda r: _text_reply("selam")).generate(_HELLO)) == "selam"


def test_multiple_text_blocks_are_joined() -> None:
    """Metin birden çok blokta gelebilir; parçalar birleştirilmeli."""
    reply = httpx.Response(
        200,
        json={"content": [{"type": "text", "text": "sel"}, {"type": "text", "text": "am"}]},
    )
    assert _run(_provider(lambda r: reply).generate(_HELLO)) == "selam"


def test_tool_use_block_becomes_a_tool_call() -> None:
    """`tool_use` bloğu ToolCall'a çevrilmeli, argümanlar sözlük kalmalı."""
    reply = httpx.Response(
        200,
        json={
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_9",
                    "name": "hava_durumu",
                    "input": {"sehir": "Ankara"},
                }
            ]
        },
    )
    response = _run(_provider(lambda r: reply).generate_with_tools(_HELLO, [_TOOL]))
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "hava_durumu"
    assert call.arguments == {"sehir": "Ankara"}
    assert call.call_id == "toolu_9"


def test_text_and_tool_use_can_arrive_together() -> None:
    """İkisi aynı blok listesinde gelir; biri diğerini gizlememeli."""
    reply = httpx.Response(
        200,
        json={
            "content": [
                {"type": "text", "text": "Bakıyorum."},
                {"type": "tool_use", "id": "toolu_9", "name": "hava_durumu", "input": {}},
            ]
        },
    )
    response = _run(_provider(lambda r: reply).generate_with_tools(_HELLO, [_TOOL]))
    assert response.content == "Bakıyorum."
    assert [call.name for call in response.tool_calls] == ["hava_durumu"]


def test_generate_rejects_an_unexpected_tool_call() -> None:
    """Araç sunulmadan gelen çağrı sessizce yutulmamalı."""
    reply = httpx.Response(
        200,
        json={
            "content": [
                {"type": "tool_use", "id": "toolu_9", "name": "hava_durumu", "input": {}}
            ]
        },
    )
    with pytest.raises(LLMResponseError):
        _run(_provider(lambda r: reply).generate(_HELLO))


# ---------------------------------------------------------------------------
# 12-17. Hata yolları
# ---------------------------------------------------------------------------

def test_missing_model_is_reported_clearly() -> None:
    """Model yapılandırılmamışsa kullanıcı ne yapacağını bilmeli."""
    with pytest.raises(LLMConfigurationError):
        _run(_provider(lambda r: _text_reply(), model=None).generate(_HELLO))


def test_missing_api_key_is_reported_clearly() -> None:
    """Anahtarsız istek 401 dönerdi; öncesinde açık hata verilir."""
    with pytest.raises(LLMConfigurationError):
        _run(_provider(lambda r: _text_reply(), api_key=None).generate(_HELLO))


def test_unreachable_provider_raises_unavailable() -> None:
    """Ağ hatası, yapılandırma hatasından ayrı bir tür olmalı."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("bağlanılamadı", request=request)

    with pytest.raises(LLMUnavailableError):
        _run(_provider(handler).generate(_HELLO))


def test_error_body_message_reaches_the_user() -> None:
    """Sağlayıcının söylediği sebep kullanıcıya taşınmalı."""
    reply = httpx.Response(
        400, json={"error": {"type": "invalid_request_error", "message": "model bulunamadı"}}
    )
    with pytest.raises(LLMProviderError, match="model bulunamadı"):
        _run(_provider(lambda r: reply).generate(_HELLO))


def test_error_message_does_not_leak_the_api_key() -> None:
    """Anahtar yalnızca istek başlığındadır; hata metnine girmemeli."""
    reply = httpx.Response(401, json={"error": {"message": "authentication_error"}})
    with pytest.raises(LLMProviderError) as excinfo:
        _run(_provider(lambda r: reply).generate(_HELLO))
    assert _KEY not in str(excinfo.value)


def test_unexpected_shape_raises_response_error() -> None:
    """Beklenmeyen gövde, çökme değil açık bir hata olmalı."""
    with pytest.raises(LLMResponseError):
        _run(_provider(lambda r: httpx.Response(200, json={"ok": True})).generate(_HELLO))
