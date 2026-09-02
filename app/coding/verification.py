"""Değişikliğin gerçekten çalıştığının DOĞRULANMASI.

Bu, kodlama döngüsünü tek seferlik bir plan yürütücüsünden ayıran adımdır:
plan uygulandıktan sonra "oldu mu?" sorusu bir modele değil, bir çıkış
koduna sorulur.

Mimari kurallar:
- Komut, ayrı bir süreç mekanizmasıyla DEĞİL, mevcut `run_command` aracıyla
  ve mevcut `ToolExecutor` sınırından geçerek çalıştırılır. Böylece komut
  politikası, kabuksuzluk, ortam yalıtımı, zaman aşımı ve denetim kaydı
  olduğu gibi geçerli olur. İkinci bir çalıştırma yolu açılsaydı, terminali
  kapalı tutan kullanıcı yine de komut çalıştırılabilir hâle gelirdi.
- Doğrulama aracı kayıtlı değilse (terminal kapalı) doğrulama ÇALIŞMAZ ve
  bu bir hata değildir: sonuç "doğrulanmadı" olur, "başarılı" değil.
- `passed` yalnızca çıkış kodu 0 olduğunda True'dur. Çıktının içeriğine
  bakılmaz — "her şey yolunda görünüyor" diyen bir çıktı, sıfır olmayan bir
  çıkış kodunu geçersiz kılmaz.
"""

from __future__ import annotations

import logging

from app.coding.diagnosis import diagnose
from app.coding.models import Verification
from app.core.chat import ToolCall
from app.tools.builtin.terminal import RUN_COMMAND_TOOL_NAME
from app.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

SKIP_NO_COMMAND = "Doğrulama komutu tanımlı değil."
SKIP_TOOL_MISSING = "Komut çalıştırma aracı bu oturumda kayıtlı değil."
SKIP_NEEDS_APPROVAL = "Doğrulama komutu kullanıcı onayı bekliyor."


class Verifier:
    """Doğrulama komutunu çalıştırır ve sonucu deterministik olarak yorumlar."""

    def __init__(
        self,
        *,
        tool_executor: ToolExecutor,
        timeout_seconds: float = 120.0,
    ) -> None:
        """
        Args:
            tool_executor: Komutun geçeceği tek yürütme sınırı — döngünün
                diğer adımlarıyla AYNI örnek olmalıdır.
            timeout_seconds: İstenecek zaman aşımı. Aracın kendi üst sınırı
                bunu yine de kısabilir; model gibi bu katman da kendi
                sınırını yükseltemez.
        """
        self._tool_executor = tool_executor
        self._timeout_seconds = timeout_seconds

    async def verify(self, command: str | None, *, session_id: str | None = None) -> Verification:
        """Komutu çalıştırıp yapılandırılmış bir doğrulama sonucu üretir.

        Hiçbir zaman istisna fırlatmaz. Komut yoksa, araç kayıtlı değilse
        veya onay bekliyorsa `ran=False` döner — bunların hiçbiri başarı
        sayılmaz.
        """
        if not command:
            return Verification(ran=False, skipped_reason=SKIP_NO_COMMAND)

        try:
            result = await self._tool_executor.execute(
                ToolCall(
                    name=RUN_COMMAND_TOOL_NAME,
                    arguments={"command": command, "timeout_seconds": self._timeout_seconds},
                ),
                session_id=session_id,
            )
        except Exception:  # noqa: BLE001
            # ToolExecutor sözleşmesi gereği buraya düşülmemeli; yine de bir
            # savunma katmanı bırakıldı — doğrulamanın çökmesi, döngünün
            # sonucunu kaybetmesi anlamına gelmemeli.
            logger.exception("coding_verification_unexpected_error")
            return Verification(
                ran=False, command=command, skipped_reason="Doğrulama çalıştırılamadı."
            )

        if result.requires_approval:
            # Onay bekleyen bir doğrulama BAŞARISIZLIK DEĞİLDİR: çalıştırılmamış
            # bir testin sonucu yoktur. Döngü bunu "doğrulanmadı" olarak okur.
            return Verification(
                ran=False, command=command, skipped_reason=SKIP_NEEDS_APPROVAL
            )

        if not result.success:
            reason = (
                SKIP_TOOL_MISSING
                if result.error_code == "unknown_tool"
                else result.error_message or "Doğrulama komutu çalıştırılamadı."
            )
            return Verification(
                ran=False,
                command=command,
                skipped_reason=reason,
                diagnosis=diagnose(rejection_message=reason),
            )

        data = result.data or {}
        exit_code = data.get("exit_code")
        timed_out = bool(data.get("timed_out"))
        passed = exit_code == 0 and not timed_out

        verification = Verification(
            ran=True,
            passed=passed,
            command=command,
            exit_code=exit_code if isinstance(exit_code, int) else None,
            timed_out=timed_out,
            diagnosis=(
                None
                if passed
                else diagnose(
                    stdout=str(data.get("stdout", "")),
                    stderr=str(data.get("stderr", "")),
                    exit_code=exit_code if isinstance(exit_code, int) else None,
                    timed_out=timed_out,
                )
            ),
        )
        logger.info(
            "coding_verification_finished",
            extra={
                "passed": passed,
                "exit_code": verification.exit_code,
                "timed_out": timed_out,
                "category": (
                    verification.diagnosis.category.value if verification.diagnosis else None
                ),
                "session_id": session_id,
            },
        )
        return verification
