"""Kayıtlı araçlar için güvenli ve sağlayıcıdan bağımsız temel sözleşmeler."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.chat import ToolDefinition


class PermissionLevel(StrEnum):
    """Bir aracın gerektirdiği risk seviyesi."""

    READ = "READ"
    WRITE = "WRITE"
    DANGEROUS = "DANGEROUS"


_RISK_RANK: dict["PermissionLevel", int] = {
    PermissionLevel.READ: 0,
    PermissionLevel.WRITE: 1,
    PermissionLevel.DANGEROUS: 2,
}
"""Seviyelerin karşılaştırılabilir sırası.

Tek tanım noktası: bir izin seviyesinin "yükseltilmiş" mi "düşürülmüş" mü
olduğu yalnızca bu sıraya bakılarak söylenir. İki yerde yazılsaydı biri
güncellenip diğeri unutulduğunda bir düşürme sessizce yükseltme sayılabilirdi.
"""


def risk_rank(level: PermissionLevel) -> int:
    """Bir izin seviyesinin sıra numarasını döndürür (READ < WRITE < DANGEROUS)."""

    return _RISK_RANK[level]


class RiskTag(StrEnum):
    """Bir aracın dokunduğu risk aileleri.

    Serbest metin DEĞİLDİR: kapalı bir kümedir, çünkü bu etiketler ileride
    politika kararlarında (ör. "ağ erişen araçlar ayrı onaya tabidir") ve
    arayüzde rozet olarak kullanılacaktır. Serbest metin olsaydı yazım
    farklarıyla aynı risk iki farklı etiket altında görünürdü.
    """

    NETWORK = "network"
    FILESYSTEM = "filesystem"
    DEVICE = "device"
    MONEY = "money"
    IRREVERSIBLE = "irreversible"
    PERSONAL_DATA = "personal_data"


class ToolInput(BaseModel):
    """Tüm araç input modelleri için katı Pydantic tabanı."""

    model_config = ConfigDict(extra="forbid")


class ToolError(RuntimeError):
    """Tool katmanından kontrollü hata gönderildiğini belirtir."""


class ToolInputValidationError(ToolError):
    """LLM veya API'nin sağladığı tool argument'leri geçersizdir."""


class ToolExecutionError(ToolError):
    """Doğrulanmış input ile araç çalıştırılırken hata oluşmuştur."""


class Tool[InputModelT: BaseModel](ABC):
    """Her kayıtlı tool'un uygulaması gereken sözleşme.

    `InputModelT` PEP 695 tip parametresidir: aracın Pydantic input modeli.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    permission: ClassVar[PermissionLevel]
    input_model: type[InputModelT]

    source: ClassVar[str] = "builtin"
    """Bu aracı sağlayan aile (ör. "builtin", "mcp", "home_assistant").

    Arayüz ve denetim bu etiketi gösterir; karar mercii değildir. Varsayılan
    "builtin" olması bilinçlidir: mevcut araçlar hiçbir şey değiştirmeden
    doğru kaynağa sahip olur.
    """

    category: ClassVar[str] = ""
    """İnsan tarafından okunabilir gruplama etiketi (ör. "dosya", "ağ")."""

    risk_tags: ClassVar[frozenset[str]] = frozenset()
    """Aracın dokunduğu risk aileleri (bkz. `RiskTag`).

    İzin seviyesinden AYRIDIR: iki araç aynı seviyede olup farklı risklere
    dokunabilir (ör. yerel dosya okumak ile kişisel veri okumak).
    """

    untrusted_output: ClassVar[bool] = False
    """Aracın çıktısı güvenilmez DIŞ veri mi?

    True ise `ToolExecutor` sonucu `{"untrusted": true, "source", "content"}`
    zarfına alır. Model, bu zarfın içindekini talimat değil veri saymalıdır.
    """

    max_output_chars: ClassVar[int | None] = None
    """Araç çıktısının modele taşınacak üst karakter sınırı (None = sınırsız).

    Sınır aşılırsa `ToolExecutor` kırpar ve sonuca `truncated: true` ekler.
    """

    timeout_seconds: ClassVar[float | None] = None
    """Aracın çalışabileceği en uzun süre (None = `ToolExecutor` varsayılanı).

    Süre dolduğunda çağrı yapılandırılmış bir `tool_timeout` hatasına döner;
    araç asla sonsuza kadar beklenmez.
    """

    _permission_override: PermissionLevel | None = None
    """Kullanıcının bu ÖRNEK için verdiği izin kararı (kalıcı override'dan).

    `permission` sınıf düzeyinde ve değişmezdir; bu alan yalnızca o örneğe
    uygulanan kararı taşır. İkisinin ayrı tutulması bilinçlidir: aracın KENDİ
    beyanı ile kullanıcının kararı karıştırılsaydı, "ne istedi" sorusunun
    cevabı kaybolurdu.
    """

    @property
    def effective_permission(self) -> PermissionLevel:
        """Bu örnek için fiilen geçerli izin seviyesi.

        Yürütücü ve bağlam kurucu bunu okur; böylece bir override tek yerden
        (bu özellikten) etkili olur ve iki katman ayrışamaz.

        Normal öznitelik araması (`self.permission`) kullanılır: araçlar
        seviyeyi çoğunlukla sınıf düzeyinde beyan eder, ama bazı araçlar
        örnek düzeyinde de atayabilir. `type(self)` ile sabitlemek, örnek
        düzeyinde atama yapan araçları kırardı.
        """

        return self._permission_override or self.permission

    def with_permission_override(self, permission: PermissionLevel) -> None:
        """Bu örnek için geçerli izin seviyesini değiştirir.

        Yalnızca `CapabilityRegistry` çağırır ve yalnızca TAZE üretilmiş bir
        örnek üzerinde çağrılır; paylaşılan bir örneği değiştirmek başka bir
        çağıranın gördüğü seviyeyi sessizce kaydırırdı.
        """

        self._permission_override = permission

    @property
    def definition(self) -> ToolDefinition:
        """LLM sağlayıcısına verilebilecek tool şemasını üretir.

        Meta veriler `ToolDefinition`'a yansıtılır ama LLM'e GİDEN şema
        yalnızca ad, açıklama ve input şemasıdır: sağlayıcı serializasyonu
        bu üç alanı açıkça seçer, dolayısıyla ek alanlar istemi şişirmez.
        """

        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
            source=self.source,
            category=self.category,
            risk_tags=tuple(sorted(self.risk_tags)),
            untrusted_output=self.untrusted_output,
            max_output_chars=self.max_output_chars,
            timeout_seconds=self.timeout_seconds,
        )

    def validate_input(self, arguments: Mapping[str, Any]) -> InputModelT:
        """Ham tool argümanlarını tool'a ait Pydantic model ile doğrular."""

        try:
            return self.input_model.model_validate(dict(arguments))
        except (TypeError, ValidationError) as exc:
            raise ToolInputValidationError(f"{self.name} için geçersiz input.") from exc

    @abstractmethod
    async def execute(self, tool_input: InputModelT) -> dict[str, Any]:
        """Doğrulanmış input ile tool davranışını çalıştırır."""
