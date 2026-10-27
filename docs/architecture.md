# Mimari

Jarvis, tek bir yerel süreçte çalışan kişisel bir asistandır. Bu belge,
katmanların sorumluluklarını, aralarındaki sınırları ve yeni bir yeteneğin
nereye eklenmesi gerektiğini anlatır.

## Katmanlar

| Katman | Sorumluluk | Nereye |
|---|---|---|
| HTTP taşıma | İstek/yanıt, hata zarfı, kimlik doğrulama, statik kabuk | `app/api` |
| Uygulama iş akışı | Sohbet, bellek, kodlama, konuşma orkestrasyonu | `app/services` |
| Ajan karar katmanı | Bağlam kurma → politika → çalıştırma döngüsü | `app/agent`, `app/coding` |
| Dış sistem köprüleri | LLM sağlayıcıları, haritalar, ağ, ses | `app/adapters`, `app/services/speech.py` |
| Araçlar | Registry, Pydantic doğrulama, izin denetimi | `app/tools` |
| Eklentiler | Yeni yeteneklerin tek yerden eklenmesi | `app/plugins` |
| Bellek | Kalıcı (SQLite) ve geçici bellek | `app/memory`, `app/notes` |
| Güvenlik | İzinler, onaylar, denetim, dosya/ağ/komut bekçileri | `app/security` |
| Ortak teknik altyapı | Logging, request-id, hata zarfı | `app/core` |
| Yapılandırma | Tek ayar kaynağı (`Settings`) | `app/config` |
| Council | Çok modelli müzakere | `app/council` |
| Arayüz kanalı | Ajanın panel açması | `app/ui` |

## İstek akışı

Sohbet:

```
API (/api/chat)
  → ChatOrchestrator
    → LLMProvider (Ollama veya OpenAI uyumlu)
      → ToolRegistry → ToolExecutor → LLM
```

Ajan:

```
API (/api/agent/*)
  → AgentService
    → ContextBuilder (bellek + deneyim + kullanıcı modeli + araç şemaları)
    → DecisionPolicy (rule_based | llm)
    → AgentRunner → ToolExecutor → ToolRegistry
```

`ToolExecutor` izin kararını **kendi vermez**: tek bir `ToolPermissionPolicy`
örneğine sorar. Aynı örnek hem yürütme sınırında hem ajan bağlamında
kullanılır, dolayısıyla iki yerde ayrışamaz.

## Yapılandırma

Tüm ayarlar tek bir yerden gelir: `app/config/settings.py` içindeki
`Settings` (pydantic-settings). Değişkenler `JARVIS_` önekiyle okunur; liste
değerleri JSON olarak verilir. `.env.example` Settings'teki her alanı
belgeler ve bir test bunun eksiksiz kalmasını korur
(`tests/test_settings.py`).

## Gözlemlenebilirlik

- **Request-id.** `RequestIdMiddleware` her isteğe bir `X-Request-ID` atar
  (istemci kendi kimliğini gönderdiyse korur), o istekteki tüm log
  satırlarına iliştirir ve yanıt başlığında döner. Kimlik `contextvars`
  ile taşınır, istekler arası sızmaz.
- **Log biçimi.** `JARVIS_LOG_FORMAT=json|text`. JSON biçimi her satırı bir
  nesne olarak yazar (`timestamp`, `level`, `logger`, `message` + ek alanlar
  + `request_id`) ve üretim/makine tüketimi için uygundur. Text biçimi
  yerel geliştirme için okunabilir.
- **Hata zarfı.** Tüm hata yanıtları aynı biçimdedir:
  `{"detail": {"code": "<kararlı simge>", "message": "<Türkçe metin>"}}`.
  Çerçevenin ürettiği 404/405/422/500 yanıtları da bu zarfa bağlanır
  (`app/api/errors.py`); uçların kendi hata kodları korunur ve 500 iç
  ayrıntı sızdırmaz (ayrıntı log'a yazılır).

## Güvenlik sınırları

- **İzinler.** `READ` serbest, `WRITE` onaya tabi, `DANGEROUS` yalnızca
  terminal açıkken onaylanabilir. Politika **deny-by-default**'tur: listede
  geçmeyen seviye reddedilir, dolayısıyla yeni bir seviye sessizce serbest
  kalmaz.
- **Bekçiler.** Dosya (`PathGuard`), ağ (`NetworkGuard`) ve komut
  (`CommandPolicy`) erişimi ayrı ayrı sınırlar. Bunlar yetki vermez; yalnızca
  verilmiş yetkinin sınırını çizer.
- **Denetim.** Her araç çağrısı — çalışan, reddedilen, onay bekleyen —
  denetim kaydına yazılır; argümanlar maskelenir.
- **Varsayılan kapalı.** Yeni yetenekler (dosya, terminal, ağ, haritalar,
  eklentiler) varsayılan olarak kapalıdır ve açıkça etkinleştirilmelidir.

## Genişletilebilirlik

Yeni araç ve entegrasyonlar **tek bir yerden**, eklenti (plugin) arayüzüyle
eklenir. Ayrıntılar ve adım adım kılavuz için
[docs/CONTRIBUTING.md](CONTRIBUTING.md).

## Çalıştırma

Tek görüntü tek adres sunar: backend derlenmiş React kabuğunu `/` altından
sunmaya devam eder, dolayısıyla CORS diye bir sorun oluşmaz. Derlenmiş çıktı
yoksa uygulama yalnızca API sunar — bu bir hata değildir.

```bash
docker compose up --build              # backend (derlenmiş kabukla)
docker compose --profile ollama up     # backend + yerel LLM
```

Sağlık denetimi `/api/v1/health` üzerinden yapılır (kimlik doğrulamadan
muaftır).
