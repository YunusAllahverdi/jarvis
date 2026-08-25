"""System prompt sağlayıcıları: soyut sözleşme ve dosya tabanlı implementasyon."""

from pathlib import Path
from typing import Protocol, runtime_checkable


class PromptLoadError(RuntimeError):
    """System prompt okunamadığında oluşur."""


@runtime_checkable
class PromptProvider(Protocol):
    """System prompt sağlayıcıları için kararlı arayüz.

    İleride şunlara yer bırakır:
    - Kişilik profilleri
    - Kullanıcı profil bağlamı
    - Görev özelinde talimatlar
    - Bellek katmanından gelen dinamik bağlam
    - Çalışma zamanı dünyası/durum bilgisi
    """

    def load(self) -> str:
        """Aktif system prompt'unu döndürür."""
        ...


class SystemPromptLoader:
    """Jarvis system prompt'unu dosyadan yükler ve önbellekte tutar.

    PromptProvider Protocol'ünü implemente eder.
    Prompt bir kez yüklenir ve uygulama yeniden başlatılana kadar önbellekte kalır.
    """

    def __init__(self, prompt_file: str | None = None) -> None:
        self._prompt_file = Path(prompt_file) if prompt_file else None
        self._cached_prompt: str | None = None

    def load(self) -> str:
        """Önbellekteki promptu veya dosyadan yüklenen promptu döndürür."""

        if self._cached_prompt is not None:
            return self._cached_prompt

        prompt_path = self._prompt_file or Path(__file__).parents[1] / "prompts" / "jarvis.txt"
        try:
            prompt = prompt_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PromptLoadError(f"System prompt okunamadı: {prompt_path}") from exc

        if not prompt:
            raise PromptLoadError(f"System prompt boş olamaz: {prompt_path}")

        self._cached_prompt = prompt
        return self._cached_prompt

    def invalidate_cache(self) -> None:
        """Önbelleği temizler; bir sonraki load() çağrısında dosya yeniden okunur.

        Prompt dosyası çalışma zamanında değiştirildiğinde kullanılabilir.
        """
        self._cached_prompt = None
