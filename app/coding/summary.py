"""Yapılan işin DETERMİNİSTİK açıklaması.

Bir LLM'e yazdırılmamasının sebebi maliyet değil, dürüstlüktür: ne yapıldığı
zaten elimizdedir — hangi araç, hangi dosya, hangi doğrulama, hangi sonuç.
Bunu modele yeniden anlattırmak, uydurma riski karşılığında hiçbir şey
kazandırmaz. Model "testleri düzelttim" diyebilirdi; bu metin yalnızca
gerçekten olanı yazar.

Aynı gerekçe `app.memory.experience_builder` ve `app.tools.builtin.project`
için de geçerlidir: elde veri varken onu modele tarif ettirmek yerine
doğrudan biçimlendirmek proje boyunca izlenen desendir.

Metin KULLANICIYA gösterilmek üzere Türkçe üretilir; sohbet akışına veri
olarak verildiğinde nihai cevabı yine normal cevap üretimi yazar.
"""

from __future__ import annotations

from app.coding.models import CodingResult, CodingStatus, Iteration

_STATUS_HEADLINE: dict[CodingStatus, str] = {
    CodingStatus.COMPLETED: "Değişiklik uygulandı ve doğrulama geçti.",
    CodingStatus.APPLIED_UNVERIFIED: (
        "Değişiklik uygulandı, ancak doğrulama çalıştırılamadı."
    ),
    CodingStatus.VERIFICATION_FAILED: (
        "Değişiklik uygulandı, ancak doğrulama hâlâ başarısız."
    ),
    CodingStatus.PENDING_APPROVAL: (
        "Bir adım kullanıcı onayı bekliyor; döngü durduruldu."
    ),
    CodingStatus.NO_PLAN: "Uygulanabilir bir plan üretilemedi.",
    CodingStatus.FAILED: "Kodlama döngüsü ilerleyemedi.",
}


def build_summary(result: CodingResult) -> str:
    """Sonucu okunabilir, olgusal bir açıklamaya çevirir.

    Yalnızca `result` içindeki verilerden üretilir; hiçbir yeni bilgi
    icat edilmez ve hiçbir tahmin yürütülmez.
    """
    lines: list[str] = [_STATUS_HEADLINE.get(result.status, "Sonuç belirsiz.")]

    if result.task is not None and result.task.goal:
        lines.append(f"Hedef: {result.task.goal}")

    changed = result.changed_files
    if changed:
        lines.append("Değiştirilen dosyalar:")
        lines.extend(f"  - {path}" for path in changed)
    elif result.status in (CodingStatus.COMPLETED, CodingStatus.APPLIED_UNVERIFIED):
        # Doğrulama geçmiş ama hiçbir dosya değişmemişse bu, kullanıcının
        # bilmesi gereken bir olgudur: istenen değişiklik zaten mevcut
        # olabilir ya da plan yalnızca okuma adımlarından oluşmuştur.
        lines.append("Hiçbir dosya değiştirilmedi.")

    steps = _step_lines(result.iterations)
    if steps:
        lines.append("Yapılan adımlar:")
        lines.extend(f"  {line}" for line in steps)

    lines.extend(_verification_lines(result))
    lines.extend(_review_lines(result))

    if result.pending_approval_ids:
        lines.append(
            f"Onay bekleyen istek sayısı: {len(result.pending_approval_ids)}."
        )
    if result.error:
        lines.append(f"Hata: {result.error}")

    return "\n".join(lines)


def _step_lines(iterations: list[Iteration]) -> list[str]:
    """Her turun adımlarını tek tek, olduğu gibi listeler.

    Başarısız adımlar da yazılır: yalnızca başarılı olanları göstermek,
    döngünün gerçekte ne yaşadığını gizlemek olurdu.
    """
    lines: list[str] = []
    for iteration in iterations:
        if len(iterations) > 1:
            label = (
                f"Tur {iteration.index + 1}"
                if iteration.repairs is None
                else f"Tur {iteration.index + 1} (düzeltme: {iteration.repairs.summary})"
            )
            lines.append(label)
        for outcome in iteration.outcomes:
            if outcome.skipped:
                mark = "atlandı"
            elif outcome.success:
                mark = "tamam"
            else:
                mark = f"başarısız ({outcome.error_code or 'bilinmiyor'})"
            target = outcome.arguments.get("path") or outcome.arguments.get("command")
            suffix = f" [{target}]" if isinstance(target, str) and target else ""
            lines.append(f"- {outcome.tool_name}{suffix}: {mark}")
    return lines


def _review_lines(result: CodingResult) -> list[str]:
    """Diff incelemesinin bulgularını anlatır.

    İnceleme yapılmadıysa bu AÇIKÇA söylenir. Sessiz kalmak, incelenmemiş
    bir değişikliği incelenmiş gibi göstermek olurdu — döngünün doğrulama
    konusundaki tutumunun aynısı.
    """
    review = result.review
    if review is None:
        return []

    ran = getattr(review, "ran", False)
    if not ran:
        reason = getattr(review, "skipped_reason", None)
        return [f"Kod incelemesi yapılmadı: {reason or 'sebep bilinmiyor'}"]

    lines = [
        f"Kod incelemesi: {getattr(review, 'reviewer_count', 0)} inceleyici."
    ]
    if getattr(review, "diff_truncated", False):
        lines.append("  Uyarı: diff kırpıldı, inceleme değişikliğin tamamını görmedi.")
    findings = str(getattr(review, "findings", "") or "").strip()
    if findings:
        lines.extend(f"  {line}" for line in findings.splitlines())
    return lines


def _verification_lines(result: CodingResult) -> list[str]:
    """Son turun doğrulama sonucunu anlatır.

    Yalnızca SON tur raporlanır: ara turların başarısızlığı zaten adım
    dökümünde görünür ve nihai durumu belirleyen son doğrulamadır.
    """
    verification = next(
        (
            iteration.verification
            for iteration in reversed(result.iterations)
            if iteration.verification is not None
        ),
        None,
    )
    if verification is None:
        return []

    if not verification.ran:
        return [f"Doğrulama çalışmadı: {verification.skipped_reason or 'sebep bilinmiyor'}"]

    lines = [f"Doğrulama komutu: {verification.command}"]
    if verification.passed:
        lines.append("Doğrulama sonucu: geçti.")
        return lines

    lines.append(
        "Doğrulama sonucu: başarısız"
        + (" (zaman aşımı)." if verification.timed_out else f" (çıkış kodu {verification.exit_code}).")
    )
    diagnosis = verification.diagnosis
    if diagnosis is not None:
        lines.append(f"Teşhis: {diagnosis.summary}")
        if diagnosis.failing_tests:
            lines.append("Başarısız testler:")
            lines.extend(f"  - {test}" for test in diagnosis.failing_tests)
    return lines
