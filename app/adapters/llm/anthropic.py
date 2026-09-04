"""Anthropic Messages API adaptörü (Claude Haiku, Sonnet, Opus vb.).

Anthropic kendi `/v1/messages` sözleşmesini kullanır — OpenAI sözleşmesinden
birkaç kritik noktada ayrılır:

1. **Mesaj biçimi:** `system` mesajı ayrı bir `system` parametresidir, mesaj
   listesinde yer almaz. Tool sonuçları `role: "user"` içinde
   `content: [{type: "tool_result", ...}]` bloğu olarak gönderilir.

2. **Tool tanımı:** `tools` dizisindeki her giriş `input_schema` alanı
   taşır; `parameters` değil. Tip şema yapısı aynıdır.

3. **Tool çağrısı:** Yanıt `content` dizisinde `type: "tool_use"` blokları
   döndürülür; argümanlar doğrudan nesne (dict) olarak gelir, JSON string
   olarak değil.

4. **Durdurma nedeni:** `stop_reason: "tool_use"` hem içerik hem tool içeren
   yanıtları kapsar. `stop_reason: "end_turn"` saf metin yanıtıdır.

5. **API anahtarı:** `x-api-key` başlığı (küçük harf); `Authorization: Bearer`
   değil.

6. **Zorunlu sürüm başlığı:** `anthropic-version: 2023-06-01` her istekte
   bulunmak zorundadır; yoksa 400 döner.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.adapters.llm.base import (
    LLMConfigurationError,
    LLMProviderError,
    LLMResponseError,
    LLMUnavailableError,
)
from app.core.chat import ChatMessage, LLMResponse, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT_SECONDS = 60.0


class AnthropicProvider:
    """Anthropic Messages API için asenkron LLM sağlayıcısı.

    httpx.AsyncClient uygulama ömrü boyunca yeniden kullanılır.
    Kapatmak için aclose() çağırın (FastAPI lifespan içinde yapılır).
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        """
        Args:
            api_key: Anthropic API anahtarı. x-api-key başlığında taşınır;
                loglara ve hata mesajlarına asla girmez.
            model: Kullanılacak model adı (ör. "claude-haiku-4-5",
                "claude-sonnet-4-5", "claude-opus-4").
            timeout_seconds: Tek bir isteğin üst süresi.
            max_tokens: Üretilecek en fazla token sayısı. Anthropic bu
                parametreyi zorunlu tutar; verilmezse 400 döner.
        """
        self._model = model.strip() if model else None
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if api_key and api_key.strip():
            headers["x-api-key"] = api_key.strip()

        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers=headers,
        )

    async def aclose(self) -> None:
        """HTTP client'ı düzgün biçimde kapatır."""
        await self._client.aclose()

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        """Tool tanımı olmadan tek bir asistan metni üretir."""
        response = await self.generate_with_tools(messages, tools=())
        if response.tool_calls:
            raise LLMResponseError("Claude beklenmeyen bir tool call döndürdü.")
        return response.content.strip()

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        """Anthropic Messages API ile bir tur üretir."""
        if not self._model:
            raise LLMConfigurationError(
                "Claude modeli yapılandırılmamış. Yönetim panelinden bir model seçin."
            )

        system_text, user_messages = self._split_system(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [self._serialize_message(m) for m in user_messages],
        }
        if system_text:
            payload["system"] = system_text
        if tools:
            payload["tools"] = [self._serialize_tool(t) for t in tools]

        try:
            response = await self._client.post(ANTHROPIC_API_URL, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(
                f"Anthropic isteği {self._timeout_seconds:g} saniye içinde "
                "zaman aşımına uğradı."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError(
                "Anthropic API'sine bağlanılamadı. "
                "İnternet bağlantısını ve API adresini kontrol edin."
            ) from exc

        if response.is_error:
            raise LLMProviderError(self._error_message(response))

        return self._parse_response(response)

    # ── istek biçimlendirme ──────────────────────────────────────────────

    @staticmethod
    def _split_system(
        messages: Sequence[ChatMessage],
    ) -> tuple[str, list[ChatMessage]]:
        """System mesajını listeden ayırır.

        Anthropic system mesajını ayrı bir üst düzey parametre olarak
        ister; mesaj listesinde bulunmamalıdır. Birden fazla system mesajı
        varsa metinleri birleştirilir.
        """
        system_parts: list[str] = []
        other: list[ChatMessage] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                other.append(m)
        return "\n\n".join(system_parts), other

    @staticmethod
    def _serialize_tool(tool: ToolDefinition) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            # Anthropic "input_schema" kullanır, OpenAI "parameters" kullanır.
            "input_schema": tool.input_schema,
        }

    @staticmethod
    def _serialize_message(message: ChatMessage) -> dict[str, Any]:
        """ChatMessage'ı Anthropic mesaj biçimine çevirir.

        Tool sonucu mesajları özel bir biçim gerektirir: `role: "user"` içinde
        `content: [{type: "tool_result", tool_use_id: ..., content: ...}]`.
        Bu Anthropic'in OpenAI sözleşmesinden en çok ayrıldığı noktadır.
        """
        if message.role == "tool":
            # Tool sonucu: user rolünde, tool_result bloğu olarak.
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_name or "",
                        "content": message.content,
                    }
                ],
            }

        if message.role == "assistant" and message.tool_calls:
            # Araç çağrısı içeren asistan mesajı: text + tool_use blokları.
            content: list[dict[str, Any]] = []
            if message.content.strip():
                content.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                content.append(
                    {
                        "type": "tool_use",
                        "id": call.call_id or call.name,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            return {"role": "assistant", "content": content}

        return {"role": message.role, "content": message.content}

    # ── yanıt çözümleme ──────────────────────────────────────────────────

    def _parse_response(self, response: httpx.Response) -> LLMResponse:
        try:
            data: dict[str, Any] = response.json()
            content_blocks = data.get("content", [])
            if not isinstance(content_blocks, list):
                raise TypeError("content must be a list")

            text_parts: list[str] = []
            tool_calls: list[ToolCall] = []

            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")

                if block_type == "text":
                    text = block.get("text", "")
                    if isinstance(text, str) and text.strip():
                        text_parts.append(text)

                elif block_type == "tool_use":
                    name = block.get("name")
                    if not isinstance(name, str):
                        raise TypeError("tool_use block must have a string name")
                    # Anthropic argümanları doğrudan dict olarak döndürür.
                    arguments = block.get("input", {})
                    if not isinstance(arguments, dict):
                        raise TypeError("tool_use input must be an object")
                    tool_calls.append(
                        ToolCall(
                            name=name,
                            arguments=arguments,
                            call_id=block.get("id") or name,
                        )
                    )

            content_text = "\n".join(text_parts)
            return LLMResponse(content=content_text, tool_calls=tool_calls)

        except (KeyError, TypeError, ValueError) as exc:
            raise LLMResponseError(
                "Anthropic beklenen mesaj yanıt biçimini döndürmedi."
            ) from exc

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        """Anthropic hata gövdesinden güvenli ve anlaşılır bir mesaj çıkarır.

        API anahtarı hata mesajlarına asla girmez.
        """
        try:
            body = response.json()
            error = body.get("error", {})
            message = error.get("message") if isinstance(error, dict) else None
        except (ValueError, AttributeError):
            message = None

        suffix = f": {message}" if isinstance(message, str) and message else ""

        # 401 özellikle raporlanır: kullanıcının ilk düşüneceği şey
        # anahtarın yanlış olduğudur — bunu açıkça söylemek bir istekten
        # vazgeçip anahtarı kontrol etmesini sağlar.
        if response.status_code == 401:
            return (
                "Anthropic API anahtarı geçersiz veya eksik. "
                "Yönetim panelinden anahtarı kontrol edin."
            )
        if response.status_code == 429:
            return "Anthropic rate limit aşıldı. Kısa bir süre bekleyip tekrar deneyin."

        return f"Anthropic HTTP {response.status_code} hatası döndürdü{suffix}"
