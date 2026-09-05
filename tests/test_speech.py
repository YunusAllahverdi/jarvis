"""ElevenLabs seslendirme.

Testlerin ağırlığı, önceki denemeyi çalışmaz kılan üç hatanın geri
gelmemesi üzerinde:

  1. Anahtar `.env`'den OKUNABİLMELİ. Eski kod `os.getenv` kullanıyordu
     ve `.env` pydantic-settings ile okunduğu için anahtar hiçbir zaman
     görünmüyordu — dosyada dururken "tanımlı değil" hatası veriyordu.
  2. Ses kimliği İSTEĞE konmalı. Eski varsayılan "salli" bir AWS Polly
     adıydı; geçerli anahtarla bile 404 dönerdi.
  3. Hata, ses baytları akmaya BAŞLAMADAN yakalanmalı. Aksi hâlde yanıt
     çoktan 200 olarak açılmış olur ve tarayıcı sebebini öğrenemeden
     bozuk bir dosya indirir.

Kapsam:
 1. Anahtar yoksa servis hiç kurulmaz (yetenek kapalı doğar)
 2. Anahtar .env önekiyle okunur
 3. Uç kapalıyken 503
 4. Metin, model ve ses kimliği isteğe doğru konur
 5. Anahtar `xi-api-key` başlığında gider
 6. Ses baytları akar
 7. İstek başına ses kimliği geçersiz kılınabilir
 8. Boş metin reddedilir
 9. Sınırı aşan metin reddedilir (maliyet koruması)
10. 401 okunabilir mesaja çevrilir
11. 404 (yanlış ses) okunabilir mesaja çevrilir
12. Hata mesajı anahtarı SIZDIRMAZ
13. Hata, akış açılmadan önce 502'ye çevrilir
14. Ses listesi çözülür
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.speech import router as speech_router
from app.config.settings import Settings
from app.main import _build_speech_service
from app.services.speech import SpeechError, SpeechService

_KEY = "sk-eleven-cok-gizli-anahtar-123456"


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _service(handler, **kwargs) -> SpeechService:
    """Ağa çıkmadan gerçek serileştirmeyi sınayan servis."""
    options = {
        "api_key": _KEY,
        "voice_id": "ses-kimligi",
        "model_id": "eleven_multilingual_v2",
        "transport": httpx.MockTransport(handler),
    }
    options.update(kwargs)
    return SpeechService(**options)  # type: ignore[arg-type]


async def _collect(service: SpeechService, text: str = "merhaba", **kwargs) -> bytes:
    return b"".join([chunk async for chunk in service.stream(text, **kwargs)])


def _client(service: SpeechService | None) -> TestClient:
    app = FastAPI()
    app.state.speech_service = service
    app.include_router(speech_router, prefix="/api")
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1-3. Yetenek kapalı doğar
# ---------------------------------------------------------------------------


def test_no_key_means_no_service() -> None:
    """Anahtar yoksa servis hiç kurulmaz; her yetenek kapalı doğar."""
    assert _build_speech_service(Settings(elevenlabs_api_key="")) is None


def test_key_is_read_from_the_jarvis_prefixed_setting() -> None:
    """Anahtar `.env`'den okunabilmeli.

    Eski kod `os.getenv("ELEVENLABS_API_KEY")` kullanıyordu; `.env` bu
    uygulamada pydantic-settings ile okunuyor ve o, değerleri işlem
    ortamına koymuyor. Sonuç: anahtar dosyada dururken sürekli
    "tanımlı değil" hatası.
    """
    service = _build_speech_service(Settings(elevenlabs_api_key=_KEY))

    assert service is not None
    assert service.voice_id  # varsayılan ses de ayardan gelir


def test_endpoint_is_closed_when_the_service_is_absent() -> None:
    response = _client(None).post("/api/speech/tts", json={"text": "merhaba"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "speech_unavailable"


# ---------------------------------------------------------------------------
# 4-7. İstek biçimi ve akış
# ---------------------------------------------------------------------------


def _audio(chunks: bytes = b"ID3ses") :
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=chunks)

    return seen, handler


def test_text_model_and_voice_reach_the_request() -> None:
    """Ses kimliği ADRESTE, metin ve model gövdede taşınır."""
    seen, handler = _audio()
    _run(_collect(_service(handler)))

    request = seen[0]
    body = json.loads(request.content.decode("utf-8"))
    assert "/text-to-speech/ses-kimligi/stream" in str(request.url)
    assert body["text"] == "merhaba"
    assert body["model_id"] == "eleven_multilingual_v2"


def test_api_key_travels_in_the_xi_api_key_header() -> None:
    seen, handler = _audio()
    _run(_collect(_service(handler)))

    assert seen[0].headers["xi-api-key"] == _KEY


def test_audio_bytes_are_streamed_back() -> None:
    _, handler = _audio(b"ID3-ses-verisi")

    assert _run(_collect(_service(handler))) == b"ID3-ses-verisi"


def test_voice_can_be_overridden_per_request() -> None:
    """Tek bir istek için başka bir ses seçilebilmeli."""
    seen, handler = _audio()
    _run(_collect(_service(handler), voice_id="baska-ses"))

    assert "/text-to-speech/baska-ses/stream" in str(seen[0].url)


# ---------------------------------------------------------------------------
# 8-9. Girdi sınırları
# ---------------------------------------------------------------------------


def test_empty_text_is_rejected() -> None:
    _, handler = _audio()
    with pytest.raises(SpeechError):
        _run(_collect(_service(handler), text="   "))


def test_text_over_the_limit_is_rejected() -> None:
    """Sınır maliyet içindir: ElevenLabs karakter başına ücretlendirir."""
    _, handler = _audio()
    with pytest.raises(SpeechError, match="çok uzun"):
        _run(_collect(_service(handler, max_chars=10), text="a" * 11))


# ---------------------------------------------------------------------------
# 10-13. Hata yolları
# ---------------------------------------------------------------------------


def test_invalid_key_becomes_a_readable_message() -> None:
    handler = lambda request: httpx.Response(401, json={"detail": "unauthorized"})
    with pytest.raises(SpeechError, match="anahtarı geçersiz"):
        _run(_collect(_service(handler)))


def test_unknown_voice_becomes_a_readable_message() -> None:
    """Eski varsayılan "salli" tam da bunu döndürürdü."""
    handler = lambda request: httpx.Response(404, json={"detail": "voice not found"})
    with pytest.raises(SpeechError, match="ses kimliği"):
        _run(_collect(_service(handler)))


def test_error_message_does_not_leak_the_api_key() -> None:
    handler = lambda request: httpx.Response(500, text="boom")
    with pytest.raises(SpeechError) as excinfo:
        _run(_collect(_service(handler)))

    assert _KEY not in str(excinfo.value)


def test_failure_is_reported_before_the_stream_opens() -> None:
    """Hata 502 olmalı, 200 + bozuk ses dosyası DEĞİL.

    Akış doğrudan yanıta bağlansaydı, başlıklar çoktan 200 gitmiş olur ve
    tarayıcı sebebini öğrenemeden bozuk bir dosya indirirdi.
    """
    handler = lambda request: httpx.Response(401, json={"detail": "unauthorized"})
    response = _client(_service(handler)).post("/api/speech/tts", json={"text": "merhaba"})

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "speech_failed"


def test_successful_request_returns_audio() -> None:
    _, handler = _audio(b"ID3-ses")
    response = _client(_service(handler)).post("/api/speech/tts", json={"text": "merhaba"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3-ses"


# ---------------------------------------------------------------------------
# 14. Ses listesi
# ---------------------------------------------------------------------------


def test_voice_list_is_parsed() -> None:
    """Kimlikler rastgele dizelerdir; kullanıcı onları ezberleyemez."""
    handler = lambda request: httpx.Response(
        200,
        json={"voices": [{"voice_id": "abc123", "name": "Rachel", "extra": 1}]},
    )
    response = _client(_service(handler)).get("/api/speech/voices")

    assert response.status_code == 200
    body = response.json()
    assert body["voices"] == [{"voice_id": "abc123", "name": "Rachel"}]
    assert body["current"] == "ses-kimligi"
