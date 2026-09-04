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
| Kimlik doğrulama (ağa açıldığında zorunlu) | Çalışıyor |
| Kalıcı notlar (kullanıcı + ajan) | Çalışıyor |
| UI aksiyon kanalı (ajan panelleri açar) | Çalışıyor |
| Araştırma / web erişimi | Çalışıyor, **varsayılan kapalı** |
| Ajan karar katmanı (bağlam → politika → runner) | Çalışıyor |
| Kodlama döngüsü (planla → uygula → doğrula → düzelt) | Çalışıyor, **varsayılan kapalı** |
| LLM Council (çok modelli müzakere, üye başına anahtar) | Çalışıyor, **varsayılan kapalı** |
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

## Kimlik doğrulama

Kural tek cümleyle: **sunucu yerel adres dışına bağlıysa anahtar zorunludur.**

| Bağlı adres | Anahtar | Sonuç |
|---|---|---|
| `127.0.0.1` | yok | Serbest (tek kullanıcılı makine) |
| `127.0.0.1` | var | Anahtar istenir |
| `0.0.0.0` vb. | yok | **Her istek reddedilir** |
| `0.0.0.0` vb. | var | Anahtar istenir |

```dotenv
JARVIS_API_TOKEN=uzun-ve-rastgele-bir-deger
```

Anahtar `X-Jarvis-Token` başlığıyla ya da `Authorization: Bearer` ile gönderilir.
Yalnızca sağlık ucu muaftır; o uç hiçbir kullanıcı verisi döndürmez.

Üçüncü satır bilinçlidir: sunucuyu ağa açmak tek bir ayardır ve onu değiştiren
kişi kimlik katmanının da gerektiğini fark etmeyebilir. Uygulamayı açılışta
reddettirmek yerine her isteği reddetmek, sebebi loglarda değil isteği yapanın
elinde gösterir.

## Notlar ve araştırma

**Notlar** kullanıcının ve ajanın paylaştığı kalıcı yüzeydir; bellekten ayrıdır
ve birleştirilmemelidir. Bellek Jarvis'in *çıkardığı* bilgidir ve kendiliğinden
eskir; not *bilerek yazılmış* bir metindir. Ajanın yazdığı notlar panelde
"Jarvis yazdı" etiketiyle görünür ve ajanın **silme aracı yoktur** — silme
kullanıcının kararıdır.

```dotenv
JARVIS_NOTES_ENABLED=true
JARVIS_NOTES_WRITABLE=true   # ajan yazabilsin mi (her yazma yine onaydan geçer)
```

**Araştırma** ajanın bir şeye bakabilmesidir (kriter 5). Varsayılan kapalıdır
ve açık olsa bile her getirme onaydan geçer:

```dotenv
JARVIS_RESEARCH_ENABLED=true
JARVIS_RESEARCH_ALLOWED_DOMAINS=["docs.python.org","developer.mozilla.org"]
```

Özel ağ adresleri **hiçbir koşulda** getirilemez. Sebebi bir URL'nin dışarıyı
değil içeriyi de gösterebilmesidir: `169.254.169.254` bulut sağlayıcısının
kimlik sunucusu, `127.0.0.1:8000/api/admin/llm` ise uygulamanın kendi yönetim
ucudur. Kontrol ada değil **çözülen adrese** bakar ve yönlendirmeler izlenmez.

## Ajanın ekranı sürmesi

Ajan `show_panel` aracıyla kabuktaki bir paneli açabilir: "notlarıma bak"
dediğinde notlar paneli kendiliğinden açılır.

Mimarinin tek cümlesi: **ajan ekrana metin gönderemez, yalnızca var olan bir
paneli açmasını isteyebilir.** Serbest içerik gönderebilseydi, bir web
sayfasından okunan metin kullanıcının ekranında Jarvis'in sözü gibi
görünebilirdi. Kapalı bir kümeden seçim yapmak, en kötü ihtimalle yanlış
panelin açılması demektir.

- `GET /api/ui/actions?session_id=...` — bekleyen istekleri döndürür ve **tüketir**

İzin seviyesi `READ`'tir: panel açmak dosyaya dokunmaz, komut çalıştırmaz ve
geri alınamaz bir şey yapmaz — kullanıcı paneli kapatabilir. Onaya tabi
olsaydı "notlarını açayım mı?" diye sorup beklemek etkileşimi zorlaştırırdı.

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

## Kodlama döngüsü

Ajan tek bir plan üretip durmak yerine, sonucunu **doğrular**: değişikliği uygular,
test komutunu çalıştırır, hatayı okur ve sınırlı sayıda düzeltme turu dener.

```text
anla → planla → uygula → doğrula → teşhis et → düzelt → (tur sınırına kadar)
```

Açılması **dört ayrı karar** gerektirir; hiçbiri diğerinin yerine geçmez:

```dotenv
JARVIS_CODING_LOOP_ENABLED=true
JARVIS_WORKSPACE_ROOT=C:\yol\proje
JARVIS_WORKSPACE_WRITABLE=true
JARVIS_TERMINAL_ENABLED=true

# İsteğe bağlı ince ayar
JARVIS_CODING_MAX_ITERATIONS=3
JARVIS_CODING_VERIFICATION_TIMEOUT_SECONDS=180
JARVIS_CODING_VERIFICATION_COMMANDS=["pytest -q"]
```

- `POST /api/coding/run` — `{"message": "...", "session_id": "..."}`

Yanıt; görevi, her turun adımlarını, doğrulama sonucunu, `git diff`'i ve yapılan işin
**deterministik** açıklamasını içerir. Birkaç davranış bilinçlidir:

- **Döngü kendini başarılı ilan edemez.** `completed` yalnızca gerçek bir doğrulama
  komutunun sıfır çıkış koduyla verilir; doğrulama çalışmadıysa sonuç
  `applied_unverified` olur, `completed` değil.
- **Onayda durur.** Onay gerektiren bir adıma gelindiğinde o adım ve sonrası
  çalıştırılmaz; onay kaydı, başvuruları çözülmüş argümanlarla açılır ve kimlikleri
  `pending_approval_ids` içinde döner.
- **Doğrulama komutunu model uyduramaz.** Yalnızca yapılandırılmış adaylar arasından
  seçebilir ve o liste de komut politikasının tanıdıklarıyla süzülür.
- Döngü sohbet akışına bağlı değildir; buradaki bir sorun normal sohbeti etkilemez.

Kabuktaki **Ajanlar** başlığı bu döngüyü açar: istek yazılır, turlar adım adım
izlenir, doğrulama sonucu ve `git diff` görülür. Panelde yalnızca `completed`
yeşildir — `applied_unverified` bilinçli olarak sarıdır, çünkü doğrulanmamış bir
değişikliği başarılı göstermek backend'in kendine yasakladığı iddiayı arayüzde
yapmak olurdu.

## Çoklu ajan — Council üyeleri

Council çoktan çok modelliydi; eksik olan tek şey her üyenin **kendi
servisine, kendi anahtarıyla** gidebilmesiydi. Artık üyeler tek tek
tanımlanıyor ve değişiklik **çalışma zamanında** devreye giriyor:

- `GET    /api/admin/council` — üyeler ve Council'ın fiilen açık olup olmadığı
- `PUT    /api/admin/council/members/{id}` — üye ekler veya günceller
- `DELETE /api/admin/council/members/{id}` — üyeyi siler

```bash
curl -X PUT localhost:8000/api/admin/council/members/uzak-model \
  -H "Content-Type: application/json" \
  -d '{"kind":"openai_compatible","base_url":"https://api.example.com/v1",
       "model":"gpt-4o","api_key":"sk-...","is_chairman":true}'
```

- **Üye tanımlamak yetmez.** Etkin üye sayısı `JARVIS_COUNCIL_MIN_CANDIDATES`
  (varsayılan 2) altındaysa müzakere kurulmaz; yanıttaki `active` alanı bunu
  açıkça söyler. Sayı altına düşerse Council **sökülür** ve sistem tek-LLM
  cevabına döner — yarım bir Council'dan iyidir.
- **Anahtar geri okunmaz.** Yanıtlarda yalnızca `has_api_key` döner. Anahtar
  gönderilmeden yapılan güncelleme mevcut anahtarı korur; silmek için
  `clear_api_key` gerekir.
- **Chairman tektir.** Yeni bir chairman atandığında eskisi sıradan üyeye
  döner. İşaretli chairman yoksa ilk üyenin sağlayıcısı yeniden kullanılır.
- **Model adı Council çekirdeğine ulaşmaz.** Üyeler `member-1`, `member-2`
  gibi opaque kimliklerle görünür; akran değerlendirmesinin anonimliği buna
  bağlıdır.
- Üye tanımlıysa `JARVIS_COUNCIL_MODELS` ayarı **yok sayılır** — ikisi birden
  geçerli olsaydı, panelden üye silen kullanıcı ayardan gelenlerin sessizce
  devam ettiğini görürdü.

### Onay ve geri alma uçları

- `GET  /api/approvals` — onay bekleyen çağrılar
- `POST /api/approvals/{id}` — `{"decision": "approve"}` veya `{"decision": "reject"}`
- `GET  /api/checkpoints` — geri alma noktaları
- `POST /api/checkpoints/{id}/restore` — dosyayı eski hâline döndürür
- `GET  /api/admin/llm` — sağlayıcı yapılandırması (anahtar hariç)
- `PUT  /api/admin/llm` — sağlayıcıyı değiştirir ve hemen devreye alır

> Bütün uçlar `JARVIS_API_TOKEN` ile korunur; sunucu yerel adres dışına bağlıysa
> anahtar zorunludur. Yönetim uçları ayrıca `JARVIS_ADMIN_TOKEN` isteyebilir —
> "bu sunucuya erişebilir misin" ile "sağlayıcıyı değiştirebilir misin" ayrı
> sorulardır ve cevapları aynı kişide olmak zorunda değildir.

## Yapılandırma

Tüm ayarlar `JARVIS_` önekiyle ortam değişkenlerinden veya `.env` dosyasından okunur.
Örnekler için `.env.example`. `.env` sürüm kontrolüne alınmaz ve ajan tarafından okunamaz.

## Docker

`Dockerfile` uygulamayı `0.0.0.0:8000`'de çalıştıracak şekilde hazırdır.
`docker-compose.yml` henüz boştur. Backend frontend'i sunmaz; geliştirmede Vite ayrı çalışır.

## Lisans

MIT — bkz. [LICENSE](LICENSE). Kullanabilir, değiştirebilir ve dağıtabilirsiniz;
tek koşul telif notunun korunması. Yazılım garanti verilmeden sunulur.

## Klasör yapısı

```text
jarvis/
├── app/
│   ├── api/          # FastAPI endpoint'leri (chat, agent, coding, approvals, checkpoints)
│   ├── agent/        # Karar katmanı: bağlam, politika, runner
│   ├── coding/       # Kodlama döngüsü: planla, uygula, doğrula, teşhis et, düzelt
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
