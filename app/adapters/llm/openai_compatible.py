"""OpenAI sohbet sözleşmesini konuşan her sağlayıcı için tek adaptör.

Bu sözleşme fiilen bir standart hâline geldi: Gemini, Groq, OpenRouter,
LM Studio ve daha pek çok servis aynı `/chat/completions` biçimini kabul
ediyor. Her biri için ayrı bir adaptör yazmak yerine tek bir sınıf yeterli;
değişen tek şey temel adres, model adı ve anahtar.

Ollama'dan iki önemli farkı vardır ve ikisi de sessiz hataya açıktır:

- Araç çağrılarının argümanları **JSON metni** olarak gelir, nesne olarak
  değil. Ayrıştırılmadan kullanılırsa araç şeması boş bir sözlük görür.
- Araç sonucu mesajları, hangi çağrıya ait olduklarını `tool_call_id` ile
  bildirmek zorundadır. Bu bağ kurulmazsa sağlayıcı isteği reddeder.

API anahtarı yalnızca `Authorization` başlığında taşınır; hata mesajlarına
ve loglara hiçbir şekilde girmez.
"""

from collections.abc import Sequence
import json
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


class OpenAICompatibleProvider:
    """OpenAI `/chat/completions` sözleşmesini kullanan sağlayıcı istemcisi."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str | None,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """
        Args:
            base_url: Sözleşmenin köküne kadar olan adres, ör.
                `https://generativelanguage.googleapis.com/v1beta/openai`.
            model: Kullanılacak model adı.
            api_key: Bearer olarak gönderilecek anahtar. Yerel sunucularda
                (LM Studio gibi) gerekmeyebilir.
            timeout_seconds: Tek bir isteğin üst süresi.
            transport: Testlerin ağa çıkmadan gerçek serileştirmeyi
                sınayabilmesi için taşıma katmanı. Üretimde verilmez.
        """
        self._base_url = base_url.rstrip("/")
        self._model = model.strip() if model else None
        self._api_key = api_key.strip() if api_key else None
        self._timeout_seconds = timeout_seconds

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
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
        """OpenAI sohbet sözleşmesiyle bir tur üretir."""

        if not self._model:
            raise LLMConfigurationError(
                "Model adı yapılandırılmamış. Yönetim panelinden bir model seçin."
            )

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [self._serialize_message(message) for message in messages],
            "stream": False,
        }
        if tools:
            payload["tools"] = [self._serialize_tool(tool) for tool in tools]

        endpoint = f"{self._base_url}/chat/completions"

        try:
            response = await self._client.post(endpoint, json=payload)
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
        if message.role == "tool":
            # Araç sonucu, ait olduğu çağrıya bağlanmak zorundadır.
            return {
                "role": "tool",
                "tool_call_id": message.tool_name or "",
                "content": message.content,
            }

        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.call_id or call.name,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        # Argümanlar bu sözleşmede METİN olarak taşınır.
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        return payload

    # ── yanıt çözümleme ──────────────────────────────────────

    def _parse_response(self, response: httpx.Response) -> LLMResponse:
        try:
            data: dict[str, Any] = response.json()
            choices = data["choices"]
            if not isinstance(choices, list) or not choices:
                raise TypeError("choices must be a non-empty list")
            message = choices[0]["message"]
            if not isinstance(message, dict):
                raise TypeError("message must be an object")

            content = message.get("content") or ""
            if not isinstance(content, str):
                raise TypeError("message content must be a string")

            tool_calls = self._parse_tool_calls(message.get("tool_calls"))
            return LLMResponse(content=content, tool_calls=tool_calls)
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMResponseError(
                "Sağlayıcı beklenen sohbet yanıt biçimini döndürmedi."
            ) from exc

    @staticmethod
    def _parse_tool_calls(raw_calls: Any) -> list[ToolCall]:
        """Araç çağrılarını çözer; argüman metnini sözlüğe çevirir."""

        if raw_calls is None:
            return []
        if not isinstance(raw_calls, list):
            raise TypeError("tool_calls must be a list")

        parsed: list[ToolCall] = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                raise TypeError("tool call must be an object")
            function = raw_call.get("function")
            if not isinstance(function, dict):
                raise TypeError("tool call must carry a function object")

            name = function.get("name")
            if not isinstance(name, str):
                raise TypeError("tool call name must be a string")

            arguments = OpenAICompatibleProvider._parse_arguments(function.get("arguments"))
            parsed.append(
                ToolCall(
                    name=name,
                    arguments=arguments,
                    call_id=str(raw_call.get("id") or uuid4().hex),
                )
            )
        return parsed

    @staticmethod
    def _parse_arguments(raw: Any) -> dict[str, Any]:
        """Argümanları sözlüğe çevirir.

        Sözleşme bunları JSON metni olarak taşır, ama bazı sağlayıcılar
        doğrudan nesne döndürüyor. İkisi de kabul edilir; ayrıştırılamayan
        bir metin sessizce boş sözlüğe düşürülmez, hata olarak bildirilir —
        yoksa araç, argümanları hiç verilmemiş gibi çalışırdı.
        """
        if raw is None or raw == "":
            return {}
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            raise TypeError("tool call arguments must be a string or object")

        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise TypeError("tool call arguments must decode to an object")
        return parsed

    def _error_message(self, response: httpx.Response) -> str:
        """Hata gövdesinden okunabilir bir mesaj çıkarır.

        Gövde JSON olmayabilir; olsa bile anahtar taşımaz, çünkü anahtar
        yalnızca istek başlığında gider.
        """
        try:
            body = response.json()
            detail = body.get("error")
            if isinstance(detail, dict):
                message = detail.get("message")
                if isinstance(message, str):
                    return f"Sağlayıcı hatası ({response.status_code}): {message}"
            if isinstance(detail, str):
                return f"Sağlayıcı hatası ({response.status_code}): {detail}"
        except (ValueError, AttributeError):
            pass
        return f"Sağlayıcı {response.status_code} döndürdü."
