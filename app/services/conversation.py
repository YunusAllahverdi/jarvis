"""Konuşma oturumu yönetimi: soyut sözleşme ve RAM tabanlı implementasyon."""

from collections.abc import Iterable
from threading import RLock
from typing import Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.chat import ChatMessage


class Conversation(BaseModel):
    """Bir kullanıcının geçici konuşma geçmişi."""

    session_id: str
    messages: list[ChatMessage] = Field(default_factory=list)


@runtime_checkable
class ConversationStore(Protocol):
    """Konuşma geçmişi sağlayıcıları için kararlı arayüz.

    Implementasyonlar RAM, SQLite, Redis veya başka bir depolama
    mekanizması kullanabilir; ChatOrchestrator yalnızca bu sözleşmeye bağımlıdır.
    """

    def get_or_create(self, session_id: str | None = None) -> Conversation:
        """Var olan oturumu veya yeni bir oturumu kopya olarak döndürür."""
        ...

    def append_messages(self, session_id: str, messages: Iterable[ChatMessage]) -> None:
        """Bir oturuma mesajları atomik olarak ekler."""
        ...


class InMemoryConversationStore:
    """Süreç ömrü boyunca conversation'ları RAM'de saklar.

    Bu store kalıcı değildir; uygulama yeniden başladığında tüm oturumlar silinir.
    ConversationStore Protocol'ünü implemente eder.
    """

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._lock = RLock()

    def get_or_create(self, session_id: str | None = None) -> Conversation:
        """Var olan oturumu veya yeni bir oturumu kopya olarak döndürür."""

        active_session_id = session_id or str(uuid4())
        with self._lock:
            conversation = self._conversations.get(active_session_id)
            if conversation is None:
                conversation = Conversation(session_id=active_session_id)
                self._conversations[active_session_id] = conversation
            return conversation.model_copy(deep=True)

    def append_messages(self, session_id: str, messages: Iterable[ChatMessage]) -> None:
        """Bir oturuma mesajları atomik olarak ekler."""

        with self._lock:
            conversation = self._conversations.get(session_id)
            if conversation is None:
                conversation = Conversation(session_id=session_id)
                self._conversations[session_id] = conversation
            conversation.messages.extend(messages)
