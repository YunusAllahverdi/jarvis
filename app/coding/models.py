"""Kodlama döngüsünün yapılandırılmış veri modelleri.

Bu modül saf veri modelidir: hiçbir depoya yazmaz, hiçbir LLM çağırmaz,
hiçbir tool çalıştırmaz, hiçbir I/O yapmaz.

Tasarım ilkeleri:
- Adım ve sonuç vokabüleri karar katmanından ÖDÜNÇ ALINIR (`AgentAction`,
  `ActionOutcome`). Kodlama döngüsü ikinci bir "eylem" kavramı icat etmez;
  aksi hâlde iki ayrı yürütme sözleşmesi oluşur ve biri sıkılaştırıldığında
  diğeri geride kalırdı.
- GİZLİ AKIL YÜRÜTME SAKLANMAZ. `rationale` ve `summary` alanları kısa,
  olgusal ifadelerdir; düşünce dökümü değildir.
- Doğrulama sonucu bir MODEL YARGISI DEĞİL, bir ÇIKIŞ KODUDUR. `passed`
  alanı deterministik olarak türetilir.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.agent.models import ActionOutcome, AgentAction

MAX_STEPS = 8
"""Tek bir turda izin verilen maksimum adım sayısı.

Karar katmanının `MAX_ACTIONS` (4) sınırından bilinçli olarak daha geniştir:
bir kod değişikliği tipik olarak "oku → değiştir → oku → değiştir" gibi
birkaç adım sürer. Yine de sınırsız değildir — sınırsız plan, sınırsız tool
döngüsü demektir. Sınırı aşan plan kırpılmaz, REDDEDİLİR: bir planı sessizce
kısaltmak kullanıcının isteğini sessizce değiştirmektir.
"""

MAX_ITERATIONS = 3
"""Doğrulama başarısız olduğunda denenecek maksimum düzeltme turu.

Küçük tutulmasının sebebi maliyet değil dürüstlüktür: üç turda düzelmeyen
bir hata, çoğunlukla modelin yanlış anladığı bir hatadır ve dördüncü tur
onu doğru anlamayacaktır. Sınır dolduğunda döngü, düzeltmiş gibi yapmak
yerine "doğrulama hâlâ başarısız" der.
"""


class CodingStatus(StrEnum):
    """Bir kodlama döngüsü çalıştırmasının sonuç durumu."""

    COMPLETED = "completed"
    """Plan uygulandı ve doğrulama GEÇTİ."""

    APPLIED_UNVERIFIED = "applied_unverified"
    """Plan uygulandı ama doğrulama hiç çalışmadı (komut yok veya terminal kapalı).

    `COMPLETED`'dan ayrı tutulur: doğrulanmamış bir değişikliği başarılı
    saymak, kullanıcıya sahip olmadığımız bir güvence vermek olurdu.
    """

    VERIFICATION_FAILED = "verification_failed"
    """Değişiklikler uygulandı ama doğrulama tur sınırına rağmen geçmedi."""

    PENDING_APPROVAL = "pending_approval"
    """Bir adım kullanıcı onayı bekliyor; döngü DURDURULDU.

    Kısmen uygulanmış bir değişiklik geride kalmış olabilir; bu yüzden
    sonuçta uygulanmış adımlar da raporlanır ve geri alma noktası
    (checkpoint) kullanıcının elindedir.
    """

    NO_PLAN = "no_plan"
    """Planlayıcı uygulanabilir bir adım üretmedi."""

    FAILED = "failed"
    """Hiçbir adım başarılı olmadı ya da döngü kendi içinde hata verdi."""


class DiagnosisCategory(StrEnum):
    """Bir doğrulama başarısızlığının deterministik olarak tanınan türü.

    Kapalı bir küme olması bilinçlidir: teşhis bir MODEL YARGISI değil,
    çıktı üzerinde yürüyen bir örüntü eşlemesidir. Tanınmayan her şey
    `UNKNOWN`'dır — uydurulmuş bir kategori, yanlış bir düzeltmeye yol açar.
    """

    TEST_FAILURE = "test_failure"
    SYNTAX_ERROR = "syntax_error"
    IMPORT_ERROR = "import_error"
    TYPE_ERROR = "type_error"
    TIMEOUT = "timeout"
    COMMAND_REJECTED = "command_rejected"
    """Komut politikası veya izin katmanı çalıştırmayı engelledi.

    Bir kod hatasından KESİNLİKLE ayrı tutulur: burada düzeltilecek bir kod
    yoktur, düzeltilecek bir yapılandırma vardır. Bu ayrım olmadan döngü,
    var olmayan bir hatayı düzeltmeye çalışırdı.
    """

    UNKNOWN = "unknown"


class Diagnosis(BaseModel):
    """Başarısız bir doğrulamanın yapılandırılmış teşhisi."""

    model_config = ConfigDict(frozen=True)

    category: DiagnosisCategory
    summary: str = Field(max_length=300)
    """Neyin başarısız olduğunu anlatan kısa, olgusal ifade."""

    failing_tests: list[str] = Field(default_factory=list)
    """Çıktıdan çıkarılmış başarısız test kimlikleri."""

    file_hints: list[str] = Field(default_factory=list)
    """Çıktıda geçen dosya yolları — düzeltmenin nereye bakacağına dair ipucu.

    "İpucu" (hint) denmesi bilinçlidir: bunlar doğrulanmış hedefler değil,
    çıktıdan okunmuş adaylardır. Düzeltme planı bunları körü körüne
    kullanamaz, yalnızca hangi dosyayı okuyacağına karar verirken bakar.
    """

    excerpt: str = Field(default="", max_length=4000)
    """Çıktının sınırlanmış bir kesiti — düzeltme turuna veri olarak gider."""

    @property
    def is_actionable(self) -> bool:
        """Bu teşhis bir KOD düzeltmesiyle giderilebilir mi?

        Reddedilmiş bir komutta düzeltilecek kod yoktur; döngünün yeni bir
        plan üretmeye çalışması boşuna bir tur harcamak olurdu.
        """
        return self.category is not DiagnosisCategory.COMMAND_REJECTED


class TaskSpec(BaseModel):
    """Kullanıcı isteğinin yapılandırılmış hâli — "istek → task" adımı.

    Serbest metin bir isteği, üzerinde karar verilebilir alanlara ayırır:
    ne yapılacak, neden, hangi dosyalar ilgili ve BAŞARININ ÖLÇÜSÜ NE.
    Son alan en önemlisidir: doğrulama komutu olmadan döngü, işini bitirip
    bitirmediğini bilemez ve her cevap "sanırım oldu" olur.
    """

    goal: str = Field(min_length=1, max_length=500)
    rationale: str = Field(default="", max_length=300)
    """Bu görevin neden bu şekilde anlaşıldığına dair kısa, olgusal ifade."""

    files_of_interest: list[str] = Field(default_factory=list, max_length=20)
    verification_command: str | None = None
    """Değişikliğin doğrulanacağı komut (tipik olarak test paketi).

    None ise doğrulama YAPILAMAZ ve sonuç `APPLIED_UNVERIFIED` olur.
    Doğrulanamamış bir değişikliği başarılı saymamak bilinçlidir.
    """


class CodingPlan(BaseModel):
    """Bir turda uygulanacak adımlar."""

    steps: list[AgentAction] = Field(default_factory=list)
    reason: str = Field(default="", max_length=300)

    @property
    def has_steps(self) -> bool:
        return bool(self.steps)

    @property
    def requires_confirmation(self) -> bool:
        """Adımlardan en az biri onay gerektiriyorsa True.

        Doğrudan atanabilir bir alan DEĞİL, adımlardan türetilen bir
        özelliktir: atanabilir olsaydı, adımlarla tutarsız kalabilirdi.
        """
        return any(step.requires_confirmation for step in self.steps)


class Verification(BaseModel):
    """Doğrulama turunun sonucu.

    `passed`, bir modelin "geçti sanırım" demesi değil, çıkış kodunun
    sıfır olmasıdır. Bu ayrım döngünün tamamının güvenilirliğini taşır.
    """

    ran: bool = False
    """Doğrulama komutu gerçekten çalıştırılabildi mi?"""

    passed: bool = False
    command: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    diagnosis: Diagnosis | None = None
    skipped_reason: str | None = None
    """Doğrulama çalışmadıysa nedeni (komut yok, araç kayıtlı değil, onay bekliyor)."""


class Iteration(BaseModel):
    """Tek bir uygula-doğrula turu."""

    index: int = Field(ge=0)
    plan: CodingPlan
    outcomes: list[ActionOutcome] = Field(default_factory=list)
    verification: Verification | None = None
    repairs: Diagnosis | None = None
    """Bu tur bir düzeltme turuysa, düzeltilmeye çalışılan teşhis."""

    @property
    def applied_outcomes(self) -> list[ActionOutcome]:
        return [outcome for outcome in self.outcomes if outcome.success]


class CodingResult(BaseModel):
    """Bir kodlama döngüsü çalıştırmasının tam sonucu."""

    request: str
    session_id: str | None = None
    status: CodingStatus
    task: TaskSpec | None = None
    iterations: list[Iteration] = Field(default_factory=list)

    summary: str = ""
    """Ne yapıldığının deterministik açıklaması — "değişikliği açıkla" adımı.

    Bir LLM'e yazdırılmaz: yapılan işin dökümü zaten elimizdedir ve onu
    modele yeniden anlattırmak, uydurma riski karşılığında hiçbir şey
    kazandırmaz.
    """

    diff: str | None = None
    """Değişikliklerin git diff'i; üretilemezse None."""

    pending_approval_ids: list[str] = Field(default_factory=list)
    """Kullanıcının yanıtlaması gereken onay kayıtları."""

    error: str | None = None
    """Döngü ilerleyemediyse makine tarafından okunabilir kısa sebep."""

    review: object | None = None
    """Diff'in güvenlik/kalite incelemesi (`app.coding.review.CodeReview`).

    Tür burada `object`'tir çünkü bu modül saf veri modelidir ve inceleme
    katmanı Council'a bağımlıdır; buradan oraya bir import, veri modelini
    Council'a bağımlı hâle getirirdi.

    İnceleme BİR KAPI DEĞİLDİR: bulguları `status` alanını değiştirmez ve
    değişikliği geri almaz. İnceleyen de bir modeldir ve yanılabilir;
    yanılan bir modelin doğru bir değişikliği geri alabilmesi, kazanılan
    güvenceden büyük bir risk olurdu. Karar kullanıcınındır.
    """

    @property
    def ok(self) -> bool:
        return self.status is CodingStatus.COMPLETED

    @property
    def changed_files(self) -> list[str]:
        """Yazma araçlarının dokunduğu dosyalar (tekilleştirilmiş, sırayı korur).

        Argümanlardan okunur, diff'ten değil: diff üretilemese bile neyin
        değiştirilmeye çalışıldığı bilinmelidir.
        """
        seen: list[str] = []
        for iteration in self.iterations:
            for outcome in iteration.applied_outcomes:
                if outcome.tool_name not in _WRITING_TOOLS:
                    continue
                path = outcome.arguments.get("path")
                if isinstance(path, str) and path and path not in seen:
                    seen.append(path)
        return seen


_WRITING_TOOLS = frozenset({"write_file", "edit_file"})
"""Dosya değiştiren araçların adları.

Burada bir liste tutmak, `changed_files`'ın her araç sonucunu dosya
değişikliği sanmasını engeller: `read_file` da bir `path` argümanı alır.
"""
