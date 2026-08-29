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

    # ------------------------------------------------------------------
    # Ajanın dosya okuyabileceği çalışma kökü.
    # BOŞ BIRAKILIRSA dosya araçları hiç kaydedilmez ve ajanın dosya sistemi
    # yeteneği hiç var olmaz. Varsayılanın kapalı olması bilinçlidir: dosya
    # erişimi kullanıcının açıkça verdiği bir yetkidir.
    workspace_root: str = ""

    # Denetim kaydı. Boş bırakılırsa bellek veritabanının yanına yazılır.
    # Kalıcıdır: onay kayıtlarının aksine, ne yapıldığının izi yeniden
    # başlatmayı atlatmalıdır.
    audit_db_path: str = ""

    # Kullanıcı onayı
    # Bir onay isteğinin geçerli kalma süresi. Kısa tutulur: onay, belirli
    # bir andaki duruma verilmiş bir karardır; dakikalar sonra dünya
    # değişmiş olabilir.
    approval_ttl_seconds: float = Field(default=300.0, gt=0, le=3600)
    # Aynı anda bekleyebilecek en fazla onay isteği.
    approval_max_pending: int = Field(default=50, ge=1, le=500)

    # LLM Council
    # ------------------------------------------------------------------
    # VARSAYILAN KAPALI. Council tur başına N+N+1 LLM çağrısı demektir ve
    # hiçbir mevcut kurulumda `council_models` dolu değildir. Kapalıyken
    # sistemin davranışı bit düzeyinde eskisi gibidir.
    council_enabled: bool = False

    # Üye model adları. Ortam değişkeninden JSON olarak verilir:
    #   JARVIS_COUNCIL_MODELS='["llama3.1","qwen2.5","mistral"]'
    # Her ad için ayrı bir sağlayıcı örneği kurulur; Council model adını
    # hiç görmez (yalnızca opaque üye kimlikleri).
    council_models: list[str] = Field(default_factory=list)

    # Sentezi üretecek model. Boş bırakılırsa ilk üye kullanılır.
    # Üyelerden biriyle aynıysa aynı sağlayıcı örneği yeniden kullanılır.
    council_chairman_model: str | None = None

    council_max_members: int = Field(default=4, ge=1, le=8)
    council_min_candidates: int = Field(default=2, ge=1, le=8)
    council_review_enabled: bool = True

    council_member_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    council_total_timeout_seconds: float = Field(default=180.0, gt=0, le=1800)
    council_max_concurrency: int = Field(default=3, ge=1, le=8)

    # Prompt'a gömülürken uygulanan deterministik kısaltma sınırları.
    # Yalnızca MODEL ÜRETİMİ metinlere uygulanır; kullanıcının isteği asla
    # kısaltılmaz.
    council_max_candidate_chars: int = Field(default=4000, ge=200, le=50_000)
    council_max_review_chars: int = Field(default=2000, ge=200, le=50_000)

    @field_validator("council_models")
    @classmethod
    def normalize_council_models(cls, value: list[str]) -> list[str]:
        """Model adlarını temizler ve tekrarları kaldırır (sırayı korur).

        Aynı modeli iki kez eklemek iki bağımsız görüş üretmez; sessizce
        tekilleştirmek, yanlış bir çeşitlilik izleniminden daha dürüsttür.
        """
        seen: list[str] = []
        for raw in value:
            name = raw.strip()
            if name and name not in seen:
                seen.append(name)
        return seen

    @field_validator("council_chairman_model")
    @classmethod
    def normalize_chairman_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

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
