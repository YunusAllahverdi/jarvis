# Jarvis Local

Yerel çalışacak kişisel AI asistanı için modüler FastAPI başlangıç projesi. Step 1 ile yalnızca text tabanlı Ollama LLM akışı eklenmiştir. Ses, görüntü işleme, kalıcı bellek, Home Assistant ve computer control bu projede henüz yoktur.

## Gereksinimler

- Python 3.12 veya üstü
- `pip`

## Kurulum ve çalıştırma

PowerShell'de proje klasöründe:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Uygulama `http://127.0.0.1:8000` adresinde çalışır.

- Health check: `GET /api/v1/health`
- OpenAPI arayüzü: `http://127.0.0.1:8000/docs`

## Test

```powershell
pytest
```

## Text Brain (Ollama)

Jarvis, `POST /api/chat` isteğini orchestrator üzerinden Ollama'nın `POST /api/chat` API'sine iletir. API katmanı LLM sağlayıcısına doğrudan bağlı değildir; `LLMProvider` arayüzünü uygulayan yeni sağlayıcılar daha sonra eklenebilir.

### Ollama kurulumu ve model indirme

1. Ollama'yı işletim sisteminiz için [resmî Ollama indirme sayfasından](https://ollama.com/download) kurun.
2. Bir modeli yerelde indirin; örneğin:

   ```powershell
   ollama pull gemma3
   ```

3. Gerekirse yerel sunucuyu başlatın:

   ```powershell
   ollama serve
   ```

   `ollama pull`, `ollama run` ve `ollama serve` komutları resmî [Ollama CLI referansında](https://docs.ollama.com/cli) açıklanır.

4. `.env.example` dosyasını `.env` olarak kopyalayın ve indirdiğiniz model adını girin:

   ```dotenv
   JARVIS_OLLAMA_BASE_URL=http://127.0.0.1:11434
   JARVIS_OLLAMA_MODEL=gemma3
   JARVIS_OLLAMA_TIMEOUT_SECONDS=30
   ```

Model adı kodda sabit değildir. `JARVIS_OLLAMA_MODEL` ayarlanmamışsa uygulama health endpoint'i çalışmaya devam eder, ancak chat endpoint'i açıklayıcı bir `503` döndürür.

### Chat isteği

Uygulamayı başlattıktan sonra:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/chat" `
  -ContentType "application/json" `
  -Body '{"message":"Merhaba Jarvis"}'
```

İlk yanıtın `session_id` değerini sonraki isteklerde göndererek aynı RAM tabanlı konuşmayı sürdürebilirsiniz:

```json
{
  "message": "Önceki mesajımı özetle",
  "session_id": "ilk-yanittan-gelen-session-id"
}
```

Konuşmalar yalnızca uygulama süreci boyunca RAM'de saklanır; yeniden başlatıldığında silinir.

## Yapılandırma

Tüm ayarlar `JARVIS_` önekiyle ortam değişkenlerinden veya `.env` dosyasından okunur. Örnekler için `.env.example` dosyasına bakın. `.env` sürüm kontrolüne alınmaz.

## Docker hazırlığı

`Dockerfile`, `.dockerignore` ve boş `docker-compose.yml` gelecek aşama için eklendi. Bu aşamada LLM, Home Assistant, veri tabanı veya başka bir servis container'a alınmamıştır.

## Klasör yapısı

```text
jarvis/
├── app/
│   ├── api/          # FastAPI endpoint'leri
│   ├── config/       # Pydantic Settings
│   ├── core/         # Ortak altyapı (structured logging)
│   ├── services/     # İş mantığı için ayrılmış alan
│   ├── adapters/     # Harici sistem köprüleri (Ollama LLM provider)
│   ├── tools/        # Asistan araçları için ayrılmış alan
│   └── memory/       # Bellek sağlayıcıları için ayrılmış alan
├── tests/
├── scripts/
└── docs/
```
