# Jarvis Local

Yerel çalışabilen kişisel AI asistanı. Modüler FastAPI backend, React tabanlı bir kabuk ve
kullanıcı onayına tabi bir ajan katmanı içerir.

Ses ve görüntü işleme, Home Assistant entegrasyonu ve bilgisayar kontrolü bu projede
**henüz yoktur**.

## Ne var

| Katman | Durum |
|---|---|
| Sohbet akışı (Ollama üzerinden) | Çalışıyor |
| Kalıcı bellek (episodic / semantic / experience, SQLite) | Çalışıyor |
| Öğrenme ve kullanıcı modeli | Çalışıyor |
| Ajan karar katmanı (bağlam → politika → runner) | Çalışıyor |
| LLM Council (çok modelli müzakere) | Çalışıyor, **varsayılan kapalı** |
| Güvenlik: izin politikası, onay akışı, denetim kaydı | Çalışıyor |
| Dosya araçları (oku / yaz / ara / proje özeti) | Çalışıyor, **varsayılan kapalı** |
| Terminal aracı | Çalışıyor, **varsayılan kapalı** |
| Geri alma (checkpoint / restore) | Çalışıyor |
| Frontend (WebGL orb kabuğu) | Çalışıyor |
| Sağlayıcı yönetim paneli (çalışma zamanında değiştirilebilir) | Çalışıyor |

## Güvenlik modeli

Ajanın yetkileri **varsayılan olarak kapalıdır** ve her biri ayrı bir karardır. Bir şeyi
açmadan ajan onu yapamaz.

**Üç izin seviyesi.** `READ` serbesttir. `WRITE` her zaman kullanıcı onayından geçer.
`DANGEROUS` yalnızca terminal açıkken onaylanabilir, kapalıyken reddedilir. Karar tek bir
`ToolPermissionPolicy` örneğinde verilir; hem yürütme sınırı hem ajan bağlamı aynı örneği
kullanır, dolayısıyla iki yerde ayrışamaz.

**Onay tek kullanımlıktır ve tam olarak gösterilen çağrıya bağlıdır.** Araç adı ve
argümanlar istek açılırken dondurulur, onay anında istemciden alınmaz. Aynı onay ikinci kez
kullanılamaz ve süresi dolar. Onay kapalı bir aracı açmaz — yalnızca zaten onaya tabi olanı
çalıştırılabilir kılar.

**Her çağrı denetim kaydına yazılır** — çalışanlar da, reddedilenler de, onay bekleyenler
de. Argümanlar maskelenerek kaydedilir.

**Dosya erişimi bir çalışma köküne hapsedilir.** Dizin dışına çıkma, sembolik bağla kaçış ve
`.env` / özel anahtar gibi hassas dosyalar engellenir. Kapalı dosyalar listede ve aramada hiç
görünmez.

**Komutlar kabuk olmadan çalışır.** Argüman listesine ayrıştırılıp doğrudan çalıştırılır;
zincirleme ve yönlendirme engellenen değil, mümkün olmayan şeylerdir. Alt sürece ortam
değişkenleri devralınmaz.

**Değişiklikler geri alınabilir.** Bir dosya değiştirilmeden önceki hâli kaydedilir. Geri
alma bir kullanıcı eylemidir (`/api/checkpoints`), ajanın bir aracı değildir.

Araçların ayrıntılı tasarımı için [docs/tools.md](docs/tools.md).

## Gereksinimler

- Python 3.12 veya üstü
- Node.js 20+ (yalnızca frontend için)
- Ollama (sohbetin çalışması için — aşağıya bakın)

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

### Frontend

```powershell
npm install --prefix frontend
npm run dev --prefix frontend
```

Vite `http://localhost:5173` adresinde açılır ve `/api` isteklerini backend'e proxy'ler.
Backend kapalıyken kabuk yüklenir ama sohbet bağlantı hatası verir.

## Test

```powershell
pytest
```

## Text Brain (Ollama)

Jarvis, `POST /api/chat` isteğini orchestrator üzerinden Ollama'nın `POST /api/chat`
API'sine iletir. API katmanı LLM sağlayıcısına doğrudan bağlı değildir; `LLMProvider`
arayüzünü uygulayan yeni sağlayıcılar eklenebilir.

### Ollama kurulumu ve model indirme

1. Ollama'yı işletim sisteminiz için [resmî indirme sayfasından](https://ollama.com/download) kurun.
2. Bir modeli indirin, örneğin:

   ```powershell
   ollama pull gemma3
   ```

3. Gerekirse sunucuyu başlatın:

   ```powershell
   ollama serve
   ```

4. `.env.example` dosyasını `.env` olarak kopyalayıp indirdiğiniz model adını girin:

   ```dotenv
   JARVIS_OLLAMA_BASE_URL=http://127.0.0.1:11434
   JARVIS_OLLAMA_MODEL=gemma3
   ```

Model adı kodda sabit değildir. `JARVIS_OLLAMA_MODEL` boşsa health endpoint çalışmaya devam
eder, chat endpoint açıklayıcı bir `503` döndürür.

Tool-calling için Ollama'nın native sözleşmesi kullanılır; bunu destekleyen bir model
seçmeniz gerekir ([Ollama Tool Calling](https://docs.ollama.com/capabilities/tool-calling)).

### Chat isteği

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/chat" `
  -ContentType "application/json" `
  -Body '{"message":"Merhaba Jarvis"}'
```

Yanıttaki `session_id` sonraki isteklerde gönderilerek aynı konuşma sürdürülür. Konuşma
dizisi RAM'de tutulur ve yeniden başlatmada silinir; kalıcı bellek ondan ayrıdır ve
SQLite'ta saklanır.

## Sağlayıcı seçimi

Kabuktaki dişli ikonundan açılan panelden sağlayıcı çalışma zamanında
değiştirilebilir — yeniden başlatma gerekmez. İki tür desteklenir:

- **Ollama (yerel)** — anahtar gerektirmez.
- **OpenAI uyumlu** — `/chat/completions` sözleşmesini konuşan her servis:
  Gemini (AI Studio), Groq, OpenRouter, LM Studio ve benzerleri. Adres, model
  ve API anahtarı panelden girilir.

Anahtar sunucuda saklanır ve **panele geri dönmez**; yalnızca tanımlı olup
olmadığı gösterilir. Boş bırakılarak kaydedilirse mevcut anahtar korunur,
silmek için ayrı bir düğme vardır.

> **Yönetim uçları hakkında:** Bu uçlar bir API anahtarı kabul ediyor ve LLM
> adresini değiştirebiliyor. Uygulamada henüz kimlik katmanı olmadığı için
> şu kural uygulanır: sunucu `127.0.0.1` dışına bağlıysa ve
> `JARVIS_ADMIN_TOKEN` tanımlanmamışsa yönetim uçları çalışmaz. Anahtar
> tanımlıysa her istekte `X-Admin-Token` başlığı istenir.

```dotenv
# Sunucuyu dışarı açacaksan zorunlu
JARVIS_ADMIN_TOKEN=uzun-ve-rastgele-bir-deger
```

## Ajan yeteneklerini açma

Hepsi `.env` üzerinden ve hepsi varsayılan kapalı:

```dotenv
# Dosya okuma — bir çalışma kökü tanımlanmadan dosya araçları hiç kaydedilmez
JARVIS_WORKSPACE_ROOT=C:\yol\proje

# Dosya yazma — okumaktan AYRI bir karar; açık olsa da her yazma onaydan geçer
JARVIS_WORKSPACE_WRITABLE=true

# Terminal — açıksa DANGEROUS seviyesi onaylanabilir hâle gelir
JARVIS_TERMINAL_ENABLED=true
JARVIS_TERMINAL_ALLOWED_COMMANDS=["pytest","ruff"]
```

### Onay ve geri alma uçları

- `GET  /api/approvals` — onay bekleyen çağrılar
- `POST /api/approvals/{id}` — `{"decision": "approve"}` veya `{"decision": "reject"}`
- `GET  /api/checkpoints` — geri alma noktaları
- `POST /api/checkpoints/{id}/restore` — dosyayı eski hâline döndürür
- `GET  /api/admin/llm` — sağlayıcı yapılandırması (anahtar hariç)
- `PUT  /api/admin/llm` — sağlayıcıyı değiştirir ve hemen devreye alır

> Bu uçlarda **kimlik doğrulama yoktur**, çünkü uygulamada henüz bir kimlik katmanı yok.
> Sunucu `127.0.0.1` dışına açılmadan önce eklenmelidir.

## Yapılandırma

Tüm ayarlar `JARVIS_` önekiyle ortam değişkenlerinden veya `.env` dosyasından okunur.
Örnekler için `.env.example`. `.env` sürüm kontrolüne alınmaz ve ajan tarafından okunamaz.

## Docker

`Dockerfile` uygulamayı `0.0.0.0:8000`'de çalıştıracak şekilde hazırdır.
`docker-compose.yml` henüz boştur. Backend frontend'i sunmaz; geliştirmede Vite ayrı çalışır.

## Klasör yapısı

```text
jarvis/
├── app/
│   ├── api/          # FastAPI endpoint'leri (chat, agent, approvals, checkpoints)
│   ├── agent/        # Karar katmanı: bağlam, politika, runner
│   ├── council/      # Çok modelli müzakere (varsayılan kapalı)
│   ├── learning/     # Kullanıcı özellikleri ve çıkarım
│   ├── memory/       # Episodic / semantic / experience + SQLite depolar
│   ├── security/     # İzin, onay, denetim, yol bekçisi, komut politikası, checkpoint
│   ├── services/     # Orchestrator ve servis katmanı
│   ├── adapters/     # Harici sistem köprüleri (Ollama LLM provider)
│   ├── config/       # Pydantic Settings
│   ├── core/         # Ortak altyapı (structured logging)
│   ├── prompts/      # Sistem prompt metinleri
│   └── tools/        # Araçlar: dosya, terminal, git, proje özeti, bağlam
├── frontend/         # React + Vite kabuk (WebGL orb)
├── design/           # Claude Design tuval çıktısı (görsel referans)
├── tests/
├── scripts/
└── docs/
```
