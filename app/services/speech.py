"""Speech services (TTS) - ElevenLabs entegrasyonu."""

import logging
import os
from typing import AsyncGenerator
import httpx

logger = logging.getLogger(__name__)


class SpeechService:
    """ElevenLabs TTS servisi ( basit implementation)."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.elevenlabs.io/v1"
        logger.info("SpeechService initialized")

    async def text_to_speech(
        self,
        text: str,
        voice_id: str = "salli",
        output_path: str = "output.mp3"
    ) -> str:
        """
        Text'ten speech'e dönüştürme (TTS).
        
        Args:
            text: Seslendirilecek metin
            voice_id: Voice identifier (varsayılan: Salli)
            output_path: Çıktı dosya yolu
            
        Returns:
            Oluşturulan ses dosyası yolu
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/text-to-speech/{voice_id}",
                    headers={
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_turbo_v2_5",
                        "voice_settings": {
                            "stability": 0.75,
                            "similarity_boost": 0.75,
                        },
                    },
                )
                response.raise_for_status()
                
                with open(output_path, "wb") as f:
                    f.write(response.content)
                
                logger.info("TTS completed: %s", output_path)
                return output_path
        except httpx.HTTPError as e:
            logger.error("TTS failed: %s", str(e))
            raise

    async def text_to_speech_stream(
        self,
        text: str,
        voice_id: str = "salli"
    ) -> AsyncGenerator[bytes, None]:
        """
        Streamed TTS - gerçek zamanlı ses akışı.
        
        Args:
            text: Seslendirilecek metin
            voice_id: Voice identifier
            
        Yields:
            Ses verisi chunk'ları
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/text-to-speech/{voice_id}/stream",
                    headers={
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_turbo_v2_5",
                        "voice_settings": {
                            "stability": 0.75,
                            "similarity_boost": 0.75,
                        },
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                
                for chunk in response.iter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as e:
            logger.error("TTS stream failed: %s", str(e))
            raise
