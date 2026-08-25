"""Kayıtlı araçlar için güvenli ve sağlayıcıdan bağımsız temel sözleşmeler."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.chat import ToolDefinition

InputModelT = TypeVar("InputModelT", bound=BaseModel)


class PermissionLevel(StrEnum):
    """Bir aracın gerektirdiği risk seviyesi."""

    READ = "READ"
    WRITE = "WRITE"
    DANGEROUS = "DANGEROUS"


class ToolInput(BaseModel):
    """Tüm araç input modelleri için katı Pydantic tabanı."""

    model_config = ConfigDict(extra="forbid")


class ToolError(RuntimeError):
    """Tool katmanından kontrollü hata gönderildiğini belirtir."""


class ToolInputValidationError(ToolError):
    """LLM veya API'nin sağladığı tool argument'leri geçersizdir."""


class ToolExecutionError(ToolError):
    """Doğrulanmış input ile araç çalıştırılırken hata oluşmuştur."""


class Tool(ABC, Generic[InputModelT]):
    """Her kayıtlı tool'un uygulaması gereken sözleşme."""

    name: ClassVar[str]
    description: ClassVar[str]
    permission: ClassVar[PermissionLevel]
    input_model: ClassVar[type[InputModelT]]

    @property
    def definition(self) -> ToolDefinition:
        """LLM sağlayıcısına verilebilecek tool şemasını üretir."""

        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
        )

    def validate_input(self, arguments: Mapping[str, Any]) -> InputModelT:
        """Ham tool argümanlarını tool'a ait Pydantic model ile doğrular."""

        try:
            return self.input_model.model_validate(dict(arguments))
        except (TypeError, ValidationError) as exc:
            raise ToolInputValidationError(f"{self.name} için geçersiz input.") from exc

    @abstractmethod
    async def execute(self, tool_input: InputModelT) -> dict[str, Any]:
        """Doğrulanmış input ile tool davranışını çalıştırır."""
