"""Agent için SINIRLANDIRILMIŞ (bounded) bağlam inşası.

Temel ilke: veritabanının tamamı asla bağlama yüklenmez. Her kaynak açık bir
bütçeyle (`ContextBudget`) sınırlıdır ve bütçe çağıran tarafından daraltılabilir.

Mimari kurallar:
- Yalnızca PUBLIC arayüzler kullanılır: MemoryRetrievalService, ExperienceStore
  Protocol'ü, UserModelService, ConversationStore Protocol'ü ve ToolRegistry.
  Hiçbir somut SQLite sınıfına, hiçbir özel (private) alana erişilmez.
- Her kaynak İSTEĞE BAĞLIDIR. Bağlı olmayan bir kaynak hata değildir; ilgili
  bölüm boş kalır ve `degraded_sources` listesine eklenir.
- Bağlam inşası HİÇBİR ZAMAN istisna fırlatmaz. Bir kaynak patlarsa hata
  loglanır, o bölüm boş bırakılır ve akış devam eder — karar katmanı eksik
  bağlamla da çalışabilmelidir.
- Bağlam inşası SALT OKUNURDUR: hiçbir kaydı değiştirmez, hiçbir şey yazmaz.
- Memory / Experience / User Model AYRI kavramlar olarak kalır; tek bir
  "dev bağlam veritabanına" birleştirilmez.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.agent.models import ToolDescriptor
from app.core.chat import ChatMessage
from app.learning.trait import UserTrait
from app.memory.experience import Experience
from app.memory.experience_store import ExperienceStore
from app.memory.record import MemoryRecord
from app.services.conversation import ConversationStore
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.user_model_service import UserModelService
from app.tools.base import PermissionLevel
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Bağlam kaynaklarının kararlı adları (gözlemlenebilirlik ve testler için).
SOURCE_CONVERSATION = "conversation"
SOURCE_MEMORY = "memory"
SOURCE_EXPERIENCE = "experience"
SOURCE_USER_MODEL = "user_model"


class ContextBudget(BaseModel):
    """Bağlama alınacak her kaynağın üst sınırı.

    Varsayılanlar bilinçli olarak KÜÇÜKTÜR: bağlam bir arşiv değil, mevcut
    isteğe karar vermek için gereken en küçük bilgi kümesidir.
    """

    model_config = ConfigDict(frozen=True)

    max_recent_messages: int = Field(default=10, ge=0, le=200)
    max_memories: int = Field(default=5, ge=0, le=50)
    max_experiences: int = Field(default=5, ge=0, le=50)
    max_traits: int = Field(default=10, ge=0, le=100)
    min_trait_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AgentContext(BaseModel):
    """Karar vermek için toplanmış, sınırlandırılmış bağlam anlık görüntüsü."""

    user_message: str
    session_id: str | None = None
    built_at: datetime

    recent_messages: list[ChatMessage] = Field(default_factory=list)
    memories: list[MemoryRecord] = Field(default_factory=list)
    """Jarvis ne biliyor — mesajla ilgili bellek kayıtları."""

    experiences: list[Experience] = Field(default_factory=list)
    """Ne oldu — son etkileşimler."""

    traits: list[UserTrait] = Field(default_factory=list)
    """Kullanıcı hakkında öğrenilmiş kalıcı örüntüler."""

    available_tools: list[ToolDescriptor] = Field(default_factory=list)
    budget: ContextBudget = Field(default_factory=ContextBudget)

    degraded_sources: list[str] = Field(default_factory=list)
    """Bağlı olmayan veya hata veren kaynakların adları.

    Boş olmaması bir hata değildir; kararın hangi bilgi eksikliğiyle
    alındığını görünür kılar.
    """

    def has_tool(self, name: str) -> bool:
        """Adı verilen tool bu oturumda kullanılabilir mi?"""
        return any(tool.name == name for tool in self.available_tools)

    def tool(self, name: str) -> ToolDescriptor | None:
        """Adı verilen tool'un tanımını döndürür; yoksa None."""
        return next((tool for tool in self.available_tools if tool.name == name), None)


class ContextBuilder:
    """İstek başına sınırlandırılmış bir `AgentContext` üretir.

    Kullanım:
        builder = ContextBuilder(
            tool_registry=registry,
            allowed_permissions={PermissionLevel.READ},
            memory_retrieval=retrieval,
        )
        context = builder.build("saat kaç?", session_id="s1")

    Tüm veri kaynakları isteğe bağlıdır; verilmeyen kaynak yalnızca ilgili
    bölümün boş kalmasına yol açar.
    """

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        allowed_permissions: Iterable[PermissionLevel],
        conversation_store: ConversationStore | None = None,
        memory_retrieval: MemoryRetrievalService | None = None,
        experience_store: ExperienceStore | None = None,
        user_model: UserModelService | None = None,
        budget: ContextBudget | None = None,
    ) -> None:
        """
        Args:
            tool_registry: Agent'ın kullanabileceği tool'ların kaydı. Sohbet
                akışının registry'sinden AYRI bir örnek olabilir; agent'ın
                tool yüzeyi LLM'in sohbet sırasında gördüğü yüzeyi değiştirmez.
            allowed_permissions: Bu oturumda onaysız çalıştırılabilecek izin
                seviyeleri. Bunun dışındaki tool'lar bağlama `requires_confirmation`
                işaretiyle girer.
            conversation_store: Son konuşma mesajlarının kaynağı.
            memory_retrieval: İlgili bellek kayıtlarının kaynağı.
            experience_store: Son deneyimlerin kaynağı.
            user_model: Öğrenilmiş kullanıcı özelliklerinin kaynağı.
            budget: Kaynak başına üst sınırlar. Verilmezse varsayılan bütçe.
        """
        self._tool_registry = tool_registry
        self._allowed_permissions = frozenset(allowed_permissions)
        self._conversation_store = conversation_store
        self._memory_retrieval = memory_retrieval
        self._experience_store = experience_store
        self._user_model = user_model
        self._budget = budget or ContextBudget()

    def build(
        self,
        user_message: str,
        *,
        session_id: str | None = None,
        now: datetime | None = None,
    ) -> AgentContext:
        """Mevcut istek için bağlamı toplar.

        Hiçbir zaman istisna fırlatmaz: her kaynak ayrı ayrı korunur ve
        başarısız olan kaynak `degraded_sources` içinde raporlanır.
        """
        degraded: list[str] = []
        return AgentContext(
            user_message=user_message,
            session_id=session_id,
            built_at=now or datetime.now(UTC),
            recent_messages=self._recent_messages(session_id, degraded),
            memories=self._memories(user_message, degraded),
            experiences=self._experiences(session_id, degraded),
            traits=self._traits(degraded),
            available_tools=self._tools(),
            budget=self._budget,
            degraded_sources=degraded,
        )

    # ------------------------------------------------------------------
    # Kaynaklar — her biri kendi hatasını yutar
    # ------------------------------------------------------------------

    def _recent_messages(self, session_id: str | None, degraded: list[str]) -> list[ChatMessage]:
        if self._conversation_store is None or session_id is None:
            degraded.append(SOURCE_CONVERSATION)
            return []
        limit = self._budget.max_recent_messages
        if limit <= 0:
            return []
        try:
            conversation = self._conversation_store.get_or_create(session_id)
        except Exception:  # noqa: BLE001
            logger.exception("agent_context_conversation_failed", extra={"session_id": session_id})
            degraded.append(SOURCE_CONVERSATION)
            return []
        return list(conversation.messages[-limit:])

    def _memories(self, user_message: str, degraded: list[str]) -> list[MemoryRecord]:
        if self._memory_retrieval is None:
            degraded.append(SOURCE_MEMORY)
            return []
        limit = self._budget.max_memories
        if limit <= 0:
            return []
        try:
            return self._memory_retrieval.retrieve(user_message, limit=limit)
        except Exception:  # noqa: BLE001
            logger.exception("agent_context_memory_failed")
            degraded.append(SOURCE_MEMORY)
            return []

    def _experiences(self, session_id: str | None, degraded: list[str]) -> list[Experience]:
        if self._experience_store is None:
            degraded.append(SOURCE_EXPERIENCE)
            return []
        limit = self._budget.max_experiences
        if limit <= 0:
            return []
        try:
            if session_id is not None:
                # Oturum içi deneyimler en ilgili olanlardır; oturum yoksa
                # genel son deneyimlere düşülür.
                scoped = self._experience_store.list_by_session(session_id, limit=limit)
                if scoped:
                    return scoped
            return self._experience_store.list_recent(limit=limit)
        except Exception:  # noqa: BLE001
            logger.exception("agent_context_experience_failed", extra={"session_id": session_id})
            degraded.append(SOURCE_EXPERIENCE)
            return []

    def _traits(self, degraded: list[str]) -> list[UserTrait]:
        if self._user_model is None:
            degraded.append(SOURCE_USER_MODEL)
            return []
        limit = self._budget.max_traits
        if limit <= 0:
            return []
        try:
            return self._user_model.list_traits(
                min_confidence=self._budget.min_trait_confidence,
                limit=limit,
            )
        except Exception:  # noqa: BLE001
            logger.exception("agent_context_user_model_failed")
            degraded.append(SOURCE_USER_MODEL)
            return []

    def _tools(self) -> list[ToolDescriptor]:
        """Kayıtlı tool'ları güvenli tanımlara çevirir.

        `Tool` nesnesinin kendisi bağlama konmaz — yalnızca adı, açıklaması,
        izin seviyesi ve bu oturumda onay gerektirip gerektirmediği taşınır.
        """
        try:
            tools = self._tool_registry.list_tools()
        except Exception:  # noqa: BLE001
            logger.exception("agent_context_tool_registry_failed")
            return []
        return [
            ToolDescriptor(
                name=tool.name,
                description=tool.description,
                permission=tool.permission,
                requires_confirmation=tool.permission not in self._allowed_permissions,
            )
            for tool in tools
        ]
