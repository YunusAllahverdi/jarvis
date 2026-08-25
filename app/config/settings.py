"""Ortam değişkenlerinden güvenli uygulama ayarları yüklenir."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Jarvis uygulamasının merkezî ve doğrulanmış yapılandırması."""

    app_name: str = "Jarvis Local"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="JARVIS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Ayarları bir süreç boyunca tek kez yükler."""

    return Settings()
