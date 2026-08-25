"""Ortam değişkenlerinden güvenli uygulama ayarları yüklenir."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
