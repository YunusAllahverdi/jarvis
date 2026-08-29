"""Agent karar katmanının yapılandırılmış veri modelleri.

Bu modül saf veri modelidir: hiçbir depoya yazmaz, hiçbir LLM çağırmaz,
hiçbir tool çalıştırmaz, hiçbir I/O yapmaz.

Tasarım ilkeleri:
- Kararlar ve sonuçlar YAPILANDIRILMIŞTIR. Serbest metin yalnızca kısa,
  olgusal `reason`/`purpose` alanlarında bulunur.
- GİZLİ AKIL YÜRÜTME SAKLANMAZ. `reason`, makine tarafından üretilmiş bir
  gerekçe cümlesidir ("aritmetik ifade tespit edildi"), bir düşünce dökümü
  (chain-of-thought) değildir. İleride bir LLM politikası eklendiğinde de
  bu alan kısa bir gerekçeyle sınırlı kalmalıdır.
- Onay gerektiren eylemler mimari olarak temsil edilebilir
  (`requires_confirmation`), ancak bu fazda tehlikeli bir eylem YOKTUR.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.chat import ToolCall
from app.council.models import CouncilResult
from app.tools.base import PermissionLevel

_TOOL_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
"""ToolDefinition/ToolCall ile aynı desen — agent ayrı bir ad alanı icat etmez."""


class Intent(StrEnum):
    """Bir kullanıcı isteğinin tanınmış amacı.

    Kapalı bir küme olması bilinçlidir ve bir GÜVENLİK özelliğidir: ileride
    eklenecek bir LLM politikası da keyfi bir amaç uyduramaz, ya bilinen bir
    amaca eşlemek ya da `UNKNOWN` demek zorundadır.
    """

    CALCULATE = "calculate"
    GET_TIME = "get_time"
    GET_DATE = "get_date"
    SYSTEM_STATUS = "system_status"
    RECALL = "recall"
    """Kullanıcı hakkında bilinenleri/geçmişi getirme isteği."""

    INFORMATION_REQUEST = "information_request"
    """Tool ile karşılanan, yukarıdakilere girmeyen genel bir bilgi isteği."""

    CONVERSATION = "conversation"
    """Yapılacak bir eylem yok — normal sohbet cevabı yeterli."""

    UNKNOWN = "unknown"
    """Politika karar veremedi. Çağıran normal sohbete düşmelidir."""


class AgentStatus(StrEnum):
    """Bir agent çalıştırmasının sonuç durumu."""

    COMPLETED = "completed"
    """Planlanan tüm eylemler başarıyla çalıştı."""

    PARTIAL = "partial"
    """Eylemlerin bir kısmı başarılı, bir kısmı başarısız."""

    PENDING_CONFIRMATION = "pending_confirmation"
    """Plan onay bekliyor; HİÇBİR eylem çalıştırılmadı."""

    NO_ACTION = "no_action"
    """Karar hiçbir eylem içermiyordu (ör. normal sohbet)."""

    FAILED = "failed"
    """Hiçbir eylem başarılı olmadı veya agent katmanı kendi içinde hata verdi."""


class ToolDescriptor(BaseModel):
    """Bir tool'un agent bağlamına ve API'ye sunulan salt-okunur görünümü.

    `Tool` nesnesinin kendisi asla bağlama veya API yanıtına konmaz —
    yalnızca bu güvenli tanım taşınır.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=_TOOL_NAME_PATTERN)
    description: str
    permission: PermissionLevel

    input_schema: dict[str, Any] = Field(default_factory=dict)
    """Tool'un argüman sözleşmesi (JSON Schema).

    Karar veren tarafın (kural tabanlı veya LLM) doğru argüman üretebilmesi
    için gereklidir. Yalnızca SÖZLEŞME taşınır — tool'un implementasyonu,
    dosya yolu veya iç durumu asla buraya girmez.
    """

    requires_confirmation: bool = False
    """Bu tool'un izin seviyesi mevcut oturumda etkin değilse True.

    Onay gereksinimi tool'un DEĞİŞMEZ bir özelliği değil, oturumun izin
    kümesine göre hesaplanan bir sonuçtur.
    """


class AgentAction(BaseModel):
    """Yürütülmesi planlanan tek bir adım.

    Bir eylem her zaman KAYITLI bir tool'a yapılan çağrıdır; agent keyfi kod
    çalıştıramaz. Yürütme sınırı `ToolExecutor`'dır.
    """

    tool_name: str = Field(pattern=_TOOL_NAME_PATTERN)
    arguments: dict[str, Any] = Field(default_factory=dict)

    purpose: str = Field(min_length=1, max_length=200)
    """Bu adımın NEDEN planlandığını anlatan kısa, olgusal ifade."""

    requires_confirmation: bool = False
    """True ise bu eylem kullanıcı onayı olmadan çalıştırılamaz."""

    def as_tool_call(self) -> ToolCall:
        """Mevcut ToolExecutor sınırının anladığı çağrıya dönüştürür.

        Agent kendi yürütme mekanizmasını icat etmez; hâlihazırda izin
        kontrolü, şema doğrulaması ve hata izolasyonu yapan ToolExecutor'ı
        kullanır.
        """
        return ToolCall(name=self.tool_name, arguments=dict(self.arguments))


class AgentDecision(BaseModel):
    """Bir politikanın ürettiği yapılandırılmış karar."""

    intent: Intent
    actions: list[AgentAction] = Field(default_factory=list)

    reason: str = Field(min_length=1, max_length=300)
    """Kararın kısa, olgusal gerekçesi — düşünce dökümü DEĞİL."""

    policy: str = Field(min_length=1, max_length=64)
    """Kararı üreten politikanın adı (gözlemlenebilirlik için)."""

    requires_confirmation: bool = False
    """Eylemlerden en az biri onay gerektiriyorsa True.

    Doğrudan atanabilir, ancak eylemlerle tutarsız olamaz: aşağıdaki
    doğrulayıcı, onay gerektiren bir eylem varken bu alanın False
    kalmasını engeller — güvenlik sınırı yanlışlıkla atlanamaz.
    """

    @model_validator(mode="after")
    def confirmation_must_cover_actions(self) -> AgentDecision:
        if any(action.requires_confirmation for action in self.actions):
            self.requires_confirmation = True
        return self

    @property
    def is_multi_step(self) -> bool:
        """Plan birden fazla adım içeriyorsa True."""
        return len(self.actions) > 1

    @property
    def has_actions(self) -> bool:
        return bool(self.actions)


class ActionOutcome(BaseModel):
    """Tek bir eylemin yürütme sonucu."""

    tool_name: str = Field(pattern=_TOOL_NAME_PATTERN)
    success: bool = False
    skipped: bool = False
    """True ise eylem hiç çalıştırılmadı (ör. onay bekliyor)."""

    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    arguments: dict[str, Any] = Field(default_factory=dict)
    """Eylemin gerçekten çağrıldığı argümanlar (başvurular çözülmüş hâliyle)."""

    permission: str | None = None
    """Çağrılan aracın risk seviyesi."""

    requires_approval: bool = False
    """Eylem izinliydi ama kullanıcı onayı beklediği için çalıştırılmadı."""

    approval_id: str | None = None
    """Onay bekleyen eylem için kullanıcının yanıtlayacağı kaydın kimliği.

    Bu alan olmadan ajan "onay gerekiyor" der ama kullanıcı hangi isteği
    onaylayacağını bilemezdi. Kaydı açan üst katmandır (AgentService);
    runner yalnızca durumu bildirir.
    """

    @classmethod
    def from_execution(
        cls, result: Any, arguments: dict[str, Any]
    ) -> "ActionOutcome":
        """Bir `ToolExecutionResult`'ı eylem sonucuna çevirir.

        Alan eşlemesi burada durur, runner'da değil: runner'ın işi eylemi
        yürütme sınırından geçirmektir, sonucun biçimini bilmek değil.
        """
        return cls(
            tool_name=result.tool_name,
            success=result.success,
            data=result.data,
            error_code=result.error_code,
            error_message=result.error_message,
            arguments=dict(arguments),
            permission=str(result.permission) if result.permission else None,
            requires_approval=result.requires_approval,
        )


class AgentResult(BaseModel):
    """Bir agent çalıştırmasının tam, yapılandırılmış sonucu."""

    decision: AgentDecision
    outcomes: list[ActionOutcome] = Field(default_factory=list)
    status: AgentStatus

    council: CouncilResult | None = None
    """Council çalıştıysa müzakerenin yapılandırılmış sonucu; aksi halde None.

    Council çalışmadığında (kapalı, kapı açılmadı) bu alan None kalır ve
    sistemin davranışı Council eklenmeden önceki hâliyle aynıdır.
    Chairman'ın metni buradan KULLANICIYA DOĞRUDAN dönmez; çağıran onu
    sınırlanmış veri olarak normal cevap üretimine aktarır.
    """

    @property
    def ok(self) -> bool:
        """Yürütme tamamen başarılıysa veya yapacak bir şey yoksa True."""
        return self.status in (AgentStatus.COMPLETED, AgentStatus.NO_ACTION)

    @property
    def successful_outcomes(self) -> list[ActionOutcome]:
        return [outcome for outcome in self.outcomes if outcome.success]


def status_for(outcomes: list[ActionOutcome]) -> AgentStatus:
    """Yürütülen eylem sonuçlarından toplu durumu deterministik olarak türetir.

    - hiç eylem yoksa            → NO_ACTION
    - hepsi atlandıysa           → PENDING_CONFIRMATION
    - hepsi başarılıysa          → COMPLETED
    - hiçbiri başarılı değilse   → FAILED
    - karışıksa                  → PARTIAL
    """
    if not outcomes:
        return AgentStatus.NO_ACTION
    if all(outcome.skipped for outcome in outcomes):
        return AgentStatus.PENDING_CONFIRMATION
    executed = [outcome for outcome in outcomes if not outcome.skipped]
    successes = [outcome for outcome in executed if outcome.success]
    if len(successes) == len(outcomes):
        return AgentStatus.COMPLETED
    if not successes:
        return AgentStatus.FAILED
    return AgentStatus.PARTIAL
