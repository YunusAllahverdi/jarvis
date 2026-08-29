"""Onay uçları — /api/approvals.

Kapsam:
 1. Bekleyen istekler listelenir ve argümanları görünür
 2. Liste oturuma göre süzülebilir
 3. Onaylamak aracı çalıştırır ve sonucu döndürür
 4. Reddetmek aracı ÇALIŞTIRMAZ
 5. Aynı onay ikinci kez kullanılamaz (409)
 6. Bilinmeyen kimlik 404 verir
 7. Süresi dolmuş istek 410 verir
 8. Karar gövdesi araç adı/argüman kabul etmez — kayıt esastır
 9. Yürütme sınırı kurulu değilse onay 503 verir
10. Uygulama onay servisini durumunda taşır (bağlantı sözleşmesi)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.core.chat import ChatMessage, LLMResponse, ToolCall, ToolDefinition
from app.api.routes.approvals import router as approvals_router
from app.main import create_app
from app.security.approvals import ApprovalService
from app.security.permissions import ToolPermissionPolicy
from app.tools.base import PermissionLevel, Tool, ToolInput
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

_START = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


class _SimpleFakeProvider:
    """LLM sunucusu olmadan çalışmak için en sade fake."""

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        return "ok"

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        return LLMResponse(content="ok")


class _Clock:
    def __init__(self) -> None:
        self.now = _START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _PathInput(ToolInput):
    path: str = ""


class _RecordingTool(Tool[_PathInput]):
    input_model = _PathInput

    def __init__(self, name: str, permission: PermissionLevel) -> None:
        self.name = name  # type: ignore[misc]
        self.description = f"{name} test aracı."  # type: ignore[misc]
        self.permission = permission  # type: ignore[misc]
        self.calls: list[str] = []

    async def execute(self, tool_input: _PathInput) -> dict[str, Any]:
        self.calls.append(tool_input.path)
        return {"written": tool_input.path}


def _build(
    *, with_executor: bool = True, clock: _Clock | None = None, ttl: float = 300.0
) -> tuple[TestClient, ApprovalService, _RecordingTool]:
    """Yalnızca onay uçlarını taşıyan sade bir uygulama kurar."""

    tool = _RecordingTool("yazici", PermissionLevel.WRITE)
    registry = ToolRegistry()
    registry.register(tool)
    executor = ToolExecutor(
        registry,
        policy=ToolPermissionPolicy(
            allowed={PermissionLevel.READ}, requires_approval={PermissionLevel.WRITE}
        ),
    )
    service = ApprovalService(ttl_seconds=ttl, clock=clock or _Clock())

    app = FastAPI()
    app.include_router(approvals_router, prefix="/api")
    app.state.approval_service = service
    app.state.approval_executor = executor if with_executor else None

    return TestClient(app), service, tool


def _open_request(service: ApprovalService, *, path: str = "a.txt", session: str | None = "s1"):
    return service.request(
        ToolCall(name="yazici", arguments={"path": path}),
        permission=PermissionLevel.WRITE,
        session_id=session,
        reason="Dosya yazılacak.",
    )


# ---------------------------------------------------------------------------
# 1-2. Listeleme
# ---------------------------------------------------------------------------

def test_pending_requests_are_listed_with_arguments() -> None:
    """Kullanıcı neyi onayladığını görebilmeli."""
    client, service, _ = _build()
    record = _open_request(service)

    body = client.get("/api/approvals").json()

    assert len(body["pending"]) == 1
    item = body["pending"][0]
    assert item["approval_id"] == record.approval_id
    assert item["tool_name"] == "yazici"
    assert item["arguments"] == {"path": "a.txt"}
    assert item["reason"] == "Dosya yazılacak."


def test_pending_can_be_filtered_by_session() -> None:
    """Oturum süzgeci çalışmalı."""
    client, service, _ = _build()
    _open_request(service, session="s1")
    _open_request(service, session="s2")

    only_s1 = client.get("/api/approvals", params={"session_id": "s1"}).json()

    assert len(only_s1["pending"]) == 1


# ---------------------------------------------------------------------------
# 3-4. Karar verme
# ---------------------------------------------------------------------------

def test_approving_runs_the_tool() -> None:
    """Onay, saklanan çağrıyı çalıştırmalı ve sonucu döndürmeli."""
    client, service, tool = _build()
    record = _open_request(service, path="rapor.txt")

    resp = client.post(f"/api/approvals/{record.approval_id}", json={"decision": "approve"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["success"] is True
    assert body["result"] == {"written": "rapor.txt"}
    assert tool.calls == ["rapor.txt"]


def test_rejecting_does_not_run_the_tool() -> None:
    """Ret, aracı hiç çalıştırmamalı."""
    client, service, tool = _build()
    record = _open_request(service)

    resp = client.post(f"/api/approvals/{record.approval_id}", json={"decision": "reject"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert tool.calls == [], "reddedilen çağrı çalıştırılmamalıydı"


# ---------------------------------------------------------------------------
# 5-7. Geçersiz durumlar
# ---------------------------------------------------------------------------

def test_second_approval_is_refused() -> None:
    """Aynı onay tekrar kullanılamamalı; araç ikinci kez çalışmamalı."""
    client, service, tool = _build()
    record = _open_request(service)

    client.post(f"/api/approvals/{record.approval_id}", json={"decision": "approve"})
    second = client.post(f"/api/approvals/{record.approval_id}", json={"decision": "approve"})

    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "approval_already_decided"
    assert tool.calls == ["a.txt"], "araç yalnızca bir kez çalışmalıydı"


def test_unknown_approval_returns_404() -> None:
    """Var olmayan kimlik 404 vermeli."""
    client, _, _ = _build()

    resp = client.post("/api/approvals/olmayan", json={"decision": "approve"})

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "approval_not_found"


def test_expired_approval_returns_410() -> None:
    """Süresi dolan istek onaylanamamalı."""
    clock = _Clock()
    client, service, tool = _build(clock=clock, ttl=60)
    record = _open_request(service)

    clock.advance(61)
    resp = client.post(f"/api/approvals/{record.approval_id}", json={"decision": "approve"})

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "approval_expired"
    assert tool.calls == []


# ---------------------------------------------------------------------------
# 8-10. Sözleşme
# ---------------------------------------------------------------------------

def test_decision_body_cannot_carry_a_different_call() -> None:
    """İstemci gövdeye araç/argüman koyarak çalıştırılanı değiştirememeli."""
    client, service, tool = _build()
    record = _open_request(service, path="guvenli.txt")

    resp = client.post(
        f"/api/approvals/{record.approval_id}",
        json={"decision": "approve", "tool_name": "yazici", "arguments": {"path": "/etc/passwd"}},
    )

    assert resp.status_code == 200
    assert tool.calls == ["guvenli.txt"], "kayıttaki argümanlar kullanılmalıydı"


def test_missing_executor_reports_unavailable() -> None:
    """Yürütme sınırı yoksa onay sessizce yutulmamalı."""
    client, service, _ = _build(with_executor=False)
    record = _open_request(service)

    resp = client.post(f"/api/approvals/{record.approval_id}", json={"decision": "approve"})

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "approvals_unavailable"


def test_app_exposes_approval_service() -> None:
    """Uygulama onay servisini durumunda taşımalı ve uç kayıtlı olmalı."""
    settings = Settings(app_name="Test", app_version="t", environment="test", ollama_model="x")
    app = create_app(settings=settings, provider=_SimpleFakeProvider())

    with TestClient(app) as client:
        assert app.state.approval_service is not None
        assert client.get("/api/approvals").status_code == 200
