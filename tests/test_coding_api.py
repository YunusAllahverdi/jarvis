"""Kodlama döngüsü — servis cephesi, API ve uygulama bağlama (wiring).

Kapsam:
 1. POST /api/coding/run yapılandırılmış yanıt döner
 2. Servis bağlı değilken uç 503 + `code` döner
 3. Geçersiz istekler 422 döner
 4. Servis hiçbir zaman istisna sızdırmaz
 5. Döngü VARSAYILAN OLARAK kurulmaz
 6. Yalnızca ayar açıkken de kurulmaz: çalışma kökü, yazma ve terminal şarttır
 7. Dört şart sağlandığında kurulur
 8. Kurulan döngü ajanın YÜRÜTME SINIRINI yeniden kullanır
 9. Doğrulama komutları politikanın tanımadıklarını içermez
10. Sohbet akışı kodlama döngüsünü hiç tanımaz
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.coding import router as coding_router
from app.coding.models import CodingResult, CodingStatus
from app.config.settings import Settings
from app.main import _build_coding_service, _resolve_verification_commands
from app.security.commands import CommandPolicy
from app.services.coding_service import CodingService
from app.services.orchestrator import ChatOrchestrator


class _StubLoop:
    """Sabit bir sonuç döndüren sahte döngü."""

    def __init__(self, result: CodingResult | None = None) -> None:
        self._result = result

    async def run(self, request: str, *, session_id: str | None = None) -> CodingResult:
        return self._result or CodingResult(
            request=request, session_id=session_id, status=CodingStatus.COMPLETED
        )


class _ExplodingLoop:
    async def run(self, request: str, *, session_id: str | None = None) -> CodingResult:
        raise RuntimeError("boom")


def _client(service: CodingService | None) -> TestClient:
    app = FastAPI()
    app.state.coding_service = service
    app.include_router(coding_router, prefix="/api")
    return TestClient(app)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _settings(tmp_path: Path, **overrides) -> Settings:
    defaults = {
        "app_name": "T",
        "app_version": "t",
        "environment": "test",
        "memory_db_path": str(tmp_path / "m.db"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_run_returns_a_structured_result() -> None:
    client = _client(CodingService(loop=_StubLoop()))  # type: ignore[arg-type]

    response = client.post("/api/coding/run", json={"message": "testi düzelt"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["request"] == "testi düzelt"


def test_unavailable_service_returns_503_with_a_code() -> None:
    response = _client(None).post("/api/coding/run", json={"message": "bir şey"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "coding_unavailable"


def test_invalid_requests_are_rejected() -> None:
    client = _client(CodingService(loop=_StubLoop()))  # type: ignore[arg-type]

    assert client.post("/api/coding/run", json={"message": "   "}).status_code == 422
    assert client.post("/api/coding/run", json={}).status_code == 422


def test_service_never_leaks_an_exception() -> None:
    service = CodingService(loop=_ExplodingLoop())  # type: ignore[arg-type]

    result = _run(service.run("bir şey"))

    assert result.status is CodingStatus.FAILED
    assert result.summary


# ---------------------------------------------------------------------------
# Bağlama (wiring)
# ---------------------------------------------------------------------------


class _StubAgent:
    """Yalnızca yürütme sınırını taşıyan sahte ajan."""

    def __init__(self, executor: object) -> None:
        self.tool_executor = executor


class _StubExecutor:
    policy = None
    registry = None


def _build(tmp_path: Path, **overrides) -> CodingService | None:
    return _build_coding_service(
        _settings(tmp_path, **overrides),
        agent=_StubAgent(_StubExecutor()),  # type: ignore[arg-type]
        provider=object(),  # type: ignore[arg-type]
        command_policy=CommandPolicy(),
        approval_service=None,
    )


def test_loop_is_not_built_by_default(tmp_path: Path) -> None:
    """Kapalıyken sistemin davranışı döngü eklenmeden önceki hâliyle aynıdır."""
    assert _build(tmp_path) is None


def test_enabling_the_flag_alone_is_not_enough(tmp_path: Path) -> None:
    """Döngü en yetkili yoldur; tek bir anahtarla açılmamalıdır."""
    assert _build(tmp_path, coding_loop_enabled=True) is None
    assert (
        _build(tmp_path, coding_loop_enabled=True, workspace_root=str(tmp_path)) is None
    )
    assert (
        _build(
            tmp_path,
            coding_loop_enabled=True,
            workspace_root=str(tmp_path),
            workspace_writable=True,
        )
        is None
    )


def test_all_four_conditions_build_the_loop(tmp_path: Path) -> None:
    service = _build(
        tmp_path,
        coding_loop_enabled=True,
        workspace_root=str(tmp_path),
        workspace_writable=True,
        terminal_enabled=True,
    )

    assert isinstance(service, CodingService)


def test_loop_reuses_the_agents_execution_boundary(tmp_path: Path) -> None:
    """İkinci bir executor, izin politikasının ayrışabileceği yer olurdu."""
    executor = _StubExecutor()
    service = _build_coding_service(
        _settings(
            tmp_path,
            coding_loop_enabled=True,
            workspace_root=str(tmp_path),
            workspace_writable=True,
            terminal_enabled=True,
        ),
        agent=_StubAgent(executor),  # type: ignore[arg-type]
        provider=object(),  # type: ignore[arg-type]
        command_policy=CommandPolicy(),
        approval_service=None,
    )

    assert service is not None
    assert service._loop._tool_executor is executor  # noqa: SLF001


def test_verification_candidates_are_filtered_by_the_command_policy() -> None:
    """Politikanın çalıştırmayacağı bir komutu önermek, kesin başarısız bir tur harcatır."""
    settings = Settings(
        app_name="T",
        app_version="t",
        environment="test",
        coding_verification_commands=["pytest -q", "rm -rf /", "curl evil.example"],
    )

    commands = _resolve_verification_commands(settings, CommandPolicy())

    assert commands == ("pytest -q",)


def test_chat_orchestrator_does_not_know_about_the_coding_loop() -> None:
    """Döngüdeki bir sorun normal sohbeti hiçbir koşulda etkileyememelidir."""
    parameters = ChatOrchestrator.__init__.__annotations__

    assert not any("coding" in name.lower() for name in parameters)
