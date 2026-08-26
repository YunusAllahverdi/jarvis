"""Ortam değişkenlerinden güvenli uygulama ayarları yüklenir."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_memory_db_path() -> str:
    """Platformdan bağımsız varsayılan bellek veritabanı yolu.

    Windows : %LOCALAPPDATA%/Jarvis/memory.db
    macOS   : ~/Library/Application Support/Jarvis/memory.db
    Linux   : ~/.local/share/jarvis/memory.db
    Fallback: ~/.jarvis/memory.db
    """
    import os
    import sys

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return str(base / "Jarvis" / "memory.db")
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Application Support" / "Jarvis" / "memory.db")
    # Linux ve diğer POSIX
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return str(base / "jarvis" / "memory.db")


class Settings(BaseSettings):
    """Jarvis uygulamasının merkezî ve doğrulanmış yapılandırması."""

    app_name: str = "Jarvis Local"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str | None = None
    ollama_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    system_prompt_file: str | None = None
    # Kaç konuşma mesajının LLM bağlamına dahil edileceği (system mesajı hariç).
    # Sıfır veya negatif değer sınırı devre dışı bırakır.
    conversation_context_limit: int = Field(default=40, ge=0)
    # Kalıcı bellek veritabanının yolu.
    # Boş bırakılırsa platforma özgü kullanıcı veri dizini kullanılır.
    memory_db_path: str = Field(default_factory=_default_memory_db_path)

    # Agent karar katmanının hangi politikayı kullanacağı.
    # "rule_based": deterministik, LLM çağırmaz (varsayılan).
    # "llm"       : kararı LLM'e verdirir, çıktıyı deterministik doğrular.
    # Varsayılanın deterministik olması bilinçlidir: LLM politikası tur başına
    # ek bir sağlayıcı çağrısı demektir ve açıkça seçilmelidir.
    agent_decision_policy: Literal["rule_based", "llm"] = "rule_based"

    # Karar katmanının sohbet akışına bağlanıp bağlanmayacağı.
    # Kapatıldığında agent yalnızca kendi API'si üzerinden kullanılabilir;
    # sohbet akışı bu bileşeni hiç çağırmaz.
    agent_chat_integration: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="JARVIS_",
        extra="ignore",
    )

    @field_validator("ollama_base_url")
    @classmethod
    def normalize_ollama_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("ollama_base_url must start with http:// or https://")
        return normalized

    @field_validator("ollama_model")
    @classmethod
    def normalize_ollama_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


@lru_cache
def get_settings() -> Settings:
    """Ayarları bir süreç boyunca tek kez yükler."""

    return Settings()
