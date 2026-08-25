"""Dosyadan veya paket varsayılanından system prompt yükleme."""

from pathlib import Path


class PromptLoadError(RuntimeError):
    """System prompt okunamadığında oluşur."""


class SystemPromptLoader:
    """Jarvis system prompt'unu uygulama kodundan ayrı tutar."""

    def __init__(self, prompt_file: str | None = None) -> None:
        self._prompt_file = Path(prompt_file) if prompt_file else None

    def load(self) -> str:
        """Yapılandırılmış dosyayı veya paket varsayılanını okur."""

        prompt_path = self._prompt_file or Path(__file__).parents[1] / "prompts" / "jarvis.txt"
        try:
            prompt = prompt_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PromptLoadError(f"System prompt okunamadı: {prompt_path}") from exc

        if not prompt:
            raise PromptLoadError(f"System prompt boş olamaz: {prompt_path}")
        return prompt
