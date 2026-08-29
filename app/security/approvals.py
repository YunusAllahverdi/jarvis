"""Kullanıcı onayı bekleyen araç çağrılarının kaydı ve akıbeti.

Onay bir yetki yükseltmesi değildir: tek bir çağrıyı, tek bir kez, aynen
önerildiği hâliyle çalıştırılabilir kılar. Oturumun izin politikası
değişmez — bir sonraki çağrı yine sıfırdan onay ister.

Kayıtlar bilerek bellekte tutulur. Bekleyen bir onay, ait olduğu ajan
turuna aittir; sunucu yeniden başladığında o tur zaten kaybolmuştur, dolayısıyla
onayın hayatta kalması yalnızca bağlamı olmayan bir çağrının onaylı
görünmesine yol açardı.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.chat import ToolCall
from app.tools.base import PermissionLevel


class ApprovalError(RuntimeError):
    """Onay akışındaki kontrollü hataların tabanı."""


class ApprovalNotFoundError(ApprovalError):
    """Verilen kimlikte bir onay isteği yok."""


class ApprovalAlreadyDecidedError(ApprovalError):
    """Bu onay daha önce kullanılmış veya reddedilmiş.

    Tek kullanımlık olmasının nedeni tekrar saldırısıdır: onaylanmış bir
    kimlik ele geçirilirse, aynı yazma işlemi defalarca çalıştırılabilirdi.
    """


class ApprovalExpiredError(ApprovalError):
    """Onay isteğinin süresi dolmuş."""


class ApprovalStatus(StrEnum):
    """Bir onay isteğinin bulunabileceği durumlar."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    """Onaylandı ve çağrısı teslim edildi — tekrar kullanılamaz."""

    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ApprovalRequest(BaseModel):
    """Onay bekleyen tek bir araç çağrısının dondurulmuş kaydı.

    `tool_name` ve `arguments` burada saklanır ve onay anında istemciden
    yeniden alınmaz. Kullanıcı neyi gördüyse onu onaylar; çalıştırılan da
    tam olarak o olur.
    """

    approval_id: str
    tool_name: str
    arguments: dict = Field(default_factory=dict)
    permission: PermissionLevel
    session_id: str | None = None
    reason: str | None = None
    created_at: datetime
    expires_at: datetime
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_at: datetime | None = None

    def as_tool_call(self) -> ToolCall:
        """Kaydedilen çağrıyı yeniden kurar."""

        return ToolCall(name=self.tool_name, arguments=dict(self.arguments))


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ApprovalService:
    """Bekleyen onayları tutar ve tek kullanımlık biçimde teslim eder."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 300.0,
        max_pending: int = 50,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """
        Args:
            ttl_seconds: Bir onay isteğinin geçerli kalacağı süre. Kullanıcı
                bu sürede karar vermezse istek düşer; eski bir öneri sonradan
                onaylanıp bambaşka bir durumda çalıştırılamasın diye.
            max_pending: Aynı anda bekleyebilecek en fazla istek. Sınır,
                yanıt vermeyen bir istemcinin belleği doldurmasını engeller.
            clock: Şimdiki zamanı üreten çağrılabilir. Testler zaman
                geçirmeden süre dolmasını sınayabilsin diye enjekte edilir.

        Raises:
            ValueError: ttl_seconds veya max_pending pozitif değilse.
        """
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds pozitif olmalıdır.")
        if max_pending <= 0:
            raise ValueError("max_pending pozitif olmalıdır.")

        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_pending = max_pending
        self._clock = clock
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = RLock()

    def request(
        self,
        call: ToolCall,
        *,
        permission: PermissionLevel,
        session_id: str | None = None,
        reason: str | None = None,
    ) -> ApprovalRequest:
        """Bir çağrı için onay isteği açar ve kaydı döndürür.

        Raises:
            ApprovalError: Bekleyen istek sayısı sınırı aşılmışsa.
        """
        now = self._clock()
        with self._lock:
            self._expire_stale(now)
            if self._count_pending() >= self._max_pending:
                raise ApprovalError(
                    "Bekleyen onay sayısı sınıra ulaştı; önce mevcutları yanıtlayın."
                )

            record = ApprovalRequest(
                approval_id=uuid4().hex,
                tool_name=call.name,
                arguments=dict(call.arguments),
                permission=permission,
                session_id=session_id,
                reason=reason,
                created_at=now,
                expires_at=now + self._ttl,
            )
            self._requests[record.approval_id] = record
            return record

    def get(self, approval_id: str) -> ApprovalRequest | None:
        """Bir kaydı döndürür; süresi dolmuşsa durumu güncellenmiş hâliyle."""

        with self._lock:
            self._expire_stale(self._clock())
            return self._requests.get(approval_id)

    def pending(self, *, session_id: str | None = None) -> list[ApprovalRequest]:
        """Hâlâ bekleyen istekleri, isteğe bağlı olarak oturuma göre süzer."""

        with self._lock:
            self._expire_stale(self._clock())
            return [
                record
                for record in self._requests.values()
                if record.status is ApprovalStatus.PENDING
                and (session_id is None or record.session_id == session_id)
            ]

    def approve(self, approval_id: str) -> ToolCall:
        """İsteği onaylar ve saklanan çağrıyı **bir kez** teslim eder.

        Dönen çağrı kayıttan gelir, çağırandan değil: onaylanan ile
        çalıştırılan arasında fark oluşamaz.

        Raises:
            ApprovalNotFoundError: Böyle bir istek yok.
            ApprovalExpiredError: Süresi dolmuş.
            ApprovalAlreadyDecidedError: Daha önce onaylanmış veya reddedilmiş.
        """
        with self._lock:
            record = self._claim(approval_id)
            record.status = ApprovalStatus.APPROVED
            record.decided_at = self._clock()
            return record.as_tool_call()

    def reject(self, approval_id: str) -> ApprovalRequest:
        """İsteği reddeder; bir daha onaylanamaz.

        Raises:
            ApprovalNotFoundError, ApprovalExpiredError, ApprovalAlreadyDecidedError
        """
        with self._lock:
            record = self._claim(approval_id)
            record.status = ApprovalStatus.REJECTED
            record.decided_at = self._clock()
            return record

    # ── iç yardımcılar ───────────────────────────────────────

    def _claim(self, approval_id: str) -> ApprovalRequest:
        """Kaydı karar verilebilir durumda bulur; değilse uygun hatayı atar."""

        now = self._clock()
        self._expire_stale(now)

        record = self._requests.get(approval_id)
        if record is None:
            raise ApprovalNotFoundError("Böyle bir onay isteği yok.")
        if record.status is ApprovalStatus.EXPIRED:
            raise ApprovalExpiredError("Onay isteğinin süresi dolmuş.")
        if record.status is not ApprovalStatus.PENDING:
            raise ApprovalAlreadyDecidedError("Bu onay isteği zaten sonuçlanmış.")
        return record

    def _expire_stale(self, now: datetime) -> None:
        """Süresi geçmiş bekleyen istekleri EXPIRED'a çevirir."""

        for record in self._requests.values():
            if record.status is ApprovalStatus.PENDING and now >= record.expires_at:
                record.status = ApprovalStatus.EXPIRED
                record.decided_at = now

    def _count_pending(self) -> int:
        return sum(
            1 for record in self._requests.values() if record.status is ApprovalStatus.PENDING
        )
