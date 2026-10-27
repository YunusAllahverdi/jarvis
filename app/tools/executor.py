"""Registry tabanlı permission, input validation ve tool çalıştırma katmanı."""

import asyncio
import json
import logging
import time
import unicodedata
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from app.core.chat import ChatMessage, ToolCall
from app.security.audit import AuditAction, AuditEvent, AuditLog, AuditOutcome, safe_record
from app.security.permissions import PermissionDecision, ToolPermissionPolicy
from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInputValidationError
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT_SECONDS = 120.0
"""Bir araç kendi `timeout_seconds`'ını beyan etmediyse uygulanan üst sınır.

Sınır olmadan bir araç (ör. yanıt vermeyen bir dış servis) tüm turu süresiz
bloklayabilirdi. Araç başına beyan edilen değer bunu geçersiz kılar.
"""

MAX_RESULT_CHARS = 100_000
"""Bir araç çıktısının kırpılacağı üst karakter sayısı (kendi sınırı yoksa).

`max_output_chars` beyan etmeyen araçlar için son bir emniyet supabıdır:
kırpma olmasaydı tek bir çağrı bağlam penceresini doldurabilirdi.
"""


def _sanitize_text(text: str) -> str:
    """Kontrol karakterlerini temizler; yeni satır ve sekmeyi korur.

    NUL ve benzeri kontrol karakterleri hem log hem model bağlamı için
    sorunludur; bazı istemciler bunları görünmez biçimde birleştirip metnin
    anlamını kaydırabilir. Yeni satır ve sekme okunabilirlik için korunur.
    """

    return "".join(ch if ch in "\n\t" or unicodedata.category(ch) != "Cc" else " " for ch in text)


def _truncate(value: Any, limit: int) -> tuple[Any, bool]:
    """Bir sonucu karakter sınırına göre kırpar ve kırpılıp kırpılmadığını döndürür.

    Kırpma JSON temsiline uygulanır: sözlüğün tek bir alanını kesmek yapıyı
    bozabilirdi; modelin gördüğü şey zaten JSON'dur.
    """

    rendered = json.dumps(value, ensure_ascii=False, default=str)
    if len(rendered) <= limit:
        return value, False
    return rendered[:limit], True


class ToolExecutionResult(BaseModel):
    """Bir tool call'un LLM'e geri verilebilecek kontrollü sonucu."""

    tool_name: str
    success: bool
    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    permission: PermissionLevel | None = None
    """Çağrılan aracın risk seviyesi; araç bulunamadıysa None.

    Sonuçla birlikte taşınır ki üst katmanlar bunu öğrenmek için registry'ye
    uzanmak zorunda kalmasın.
    """

    requires_approval: bool = False
    """Araç izinliydi ama önce kullanıcı onayı gerekiyor.

    Bu bir hata değil, duraklamadır: çağıran taraf onay alıp aynı çağrıyı
    yeniden yürütebilir. Reddedilmiş bir çağrıdan (`permission_denied`)
    ayırt edilebilsin diye ayrı bir alan olarak taşınır.
    """

    truncated: bool = False
    """Sonuç, aracın `max_output_chars` sınırına göre kırpıldı mı.

    Kırpma SESSİZ olmamalıdır: kırpılmış bir çıktıyı tam sanan model yanlış
    bir sonuca varabilir.
    """

    def as_chat_message(self) -> ChatMessage:
        """Ollama ve diğer provider'ların anlayabileceği tool-result mesajını üretir."""

        payload: dict[str, Any] = {"ok": self.success}
        if self.success:
            payload["result"] = self.data
        else:
            payload["error"] = {"code": self.error_code, "message": self.error_message}
        if self.truncated:
            payload["truncated"] = True
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

    Her çağrı — çalışsın ya da çalışmasın — denetim kaydına yazılır.
    Reddedilen ve onay bekleyen çağrılar da yazılır: bir saldırının izi
    çoğunlukla başarısız denemelerdedir.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        allowed_permissions: Iterable[PermissionLevel] | None = None,
        *,
        policy: ToolPermissionPolicy | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        """
        Args:
            registry: Çalıştırılabilecek araçların kaydı.
            allowed_permissions: Onaysız çalıştırılabilecek seviyeler. Kısa
                yol: verilirse bu seviyelerden bir politika üretilir ve geri
                kalan her seviye reddedilir.
            policy: Tam izin politikası. `allowed_permissions` ile birlikte
                verilemez — ikisi aynı soruya farklı cevap verebilirdi.
            audit_log: Çağrıların yazılacağı denetim kaydı. Verilmezse hiçbir
                şey yazılmaz; kayıt tutmak isteyen çağıran açıkça vermelidir.

        Raises:
            ValueError: Her iki izin argümanı da verildiyse ya da hiçbiri verilmediyse.
        """
        if policy is not None and allowed_permissions is not None:
            raise ValueError("allowed_permissions ve policy birlikte verilemez; birini seçin.")
        if policy is None and allowed_permissions is None:
            raise ValueError("allowed_permissions veya policy verilmelidir.")

        self._registry = registry
        self._policy = (
            policy
            if policy is not None
            else ToolPermissionPolicy(allowed=allowed_permissions or ())
        )
        self._audit_log = audit_log

    def set_audit_log(self, audit_log: AuditLog | None) -> None:
        """Denetim kaydını sonradan bağlar.

        Kalıcı kayıt bir dosya açar; bu yüzden import anında değil, uygulama
        fiilen başlarken kurulur. Bellek yığınında da aynı geç bağlama
        kalıbı kullanılıyor.
        """
        self._audit_log = audit_log

    @property
    def policy(self) -> ToolPermissionPolicy:
        """Bu executor'ın uyguladığı izin politikası."""

        return self._policy

    @property
    def registry(self) -> ToolRegistry:
        """Bu sınırdan çalıştırılabilecek araçların kaydı.

        Üst katmanların "hangi araçlar var?" sorusunu, ikinci bir registry
        örneği kurmadan yanıtlayabilmesi için açılır. İkinci bir örnek,
        yürütme sınırıyla ayrışabilecek bir araç yüzeyi demek olurdu:
        planlayan taraf, çalıştıran tarafta olmayan bir aracı görebilirdi.
        """

        return self._registry

    async def execute(
        self,
        call: ToolCall,
        *,
        approved: bool = False,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        """Tool call'u güvenli biçimde çalıştırır veya LLM'e hata sonucu döndürür.

        Args:
            call: Çalıştırılacak araç çağrısı.
            approved: Bu çağrı için kullanıcı onayı alınmış olduğunu belirtir.
                Yalnızca `REQUIRE_APPROVAL` kararını geçirir; `DENY` kararını
                geçirmez. Yani onay, kapalı bir aracı açamaz — sadece zaten
                onaya tabi olan bir aracı çalıştırılabilir kılar.

                Bu bayrağı LLM çıktısından türetmeyin: yalnızca gerçekten
                onay kaydı tüketilmiş bir akış True geçmelidir.
            session_id: Denetim kaydına yazılacak oturum kimliği.
        """

        tool = self._registry.get(call.name)
        if tool is None:
            return self._finish(
                call,
                ToolExecutionResult(
                    tool_name=call.name,
                    success=False,
                    error_code="unknown_tool",
                    error_message="İstenen tool kayıtlı değil.",
                ),
                outcome=AuditOutcome.BLOCKED,
                session_id=session_id,
            )

        decision = self._policy.decide(tool.effective_permission)

        if decision is PermissionDecision.DENY:
            return self._finish(
                call,
                ToolExecutionResult(
                    tool_name=call.name,
                    success=False,
                    error_code="permission_denied",
                    error_message=(f"{tool.effective_permission} izni bu oturumda etkin değil."),
                ),
                outcome=AuditOutcome.BLOCKED,
                permission=tool.effective_permission,
                decision=decision,
                session_id=session_id,
            )

        if decision is PermissionDecision.REQUIRE_APPROVAL and not approved:
            return self._finish(
                call,
                ToolExecutionResult(
                    tool_name=call.name,
                    success=False,
                    requires_approval=True,
                    error_code="approval_required",
                    error_message=(
                        f"{tool.effective_permission} izinli '{tool.name}' aracı için kullanıcı "
                        "onayı gerekiyor."
                    ),
                ),
                outcome=AuditOutcome.PENDING_APPROVAL,
                permission=tool.effective_permission,
                decision=decision,
                session_id=session_id,
            )

        try:
            tool_input = tool.validate_input(call.arguments)
        except ToolInputValidationError:
            return self._finish(
                call,
                ToolExecutionResult(
                    tool_name=call.name,
                    success=False,
                    error_code="invalid_arguments",
                    error_message="Tool argument'leri şemaya uymuyor.",
                ),
                outcome=AuditOutcome.FAILURE,
                permission=tool.effective_permission,
                decision=decision,
                session_id=session_id,
            )

        started = time.perf_counter()
        timeout = tool.timeout_seconds or DEFAULT_TOOL_TIMEOUT_SECONDS
        try:
            data = await asyncio.wait_for(tool.execute(tool_input), timeout=timeout)
        except TimeoutError:
            logger.warning(
                "tool_execution_timeout",
                extra={"tool_name": tool.name, "timeout_seconds": timeout},
            )
            return self._finish(
                call,
                ToolExecutionResult(
                    tool_name=call.name,
                    success=False,
                    error_code="tool_timeout",
                    error_message=(f"'{tool.name}' aracı {timeout:g} saniye içinde yanıt vermedi."),
                ),
                outcome=AuditOutcome.FAILURE,
                permission=tool.effective_permission,
                decision=decision,
                session_id=session_id,
                started=started,
            )
        except ToolExecutionError as exc:
            return self._finish(
                call,
                ToolExecutionResult(
                    tool_name=call.name,
                    success=False,
                    error_code="tool_execution_failed",
                    error_message=str(exc),
                ),
                outcome=AuditOutcome.FAILURE,
                permission=tool.effective_permission,
                decision=decision,
                session_id=session_id,
                started=started,
            )
        except Exception:
            logger.exception("tool_execution_unexpected_error", extra={"tool_name": tool.name})
            return self._finish(
                call,
                ToolExecutionResult(
                    tool_name=call.name,
                    success=False,
                    error_code="tool_execution_failed",
                    error_message="Tool çalıştırılırken beklenmeyen bir hata oluştu.",
                ),
                outcome=AuditOutcome.FAILURE,
                permission=tool.effective_permission,
                decision=decision,
                session_id=session_id,
                started=started,
            )

        processed, truncated = self._post_process(tool, data)
        return self._finish(
            call,
            ToolExecutionResult(
                tool_name=call.name,
                success=True,
                data=processed,
                truncated=truncated,
            ),
            outcome=AuditOutcome.SUCCESS,
            permission=tool.effective_permission,
            decision=decision,
            session_id=session_id,
            started=started,
        )

    @staticmethod
    def _post_process(tool: Tool[Any], data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Araç çıktısını sınırlar, temizler ve gerekirse güvenilmez olarak sarar.

        Üç iş TEK yerde yapılır çünkü üçü de "modele ne gidecek" sorusunun
        parçasıdır ve ayrı yerlere dağılsalardı biri unutulabilirdi.
        """

        if tool.untrusted_output:
            # Güvenilmez çıktı çitlenir ve bir zarf içinde verilir: model
            # buradakini talimat değil VERİ saymalıdır.
            content = data.get("content") if isinstance(data, dict) else None
            body = (
                content
                if isinstance(content, str)
                else json.dumps(data, ensure_ascii=False, default=str)
            )
            payload: dict[str, Any] = {
                "untrusted": True,
                "source": tool.source,
                "content": _sanitize_text(body),
            }
            if isinstance(data, dict):
                # Güvenilmez olmayan üst veri (url, status_code) kaybolmasın.
                payload.update({key: value for key, value in data.items() if key != "content"})
            processed: dict[str, Any] = payload
        else:
            processed = data

        limit = tool.max_output_chars or MAX_RESULT_CHARS
        result, truncated = _truncate(processed, limit)
        if isinstance(result, dict):
            return result, truncated
        return {"content": result}, truncated

    def _finish(
        self,
        call: ToolCall,
        result: ToolExecutionResult,
        *,
        outcome: AuditOutcome,
        permission: PermissionLevel | None = None,
        decision: PermissionDecision | None = None,
        session_id: str | None = None,
        started: float | None = None,
    ) -> ToolExecutionResult:
        """Sonucu denetim kaydına yazar ve olduğu gibi döndürür.

        Her çıkış yolu buradan geçer; yeni bir dal eklendiğinde kaydın
        atlanması için ayrıca bir şey yapılması gerekir.
        """
        result.permission = permission
        safe_record(
            self._audit_log,
            AuditEvent(
                action=AuditAction.TOOL_CALL,
                outcome=outcome,
                tool_name=call.name,
                arguments=dict(call.arguments),
                permission=permission,
                decision=decision,
                session_id=session_id,
                error_code=result.error_code,
                duration_ms=(
                    None if started is None else round((time.perf_counter() - started) * 1000, 3)
                ),
            ),
        )
        return result
