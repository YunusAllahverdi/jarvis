"""Kullanıcı metnini conversation ve LLM sağlayıcı katmanları arasında orkestre eder."""

import logging

from pydantic import BaseModel

from app.adapters.llm.base import LLMProvider, LLMResponseError
from app.core.chat import ChatMessage, ToolCall
from app.services.conversation import ConversationStore
from app.services.memory_service import MemoryWriteService
from app.services.prompts import PromptProvider
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ChatResult(BaseModel):
    """Orchestrator'ın API'den bağımsız chat çıktısı."""

    response: str
    session_id: str


class ChatOrchestrator:
    """Text, LLM ve yalnızca kayıtlı tool'lar arasındaki güvenli akış.

    ConversationStore ve PromptProvider soyutlamalarına bağımlıdır; somut
    implementasyonlara değil. Bu sayede bellek ve prompt katmanları bağımsız
    olarak değiştirilebilir.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        conversation_store: ConversationStore,
        prompt_loader: PromptProvider,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        memory_service: MemoryWriteService | None = None,
        max_tool_rounds: int = 4,
        context_message_limit: int = 0,
    ) -> None:
        """
        Args:
            provider: LLM metin üretici.
            conversation_store: Oturum geçmişini saklayan ve döndüren sağlayıcı.
            prompt_loader: System prompt'unu sağlayan sağlayıcı.
            tool_registry: Kullanılabilir tool tanımlarını tutar.
            tool_executor: Tool'ları güvenli biçimde çalıştırır.
            memory_service: Konuşma turlarından bellek çıkarıp kalıcı hale
                getiren opsiyonel servis. None ise bellek çıkarımı hiç
                yapılmaz (mevcut davranış korunur). MemoryStore'un somut
                implementasyonu (SQLite vb.) bu katmana hiç sızmaz —
                yalnızca MemoryWriteService'e bağımlı olunur.
            max_tool_rounds: LLM'e izin verilen maksimum tool-call turu.
            context_message_limit: LLM bağlamına gönderilecek maksimum geçmiş
                mesaj sayısı (system mesajı hariç). 0 veya negatif = sınırsız.
                Bu limit yalnızca LLM bağlamını yönetir; kalıcı geçmişi silmez.
        """
        self._provider = provider
        self._conversation_store = conversation_store
        self._prompt_loader = prompt_loader
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._memory_service = memory_service
        self._max_tool_rounds = max_tool_rounds
        self._context_message_limit = context_message_limit

    def _trim_context(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        """Geçmiş mesajları context window limitine göre kırpar.

        Yalnızca LLM'e gönderilecek listeyi kırpar; depodaki gerçek geçmişe
        dokunmaz. Limit 0 veya negatifse kırpma yapılmaz.
        """
        if self._context_message_limit <= 0:
            return messages
        return messages[-self._context_message_limit :]

    async def respond(self, message: str, session_id: str | None = None) -> ChatResult:
        """Kullanıcı mesajına sağlayıcı cevabı üretir ve konuşmayı günceller."""

        conversation = self._conversation_store.get_or_create(session_id)
        user_message = ChatMessage(role="user", content=message)

        trimmed_history = self._trim_context(conversation.messages)
        provider_messages: list[ChatMessage] = [
            ChatMessage(role="system", content=self._prompt_loader.load()),
            *trimmed_history,
            user_message,
        ]
        new_history: list[ChatMessage] = [user_message]
        tool_definitions = self._tool_registry.list_definitions()

        for _ in range(self._max_tool_rounds):
            response = await self._provider.generate_with_tools(provider_messages, tool_definitions)

            if not response.tool_calls:
                final_response = response.content.strip()
                if not final_response:
                    raise LLMResponseError("LLM sağlayıcısı boş bir yanıt döndürdü.")
                assistant_message = ChatMessage(role="assistant", content=final_response)
                new_history.append(assistant_message)
                self._conversation_store.append_messages(conversation.session_id, new_history)
                if self._memory_service is not None:
                    await self._process_memory_safely(message, conversation.session_id)
                return ChatResult(response=final_response, session_id=conversation.session_id)

            tool_call_message = ChatMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            new_history.append(tool_call_message)
            provider_messages.append(tool_call_message)

            tool_result_messages = await self._execute_tool_calls(response.tool_calls)
            new_history.extend(tool_result_messages)
            provider_messages.extend(tool_result_messages)

        raise LLMResponseError("LLM izin verilen tool-call turu sınırını aştı.")

    async def _process_memory_safely(self, message: str, session_id: str) -> None:
        """Bellek çıkarımını/yazımını sohbet cevabından tamamen izole çalıştırır.

        MemoryWriteService kendi içinde tüm hataları yutar; burada ayrıca
        sarmalamamızın nedeni savunma katmanı eklemektir — bellek katmanında
        beklenmedik bir hata olsa bile kullanıcının normal cevabı asla
        etkilenmemelidir.
        """
        try:
            await self._memory_service.process_turn(message, session_id=session_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "memory_service_failed",
                extra={"session_id": session_id},
            )

    async def _execute_tool_calls(self, calls: list[ToolCall]) -> list[ChatMessage]:
        """Her tool call'u sadece registry üzerinden çalıştırır."""

        result_messages: list[ChatMessage] = []
        for call in calls:
            result = await self._tool_executor.execute(call)
            result_messages.append(result.as_chat_message())
        return result_messages
