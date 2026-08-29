"""Araç izinlerinin tek karar noktası."""

from collections.abc import Iterable
from enum import StrEnum

from app.tools.base import PermissionLevel


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
            raise ValueError(
                f"Bir izin seviyesi hem serbest hem onaylı olamaz: {names}"
            )

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
