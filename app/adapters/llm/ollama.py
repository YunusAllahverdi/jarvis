"""Ollama `/api/chat` API adaptörü."""

from collections.abc import Sequence
import json
from typing import Any

import httpx

from app.adapters.llm.base import (
    LLMConfigurationError,
    LLMProviderError,
    LLMResponseError,
    LLMUnavailableError,
)
from app.core.chat import ChatMessage, LLMResponse, ToolCall, ToolDefinition


class OllamaProvider:
    """Yerel Ollama HTTP API'si için asenkron LLM sağlayıcısı.

    httpx.AsyncClient uygulama ömrü boyunca yeniden kullanılır.
    Kapatmak için aclose() çağırın (FastAPI lifespan içinde yapılır).
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str | None,
        timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model.strip() if model else None
        self._timeout_seconds = timeout_seconds
        self._client = httpx.AsyncClient(timeout=self._timeout_seconds)

    async def aclose(self) -> None:
        """HTTP client'ı düzgün biçimde kapatır.

        Uygulama kapatılırken FastAPI lifespan içinden çağrılmalıdır.
        """
        await self._client.aclose()

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        """Tool tanımı olmadan tek bir asistan metni üretir."""

        response = await self.generate_with_tools(messages, tools=())
        if response.tool_calls:
            raise LLMResponseError("Ollama beklenmeyen bir tool call döndürdü.")
        return response.content.strip()

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        """Ollama'nın native `/api/chat` tool-calling sözleşmesini kullanır."""

        if not self._model:
            raise LLMConfigurationError(
                "Ollama modeli yapılandırılmamış. JARVIS_OLLAMA_MODEL değerini ayarlayın."
            )

        payload = {
            "model": self._model,
            "messages": [self._serialize_message(message) for message in messages],
            "stream": False,
        }
        if tools:
            payload["tools"] = [self._serialize_tool(tool) for tool in tools]
        endpoint = f"{self._base_url}/api/chat"

        try:
            response = await self._client.post(endpoint, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(
                f"Ollama isteği {self._timeout_seconds:g} saniye içinde zaman aşımına uğradı."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError(
                f"Ollama bağlantısı kurulamadı ({self._base_url}). "
                "Ollama'nın çalıştığını ve base URL ayarını kontrol edin."
            ) from exc

        if response.is_error:
            raise LLMProviderError(self._error_message(response))

        try:
            response_data: dict[str, Any] = response.json()
            message = response_data["message"]
            if not isinstance(message, dict):
                raise TypeError("message must be an object")
            content = message.get("content", "")
            if content is None:
                content = ""
            if not isinstance(content, str):
                raise TypeError("message content must be a string")
            tool_calls = self._parse_tool_calls(message.get("tool_calls", []))
            return LLMResponse(content=content, tool_calls=tool_calls)
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMResponseError("Ollama beklenen chat yanıt biçimini döndürmedi.") from exc

    @staticmethod
    def _serialize_tool(tool: ToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    @staticmethod
    def _serialize_message(message: ChatMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in message.tool_calls
            ]
        if message.tool_name:
            payload["tool_name"] = message.tool_name
        return payload

    @staticmethod
    def _parse_tool_calls(raw_calls: Any) -> list[ToolCall]:
        if raw_calls is None:
            return []
        if not isinstance(raw_calls, list):
            raise TypeError("tool_calls must be a list")

        parsed_calls: list[ToolCall] = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                raise TypeError("tool call must be an object")
            function = raw_call.get("function")
            if not isinstance(function, dict):
                raise TypeError("tool call function must be an object")
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise TypeError("tool call arguments must be an object")
            parsed_calls.append(
                ToolCall(
                    name=function["name"],
                    arguments=arguments,
                    call_id=raw_call.get("id"),
                )
            )
        return parsed_calls

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        """Ollama hata gövdesinden güvenli ve anlaşılır bir mesaj çıkarır."""

        try:
            details = response.json().get("error")
        except (ValueError, AttributeError):
            details = None

        suffix = f": {details}" if isinstance(details, str) and details else ""
        return f"Ollama HTTP {response.status_code} hatası döndürdü{suffix}"
