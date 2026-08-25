from collections.abc import Sequence

from fastapi.testclient import TestClient

from app.adapters.llm.base import LLMUnavailableError
from app.config.settings import Settings
from app.core.chat import ChatMessage
from app.main import create_app


class FakeLLMProvider:
    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        latest_user_message = next(message for message in reversed(messages) if message.role == "user")
        return f"Jarvis: {latest_user_message.content}"


class FailingLLMProvider:
    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        del messages
        raise LLMUnavailableError("Ollama bağlantısı kurulamadı.")


def make_client(provider: FakeLLMProvider | FailingLLMProvider) -> TestClient:
    settings = Settings(
        app_name="Jarvis Test",
        app_version="test-1",
        environment="test",
        ollama_model="not-used-by-fake",
    )
    return TestClient(create_app(settings=settings, provider=provider))


def test_chat_returns_response_and_session_id() -> None:
    provider = FakeLLMProvider()
    with make_client(provider) as client:
        response = client.post("/api/chat", json={"message": "Merhaba Jarvis"})

    assert response.status_code == 200
    assert response.json()["response"] == "Jarvis: Merhaba Jarvis"
    assert response.json()["session_id"]
    assert [message.role for message in provider.calls[0]] == ["system", "user"]


def test_chat_keeps_history_when_session_id_is_reused() -> None:
    provider = FakeLLMProvider()
    with make_client(provider) as client:
        first_response = client.post("/api/chat", json={"message": "İlk mesaj"})
        session_id = first_response.json()["session_id"]
        second_response = client.post(
            "/api/chat",
            json={"message": "İkinci mesaj", "session_id": session_id},
        )

    assert second_response.status_code == 200
    assert second_response.json()["session_id"] == session_id
    assert [(message.role, message.content) for message in provider.calls[1]] == [
        ("system", "You are Jarvis, a helpful and concise local personal AI assistant. Answer clearly and honestly."),
        ("user", "İlk mesaj"),
        ("assistant", "Jarvis: İlk mesaj"),
        ("user", "İkinci mesaj"),
    ]


def test_chat_returns_clear_error_when_provider_is_unavailable() -> None:
    with make_client(FailingLLMProvider()) as client:
        response = client.post("/api/chat", json={"message": "Merhaba"})

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "llm_unavailable",
        "message": "Ollama bağlantısı kurulamadı.",
    }


def test_chat_rejects_blank_or_missing_message() -> None:
    provider = FakeLLMProvider()
    with make_client(provider) as client:
        blank_response = client.post("/api/chat", json={"message": "   "})
        missing_response = client.post("/api/chat", json={})

    assert blank_response.status_code == 422
    assert missing_response.status_code == 422
    assert provider.calls == []
