"""ElevenLabs speech services (TTS/STT) API endpoints."""

import os
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.services.speech import SpeechService

router = APIRouter(tags=["speech"])


class TTSRequest(BaseModel):
    text: str
    voice_id: str = "salli"
    output_path: str = "output.mp3"


class STTRequest(BaseModel):
    audio_data: str  # Base64 encoded audio
    model: str = "echo"


class TTSResponse(BaseModel):
    audio_path: str


@router.post("/speech/tts", response_model=TTSResponse, status_code=status.HTTP_200_OK)
async def text_to_speech(request_body: TTSRequest, request: Request) -> TTSResponse:
    """
    Text-to-Speech endpoint - ElevenLabs ile ses oluşturma.
    
    Args:
        text: Seslendirilecek metin
        voice_id: Voice identifier (default: Salli - kadın)
        output_path: Çıktı dosya yolu
        
    Returns:
        Oluşturulan ses dosyası yolu
    """
    try:
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "elevenlabs_missing_key", "message": "ELEVENLABS_API_KEY not configured"},
            )
        
        speech_service = SpeechService(api_key=api_key)
        output_path = await speech_service.text_to_speech(
            text=request_body.text,
            voice_id=request_body.voice_id,
            output_path=request_body.output_path,
        )
        return TTSResponse(audio_path=output_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "speech_error", "message": str(e)},
        ) from e


@router.post("/speech/stt", response_model=dict, status_code=status.HTTP_200_OK)
async def speech_to_text(request_body: STTRequest, request: Request) -> dict:
    """
    Speech-to-Text endpoint - ElevenLabs ile transcription.
    
    Args:
        audio_data: Base64 encoded audio data
        model: STT model identifier
        
    Returns:
        Transkripsiyon metni
    """
    try:
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "elevenlabs_missing_key", "message": "ELEVENLABS_API_KEY not configured"},
            )
        
        # Geçici: Placeholder - gerçek STT implementation daha sonra eklenecek
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "stt_not_implemented", "message": "Speech-to-text yetkinin implementation'ı devam ediyor"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "speech_error", "message": str(e)},
        ) from e
