"""Learning katmanı — UserModelService ve kullanıcı modeli API'si testleri.

Kapsam:
 1. Profil trait'leri güven sırasına göre birleştirir
 2. Tür sayımları listeyle tutarlıdır (aynı güven eşiğine tabidir)
 3. Deneyim deposu yoksa istatistikler boş ama geçerlidir
 4. UserModelService salt-okunurdur (hiçbir kayıt değiştirmez)
 5. GET /api/user/profile tam profili döndürür
 6. GET /api/user/traits filtreleme ve sayfalama yapar
 7. GET /api/user/stats hafif istatistik ucudur
 8. POST /api/user/learn geçişi çalıştırır ve sonucu döndürür
 9. POST /api/user/learn idempotenttir
10. Kullanıcı modeli bağlı değilken uçlar 503 + makine okunur `code` döner
11. Geçersiz sorgu parametreleri 422 döner
12. Varsayılan sağlayıcı ile lifespan öğrenme yığınını otomatik kurar
13. Enjekte edilen sağlayıcı veritabanı oluşturulmasını engeller
14. Açıkça verilen trait deposu otomatik kurulumu engeller
15. `app.main` importu veritabanı oluşturmaz
16. Uçtan uca: sohbet → deneyim → öğrenme → profil
17. Mevcut chat/health uçları değişmeden çalışır
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings, get_settings
from app.core.chat import ChatMessage, LLMResponse, ToolDefinition
from app.learning.sqlite_trait_store import SQLiteUserTraitStore
from app.learning.trait import (
    TraitSource,
    TraitType,
    UserTrait,
    confidence_from_evidence,
)
from app.main import create_app
from app.memory.experience import Experience
from app.memory.sqlite_experience_store import SQLiteExperienceStore
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services.user_model_service import UserModelService

_NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)


class _FakeChatProvider:
    """/api/chat isteklerini sabit bir metinle cevaplayan sahte sağlayıcı."""

    def __init__(self, reply: str = "Jarvis: ok") -> None:
        self._reply = reply
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        response = await self.generate_with_tools(messages, tools=())
        return response.content

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append(list(messages))
        return LLMResponse(content=self._reply)


def _make_settings(tmp_path: Path, **kwargs: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        app_name="Jarvis Test",
        app_version="test-1",
        environment="test",
        ollama_model="not-used-by-fake",
        memory_db_path=str(tmp_path / "memory.db"),
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _trait(**overrides: Any) -> UserTrait:
    defaults: dict[str, Any] = dict(
        trait_type=TraitType.INTEREST,
        key="topic:python",
        value="python",
        evidence_count=4,
        confidence=confidence_from_evidence(4),
        source=TraitSource.EXPERIENCE,
        first_observed_at=_NOW,
        last_observed_at=_NOW,
    )
    defaults.update(overrides)
    return UserTrait(**defaults)


def _exp(*, user_message: str = "python", day: int = 26, tools: list[str] | None = None) -> Experience:
    return Experience(
        session_id="sess-1",
        occurred_at=datetime(2026, 8, day, 20, 0, tzinfo=UTC),
        user_message=user_message,
        assistant_response="cevap",
        tool_calls=tools or [],
    )


# ---------------------------------------------------------------------------
# 1-4. UserModelService
# ---------------------------------------------------------------------------


class TestUserModelService:
    def test_profile_orders_traits_by_confidence(self, tmp_path: Path) -> None:
        store = SQLiteUserTraitStore(str(tmp_path / "memory.db"))
        store.upsert(_trait(key="topic:weak", evidence_count=1, confidence=0.2))
        store.upsert(_trait(key="topic:strong", evidence_count=36, confidence=0.9))
        service = UserModelService(trait_store=store)

        profile = service.build_profile(now=_NOW)

        assert [t.key for t in profile.traits] == ["topic:strong", "topic:weak"]
        assert profile.generated_at == _NOW

    def test_type_counts_are_consistent_with_the_returned_list(self, tmp_path: Path) -> None:
        """Gösterilen sayılar, filtreden geçen listeyle aynı eşiğe tabi olmalı."""
        store = SQLiteUserTraitStore(str(tmp_path / "memory.db"))
        store.upsert(_trait(key="topic:weak", confidence=0.2))
        store.upsert(_trait(key="topic:strong", confidence=0.9))
        store.upsert(_trait(trait_type=TraitType.GOAL, key="memory:g1", confidence=0.9))
        service = UserModelService(trait_store=store)

        filtered = service.build_profile(min_confidence=0.5, now=_NOW)

        assert filtered.trait_count == 2
        assert filtered.traits_by_type[TraitType.INTEREST.value] == 1
        assert filtered.traits_by_type[TraitType.GOAL.value] == 1
        assert len(filtered.traits) == filtered.trait_count

    def test_all_trait_types_appear_in_counts_even_when_zero(self, tmp_path: Path) -> None:
        store = SQLiteUserTraitStore(str(tmp_path / "memory.db"))
        service = UserModelService(trait_store=store)

        profile = service.build_profile(now=_NOW)

        assert set(profile.traits_by_type) == {t.value for t in TraitType}
        assert profile.trait_count == 0

    def test_missing_experience_store_yields_empty_but_valid_stats(
        self, tmp_path: Path
    ) -> None:
        store = SQLiteUserTraitStore(str(tmp_path / "memory.db"))
        service = UserModelService(trait_store=store)

        stats = service.interaction_stats()

        assert stats.total_experiences == 0
        assert stats.first_seen_at is None

    def test_stats_are_computed_from_the_experience_history(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "memory.db")
        experience_store = SQLiteExperienceStore(db_path)
        experience_store.add(_exp(day=20, tools=["get_time"]))
        experience_store.add(_exp(day=26))
        service = UserModelService(
            trait_store=SQLiteUserTraitStore(db_path), experience_store=experience_store
        )

        stats = service.interaction_stats()

        assert stats.total_experiences == 2
        assert stats.total_tool_calls == 1
        assert stats.session_count == 1

    def test_building_a_profile_never_writes(self, tmp_path: Path) -> None:
        """Profil sorgusu yan etkisizdir — frontend istediği sıklıkta çağırabilir."""
        db_path = str(tmp_path / "memory.db")
        store = SQLiteUserTraitStore(db_path)
        experience_store = SQLiteExperienceStore(db_path)
        store.upsert(_trait())
        experience_store.add(_exp())
        service = UserModelService(trait_store=store, experience_store=experience_store)

        before = (store.count(include_invalidated=True), experience_store.count())
        for _ in range(3):
            service.build_profile(now=_NOW)
        after = (store.count(include_invalidated=True), experience_store.count())

        assert before == after

    def test_list_traits_filters_by_type(self, tmp_path: Path) -> None:
        store = SQLiteUserTraitStore(str(tmp_path / "memory.db"))
        store.upsert(_trait(trait_type=TraitType.INTEREST, key="topic:x"))
        store.upsert(_trait(trait_type=TraitType.PATTERN, key="active_period"))
        service = UserModelService(trait_store=store)

        patterns = service.list_traits(trait_type=TraitType.PATTERN)

        assert [t.key for t in patterns] == ["active_period"]


# ---------------------------------------------------------------------------
# 5-9. API uçları
# ---------------------------------------------------------------------------


@pytest.fixture()
def wired_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Gerçek depolarla, sahte bir sohbet sağlayıcısıyla bağlanmış uygulama."""
    db_path = str(tmp_path / "memory.db")
    return create_app(
        settings=_make_settings(tmp_path),
        provider=_FakeChatProvider(),
        experience_store=SQLiteExperienceStore(db_path),
        memory_store=SQLiteMemoryStore(db_path),
        user_trait_store=SQLiteUserTraitStore(db_path),
    )


class TestUserModelEndpoints:
    def test_profile_endpoint_returns_the_full_profile(self, wired_app) -> None:  # type: ignore[no-untyped-def]
        wired_app.state.user_trait_store.upsert(_trait())

        with TestClient(wired_app) as client:
            response = client.get("/api/user/profile")

        assert response.status_code == 200
        body = response.json()
        assert body["trait_count"] == 1
        assert body["traits"][0]["key"] == "topic:python"
        assert body["traits_by_type"]["interest"] == 1
        assert "generated_at" in body
        assert body["interaction"]["total_experiences"] == 0

    def test_profile_endpoint_honours_min_confidence(self, wired_app) -> None:  # type: ignore[no-untyped-def]
        wired_app.state.user_trait_store.upsert(_trait(key="topic:weak", confidence=0.2))
        wired_app.state.user_trait_store.upsert(_trait(key="topic:strong", confidence=0.9))

        with TestClient(wired_app) as client:
            response = client.get("/api/user/profile", params={"min_confidence": 0.5})

        assert response.status_code == 200
        assert [t["key"] for t in response.json()["traits"]] == ["topic:strong"]

    def test_traits_endpoint_filters_by_type(self, wired_app) -> None:  # type: ignore[no-untyped-def]
        wired_app.state.user_trait_store.upsert(_trait(trait_type=TraitType.INTEREST))
        wired_app.state.user_trait_store.upsert(
            _trait(trait_type=TraitType.GOAL, key="memory:goal_1")
        )

        with TestClient(wired_app) as client:
            response = client.get("/api/user/traits", params={"trait_type": "goal"})

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["traits"][0]["trait_type"] == "goal"

    def test_traits_endpoint_paginates(self, wired_app) -> None:  # type: ignore[no-untyped-def]
        for index in range(5):
            wired_app.state.user_trait_store.upsert(
                _trait(key=f"topic:t{index}", confidence=0.9 - index * 0.1)
            )

        with TestClient(wired_app) as client:
            response = client.get("/api/user/traits", params={"limit": 2, "offset": 2})

        assert response.status_code == 200
        assert [t["key"] for t in response.json()["traits"]] == ["topic:t2", "topic:t3"]

    def test_stats_endpoint_returns_interaction_summary(self, wired_app) -> None:  # type: ignore[no-untyped-def]
        wired_app.state.experience_store.add(_exp(day=20, tools=["get_time"]))
        wired_app.state.experience_store.add(_exp(day=26))

        with TestClient(wired_app) as client:
            response = client.get("/api/user/stats")

        assert response.status_code == 200
        body = response.json()
        assert body["total_experiences"] == 2
        assert body["total_tool_calls"] == 1

    def test_learn_endpoint_runs_a_pass_and_reports_changes(self, wired_app) -> None:  # type: ignore[no-untyped-def]
        for day in range(20, 26):
            wired_app.state.experience_store.add(_exp(day=day, tools=["get_time"]))

        with TestClient(wired_app) as client:
            response = client.post("/api/user/learn")

        assert response.status_code == 200
        body = response.json()
        assert body["failed"] is False
        assert body["experiences_analyzed"] == 6
        assert body["traits_created"] > 0
        assert wired_app.state.user_trait_store.count() == body["traits_created"]

    def test_learn_endpoint_is_idempotent(self, wired_app) -> None:  # type: ignore[no-untyped-def]
        for day in range(20, 26):
            wired_app.state.experience_store.add(_exp(day=day, tools=["get_time"]))

        with TestClient(wired_app) as client:
            first = client.post("/api/user/learn").json()
            after_first = wired_app.state.user_trait_store.count()
            second = client.post("/api/user/learn").json()

        assert second["traits_created"] == 0
        assert second["traits_updated"] == first["traits_created"]
        assert wired_app.state.user_trait_store.count() == after_first

    def test_learn_then_profile_reflects_learned_traits(self, wired_app) -> None:  # type: ignore[no-untyped-def]
        for day in range(20, 26):
            wired_app.state.experience_store.add(
                _exp(user_message="python projesi", day=day, tools=["get_time"])
            )

        with TestClient(wired_app) as client:
            client.post("/api/user/learn")
            profile = client.get("/api/user/profile").json()

        keys = {t["key"] for t in profile["traits"]}
        assert "tool:get_time" in keys
        assert "topic:python" in keys
        assert profile["interaction"]["total_experiences"] == 6


# ---------------------------------------------------------------------------
# 10-11. Hata davranışı
# ---------------------------------------------------------------------------


class TestEndpointErrorBehaviour:
    def test_endpoints_return_503_when_the_user_model_is_not_wired(
        self, tmp_path: Path
    ) -> None:
        app = create_app(settings=_make_settings(tmp_path), provider=_FakeChatProvider())

        with TestClient(app) as client:
            for path in ("/api/user/profile", "/api/user/traits", "/api/user/stats"):
                response = client.get(path)
                assert response.status_code == 503
                assert response.json()["detail"]["code"] == "user_model_unavailable"

            learn = client.post("/api/user/learn")
            assert learn.status_code == 503
            assert learn.json()["detail"]["code"] == "user_model_unavailable"

    def test_invalid_query_parameters_are_rejected(self, wired_app) -> None:  # type: ignore[no-untyped-def]
        with TestClient(wired_app) as client:
            assert client.get("/api/user/profile", params={"min_confidence": 2}).status_code == 422
            assert client.get("/api/user/traits", params={"limit": 0}).status_code == 422
            assert client.get("/api/user/traits", params={"offset": -1}).status_code == 422
            assert (
                client.get("/api/user/traits", params={"trait_type": "nope"}).status_code == 422
            )


# ---------------------------------------------------------------------------
# 12-15. Uygulama bağlama (wiring)
# ---------------------------------------------------------------------------


class TestApplicationWiring:
    def test_create_app_alone_does_not_build_the_learning_stack(self, tmp_path: Path) -> None:
        app = create_app(settings=_make_settings(tmp_path))

        assert app.state.user_trait_store is None
        assert app.state.learning_service is None
        assert app.state.user_model_service is None

    def test_default_provider_auto_wires_the_learning_stack_on_startup(
        self, tmp_path: Path
    ) -> None:
        app = create_app(settings=_make_settings(tmp_path))

        with TestClient(app):
            assert isinstance(app.state.user_trait_store, SQLiteUserTraitStore)
            assert app.state.learning_service is not None
            assert app.state.user_model_service is not None

    def test_auto_wired_learning_shares_the_one_database_file(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        app = create_app(settings=settings)

        with TestClient(app):
            assert app.state.user_trait_store._db_path == settings.memory_db_path
            assert [p.name for p in tmp_path.glob("*.db")] == ["memory.db"]

    def test_auto_wired_learning_receives_the_auto_wired_sources(
        self, tmp_path: Path
    ) -> None:
        """Öğrenme servisi, lifespan'de kurulan bellek ve deneyim depolarını almalı."""
        app = create_app(settings=_make_settings(tmp_path))

        with TestClient(app):
            learning = app.state.learning_service
            assert learning._memory_store is app.state.memory_store
            assert learning._experience_store is app.state.experience_store

    def test_injected_provider_prevents_any_database_creation(self, tmp_path: Path) -> None:
        db_path = tmp_path / "should_not_exist.db"
        app = create_app(
            settings=_make_settings(tmp_path, memory_db_path=str(db_path)),
            provider=_FakeChatProvider(),
        )

        with TestClient(app):
            assert app.state.user_trait_store is None
            assert app.state.learning_service is None

        assert not db_path.exists()

    def test_explicit_trait_store_prevents_auto_wiring(self, tmp_path: Path) -> None:
        custom = SQLiteUserTraitStore(str(tmp_path / "custom.db"))
        app = create_app(settings=_make_settings(tmp_path), user_trait_store=custom)

        assert app.state.user_trait_store is custom
        with TestClient(app):
            assert app.state.user_trait_store is custom

    def test_learning_stack_is_independent_of_memory_injection(self, tmp_path: Path) -> None:
        """Bellek yığınının elle verilmesi öğrenme katmanını kapatmamalı."""
        db_path = str(tmp_path / "memory.db")
        app = create_app(
            settings=_make_settings(tmp_path),
            provider=_FakeChatProvider(),
            user_trait_store=SQLiteUserTraitStore(db_path),
        )

        assert app.state.learning_service is not None
        assert app.state.user_model_service is not None

    def test_importing_app_main_does_not_create_the_database(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "import_side_effect.db"
        monkeypatch.setenv("JARVIS_MEMORY_DB_PATH", str(db_path))
        monkeypatch.setenv("JARVIS_ENVIRONMENT", "test")
        get_settings.cache_clear()

        import app.main as main_module

        try:
            importlib.reload(main_module)

            assert not db_path.exists()
            assert main_module.app.state.user_trait_store is None

            with TestClient(main_module.app):
                assert db_path.exists()
                assert isinstance(
                    main_module.app.state.user_trait_store, SQLiteUserTraitStore
                )
        finally:
            get_settings.cache_clear()
            importlib.reload(main_module)


# ---------------------------------------------------------------------------
# 16-17. Uçtan uca ve regresyon
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_chat_then_learn_then_profile(self, tmp_path: Path) -> None:
        """Tam döngü: sohbet → deneyim kalıcılaşır → öğrenme → profil."""
        db_path = str(tmp_path / "memory.db")
        experience_store = SQLiteExperienceStore(db_path)
        app = create_app(
            settings=_make_settings(tmp_path),
            provider=_FakeChatProvider("Jarvis: tamam."),
            experience_store=experience_store,
            user_trait_store=SQLiteUserTraitStore(db_path),
        )

        with TestClient(app) as client:
            for _ in range(4):
                chat = client.post("/api/chat", json={"message": "python projesi hakkında"})
                assert chat.status_code == 200

            assert experience_store.count() == 4

            learn = client.post("/api/user/learn").json()
            assert learn["experiences_analyzed"] == 4
            assert learn["failed"] is False

            profile = client.get("/api/user/profile").json()

        keys = {t["key"] for t in profile["traits"]}
        assert "topic:python" in keys
        assert "topic:projesi" in keys
        assert profile["interaction"]["total_experiences"] == 4

    def test_existing_chat_and_health_endpoints_are_unaffected(self, tmp_path: Path) -> None:
        app = create_app(
            settings=_make_settings(tmp_path), provider=_FakeChatProvider("Jarvis: ok")
        )

        with TestClient(app) as client:
            assert client.get("/api/v1/health").status_code == 200
            chat = client.post("/api/chat", json={"message": "merhaba"})
            assert chat.status_code == 200
            assert chat.json()["response"] == "Jarvis: ok"
            assert client.get("/").status_code == 200
