"""LLM sağlayıcı adaptörleri."""

from app.adapters.llm.base import LLMProvider
from app.adapters.llm.ollama import OllamaProvider

__all__ = ["LLMProvider", "OllamaProvider"]
