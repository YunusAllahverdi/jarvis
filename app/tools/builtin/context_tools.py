"""Jarvis'in kendi bilgi katmanlarını okuyan salt-okunur tool'lar.

Bu tool'lar mevcut `Tool` sözleşmesini kullanır — agent için ayrı bir tool
mekanizması icat edilmez. İkisi de yalnızca PUBLIC servis arayüzlerine
bağımlıdır (MemoryRetrievalService, UserModelService); hiçbir somut SQLite
sınıfına veya özel alana erişmezler.

Diğer built-in tool'lardan tek farkı: bunlar durumsuz (stateless) sınıflar
değildir, kurucularında bir servis alırlar. Bu yüzden varsayılan registry'ye
otomatik eklenmezler; yalnızca ilgili servis mevcut olduğunda kaydedilirler
(bkz. `app.tools.defaults.register_context_tools`).

İzin seviyesi READ'dir: ikisi de yalnızca okur, hiçbir kaydı değiştirmez.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.services.memory_retrieval import MemoryRetrievalService
from app.services.user_model_service import UserModelService
from app.tools.base import PermissionLevel, Tool, ToolInput

MEMORY_SEARCH_TOOL_NAME = "memory_search"
USER_PROFILE_TOOL_NAME = "user_profile"


class MemorySearchInput(ToolInput):
    """`memory_search` tool'unun doğrulanmış input'u."""

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class MemorySearchTool(Tool[MemorySearchInput]):
    """Kalıcı bellekte ilgili kayıtları arar (salt okunur)."""

    name = MEMORY_SEARCH_TOOL_NAME
    description = "Kullanıcı hakkında saklanmış bellek kayıtlarında arama yapar."
    permission = PermissionLevel.READ
    input_model = MemorySearchInput

    def __init__(self, *, retrieval: MemoryRetrievalService) -> None:
        """
        Args:
            retrieval: Arama için kullanılacak public getirme servisi.
        """
        self._retrieval = retrieval

    async def execute(self, tool_input: MemorySearchInput) -> dict[str, Any]:
        records = self._retrieval.retrieve(tool_input.query, limit=tool_input.limit)
        return {
            "query": tool_input.query,
            "count": len(records),
            "memories": [
                {
                    "content": record.content,
                    "memory_type": record.memory_type.value,
                    "valid_at": record.valid_at.isoformat(),
                }
                for record in records
            ],
        }


class UserProfileInput(ToolInput):
    """`user_profile` tool'unun doğrulanmış input'u."""

    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=10, ge=1, le=50)


class UserProfileTool(Tool[UserProfileInput]):
    """Kullanıcı hakkında öğrenilmiş kalıcı örüntüleri döndürür (salt okunur)."""

    name = USER_PROFILE_TOOL_NAME
    description = "Kullanıcı hakkında öğrenilmiş tercih ve davranış örüntülerini döndürür."
    permission = PermissionLevel.READ
    input_model = UserProfileInput

    def __init__(self, *, user_model: UserModelService) -> None:
        """
        Args:
            user_model: Profil okumaları için kullanılacak public servis.
        """
        self._user_model = user_model

    async def execute(self, tool_input: UserProfileInput) -> dict[str, Any]:
        profile = self._user_model.build_profile(
            min_confidence=tool_input.min_confidence,
            limit=tool_input.limit,
        )
        return {
            "trait_count": profile.trait_count,
            "traits_by_type": profile.traits_by_type,
            "traits": [
                {
                    "trait_type": trait.trait_type.value,
                    "key": trait.key,
                    "value": trait.value,
                    "confidence": trait.confidence,
                    "evidence_count": trait.evidence_count,
                }
                for trait in profile.traits
            ],
            "interaction": profile.interaction.model_dump(mode="json"),
        }
