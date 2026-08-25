from collections.abc import Sequence

from fastapi.testclient import TestClient

from app.adapters.llm.base import LLMUnavailableError
from app.config.settings import Settings
from app.core.chat import ChatMessage, LLMResponse, ToolCall, ToolDefinition
from app.main import create_app


class FakeLLMProvider:
    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []
        self.tool_definitions: list[list[ToolDefinition]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        response = await self.generate_with_tools(messages, tools=())
        return response.content

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append(list(messages))
        self.tool_definitions.append(list(tools))
        latest_user_message = next(message for message in reversed(messages) if message.role == "user")
        return LLMResponse(content=f"Jarvis: {latest_user_message.content}")


class FailingLLMProvider:
    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        del messages
        raise LLMUnavailableError("Ollama bağlantısı kurulamadı.")

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        del messages, tools
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
    assert {tool.name for tool in provider.tool_definitions[0]} == {
        "calculator",
        "get_date",
        "get_time",
        "system_status",
    }


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
        (
            "system",
            "You are Jarvis, a helpful and concise local personal AI assistant. "
            "Answer clearly and honestly. Use a supplied tool only when it is needed, "
            "and never claim a tool was used when it was not.",
        ),
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


class CalculatorToolCallingProvider:
    def __init__(self) -> None:
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
        if len(self.calls) == 1:
            assert {tool.name for tool in tools} >= {"calculator", "get_time"}
            return LLMResponse(tool_calls=[ToolCall(name="calculator", arguments={"expression": "2 + 3"})])

        tool_result = messages[-1]
        assert tool_result.role == "tool"
        assert tool_result.tool_name == "calculator"
        assert '"result": 5' in tool_result.content
        return LLMResponse(content="2 + 3 sonucu 5.")


def test_chat_executes_registered_tool_then_returns_final_response() -> None:
    provider = CalculatorToolCallingProvider()
    with make_client(provider) as client:
        response = client.post("/api/chat", json={"message": "2 + 3 kaç eder?"})

    assert response.status_code == 200
    assert response.json()["response"] == "2 + 3 sonucu 5."
    assert len(provider.calls) == 2


class RejectedToolCallingProvider:
    def __init__(self, call: ToolCall) -> None:
        self._call = call
        self.calls: list[list[ChatMessage]] = []

    async def generate(self, messages: Sequence[ChatMessage]) -> str:
        response = await self.generate_with_tools(messages, tools=())
        return response.content

    async def generate_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        del tools
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            return LLMResponse(tool_calls=[self._call])
        return LLMResponse(content="Bu tool çağrısı güvenli biçimde reddedildi.")


def test_chat_rejects_unknown_tool_call() -> None:
    provider = RejectedToolCallingProvider(ToolCall(name="not_registered", arguments={}))
    with make_client(provider) as client:
        response = client.post("/api/chat", json={"message": "Bilinmeyen bir tool kullan"})

    assert response.status_code == 200
    assert '"code": "unknown_tool"' in provider.calls[1][-1].content


def test_chat_rejects_invalid_tool_arguments() -> None:
    provider = RejectedToolCallingProvider(ToolCall(name="calculator", arguments={"value": 7}))
    with make_client(provider) as client:
        response = client.post("/api/chat", json={"message": "Hesapla"})

    assert response.status_code == 200
    assert '"code": "invalid_arguments"' in provider.calls[1][-1].content
