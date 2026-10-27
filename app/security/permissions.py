"""Araç izinlerinin tek karar noktası.

Bu modül iki soruyu birden yanıtlar ve ikisi de TEK bir yerde durur:

1. **Bir izin seviyesi bu oturumda çalışabilir mi?** — `ToolPermissionPolicy`.
   `READ` serbest, `WRITE` onaya tabi, `DANGEROUS` açık bayrak yoksa reddedilir.

2. **Kullanıcının bir araç için verdiği override kabul edilebilir mi?** —
   `plan_override`. Kapatma ve yükseltme serbesttir; düşürme yalnızca açık
   istekle; `DANGEROUS` asla düşürülemez.

İkinci kuralın da burada durması bilinçlidir: "bu araç ne kadar riskli" ile
"bu araç şu an çalışabilir mi" soruları birbirine bağlıdır ve iki ayrı modüle
dağılsalardı biri güncellenip diğeri unutulabilirdi.
"""

from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import PermissionLevel, risk_rank

TOOL_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"

AUDIT_TOOL_OVERRIDE = "tool_override"
"""Kapatma/yükseltme gibi olağan override değişikliklerinin denetim eylemi."""

AUDIT_PERMISSION_DOWNGRADE = "permission_downgrade"
"""Yetki DÜŞÜREN değişikliklerin denetim eylemi — ayrı izlenmelidir."""


class ToolOverride(BaseModel):
    """Tek bir araç için kalıcı kullanıcı kararı."""

    model_config = ConfigDict(frozen=True)

    tool_name: str = Field(pattern=TOOL_NAME_PATTERN)
    enabled: bool = True
    """False ise araç hiç kaydedilmez — yetki daraltmanın en kesin biçimi."""

    permission: PermissionLevel | None = None
    """Geçersiz kılınan izin seviyesi. None ise aracın kendi seviyesi geçerli."""


class OverridePlan(BaseModel):
    """Bir override isteğinin deterministik değerlendirme sonucu."""

    model_config = ConfigDict(frozen=True)

    accepted: bool
    override: ToolOverride | None = None
    audit_action: str | None = None
    """Kabul edildiyse denetim kaydına yazılacak eylem; reddedildiyse None."""

    reason: str
    """Kısa, olgusal gerekçe — kullanıcıya gösterilebilir."""


def plan_override(
    tool_name: str,
    base_permission: PermissionLevel,
    *,
    enabled: bool = True,
    permission: PermissionLevel | None = None,
    allow_downgrade: bool = False,
) -> OverridePlan:
    """Bir override isteğini kurallara göre değerlendirir — tek karar noktası.

    Kurallar bilinçli olarak asimetriktir:

    - **Kapatma serbesttir.** Bir yeteneği kapatmak yetkiyi daraltır.
    - **Yükseltme serbesttir.** Daha çok onay istemek güvenli taraftır.
    - **Düşürme yalnızca açık istekle.** Sessiz bir `WRITE → READ` bir yetki
      genişlemesidir; `allow_downgrade` gerektirir ve denetim kaydına
      `permission_downgrade` olarak yazılır.
    - **`DANGEROUS` asla düşürülemez.** Açık istek verilse bile reddedilir.

    Args:
        tool_name: Aracın adı.
        base_permission: Aracın KENDİ beyan ettiği izin seviyesi.
        enabled: Araç açık kalsın mı.
        permission: İstenen yeni izin seviyesi; None ise yalnızca aç/kapa.
        allow_downgrade: Yetki DÜŞÜREN bir değişiklik için açık kullanıcı onayı.

    Returns:
        `OverridePlan`. Reddedilen bir istek de bir sonuçtur; istisna fırlatılmaz.
    """

    if permission is None:
        override = ToolOverride(tool_name=tool_name, enabled=enabled, permission=None)
        return OverridePlan(
            accepted=True,
            override=override,
            audit_action=AUDIT_TOOL_OVERRIDE,
            reason="Araç açıldı." if enabled else "Araç kapatıldı.",
        )

    if risk_rank(permission) < risk_rank(base_permission):
        if base_permission is PermissionLevel.DANGEROUS:
            return OverridePlan(
                accepted=False,
                reason=(
                    "DANGEROUS seviyeli bir aracın izni düşürülemez. "
                    "Onay akışını devre dışı bırakmak bu yolla mümkün olmamalıdır."
                ),
            )
        if not allow_downgrade:
            return OverridePlan(
                accepted=False,
                reason=(
                    "İzin düşürme yalnızca açık kullanıcı isteğiyle yapılabilir "
                    "(allow_downgrade=true)."
                ),
            )
        override = ToolOverride(tool_name=tool_name, enabled=enabled, permission=permission)
        return OverridePlan(
            accepted=True,
            override=override,
            audit_action=AUDIT_PERMISSION_DOWNGRADE,
            reason=f"İzin {base_permission} → {permission} düşürüldü.",
        )

    override = ToolOverride(tool_name=tool_name, enabled=enabled, permission=permission)
    return OverridePlan(
        accepted=True,
        override=override,
        audit_action=AUDIT_TOOL_OVERRIDE,
        reason=f"İzin {base_permission} → {permission} olarak ayarlandı.",
    )


class PermissionDecision(StrEnum):
    """Bir izin seviyesi için verilebilecek üç karar."""

    ALLOW = "ALLOW"
    """Doğrudan çalıştırılabilir."""

    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    """Çalıştırılabilir, ama önce kullanıcı onayı gerekir."""

    DENY = "DENY"
    """Bu oturumda hiç çalıştırılamaz."""


class ToolPermissionPolicy:
    """Bir izin seviyesinin akıbetine karar verir.

    Politika **deny-by-default**'tur: hiçbir listede geçmeyen seviye
    reddedilir. Bu, ileride yeni bir `PermissionLevel` eklendiğinde onun
    sessizce serbest kalmasını engeller — yeni seviye, biri onu açıkça
    listeye koyana kadar kapalıdır.

    Bir seviye aynı anda hem serbest hem onaylı olamaz; kurucu bunu
    reddeder, çünkü böyle bir yapılandırma hangi kuralın kazandığına dair
    sessiz bir varsayıma dayanırdı.

    Kullanım:
        policy = ToolPermissionPolicy(
            allowed={PermissionLevel.READ},
            requires_approval={PermissionLevel.WRITE},
        )
        policy.decide(PermissionLevel.WRITE)  # REQUIRE_APPROVAL
        policy.decide(PermissionLevel.DANGEROUS)  # DENY
    """

    def __init__(
        self,
        *,
        allowed: Iterable[PermissionLevel] = (),
        requires_approval: Iterable[PermissionLevel] = (),
    ) -> None:
        """
        Args:
            allowed: Onay istemeden çalıştırılabilecek izin seviyeleri.
            requires_approval: Kullanıcı onayından sonra çalıştırılabilecek
                izin seviyeleri.

        Raises:
            ValueError: Bir seviye her iki listede birden geçiyorsa.
        """
        allowed_set = frozenset(allowed)
        approval_set = frozenset(requires_approval)

        overlap = allowed_set & approval_set
        if overlap:
            names = ", ".join(sorted(str(level) for level in overlap))
            raise ValueError(f"Bir izin seviyesi hem serbest hem onaylı olamaz: {names}")

        self._allowed = allowed_set
        self._requires_approval = approval_set

    @classmethod
    def read_only(cls) -> "ToolPermissionPolicy":
        """Yalnızca okuma araçlarını serbest bırakan varsayılan politika."""

        return cls(allowed={PermissionLevel.READ})

    @classmethod
    def deny_all(cls) -> "ToolPermissionPolicy":
        """Hiçbir aracın çalışmasına izin vermeyen politika."""

        return cls()

    @property
    def allowed(self) -> frozenset[PermissionLevel]:
        """Onaysız çalıştırılabilen seviyeler."""

        return self._allowed

    @property
    def requires_approval(self) -> frozenset[PermissionLevel]:
        """Onay sonrası çalıştırılabilen seviyeler."""

        return self._requires_approval

    def decide(self, permission: PermissionLevel) -> PermissionDecision:
        """Verilen izin seviyesi için kararı döndürür."""

        if permission in self._allowed:
            return PermissionDecision.ALLOW
        if permission in self._requires_approval:
            return PermissionDecision.REQUIRE_APPROVAL
        return PermissionDecision.DENY

    def is_allowed(self, permission: PermissionLevel) -> bool:
        """Seviyenin onaysız çalıştırılabilir olup olmadığını söyler."""

        return self.decide(permission) is PermissionDecision.ALLOW
