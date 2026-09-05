"""ElevenLabs seslendirme (TTS) istemcisi.

Tarayıcının kendi `speechSynthesis` motoru zaten var ve ücretsiz. Bu
servis onun YERİNE değil, YANINDA duruyor: tarayıcı sesi cihazdan cihaza
değişir (tablette bambaşka bir ses çıkar) ve Türkçesi çoğu platformda
kötüdür. ElevenLabs sabit ve iyi bir ses verir — karşılığında para ve
bir ağ turu ister.

Bu yüzden yetenek KAPALI doğar: anahtar yoksa servis hiç kurulmaz ve
arayüz tarayıcı motoruyla çalışmaya devam eder.

Ses verisi diske YAZILMAZ. Önceki denemede `output.mp3` adında sabit bir
dosyaya yazılıyordu; bu hem sunucunun çalışma dizinini kirletiyordu hem
de iki eşzamanlı istek birbirinin dosyasını eziyordu. Ses doğrudan
çağırana akıtılır.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.elevenlabs.io/v1"


class SpeechError(RuntimeError):
    """Seslendirme başarısız oldu.

    Mesaj kullanıcıya gösterilir, bu yüzden anahtar ASLA içine konmaz.
    """


class SpeechService:
    """ElevenLabs metin-konuşma servisi."""

    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str,
        model_id: str,
        timeout_seconds: float = 30.0,
        max_chars: int = 2500,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """
        Args:
            api_key: `xi-api-key` başlığında gönderilecek anahtar.
            voice_id: ElevenLabs ses kimliği (insan okunur ad DEĞİL).
            model_id: Kullanılacak model.
            timeout_seconds: Tek bir isteğin üst süresi.
            max_chars: Seslendirilecek en uzun metin.
            transport: Testlerin ağa çıkmadan gerçek serileştirmeyi
                sınayabilmesi için. Üretimde verilmez.
        """
        self._api_key = api_key.strip()
        self._voice_id = voice_id.strip()
        self._model_id = model_id.strip()
        self._timeout = timeout_seconds
        self._max_chars = max_chars
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    @property
    def voice_id(self) -> str:
        """Varsayılan ses; arayüz hangi sesin kullanıldığını gösterebilsin."""

        return self._voice_id

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            headers={"xi-api-key": self._api_key},
        )

    async def stream(
        self, text: str, *, voice_id: str | None = None
    ) -> AsyncIterator[bytes]:
        """Metni seslendirir ve ses baytlarını parça parça verir.

        Gerçek akış kullanılır (`client.stream`): yanıtın tamamını belleğe
        alıp sonra parçalamak, ilk sesin duyulması için tüm dosyanın
        inmesini beklemek demekti — uzun bir cevapta bu saniyeler eder.

        Raises:
            SpeechError: Metin boşsa, sınırı aşıyorsa ya da servis
                erişilemez/hata döndürdüyse.
        """
        clean = text.strip()
        if not clean:
            raise SpeechError("Seslendirilecek metin boş.")
        if len(clean) > self._max_chars:
            raise SpeechError(
                f"Metin çok uzun ({len(clean)} karakter). "
                f"Sınır {self._max_chars} karakter."
            )

        payload = {
            "text": clean,
            "model_id": self._model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        url = f"{self._base_url}/text-to-speech/{voice_id or self._voice_id}/stream"

        client = self._client()
        try:
            async with client.stream("POST", url, json=payload) as response:
                if response.is_error:
                    # Gövde hata ayrıntısını taşır ama akış modunda önce
                    # okunması gerekir; okunmazsa boş bir metin kalırdı.
                    await response.aread()
                    raise SpeechError(self._error_message(response))

                logger.info("tts_started", extra={"chars": len(clean)})
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.TimeoutException as exc:
            raise SpeechError(
                f"Seslendirme {self._timeout:g} saniyede yanıt vermedi."
            ) from exc
        except httpx.RequestError as exc:
            raise SpeechError("ElevenLabs'e ulaşılamadı.") from exc
        finally:
            await client.aclose()

    async def voices(self) -> list[dict[str, str]]:
        """Hesaptaki sesleri döndürür.

        Arayüzün ses seçebilmesi için gerekli: ElevenLabs kimlikleri
        rastgele dizelerdir ve kullanıcının onları ezberlemesi beklenemez.
        """
        client = self._client()
        try:
            response = await client.get(f"{self._base_url}/voices")
        except httpx.TimeoutException as exc:
            raise SpeechError("Ses listesi zaman aşımına uğradı.") from exc
        except httpx.RequestError as exc:
            raise SpeechError("ElevenLabs'e ulaşılamadı.") from exc
        finally:
            await client.aclose()

        if response.is_error:
            raise SpeechError(self._error_message(response))

        try:
            data = response.json()
            return [
                {
                    "voice_id": str(v["voice_id"]),
                    "name": str(v.get("name", "")),
                }
                for v in data["voices"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise SpeechError("Ses listesi beklenen biçimde gelmedi.") from exc

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        """Hata gövdesinden okunabilir bir mesaj çıkarır.

        Anahtar yalnızca istek BAŞLIĞINDA taşınır; gövdede bulunmaz,
        dolayısıyla buradan sızması mümkün değildir.
        """
        if response.status_code == 401:
            return "ElevenLabs anahtarı geçersiz."
        if response.status_code == 404:
            return "Böyle bir ses kimliği yok. Ayarlardan geçerli bir ses seçin."
        if response.status_code == 429:
            return "ElevenLabs kotası doldu ya da istek sınırı aşıldı."

        try:
            detail = response.json().get("detail")
            if isinstance(detail, dict) and isinstance(detail.get("message"), str):
                return f"ElevenLabs hatası: {detail['message']}"
            if isinstance(detail, str):
                return f"ElevenLabs hatası: {detail}"
        except ValueError:
            pass
        return f"ElevenLabs {response.status_code} döndü."
