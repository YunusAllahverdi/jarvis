"""Kullanıcı metnini conversation ve LLM sağlayıcı katmanları arasında orkestre eder."""

from pydantic import BaseModel

from app.adapters.llm.base import LLMProvider, LLMResponseError
from app.core.chat import ChatMessage
from app.services.conversation import InMemoryConversationStore
from app.services.prompts import SystemPromptLoader


class ChatResult(BaseModel):
    """Orchestrator'ın API'den bağımsız chat çıktısı."""

    response: str
    session_id: str


class ChatOrchestrator:
    """Text → LLM → text akışının uygulama katmanı."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        conversation_store: InMemoryConversationStore,
        prompt_loader: SystemPromptLoader,
    ) -> None:
        self._provider = provider
        self._conversation_store = conversation_store
        self._prompt_loader = prompt_loader

    async def respond(self, message: str, session_id: str | None = None) -> ChatResult:
        """Kullanıcı mesajına sağlayıcı cevabı üretir ve konuşmayı günceller."""

        conversation = self._conversation_store.get_or_create(session_id)
        user_message = ChatMessage(role="user", content=message)
        provider_messages = [
            ChatMessage(role="system", content=self._prompt_loader.load()),
            *conversation.messages,
            user_message,
        ]
        response = (await self._provider.generate(provider_messages)).strip()

        if not response:
            raise LLMResponseError("LLM sağlayıcısı boş bir yanıt döndürdü.")

        assistant_message = ChatMessage(role="assistant", content=response)
        self._conversation_store.append_messages(
            conversation.session_id,
            [user_message, assistant_message],
        )
        return ChatResult(response=response, session_id=conversation.session_id)
