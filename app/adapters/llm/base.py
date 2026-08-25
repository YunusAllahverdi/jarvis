"""LLM sağlayıcıları arasındaki kararlı uygulama sınırı."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.core.chat import ChatMessage


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
    """Her metin LLM sağlayıcısının uygulaması gereken küçük arayüz."""

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        """Verilen konuşma mesajları için tek bir asistan cevabı üretir."""
