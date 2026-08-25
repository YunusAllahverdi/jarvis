"""Ollama `/api/chat` API adaptörü."""

from collections.abc import Sequence
from typing import Any

import httpx

from app.adapters.llm.base import (
    LLMConfigurationError,
    LLMProviderError,
    LLMResponseError,
    LLMUnavailableError,
)
from app.core.chat import ChatMessage


class OllamaProvider:
    """Yerel Ollama HTTP API'si için asenkron LLM sağlayıcısı."""

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

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        """Ollama'ya non-streaming chat isteği gönderir."""

        if not self._model:
            raise LLMConfigurationError(
                "Ollama modeli yapılandırılmamış. JARVIS_OLLAMA_MODEL değerini ayarlayın."
            )

        payload = {
            "model": self._model,
            "messages": [message.model_dump() for message in messages],
            "stream": False,
        }
        endpoint = f"{self._base_url}/api/chat"

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(endpoint, json=payload)
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
            content = response_data["message"]["content"]
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMResponseError("Ollama beklenen chat yanıt biçimini döndürmedi.") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("Ollama boş bir chat yanıtı döndürdü.")

        return content.strip()

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        """Ollama hata gövdesinden güvenli ve anlaşılır bir mesaj çıkarır."""

        try:
            details = response.json().get("error")
        except (ValueError, AttributeError):
            details = None

        suffix = f": {details}" if isinstance(details, str) and details else ""
        return f"Ollama HTTP {response.status_code} hatası döndürdü{suffix}"
