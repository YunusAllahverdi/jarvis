"""Anthropic Messages API adaptörü.

Ayrı bir adaptör GEREKTİ çünkü Anthropic OpenAI sözleşmesini konuşmaz ve
`OpenAICompatibleProvider` ile kullanılamaz. Farklar sessiz hataya açık
olduğu için tek tek yazılıyor:

- Uç nokta `/v1/messages`, `/chat/completions` değil.
- Anahtar `Authorization: Bearer` yerine `x-api-key` başlığında gider ve
  ayrıca `anthropic-version` başlığı ZORUNLUDUR.
- **System mesajı listede taşınmaz**, üst düzey `system` alanına konur.
  Listede bırakılırsa API isteği reddeder.
- `max_tokens` ZORUNLUDUR; verilmezse istek reddedilir.
- Araç şeması `{"name", "description", "input_schema"}` biçimindedir —
  OpenAI'deki `{"type": "function", "function": {...}}` sarmalayıcısı yoktur.
- Araç argümanları NESNE olarak gelir (`input`), JSON metni olarak değil.
- Araç sonucu, `user` rolünde bir `tool_result` bloğu olarak geri gönderilir
  ve `tool_use_id` ile çağrıya bağlanır.
- Yanıt içeriği bir BLOK LİSTESİDİR: metin ve araç çağrıları aynı listede
  `type` alanıyla ayrılır.

API anahtarı yalnızca istek başlığında taşınır; loglara ve hata mesajlarına
hiçbir şekilde girmez.
"""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import httpx

from app.adapters.llm.base import (
    LLMConfigurationError,
    LLMProviderError,
    LLMResponseError,
    LLMUnavailableError,
)
from app.core.chat import ChatMessage, LLMResponse, ToolCall, ToolDefinition

DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"

DEFAULT_MAX_TOKENS = 4096
"""Zorunlu `max_tokens` için varsayılan.

Anthropic bu alanı isteğe bağlı bırakmaz. Sabit bir değer seçmek, her
çağrıda kullanıcıdan istemekten iyidir; sınır cevabı kesecek kadar
küçük olmamalı, bu yüzden cömert tutuldu.
"""


class AnthropicProvider:
    """Anthropic Messages API istemcisi."""

    def __init__(
        self,
        *,
        model: str | None,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """
        Args:
            model: Model adı, ör. `claude-haiku-4-5`.
            api_key: `x-api-key` başlığında gönderilecek anahtar.
            base_url: API kökü.
            timeout_seconds: Tek bir isteğin üst süresi.
            max_tokens: Cevabın üst sınırı (Anthropic'te zorunlu alan).
            transport: Testlerin ağa çıkmadan gerçek serileştirmeyi
                sınayabilmesi için taşıma katmanı. Üretimde verilmez.
        """
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._model = model.strip() if model else None
        self._api_key = api_key.strip() if api_key else None
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds, headers=headers, transport=transport
        )

    async def aclose(self) -> None:
        """HTTP client'ı düzgün biçimde kapatır."""
        await self._client.aclose()

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        """Tool tanımı olmadan tek bir asistan metni üretir."""
        response = await self.generate_with_tools(messages, tools=())
        if response.tool_calls:
            raise LLMResponseError("Sağlayıcı beklenmeyen bir tool call döndürdü.")
        return response.content.strip()

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        """Anthropic Messages sözleşmesiyle bir tur üretir."""
        if not self._model:
            raise LLMConfigurationError(
                "Model adı yapılandırılmamış. Yönetim panelinden bir model seçin."
            )
        if not self._api_key:
            raise LLMConfigurationError(
                "Anthropic anahtarı yapılandırılmamış. Yönetim panelinden girin."
            )

        system_text, conversation = self._split_system(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": conversation,
        }
        # System, mesaj listesinde DEĞİL üst düzeyde taşınır.
        if system_text:
            payload["system"] = system_text
        if tools:
            payload["tools"] = [self._serialize_tool(tool) for tool in tools]

        try:
            response = await self._client.post(f"{self._base_url}/v1/messages", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(
                f"Sağlayıcı isteği {self._timeout_seconds:g} saniye içinde zaman aşımına uğradı."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError(
                f"Sağlayıcıya bağlanılamadı ({self._base_url}). Adres ayarını kontrol edin."
            ) from exc

        if response.is_error:
            raise LLMProviderError(self._error_message(response))

        return self._parse_response(response)

    # ── istek biçimlendirme ──────────────────────────────────

    @staticmethod
    def _split_system(
        messages: Sequence[ChatMessage],
    ) -> tuple[str, list[dict[str, Any]]]:
        """System mesajlarını ayırır ve kalanları Anthropic biçimine çevirir.

        Birden fazla system mesajı olabilir (prompt + bellek bloğu + araç
        uyarısı); Anthropic tek bir `system` alanı kabul ettiği için hepsi
        sırayla birleştirilir. Atılmaları, bellek bağlamının ve güvenlik
        uyarısının sessizce kaybolması demek olurdu.
        """
        system_parts: list[str] = []
        conversation: list[dict[str, Any]] = []

        for message in messages:
            if message.role == "system":
                if message.content.strip():
                    system_parts.append(message.content)
                continue

            if message.role == "tool":
                # Araç sonucu `user` rolünde bir blok olarak döner ve
                # `tool_use_id` ile ait olduğu çağrıya bağlanır.
                conversation.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_name or "",
                                "content": message.content,
                            }
                        ],
                    }
                )
                continue

            if message.role == "assistant" and message.tool_calls:
                blocks: list[dict[str, Any]] = []
                if message.content.strip():
                    blocks.append({"type": "text", "text": message.content})
                blocks.extend(
                    {
                        "type": "tool_use",
                        "id": call.call_id or call.name,
                        "name": call.name,
                        # Argümanlar NESNE olarak taşınır, metin değil.
                        "input": dict(call.arguments),
                    }
                    for call in message.tool_calls
                )
                conversation.append({"role": "assistant", "content": blocks})
                continue

            conversation.append({"role": message.role, "content": message.content})

        return "\n\n".join(system_parts), conversation

    @staticmethod
    def _serialize_tool(tool: ToolDefinition) -> dict[str, Any]:
        """Araç şemasını Anthropic biçimine çevirir (sarmalayıcı yoktur)."""
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }

    # ── yanıt çözümleme ──────────────────────────────────────

    def _parse_response(self, response: httpx.Response) -> LLMResponse:
        """Blok listesini metin ve araç çağrılarına ayırır."""
        try:
            data: dict[str, Any] = response.json()
            blocks = data["content"]
            if not isinstance(blocks, list):
                raise TypeError("content must be a list")

            text_parts: list[str] = []
            tool_calls: list[ToolCall] = []

            for block in blocks:
                if not isinstance(block, dict):
                    raise TypeError("content block must be an object")
                block_type = block.get("type")

                if block_type == "text":
                    text = block.get("text")
                    if not isinstance(text, str):
                        raise TypeError("text block must carry a string")
                    text_parts.append(text)

                elif block_type == "tool_use":
                    name = block.get("name")
                    if not isinstance(name, str):
                        raise TypeError("tool_use block must carry a name")
                    arguments = block.get("input")
                    if arguments is None:
                        arguments = {}
                    if not isinstance(arguments, dict):
                        raise TypeError("tool_use input must be an object")
                    tool_calls.append(
                        ToolCall(
                            name=name,
                            arguments=arguments,
                            call_id=str(block.get("id") or uuid4().hex),
                        )
                    )

            return LLMResponse(content="".join(text_parts), tool_calls=tool_calls)
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMResponseError(
                "Sağlayıcı beklenen mesaj yanıt biçimini döndürmedi."
            ) from exc

    def _error_message(self, response: httpx.Response) -> str:
        """Hata gövdesinden okunabilir bir mesaj çıkarır.

        Gövde anahtar taşımaz; anahtar yalnızca istek başlığında gider.
        """
        try:
            body = response.json()
            detail = body.get("error")
            if isinstance(detail, dict):
                message = detail.get("message")
                if isinstance(message, str):
                    return f"Sağlayıcı hatası ({response.status_code}): {message}"
        except (ValueError, AttributeError):
            pass
        return f"Sağlayıcı {response.status_code} döndürdü."
