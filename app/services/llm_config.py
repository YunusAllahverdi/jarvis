"""Çalışma zamanında değiştirilebilir LLM sağlayıcı yapılandırması.

Sağlayıcıyı değiştirmek için uygulamayı yeniden başlatmak gerekmesin diye
iki parça vardır:

- `LLMConfigStore` — seçilen sağlayıcıyı, adresi, modeli ve anahtarı saklar.
- `SwitchableProvider` — `LLMProvider` arayüzünü uygulayan ince bir
  sarmalayıcı. Sohbet, bellek çıkarımı ve ajan hep BU nesneyi tutar;
  yapılandırma değiştiğinde içindeki gerçek sağlayıcı değişir. Aksi hâlde
  her tüketiciyi tek tek yeniden bağlamak gerekirdi ve biri unutulduğunda
  sistemin bir yarısı eski sağlayıcıda kalırdı.

API anahtarı hakkında: veritabanında düz metin olarak durur. Bu, `.env`
dosyasında durmasından daha kötü değildir — ikisi de aynı makinede, aynı
kullanıcının okuyabildiği yerdedir. Ama anahtar **hiçbir zaman geri
okunmaz**: dışarıya yalnızca "tanımlı mı" bilgisi verilir.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, Field, ValidationError

from app.adapters.llm.anthropic import (
    DEFAULT_BASE_URL as ANTHROPIC_BASE_URL,
    AnthropicProvider,
)
from app.adapters.llm.base import LLMProvider
from app.adapters.llm.ollama import OllamaProvider
from app.adapters.llm.openai_compatible import OpenAICompatibleProvider
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition

logger = logging.getLogger(__name__)


class LLMProviderKind(StrEnum):
    """Desteklenen sağlayıcı türleri."""

    OLLAMA = "ollama"
    """Yerel Ollama sunucusu; anahtar gerektirmez."""

    OPENAI_COMPATIBLE = "openai_compatible"
    """OpenAI sohbet sözleşmesini konuşan her servis."""

    ANTHROPIC = "anthropic"
    """Anthropic Messages API.

    Ayrı bir tür olması gerekti: Anthropic OpenAI sözleşmesini konuşmaz —
    farklı uç nokta, farklı kimlik başlığı, system mesajının ayrı alanda
    taşınması ve blok tabanlı yanıt biçimi. `openai_compatible` altına
    sıkıştırılsaydı hiçbir istek çalışmazdı.
    """


class LLMConfig(BaseModel):
    """Sağlayıcı yapılandırmasının anahtar İÇERMEYEN görünümü.

    Anahtar bilerek bu modelde yoktur: yanlışlıkla loglanacak ya da API
    yanıtına konacak bir yer bırakmamak için.
    """

    kind: LLMProviderKind = LLMProviderKind.OLLAMA
    base_url: str = Field(default="http://127.0.0.1:11434", max_length=500)
    model: str | None = Field(default=None, max_length=200)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    has_api_key: bool = False


def build_llm_provider(
    *,
    kind: LLMProviderKind,
    base_url: str,
    model: str | None,
    api_key: str | None = None,
    timeout_seconds: float = 60.0,
) -> LLMProvider:
    """Yapılandırma alanlarından gerçek bir sağlayıcı kurar — tek tanım noktası.

    Hem tekil sağlayıcı yapılandırması hem de Council'ın üye başına
    yapılandırması buradan geçer. İki kopya bırakılsaydı, yeni bir sağlayıcı
    türü eklendiğinde biri güncellenip diğeri unutulabilirdi ve Council
    sessizce eski türlerle sınırlı kalırdı.

    Anahtar doğrudan sağlayıcıya verilir, hiçbir yere kopyalanmaz.
    """
    if kind is LLMProviderKind.ANTHROPIC:
        return AnthropicProvider(
            base_url=base_url or ANTHROPIC_BASE_URL,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    if kind is LLMProviderKind.OPENAI_COMPATIBLE:
        return OpenAICompatibleProvider(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    return OllamaProvider(
        base_url=base_url, model=model, timeout_seconds=timeout_seconds
    )


_DDL_CONFIG = """
CREATE TABLE IF NOT EXISTS llm_config (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    kind            TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    model           TEXT,
    timeout_seconds REAL NOT NULL DEFAULT 60.0,
    api_key         TEXT
);
"""


class LLMConfigStore:
    """Sağlayıcı yapılandırmasını kalıcı olarak saklar."""

    def __init__(self, db_path: str, *, default: LLMConfig | None = None) -> None:
        """
        Args:
            db_path: SQLite dosyasının yolu.
            default: Kayıt yoksa kullanılacak başlangıç yapılandırması.
        """
        self._db_path = db_path
        self._default = default or LLMConfig()
        self._lock = RLock()
        self._ensure_dir()
        self._initialize_schema()

    def _ensure_dir(self) -> None:
        if self._db_path == ":memory:":
            return
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_DDL_CONFIG)

    def get(self) -> LLMConfig:
        """Anahtarsız yapılandırmayı döndürür; kayıt yoksa varsayılanı.

        BOZUK BİR KAYIT UYGULAMAYI ÇÖKERTMEZ. Bu satır bir başka sürüm
        tarafından yazılmış olabilir ve o sürüm burada tanınmayan bir
        sağlayıcı türü kullanıyor olabilir — veritabanı sürümler arasında
        paylaşılıyor. Tanınmayan bir değerde istisna fırlatmak, uygulamanın
        açılışta ölmesi demekti: kullanıcı ayarı DÜZELTEBİLECEĞİ paneli bile
        açamazdı, çünkü sunucu hiç ayağa kalkmıyordu.

        Bu yüzden tanınmayan tür varsayılana düşer ve durum loglanır.
        Kullanıcı panelden geçerli bir sağlayıcı seçtiğinde satır düzelir.
        """
        row = self._row()
        if row is None:
            return self._default.model_copy()

        try:
            kind = LLMProviderKind(row["kind"])
        except ValueError:
            logger.warning(
                "llm_config_unknown_kind",
                extra={"stored_kind": str(row["kind"])[:64]},
            )
            kind = self._default.kind

        try:
            return LLMConfig(
                kind=kind,
                base_url=row["base_url"],
                model=row["model"],
                timeout_seconds=row["timeout_seconds"],
                has_api_key=bool(row["api_key"]),
            )
        except ValidationError:
            # Alanların kendisi de bozuk olabilir (ör. negatif timeout).
            # Aynı gerekçe: açılışı engellemek yerine varsayılana dönülür.
            logger.warning("llm_config_row_invalid")
            return self._default.model_copy()

    def update(
        self,
        *,
        kind: LLMProviderKind,
        base_url: str,
        model: str | None,
        timeout_seconds: float = 60.0,
        api_key: str | None = None,
        clear_api_key: bool = False,
    ) -> LLMConfig:
        """Yapılandırmayı günceller.

        Args:
            api_key: Yeni anahtar. **None verilirse mevcut anahtar
                korunur** — panel anahtarı geri okuyamadığı için, her
                kaydetmede yeniden girilmesini istemek anlamsız olurdu.
            clear_api_key: Anahtarı silmek için açıkça kullanılır.
        """
        with self._lock:
            existing = self._row()
            if clear_api_key:
                stored_key: str | None = None
            elif api_key is not None:
                stored_key = api_key.strip() or None
            else:
                stored_key = existing["api_key"] if existing else None

            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO llm_config (id, kind, base_url, model, timeout_seconds, api_key)
                    VALUES (1, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind = excluded.kind,
                        base_url = excluded.base_url,
                        model = excluded.model,
                        timeout_seconds = excluded.timeout_seconds,
                        api_key = excluded.api_key
                    """,
                    (str(kind), base_url, model, timeout_seconds, stored_key),
                )
        return self.get()

    def build_provider(self) -> LLMProvider:
        """Kayıtlı yapılandırmadan gerçek bir sağlayıcı kurar.

        Anahtar yalnızca burada okunur ve doğrudan sağlayıcıya verilir;
        başka hiçbir yere kopyalanmaz.
        """
        row = self._row()
        config = self.get()
        return build_llm_provider(
            kind=config.kind,
            base_url=config.base_url,
            model=config.model,
            api_key=row["api_key"] if row else None,
            timeout_seconds=config.timeout_seconds,
        )

    def _row(self) -> sqlite3.Row | None:
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT * FROM llm_config WHERE id = 1").fetchone()


class SwitchableProvider:
    """Altındaki sağlayıcıyı değiştirebilen `LLMProvider` sarmalayıcısı.

    Tüketiciler (sohbet, bellek çıkarımı, ajan) bu nesneyi tutar. Böylece
    sağlayıcı değiştiğinde hepsi aynı anda yeni sağlayıcıya geçer; birinin
    eski sağlayıcıda kalması mümkün olmaz.
    """

    def __init__(self, delegate: LLMProvider) -> None:
        self._delegate = delegate
        self._lock = RLock()

    @property
    def delegate(self) -> LLMProvider:
        """Şu an kullanılan gerçek sağlayıcı."""

        with self._lock:
            return self._delegate

    async def switch(self, delegate: LLMProvider) -> None:
        """Sağlayıcıyı değiştirir ve eskisini düzgünce kapatır.

        Eski sağlayıcı kapatılmazsa açık HTTP bağlantıları sızar; her
        yapılandırma değişikliğinde bir tane daha birikirdi.
        """
        with self._lock:
            previous = self._delegate
            self._delegate = delegate

        closer = getattr(previous, "aclose", None)
        if closer is not None:
            try:
                await closer()
            except Exception:  # noqa: BLE001
                logger.exception("llm_provider_close_failed")

    async def aclose(self) -> None:
        """Altındaki sağlayıcıyı kapatır."""

        closer = getattr(self.delegate, "aclose", None)
        if closer is not None:
            await closer()

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        return await self.delegate.generate(messages)

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        return await self.delegate.generate_with_tools(messages, tools)
