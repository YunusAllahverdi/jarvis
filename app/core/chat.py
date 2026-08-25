"""Text conversation için sağlayıcıdan bağımsız ortak modeller."""

from typing import Literal

from pydantic import BaseModel, Field

MessageRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """Bir LLM konuşma mesajı."""

    role: MessageRole
    content: str = Field(min_length=1)
