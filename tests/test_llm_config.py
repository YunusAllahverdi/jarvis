"""Çalışma zamanı LLM yapılandırması ve değiştirilebilir sağlayıcı.

Kapsam:
 1. Kayıt yokken varsayılan yapılandırma döner
 2. Güncelleme kalıcıdır ve yeniden başlatmayı atlatır
 3. Anahtar GERİ OKUNMAZ; yalnızca "tanımlı mı" bilgisi verilir
 4. Anahtar verilmeden kaydetmek mevcut anahtarı korur
 5. Anahtar açıkça silinebilir
 6. Yapılandırmadan doğru sağlayıcı türü kurulur
 7. Anahtar sağlayıcıya aktarılır
 8. Sarmalayıcı çağrıları altındaki sağlayıcıya iletir
 9. Değişim tüm tüketiciler için aynı anda geçerli olur
10. Değişimde eski sağlayıcı kapatılır
11. Eski sağlayıcı kapanırken hata verse bile değişim tamamlanır
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.adapters.llm.ollama import OllamaProvider
from app.adapters.llm.openai_compatible import OpenAICompatibleProvider
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.services.llm_config import (
    LLMConfigStore,
    LLMProviderKind,
    SwitchableProvider,
)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


@pytest.fixture()
def store(tmp_path: Path) -> LLMConfigStore:
    return LLMConfigStore(str(tmp_path / "jarvis.db"))


class _FakeProvider:
    """Çağrıldığını ve kapatıldığını kaydeden sahte sağlayıcı."""

    def __init__(self, name: str, *, fail_on_close: bool = False) -> None:
        self.name = name
        self.closed = False
        self._fail_on_close = fail_on_close

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        return self.name

    async def generate_with_tools(
        self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]
    ) -> LLMResponse:
        return LLMResponse(content=self.name)

    async def aclose(self) -> None:
        self.closed = True
        if self._fail_on_close:
            raise RuntimeError("kapatılamadı")


# ---------------------------------------------------------------------------
# 1-5. Yapılandırma deposu
# ---------------------------------------------------------------------------

def test_default_config_when_nothing_saved(store: LLMConfigStore) -> None:
    """Hiç kaydedilmemişken makul bir varsayılan dönmeli."""
    config = store.get()

    assert config.kind is LLMProviderKind.OLLAMA
    assert config.has_api_key is False


def test_update_survives_a_new_store(tmp_path: Path) -> None:
    """Yapılandırma kalıcı olmalı."""
    db = str(tmp_path / "jarvis.db")
    LLMConfigStore(db).update(
        kind=LLMProviderKind.OPENAI_COMPATIBLE,
        base_url="https://saglayici.example/v1",
        model="bir-model",
        api_key="sk-gizli",
    )

    config = LLMConfigStore(db).get()

    assert config.kind is LLMProviderKind.OPENAI_COMPATIBLE
    assert config.model == "bir-model"


def test_the_key_is_never_read_back(store: LLMConfigStore) -> None:
    """Anahtar dışarıya çıkmamalı; yalnızca varlığı bildirilmeli."""
    config = store.update(
        kind=LLMProviderKind.OPENAI_COMPATIBLE,
        base_url="https://saglayici.example/v1",
        model="m",
        api_key="sk-cok-gizli",
    )

    assert config.has_api_key is True
    assert "sk-cok-gizli" not in config.model_dump_json()
    assert not hasattr(config, "api_key")


def test_saving_without_a_key_keeps_the_existing_one(store: LLMConfigStore) -> None:
    """Panel anahtarı geri okuyamıyor; her kaydetmede yeniden istememeli."""
    store.update(
        kind=LLMProviderKind.OPENAI_COMPATIBLE,
        base_url="https://saglayici.example/v1",
        model="m",
        api_key="sk-gizli",
    )

    config = store.update(
        kind=LLMProviderKind.OPENAI_COMPATIBLE,
        base_url="https://saglayici.example/v1",
        model="baska-model",
        api_key=None,
    )

    assert config.has_api_key is True
    assert config.model == "baska-model"


def test_the_key_can_be_cleared_explicitly(store: LLMConfigStore) -> None:
    """Anahtar silinebilmeli, ama bunun açıkça istenmesi gerekmeli."""
    store.update(
        kind=LLMProviderKind.OPENAI_COMPATIBLE,
        base_url="https://saglayici.example/v1",
        model="m",
        api_key="sk-gizli",
    )

    config = store.update(
        kind=LLMProviderKind.OLLAMA,
        base_url="http://127.0.0.1:11434",
        model="gemma3",
        clear_api_key=True,
    )

    assert config.has_api_key is False


# ---------------------------------------------------------------------------
# 6-7. Sağlayıcı kurulumu
# ---------------------------------------------------------------------------

def test_the_right_provider_type_is_built(store: LLMConfigStore) -> None:
    """Seçilen türe göre doğru sınıf kurulmalı."""
    store.update(
        kind=LLMProviderKind.OLLAMA, base_url="http://127.0.0.1:11434", model="gemma3"
    )
    assert isinstance(store.build_provider(), OllamaProvider)

    store.update(
        kind=LLMProviderKind.OPENAI_COMPATIBLE,
        base_url="https://saglayici.example/v1",
        model="m",
    )
    assert isinstance(store.build_provider(), OpenAICompatibleProvider)


def test_the_key_reaches_the_provider(store: LLMConfigStore) -> None:
    """Anahtar yalnızca sağlayıcıya gitmeli — ve gerçekten gitmeli."""
    store.update(
        kind=LLMProviderKind.OPENAI_COMPATIBLE,
        base_url="https://saglayici.example/v1",
        model="m",
        api_key="sk-gizli",
    )

    provider = store.build_provider()

    assert provider._client.headers["Authorization"] == "Bearer sk-gizli"


# ---------------------------------------------------------------------------
# 8-11. Değiştirilebilir sarmalayıcı
# ---------------------------------------------------------------------------

def test_calls_reach_the_delegate() -> None:
    """Sarmalayıcı çağrıları altındaki sağlayıcıya iletmeli."""
    provider = SwitchableProvider(_FakeProvider("ilk"))

    assert _run(provider.generate([ChatMessage(role="user", content="x")])) == "ilk"


def test_switching_applies_to_every_consumer() -> None:
    """Aynı nesneyi tutan herkes yeni sağlayıcıya geçmeli.

    Tüketicileri tek tek yeniden bağlasaydık biri unutulduğunda sistemin
    bir yarısı eski sağlayıcıda kalırdı.
    """
    switchable = SwitchableProvider(_FakeProvider("ilk"))
    # İki ayrı tüketici, aynı nesneyi tutuyor.
    chat_side = switchable
    memory_side = switchable

    _run(switchable.switch(_FakeProvider("ikinci")))

    assert _run(chat_side.generate([ChatMessage(role="user", content="x")])) == "ikinci"
    assert _run(memory_side.generate([ChatMessage(role="user", content="x")])) == "ikinci"


def test_the_previous_provider_is_closed_on_switch() -> None:
    """Eski sağlayıcı kapatılmalı; yoksa bağlantılar birikir."""
    first = _FakeProvider("ilk")
    switchable = SwitchableProvider(first)

    _run(switchable.switch(_FakeProvider("ikinci")))

    assert first.closed is True


def test_a_failing_close_does_not_block_the_switch() -> None:
    """Eski sağlayıcı kapanamasa bile yeni sağlayıcı devreye girmeli."""
    switchable = SwitchableProvider(_FakeProvider("ilk", fail_on_close=True))

    _run(switchable.switch(_FakeProvider("ikinci")))

    assert _run(switchable.generate([ChatMessage(role="user", content="x")])) == "ikinci"
