"""Registry tabanlı permission, input validation ve tool çalıştırma katmanı."""

import json
import logging
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from app.core.chat import ChatMessage, ToolCall
from app.security.permissions import PermissionDecision, ToolPermissionPolicy
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
    requires_approval: bool = False
    """Araç izinliydi ama önce kullanıcı onayı gerekiyor.

    Bu bir hata değil, duraklamadır: çağıran taraf onay alıp aynı çağrıyı
    yeniden yürütebilir. Reddedilmiş bir çağrıdan (`permission_denied`)
    ayırt edilebilsin diye ayrı bir alan olarak taşınır.
    """

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
    """Bir tool call'u sadece registry, input şeması ve izin kontrolünden sonra çalıştırır.

    İzin kararı bu sınıfa ait değildir: `ToolPermissionPolicy`'ye sorulur.
    Böylece aynı kural hem burada hem de agent bağlamında geçerli olur ve
    iki yerde ayrışma ihtimali kalmaz.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        allowed_permissions: Iterable[PermissionLevel] | None = None,
        *,
        policy: ToolPermissionPolicy | None = None,
    ) -> None:
        """
        Args:
            registry: Çalıştırılabilecek araçların kaydı.
            allowed_permissions: Onaysız çalıştırılabilecek seviyeler. Kısa
                yol: verilirse bu seviyelerden bir politika üretilir ve geri
                kalan her seviye reddedilir.
            policy: Tam izin politikası. `allowed_permissions` ile birlikte
                verilemez — ikisi aynı soruya farklı cevap verebilirdi.

        Raises:
            ValueError: Her iki argüman da verildiyse ya da hiçbiri verilmediyse.
        """
        if policy is not None and allowed_permissions is not None:
            raise ValueError(
                "allowed_permissions ve policy birlikte verilemez; birini seçin."
            )
        if policy is None and allowed_permissions is None:
            raise ValueError("allowed_permissions veya policy verilmelidir.")

        self._registry = registry
        self._policy = (
            policy
            if policy is not None
            else ToolPermissionPolicy(allowed=allowed_permissions or ())
        )

    @property
    def policy(self) -> ToolPermissionPolicy:
        """Bu executor'ın uyguladığı izin politikası."""

        return self._policy

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

        decision = self._policy.decide(tool.permission)
        if decision is PermissionDecision.DENY:
            return ToolExecutionResult(
                tool_name=call.name,
                success=False,
                error_code="permission_denied",
                error_message=f"{tool.permission} izni bu oturumda etkin değil.",
            )
        if decision is PermissionDecision.REQUIRE_APPROVAL:
            return ToolExecutionResult(
                tool_name=call.name,
                success=False,
                requires_approval=True,
                error_code="approval_required",
                error_message=(
                    f"{tool.permission} izinli '{tool.name}' aracı için kullanıcı "
                    "onayı gerekiyor."
                ),
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
