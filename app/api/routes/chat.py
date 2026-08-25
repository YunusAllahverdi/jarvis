"""Text tabanlı Jarvis chat API'si."""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from app.adapters.llm.base import LLMConfigurationError, LLMProviderError, LLMUnavailableError

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Bir text chat isteği."""

    message: str = Field(max_length=10_000)
    session_id: str | None = Field(default=None, max_length=128)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message boş olamaz")
        return normalized

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("session_id boş olamaz")
        return normalized


class ChatResponse(BaseModel):
    """Bir text chat cevabı."""

    response: str
    session_id: str


@router.post("/chat", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def chat(request_body: ChatRequest, request: Request) -> ChatResponse:
    """Kullanıcı mesajını orchestrator'a iletir."""

    try:
        result = await request.app.state.chat_orchestrator.respond(
            request_body.message,
            request_body.session_id,
        )
    except (LLMConfigurationError, LLMUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "llm_unavailable", "message": str(exc)},
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "llm_provider_error", "message": str(exc)},
        ) from exc

    return ChatResponse(response=result.response, session_id=result.session_id)
