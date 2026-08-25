"""LLM sağlayıcılarından bağımsız chat ve tool-calling modelleri."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

MessageRole = Literal["system", "user", "assistant", "tool"]


class ToolDefinition(BaseModel):
    """Bir sağlayıcıya sunulabilecek araç sözleşmesi."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    """LLM'in talep ettiği bir kayıtlı araç çağrısı."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = Field(default=None, max_length=128)


class LLMResponse(BaseModel):
    """Bir LLM turunun text cevabını ve isteğe bağlı araç çağrılarını taşır."""

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_content_or_tool_call(self) -> "LLMResponse":
        if not self.content.strip() and not self.tool_calls:
            raise ValueError("LLM response must include content or at least one tool call")
        return self


class ChatMessage(BaseModel):
    """Bir LLM konuşma mesajı."""

    role: MessageRole
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_name: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_message_shape(self) -> "ChatMessage":
        if self.role == "assistant" and self.tool_calls:
            return self
        if self.role == "tool" and self.tool_name and self.content.strip():
            return self
        if self.role != "tool" and self.content.strip():
            return self
        raise ValueError("chat message is missing required content or tool metadata")
