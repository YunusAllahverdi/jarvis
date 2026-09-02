"""Council — üye başına sağlayıcı yapılandırması (çoklu ajan, çoklu anahtar).

Kapsam:
 1. Üye eklenir ve sırayla listelenir
 2. API anahtarı HİÇBİR görünümde geri okunmaz
 3. Anahtar gönderilmezse korunur, açıkça temizlenebilir
 4. Chairman TEKTİR: yeni chairman eskisini sıradan üye yapar
 5. Kapalı üye kurulmaz
 6. Üye sınırı aşılamaz
 7. Her üye KENDİ sağlayıcı örneğini alır
 8. Üyeler farklı türde sağlayıcılara gidebilir
 9. Council'a verilen kimlikler OPAQUE'tir; model adı sızmaz
10. Chairman işaretlenmemişse ilk üyenin sağlayıcısı YENİDEN KULLANILIR
11. Üye yoksa kurulum boş döner (hata değil)
12. Silme çalışır ve olmayan üye False döner
13. Yönetim ucu üyeleri listeler ve anahtar döndürmez
14. Yönetim ucu üye ekler, siler ve Council durumunu bildirir
15. Geçersiz üye kimliği reddedilir
16. Depo kurulu değilse uç 503 döner
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.llm.ollama import OllamaProvider
from app.adapters.llm.openai_compatible import OpenAICompatibleProvider
from app.api.routes.admin import router as admin_router
from app.config.settings import Settings
from app.services.council_config import MAX_MEMBERS, CouncilMemberStore
from app.services.llm_config import LLMProviderKind

_KEY = "sk-cok-gizli-anahtar"


def _store(tmp_path: Path) -> CouncilMemberStore:
    return CouncilMemberStore(str(tmp_path / "jarvis.db"))


def _add(
    store: CouncilMemberStore,
    member_id: str,
    *,
    kind: LLMProviderKind = LLMProviderKind.OLLAMA,
    base_url: str = "http://127.0.0.1:11434",
    model: str | None = "llama3.1",
    is_chairman: bool = False,
    enabled: bool = True,
    api_key: str | None = None,
    clear_api_key: bool = False,
):
    return store.upsert(
        member_id=member_id,
        kind=kind,
        base_url=base_url,
        model=model,
        is_chairman=is_chairman,
        enabled=enabled,
        api_key=api_key,
        clear_api_key=clear_api_key,
    )


# ---------------------------------------------------------------------------
# Depo
# ---------------------------------------------------------------------------


def test_members_are_stored_in_insertion_order(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _add(store, "birinci")
    _add(store, "ikinci")
    _add(store, "ucuncu")

    assert [member.member_id for member in store.list()] == ["birinci", "ikinci", "ucuncu"]


def test_api_key_is_never_readable(tmp_path: Path) -> None:
    """Anahtar yalnızca sağlayıcı kurulurken okunur, hiçbir görünümde dönmez."""
    store = _store(tmp_path)
    config = _add(store, "gizli", kind=LLMProviderKind.OPENAI_COMPATIBLE, api_key=_KEY)

    assert config.has_api_key is True
    assert _KEY not in config.model_dump_json()
    assert all(_KEY not in member.model_dump_json() for member in store.list())


def test_absent_key_is_preserved_and_can_be_cleared(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _add(store, "uye", kind=LLMProviderKind.OPENAI_COMPATIBLE, api_key=_KEY)

    # Anahtar gönderilmeden güncelleme: korunmalı.
    assert _add(store, "uye", kind=LLMProviderKind.OPENAI_COMPATIBLE).has_api_key is True
    # Açıkça temizleme.
    assert (
        _add(
            store,
            "uye",
            kind=LLMProviderKind.OPENAI_COMPATIBLE,
            clear_api_key=True,
        ).has_api_key
        is False
    )


def test_chairman_is_unique(tmp_path: Path) -> None:
    """İki chairman, sentezi hangisinin ürettiğini belirsiz bırakırdı."""
    store = _store(tmp_path)
    _add(store, "ilk", is_chairman=True)
    _add(store, "ikinci", is_chairman=True)

    chairs = [member.member_id for member in store.list() if member.is_chairman]
    assert chairs == ["ikinci"]


def test_disabled_members_are_not_built(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _add(store, "acik")
    _add(store, "kapali", enabled=False)

    members, _chairman, providers = store.build_members()

    assert len(members) == 1
    assert len(providers) == 1


def test_member_limit_is_enforced(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for index in range(MAX_MEMBERS):
        _add(store, f"uye-{index}")

    with pytest.raises(ValueError):
        _add(store, "bir-fazla")


def test_each_member_gets_its_own_provider(tmp_path: Path) -> None:
    """Farklı adreslere ve farklı anahtarlara gitmek buna bağlıdır."""
    store = _store(tmp_path)
    _add(store, "bir")
    _add(store, "iki")

    members, _chairman, providers = store.build_members()

    assert len({id(member.provider) for member in members}) == 2
    assert len(providers) == 2


def test_members_may_use_different_provider_kinds(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _add(store, "yerel", kind=LLMProviderKind.OLLAMA)
    _add(
        store,
        "uzak",
        kind=LLMProviderKind.OPENAI_COMPATIBLE,
        base_url="https://api.example.com/v1",
        api_key=_KEY,
    )

    members, _chairman, _providers = store.build_members()

    assert isinstance(members[0].provider, OllamaProvider)
    assert isinstance(members[1].provider, OpenAICompatibleProvider)


def test_council_only_sees_opaque_ids(tmp_path: Path) -> None:
    """Akran değerlendirmesinin anonimliği buna bağlıdır."""
    store = _store(tmp_path)
    _add(store, "openai-4o", model="gpt-4o")
    _add(store, "yerel-llama", model="llama3.1")

    members, chairman, _providers = store.build_members()

    assert [member.member_id for member in members] == ["member-1", "member-2"]
    assert chairman.member_id == "chairman"


def test_default_chairman_reuses_the_first_members_provider(tmp_path: Path) -> None:
    """Gereksiz ikinci bir HTTP istemcisi açılmamalıdır."""
    store = _store(tmp_path)
    _add(store, "bir")
    _add(store, "iki")

    members, chairman, providers = store.build_members()

    assert chairman.provider is members[0].provider
    assert len(providers) == 2


def test_empty_store_builds_nothing(tmp_path: Path) -> None:
    members, chairman, providers = _store(tmp_path).build_members()

    assert (members, chairman, providers) == ([], None, [])


def test_delete_removes_a_member(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _add(store, "gidecek")

    assert store.delete("gidecek") is True
    assert store.delete("gidecek") is False
    assert store.list() == []


# ---------------------------------------------------------------------------
# Yönetim uçları
# ---------------------------------------------------------------------------


def _client(tmp_path: Path, *, with_store: bool = True) -> tuple[TestClient, CouncilMemberStore | None]:
    app = FastAPI()
    store = _store(tmp_path) if with_store else None
    app.state.settings = Settings(
        app_name="T", app_version="t", environment="test", host="127.0.0.1"
    )
    app.state.council_member_store = store
    app.state.audit_log = None
    app.state.agent_service = None
    app.state.council_providers = []
    app.include_router(admin_router, prefix="/api")
    return TestClient(app), store


def test_endpoint_lists_members_without_keys(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    _add(store, "uye", kind=LLMProviderKind.OPENAI_COMPATIBLE, api_key=_KEY)

    response = client.get("/api/admin/council")

    assert response.status_code == 200
    assert _KEY not in response.text
    assert response.json()["members"][0]["has_api_key"] is True


def test_endpoint_adds_and_deletes_members(tmp_path: Path) -> None:
    client, _store_ = _client(tmp_path)

    created = client.put(
        "/api/admin/council/members/uzak-model",
        json={
            "kind": "openai_compatible",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-4o",
            "api_key": _KEY,
        },
    )

    assert created.status_code == 200
    assert created.json()["count"] == 1
    # Tek üye `council_min_candidates` (2) altındadır; Council açılmamalı.
    assert created.json()["active"] is False
    assert _KEY not in created.text

    removed = client.delete("/api/admin/council/members/uzak-model")
    assert removed.status_code == 200
    assert removed.json()["count"] == 0

    assert client.delete("/api/admin/council/members/yok").status_code == 404


def test_invalid_member_id_is_rejected(tmp_path: Path) -> None:
    client, _store_ = _client(tmp_path)

    response = client.put(
        "/api/admin/council/members/Büyük Harfli Ad",
        json={"kind": "ollama", "base_url": "http://127.0.0.1:11434"},
    )

    assert response.status_code == 422


def test_endpoint_reports_missing_store(tmp_path: Path) -> None:
    client, _store_ = _client(tmp_path, with_store=False)

    response = client.get("/api/admin/council")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "council_store_unavailable"


class _RecordingAgent:
    """`set_council` çağrılarını kaydeden sahte ajan."""

    def __init__(self) -> None:
        self.council_service = None
        self.gate = None

    def set_council(self, service, gate) -> None:  # type: ignore[no-untyped-def]
        self.council_service = service
        self.gate = gate


def test_saving_a_second_member_activates_the_council_live(tmp_path: Path) -> None:
    """Değişikliğin etkili olması için uygulamayı yeniden başlatmak gerekmez."""
    client, _store_ = _client(tmp_path)
    agent = _RecordingAgent()
    client.app.state.agent_service = agent

    first = client.put(
        "/api/admin/council/members/bir",
        json={"kind": "ollama", "base_url": "http://127.0.0.1:11434", "model": "llama3.1"},
    )
    # Tek üye yeterli değil: Council sökülü kalır.
    assert first.json()["active"] is False
    assert agent.council_service is None

    second = client.put(
        "/api/admin/council/members/iki",
        json={"kind": "ollama", "base_url": "http://127.0.0.1:11434", "model": "qwen2.5"},
    )

    assert second.json()["active"] is True
    assert agent.council_service is not None
    assert agent.gate is not None
    assert client.app.state.council_service is agent.council_service


def test_dropping_below_the_minimum_dismantles_the_council(tmp_path: Path) -> None:
    """Yarım bir Council yerine tek-LLM davranışına dönülür."""
    client, _store_ = _client(tmp_path)
    agent = _RecordingAgent()
    client.app.state.agent_service = agent

    for member_id in ("bir", "iki"):
        client.put(
            "/api/admin/council/members/" + member_id,
            json={"kind": "ollama", "base_url": "http://127.0.0.1:11434", "model": "m"},
        )
    assert agent.council_service is not None

    removed = client.delete("/api/admin/council/members/iki")

    assert removed.json()["active"] is False
    assert agent.council_service is None
    assert agent.gate is None
