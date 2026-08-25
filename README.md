# Jarvis Local

Yerel çalışacak kişisel AI asistanı için modüler FastAPI başlangıç projesi. Bu katman yalnızca uygulama omurgasını içerir; LLM, ses, görüntü işleme, kalıcı bellek ve Home Assistant entegrasyonları bilinçli olarak eklenmemiştir.

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
│   ├── adapters/     # Harici sistem köprüleri için ayrılmış alan
│   ├── tools/        # Asistan araçları için ayrılmış alan
│   └── memory/       # Bellek sağlayıcıları için ayrılmış alan
├── tests/
├── scripts/
└── docs/
```
