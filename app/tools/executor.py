"""Registry tabanlı permission, input validation ve tool çalıştırma katmanı."""

import json
import logging
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field

from app.core.chat import ChatMessage, ToolCall
from app.tools.base import PermissionLevel, ToolExecutionError, ToolInputValidationError
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolExecutionResult(BaseModel):
    """Bir tool call'un LLM'e geri verilebilecek kontrollü sonucu."""

    tool_name: str
    success: bool
    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    def as_chat_message(self) -> ChatMessage:
        """Ollama ve diğer provider'ların anlayabileceği tool-result mesajını üretir."""

        payload: dict[str, Any] = {"ok": self.success}
        if self.success:
            payload["result"] = self.data
        else:
            payload["error"] = {"code": self.error_code, "message": self.error_message}
        return ChatMessage(
            role="tool",
            tool_name=self.tool_name,
            content=json.dumps(payload, ensure_ascii=False, default=str),
        )


class ToolExecutor:
    """Bir tool call'u sadece registry, input şeması ve izin kontrolünden sonra çalıştırır."""

    def __init__(
        self,
        registry: ToolRegistry,
        allowed_permissions: Iterable[PermissionLevel],
    ) -> None:
        self._registry = registry
        self._allowed_permissions = frozenset(allowed_permissions)

    async def execute(self, call: ToolCall) -> ToolExecutionResult:
        """Tool call'u güvenli biçimde çalıştırır veya LLM'e hata sonucu döndürür."""

        tool = self._registry.get(call.name)
        if tool is None:
            return ToolExecutionResult(
                tool_name=call.name,
                success=False,
                error_code="unknown_tool",
                error_message="İstenen tool kayıtlı değil.",
            )

        if tool.permission not in self._allowed_permissions:
            return ToolExecutionResult(
                tool_name=call.name,
                success=False,
                error_code="permission_denied",
                error_message=f"{tool.permission} izni bu oturumda etkin değil.",
            )

        try:
            tool_input = tool.validate_input(call.arguments)
        except ToolInputValidationError:
            return ToolExecutionResult(
                tool_name=call.name,
                success=False,
                error_code="invalid_arguments",
                error_message="Tool argument'leri şemaya uymuyor.",
            )

        try:
            data = await tool.execute(tool_input)
        except ToolExecutionError as exc:
            return ToolExecutionResult(
                tool_name=call.name,
                success=False,
                error_code="tool_execution_failed",
                error_message=str(exc),
            )
        except Exception:
            logger.exception("tool_execution_unexpected_error", extra={"tool_name": tool.name})
            return ToolExecutionResult(
                tool_name=call.name,
                success=False,
                error_code="tool_execution_failed",
                error_message="Tool çalıştırılırken beklenmeyen bir hata oluştu.",
            )

        return ToolExecutionResult(tool_name=call.name, success=True, data=data)
