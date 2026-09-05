"""Seslendirme uçları.

Ses, dosya yolu olarak DEĞİL doğrudan bayt olarak döner: tarayıcı sesi
çalabilmek için baytları ister ve sunucunun diskindeki bir yol ona hiçbir
şey ifade etmez. Ayrıca dosya bırakmamak, iki eşzamanlı isteğin
birbirinin çıktısını ezmesini de imkânsız kılar.

Servis kurulu değilse (anahtar yok) uçlar 503 döner. Bu bir hata değil,
kapalı bir yetenektir — arayüz bunu görünce tarayıcının kendi ses
motoruna düşer ve kullanıcı için hiçbir şey bozulmaz.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.speech import SpeechError, SpeechService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["speech"], prefix="/speech")

_UNAVAILABLE_DETAIL = {
    "code": "speech_unavailable",
    "message": (
        "Seslendirme kapalı. .env dosyasına JARVIS_ELEVENLABS_API_KEY "
        "ekleyip sunucuyu yeniden başlatın."
    ),
}


class TTSRequest(BaseModel):
    """Seslendirilecek metin."""

    text: str = Field(min_length=1, max_length=10_000)

    voice_id: str | None = Field(default=None, max_length=100)
    """Bu istek için ses. Verilmezse ayarlardaki varsayılan kullanılır."""


class VoiceView(BaseModel):
    """Hesaptaki bir ses."""

    voice_id: str
    name: str


class VoiceListResponse(BaseModel):
    voices: list[VoiceView] = Field(default_factory=list)
    """Şu an seçili olan ses; arayüz hangisinin kullanıldığını gösterebilsin."""
    current: str = ""


def _service(request: Request) -> SpeechService:
    service = getattr(request.app.state, "speech_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE_DETAIL
        )
    return service


@router.post("/tts")
async def text_to_speech(body: TTSRequest, request: Request) -> StreamingResponse:
    """Metni seslendirir ve MP3 akışı döndürür."""
    service = _service(request)

    # İlk parça BURADA çekiliyor. Akışı doğrudan StreamingResponse'a
    # vermek daha kısa olurdu ama o zaman hata, yanıt başlıkları çoktan
    # 200 olarak gönderildikten SONRA ortaya çıkardı: tarayıcı bozuk bir
    # ses dosyası indirir ve sebebini asla öğrenemezdi.
    iterator = service.stream(body.text, voice_id=body.voice_id)
    try:
        first = await anext(iterator)
    except StopAsyncIteration:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "speech_empty", "message": "Ses üretilemedi."},
        ) from None
    except SpeechError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "speech_failed", "message": str(exc)},
        ) from exc

    async def body_stream():
        yield first
        async for chunk in iterator:
            yield chunk

    return StreamingResponse(
        body_stream(),
        media_type="audio/mpeg",
        # Tarayıcı sesi indirmek yerine çalsın.
        headers={"Cache-Control": "no-store"},
    )


@router.get("/voices", response_model=VoiceListResponse)
async def list_voices(request: Request) -> VoiceListResponse:
    """Hesaptaki sesleri döndürür."""
    service = _service(request)
    try:
        voices = await service.voices()
    except SpeechError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "speech_failed", "message": str(exc)},
        ) from exc

    return VoiceListResponse(
        voices=[VoiceView(**v) for v in voices], current=service.voice_id
    )
