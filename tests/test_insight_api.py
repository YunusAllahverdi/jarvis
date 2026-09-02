"""Kabuğun okuduğu salt-okunur görünümler — bellek, deneyim, sistem durumu.

Kapsam:
 1. Bellek kayıtları listelenir
 2. Sorgu verildiğinde arama yolu kullanılır
 3. Uzun içerik sunucuda kırpılır
 4. Geçersiz bellek türü 422 döner
 5. Bellek deposu yoksa 503 + `code`
 6. Depo patlarsa 503'e çevrilir, istisna sızmaz
 7. Deneyimler listelenir
 8. Oturum verildiğinde o oturuma daraltılır
 9. Deneyim deposu yoksa 503 + `code`
10. Sistem durumu ölçülen değerleri döndürür
11. Yerel olmayan sunucu `is_local=False` ile işaretlenir
12. Uçların hiçbiri yazma yapmaz
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.insight import MAX_CONTENT_CHARS, router as insight_router
from app.config.settings import Settings
from app.memory.experience import Experience, ExperienceOutcome
from app.memory.record import MemoryRecord, MemoryType

_NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


class _FakeMemoryStore:
    """Sadece okuma yollarını taklit eden bellek deposu."""

    def __init__(self, records: list[MemoryRecord] | None = None, *, explode: bool = False) -> None:
        self._records = records or []
        self._explode = explode
        self.searched: str | None = None
        self.listed = False

    def list_active(self, *, memory_type=None, limit=50, **kwargs):  # type: ignore[no-untyped-def]
        if self._explode:
            raise RuntimeError("depo patladı")
        self.listed = True
        return self._records[:limit]

    def search(self, query, *, memory_type=None, limit=20, **kwargs):  # type: ignore[no-untyped-def]
        if self._explode:
            raise RuntimeError("depo patladı")
        self.searched = query
        return self._records[:limit]


class _FakeExperienceStore:
    def __init__(self, experiences: list[Experience] | None = None) -> None:
        self._experiences = experiences or []
        self.session_scoped: str | None = None

    def list_recent(self, *, limit=50, **kwargs):  # type: ignore[no-untyped-def]
        return self._experiences[:limit]

    def list_by_session(self, session_id, *, limit=50):  # type: ignore[no-untyped-def]
        self.session_scoped = session_id
        return self._experiences[:limit]


def _record(content: str = "Kullanıcı Python seviyor.") -> MemoryRecord:
    return MemoryRecord(
        memory_type=MemoryType.PREFERENCE,
        content=content,
        valid_at=_NOW,
        importance=0.7,
        source_session_id="s1",
    )


def _experience(message: str = "merhaba") -> Experience:
    return Experience(
        session_id="s1",
        occurred_at=_NOW,
        user_message=message,
        assistant_response="selam",
        outcome=ExperienceOutcome.SUCCESS,
        tool_calls=["get_time"],
    )


def _client(
    *,
    memory_store: object | None = None,
    experience_store: object | None = None,
    host: str = "127.0.0.1",
) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(
        app_name="T", app_version="t", environment="test", host=host
    )
    app.state.memory_store = memory_store
    app.state.experience_store = experience_store
    app.include_router(insight_router, prefix="/api")
    return TestClient(app)


# ---------------------------------------------------------------------------
# Bellek
# ---------------------------------------------------------------------------


def test_memory_records_are_listed() -> None:
    client = _client(memory_store=_FakeMemoryStore([_record(), _record("başka")]))

    response = client.get("/api/memory/records")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["records"][0]["memory_type"] == "preference"


def test_query_uses_the_search_path() -> None:
    """Listeleme ve arama tek uçtadır; sorgu verildiğinde arama çalışmalıdır."""
    store = _FakeMemoryStore([_record()])
    client = _client(memory_store=store)

    client.get("/api/memory/records", params={"query": "python"})

    assert store.searched == "python"
    assert store.listed is False


def test_long_content_is_clipped_on_the_server() -> None:
    """Tek bir uzun kayıt listeyi ele geçirmemeli; kırpma tarayıcıya bırakılmaz."""
    client = _client(memory_store=_FakeMemoryStore([_record("x" * (MAX_CONTENT_CHARS * 3))]))

    content = client.get("/api/memory/records").json()["records"][0]["content"]

    assert len(content) <= MAX_CONTENT_CHARS + 1  # kırpma işareti dahil


def test_unknown_memory_type_is_rejected() -> None:
    client = _client(memory_store=_FakeMemoryStore([_record()]))

    response = client.get("/api/memory/records", params={"memory_type": "yok-boyle"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "memory_type_invalid"


def test_missing_memory_store_returns_503() -> None:
    response = _client().get("/api/memory/records")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "memory_unavailable"


def test_store_failure_becomes_503_not_an_exception() -> None:
    client = _client(memory_store=_FakeMemoryStore(explode=True))

    response = client.get("/api/memory/records")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "memory_read_failed"


# ---------------------------------------------------------------------------
# Deneyimler
# ---------------------------------------------------------------------------


def test_experiences_are_listed() -> None:
    client = _client(experience_store=_FakeExperienceStore([_experience()]))

    body = client.get("/api/experiences").json()

    assert body["count"] == 1
    assert body["experiences"][0]["outcome"] == "success"
    assert body["experiences"][0]["tool_calls"] == ["get_time"]


def test_session_scopes_the_experience_list() -> None:
    store = _FakeExperienceStore([_experience()])
    client = _client(experience_store=store)

    client.get("/api/experiences", params={"session_id": "s1"})

    assert store.session_scoped == "s1"


def test_missing_experience_store_returns_503() -> None:
    response = _client().get("/api/experiences")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "experience_unavailable"


# ---------------------------------------------------------------------------
# Sistem durumu
# ---------------------------------------------------------------------------


def test_system_status_reports_measured_values() -> None:
    body = _client().get("/api/system/status").json()

    assert 0.0 <= body["cpu_percent"] <= 100.0
    assert 0.0 <= body["memory_percent"] <= 100.0
    assert body["memory_total_bytes"] > 0
    assert body["is_local"] is True


def test_non_local_host_is_flagged() -> None:
    """Bulutta çalışan bir örnek container'ı ölçer, kullanıcının makinesini değil."""
    body = _client(host="0.0.0.0").get("/api/system/status").json()

    assert body["is_local"] is False


def test_insight_endpoints_are_read_only() -> None:
    """Yazma yolları bilinçli olarak yoktur."""
    client = _client(memory_store=_FakeMemoryStore([_record()]))

    for path in ("/api/memory/records", "/api/experiences", "/api/system/status"):
        assert client.post(path, json={}).status_code == 405
        assert client.delete(path).status_code == 405
