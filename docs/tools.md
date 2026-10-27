# Tool System

## Tool nedir?

Tool, Jarvis'in doğrudan çalıştırabildiği açıkça kayıtlı bir yetenektir. Her tool; sabit bir `name`, açıklama, Pydantic input modeli, permission seviyesi ve `execute()` davranışı tanımlar. LLM hiçbir Python fonksiyonunu doğrudan çağıramaz; yalnızca ToolRegistry içinde bulunan tool adlarını isteyebilir.

Step 2'de kayıtlı tool'ların tümü `READ` seviyesindedir:

- `get_time`: yerel sistem saatini verir.
- `get_date`: yerel tarihi verir.
- `calculator`: `eval()` kullanmadan sınırlı aritmetik ifadeleri hesaplar.
- `system_status`: CPU, RAM ve disk kullanımını verir.

## ToolRegistry nedir?

`ToolRegistry`, tool'ların tek erişim noktasıdır. Aynı isimli ikinci kaydı reddeder; kayıt, lookup, listeleme ve unregister işlemlerini sağlar. Orchestrator, sağlayıcıya yalnızca registry'nin tool şemalarını gönderir ve yalnızca registry'den bulduğu tool'ları çalıştırabilir.

## Permission sistemi

`READ`, `WRITE` ve `DANGEROUS` seviyeleri vardır. ToolExecutor, her çağrıdan önce tool'un izin seviyesini etkin izin setiyle kontrol eder. Bu step'te sadece `READ` etkin olduğundan `WRITE` ve `DANGEROUS` tool'ları kaydedilmiş olsalar bile çalıştırılamaz. İlerideki onay/politika katmanları bu noktada uygulanacaktır.

## Yeni tool eklemek

1. `ToolInput` sınıfından türeyen, `extra="forbid"` kullanan bir Pydantic input modeli oluşturun.
2. `Tool[InputModel]` sınıfından türeyin; `name`, `description`, `permission`, `input_model` ve async `execute()` üyelerini tanımlayın.
3. Tool'u `ToolRegistry.register()` ile açıkça kaydedin. Varsayılan bir tool ise `app/tools/defaults.py` içine ekleyin.
4. Geçerli/geçersiz input, permission ve execution davranışı için test ekleyin.

## Tool-calling akışı

```text
User → Orchestrator → LLM
                         │
                    tool call?
                    ├─ hayır → final response
                    └─ evet → registry lookup → Pydantic validation → permission check
                                                        │
                                                   Tool.execute()
                                                        │
                                      tool result → LLM → final response
```

Hatalı argüman, bilinmeyen tool veya reddedilmiş permission bir tool-result olarak LLM'e iletilir; registry dışındaki hiçbir çağrı çalıştırılmaz. Orchestrator sonsuz döngüleri önlemek için en fazla dört tool-call turuna izin verir.

## Araç sağlayıcıları

Çok kaynaklı araçlar (MCP sunucuları, Home Assistant, tarayıcı, bilgisayar
kontrolü…) tek bir `ToolProvider` sözleşmesinden geçer. Sağlayıcı dört soruyu
yanıtlar:

| Üye | Soru |
|---|---|
| `id` | Sen kimsin? (kararlı kimlik, ör. `builtin`, `mcp`) |
| `enabled(settings)` | Bu yapılandırmada etkin misin? |
| `async tools()` | Hangi araçları sağlıyorsun? |
| `async health()` | Şu an sağlıklı mısın? (`ProviderHealth`) |
| `async aclose()` | Kaynaklarını serbest bırak. |

Sağlayıcı araçları KENDİSİ bir registry'ye kaydetmez; yalnızca üretir. Kayıt
ve çakışma denetimi `CapabilityRegistry`'nin işidir. Böylece iki sağlayıcı aynı
araç adını sağlarsa ikincisi sessizce birinciyi EZMEZ; çakışma raporlanır.

`CapabilityRegistry`, etkin sağlayıcıların araçlarını PAYLAŞILAN
`ToolRegistry`'ye **yerinde** kurar (`rebuild()`). "Yerinde" olması şarttır:
registry örneği yürütücüler tarafından tutulur; yeni bir örnek üretilseydi iki
paralel araç yüzeyi doğardı. `rebuild()` çalışma zamanında çağrılabilir —
bir sağlayıcı açıldığında ya da bir override değiştiğinde uygulamayı yeniden
başlatmak gerekmez.

Yerleşik araçlar da birer sağlayıcıdır (`builtin`): mevcut `register_*`
fonksiyonları davranış değiştirilmeden bu sözleşmeye sarılır.

## Meta veriler

`Tool` sınıfı, LLM'e giden şemayı şişirmeyen opsiyonel meta veriler taşır:

| Alan | Anlamı |
|---|---|
| `source` | Aracın geldiği sağlayıcı kimliği (varsayılan `"builtin"`) |
| `category` | İnsan için gruplama etiketi |
| `risk_tags` | `frozenset[str]`: `network`, `filesystem`, `device`, `money`, `irreversible`, `personal_data` |
| `untrusted_output` | `True` ise sonuç güvenilmez veri olarak işaretlenir |
| `max_output_chars` | Sonuç bu uzunlukta kırpılır |
| `timeout_seconds` | Araç bu süreyi aşarsa yapılandırılmış hataya döner |

Bu alanlar yalnızca yönetim/denetim katmanına gider; LLM'e yalnızca `name`,
`description` ve `input_schema` gönderilir.

## Güvenilmez çıktı

Web, MCP ya da herhangi bir dış kaynaktan gelen içerik **veridir, talimat
değil**. `untrusted_output = True` olan bir aracın sonucu zarf içine alınır:

```json
{ "untrusted": true, "source": "research", "content": "..." }
```

Ayrıca kontrol karakterleri temizlenir ve içerik `max_output_chars` ile
kırpılır (kırpıldığında sonuçta `truncated: true` görünür). Sistem promptu,
işaretli içerikteki talimatların ASLA uygulanmamasını, onun yalnızca veri
olarak değerlendirilmesini söyler. Mevcut `research` / `fetch_url` aracı
güvenilmez işaretlidir.

## İzin override kuralları

Kullanıcı, araç başına kararlarını `tool_overrides` tablosunda (SQLite,
`council_config` deseninde) kalıcılaştırabilir. Karar TEK bir yerde verilir:
`ToolPermissionPolicy` / `plan_override`. Kurallar:

1. **Kapatma serbest.** Bir araç kapatılabilir; kapatılan aracın araçları
   kayıtlı DEĞİLDİR.
2. **Yükseltme serbest.** `READ → WRITE → DANGEROUS` yükseltilebilir.
3. **Düşürme yalnızca açık istekle.** `WRITE → READ` gibi bir düşürme, açık
   kullanıcı isteği (`allow_downgrade`) olmadan reddedilir; kabul edilirse
   denetim kaydına `permission_downgrade` olarak yazılır.
4. **DANGEROUS asla düşürülemez.** Açık istek verilse bile deterministik
   olarak reddedilir.

İzin seviyesini model ya da dış sunucu belirleyemez; yalnızca kullanıcı
(yönetim ucu üzerinden) belirler. `WRITE` her zaman onaya tabidir; `DANGEROUS`
yalnızca ilgili bayrak açıkken onaylanabilir.

### Uçlar

| Uç | Erişim | Ne yapar |
|---|---|---|
| `GET /api/admin/capabilities` | `admin_token` kuralı | Sağlayıcı + araç listesi, kayıt uyarıları |
| `PUT /api/admin/capabilities/tools/{name}` | `admin_token` kuralı | Aç/kapa ve izin override'ı |
| `GET /api/v1/capabilities` | Salt-okunur | Hangi yetenek ailesi açık, kaç araç sağlıyor |

Yanıtlarda anahtar, token ya da araç argümanı GÖRÜNMEZ; salt-okunur uç yalnızca
aile kimliği, açık/kapalı durumu ve araç sayısı taşır.
