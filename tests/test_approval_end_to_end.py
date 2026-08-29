"""Onay döngüsünün uçtan uca çalışması.

Senaryo: ajan bir dosya yazmak ister, yürütme sınırı onu durdurur, kullanıcı
bekleyen isteği görür ve onaylar, dosya ancak o zaman değişir.

Kapsam:
 1. Yazma eylemi çalıştırılmaz ve dosya değişmez
 2. Ajan sonucu, kullanıcının yanıtlayacağı onay kimliğini taşır
 3. Bekleyen istek API'de görünür ve argümanları okunabilir
 4. Onaylandığında dosya gerçekten değişir
 5. Reddedildiğinde dosya değişmez
 6. Onay servisi bağlı değilse eylem yine çalıştırılmaz
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.context import AgentContext, ContextBuilder
from app.agent.models import AgentAction, AgentDecision, Intent
from app.agent.runner import AgentRunner
from app.api.routes.approvals import router as approvals_router
from app.security.approvals import ApprovalService
from app.security.paths import PathGuard
from app.security.permissions import ToolPermissionPolicy
from app.services.agent_service import AgentService
from app.services.conversation import InMemoryConversationStore
from app.tools.base import PermissionLevel
from app.tools.defaults import build_default_tool_registry, register_filesystem_tools
from app.tools.executor import ToolExecutor


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class _WritePolicy:
    """Dosya yazmayı planlayan, ama onay gerektiğini İŞARETLEMEYEN politika.

    Bilerek böyle: burada sınanan şey, karar katmanı gözden kaçırsa bile
    yürütme sınırının yazmayı durdurup durdurmadığıdır.
    """

    name = "test-write"

    def __init__(self, path: str, content: str) -> None:
        self._path = path
        self._content = content

    async def decide(self, context: AgentContext) -> AgentDecision:
        return AgentDecision(
            intent=Intent.INFORMATION_REQUEST,
            actions=[
                AgentAction(
                    tool_name="write_file",
                    arguments={"path": self._path, "content": self._content},
                    purpose="Kullanıcının istediği dosyayı yaz.",
                )
            ],
            reason="Kullanıcı dosya yazılmasını istedi.",
            policy="test-write",
        )


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "rapor.txt").write_text("özgün içerik", encoding="utf-8")
    return tmp_path


def _build(workspace: Path, *, with_approvals: bool = True):
    guard = PathGuard(workspace)
    registry = build_default_tool_registry()
    register_filesystem_tools(registry, guard=guard, writable=True)

    policy = ToolPermissionPolicy(
        allowed={PermissionLevel.READ}, requires_approval={PermissionLevel.WRITE}
    )
    executor = ToolExecutor(registry, policy=policy)
    service = ApprovalService() if with_approvals else None

    agent = AgentService(
        context_builder=ContextBuilder(
            tool_registry=registry,
            policy=policy,
            conversation_store=InMemoryConversationStore(),
        ),
        policy=_WritePolicy("rapor.txt", "ajanın yazdığı"),
        runner=AgentRunner(tool_executor=executor),
        approval_service=service,
    )

    app = FastAPI()
    app.include_router(approvals_router, prefix="/api")
    app.state.approval_service = service
    app.state.approval_executor = executor

    return agent, service, TestClient(app)


# ---------------------------------------------------------------------------
# 1-2. Ajan durur ve onay kimliği üretir
# ---------------------------------------------------------------------------

def test_write_is_stopped_and_the_file_is_untouched(workspace: Path) -> None:
    """Onay alınmadan dosya değişmemeli."""
    agent, _, _ = _build(workspace)

    result = _run(agent.run("rapor.txt dosyasını güncelle", session_id="s1"))

    outcome = result.outcomes[0]
    assert outcome.success is False
    assert outcome.requires_approval is True
    assert (workspace / "rapor.txt").read_text(encoding="utf-8") == "özgün içerik"


def test_result_carries_the_approval_id(workspace: Path) -> None:
    """Kullanıcı hangi isteği onaylayacağını sonuçtan öğrenebilmeli."""
    agent, _, _ = _build(workspace)

    result = _run(agent.run("rapor.txt dosyasını güncelle", session_id="s1"))

    assert result.outcomes[0].approval_id is not None


# ---------------------------------------------------------------------------
# 3-5. Kullanıcı kararı
# ---------------------------------------------------------------------------

def test_pending_request_is_visible_with_its_arguments(workspace: Path) -> None:
    """Kullanıcı neyi onayladığını görebilmeli."""
    agent, _, client = _build(workspace)
    _run(agent.run("güncelle", session_id="s1"))

    pending = client.get("/api/approvals").json()["pending"]

    assert len(pending) == 1
    assert pending[0]["tool_name"] == "write_file"
    assert pending[0]["arguments"]["path"] == "rapor.txt"
    assert pending[0]["permission"] == "WRITE"


def test_approving_actually_writes_the_file(workspace: Path) -> None:
    """Onaydan sonra aynı çağrı çalışmalı ve dosya değişmeli."""
    agent, _, client = _build(workspace)
    result = _run(agent.run("güncelle", session_id="s1"))
    approval_id = result.outcomes[0].approval_id

    response = client.post(f"/api/approvals/{approval_id}", json={"decision": "approve"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert (workspace / "rapor.txt").read_text(encoding="utf-8") == "ajanın yazdığı"


def test_rejecting_leaves_the_file_alone(workspace: Path) -> None:
    """Ret sonrası dosya özgün hâlinde kalmalı."""
    agent, _, client = _build(workspace)
    result = _run(agent.run("güncelle", session_id="s1"))
    approval_id = result.outcomes[0].approval_id

    client.post(f"/api/approvals/{approval_id}", json={"decision": "reject"})

    assert (workspace / "rapor.txt").read_text(encoding="utf-8") == "özgün içerik"


# ---------------------------------------------------------------------------
# 6. Onay altyapısı yoksa
# ---------------------------------------------------------------------------

def test_without_an_approval_service_the_write_still_does_not_happen(workspace: Path) -> None:
    """Onay servisi bağlı değilken de yazma gerçekleşmemeli.

    Kayıt açılamaması, engellenen bir yazmanın serbest kalması anlamına
    gelmemelidir.
    """
    agent, _, _ = _build(workspace, with_approvals=False)

    result = _run(agent.run("güncelle", session_id="s1"))

    assert result.outcomes[0].requires_approval is True
    assert result.outcomes[0].approval_id is None
    assert (workspace / "rapor.txt").read_text(encoding="utf-8") == "özgün içerik"
