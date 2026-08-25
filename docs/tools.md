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
