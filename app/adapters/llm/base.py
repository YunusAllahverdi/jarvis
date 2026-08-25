"""LLM sağlayıcıları arasındaki kararlı uygulama sınırı."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.core.chat import ChatMessage, LLMResponse, ToolDefinition


class LLMProviderError(RuntimeError):
    """Bir sağlayıcıdan yanıt alınamadığında oluşan temel hata."""


class LLMUnavailableError(LLMProviderError):
    """Sağlayıcıya ağ üzerinden ulaşılamadığını belirtir."""


class LLMConfigurationError(LLMProviderError):
    """Sağlayıcının çalışması için zorunlu bir ayarın eksik olduğunu belirtir."""


class LLMResponseError(LLMProviderError):
    """Sağlayıcının geçersiz veya kullanılamaz bir yanıt ürettiğini belirtir."""


@runtime_checkable
class LLMProvider(Protocol):
    """Metin üretimi ve tool-calling sağlayıcıları için küçük arayüz."""

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        """Verilen konuşma mesajları için tek bir asistan cevabı üretir."""

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        """Tool tanımlarıyla birlikte bir LLM turu üretir."""
