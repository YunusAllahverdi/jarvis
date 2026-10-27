# Katkı rehberi

Bu belge, Jarvis'e nasıl katkı verileceğini ve özellikle **yeni bir yeteneğin
(araç/entegrasyon) nasıl ekleneceğini** anlatır.

## Geliştirme ortamı

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

Kod kalitesi araçları `pre-commit` ile bağlıdır; elle de çalıştırılabilir:

```bash
ruff check .            # lint
ruff format .           # biçimlendirme
mypy app                # tip denetimi
pytest                  # testler
```

Commit öncesi tüm testlerin geçtiğinden emin olun. Test silerek ya da
atlayarak (`skip`) geçirmek kabul edilmez.

## Yeni bir yetenek nasıl eklenir?

Yeni bir yetenek (MCP sunucusu, ses, wake word, Home Assistant, tarayıcı
ajanı, bilgisayar kontrolü…) eklemenin yolu **eklenti (plugin) yazmaktır**.
Eklentiler `app/plugins/` altında yaşar ve tek bir yerden uygulanır.

### 1. Eklenti sınıfını yaz

En basit yol, `app/plugins/example.py` dosyasını kopyalamaktır. Bir eklenti
iki şeyi sağlar: `name`/`description` ve `register()`.

```python
from collections.abc import Sequence

from app.plugins.base import Plugin, PluginContext
from app.tools.base import PermissionLevel, Tool, ToolInput


class WeatherInput(ToolInput):
    city: str


class WeatherTool(Tool[WeatherInput]):
    name = "weather"
    description = "Bir şehrin hava durumunu döndürür."
    permission = PermissionLevel.READ
    input_model = WeatherInput

    async def execute(self, tool_input: WeatherInput) -> dict[str, object]:
        return {"city": tool_input.city, "temperature": 21}


class WeatherPlugin(Plugin):
    name = "weather"
    description = "Hava durumu aracı."

    def register(self, context: PluginContext) -> Sequence[str]:
        tool = WeatherTool()
        context.registry.register(tool)
        return [tool.name]
```

### 2. Eklentiyi kaydet

`app/plugins/builtin.py` içindeki `BUILTIN_PLUGINS` listesine ekleyin:

```python
BUILTIN_PLUGINS: tuple[Plugin, ...] = (
    ...,
    WeatherPlugin(),
)
```

### 3. Varsayılan KAPALI olduğunu doğrula

Yeni bir eklenti, kullanıcı açıkça açmadıkça çalışmaz. `Plugin.enabled()`
taban uygulaması, adın `JARVIS_ENABLED_PLUGINS` listesinde olmasını bekler:

```dotenv
JARVIS_ENABLED_PLUGINS=["weather"]
```

Eklentinin kendi ön koşulu varsa (ör. bir API anahtarı), `enabled()`'ı
geçersiz kılın — ama kapalılık varsayılanını koruyun:

```python
def enabled(self, settings) -> bool:
    return self.name in settings.enabled_plugins and bool(settings.weather_api_key)
```

### 4. Test yaz

`tests/test_plugins.py`'yi örnek alın. En azından şunları doğrulayın:

- Eklenti **varsayılan kapalıdır** (bayrak verilmeden araç kaydedilmez).
- Bayrak verildiğinde araç kaydedilir ve çalışır.
- Aracın izin seviyesi beklediğiniz gibi davranır (READ serbest, WRITE onay
  ister, DANGEROUS kapalıyken reddedilir).

### Kurallar

- **Varsayılan kapalı.** Yeni bir yetenek, sessizce etkinleşemez.
- **İzin akışını atlamayın.** Eklentinin kaydettiği her araç, tıpkı yerleşik
  araçlar gibi `ToolPermissionPolicy` + onay akışından geçer. Eklenti bu
  akışı devre dışı bırakamaz; yalnızca aracın izin seviyesini bildirir.
- **Girdi doğrulaması.** Araç girdisi `ToolInput` türevi bir Pydantic
  modelidir; ham argümanlar LLM'den gelir ve güvenilmez.
- **Sır yok.** Anahtarlar `Settings`'e (ortam değişkeni) eklenir, koda
  gömülmez.
- **Kaynağı belgeleyin.** Başka bir açık kaynak projeden kod alıyorsanız
  kök dizindeki `THIRD_PARTY_NOTICES.md` dosyasına lisans/atıf kaydını
  ekleyin.

## Eklenti arayüzünün özeti

| Kavram | Dosya | Rol |
|---|---|---|
| `Plugin` | `app/plugins/base.py` | Sözleşme: `name`, `description`, `enabled()`, `register()` |
| `PluginContext` | `app/plugins/base.py` | Eklentiye verilen bağımlılıklar (registry, settings, bekçiler…) |
| `PluginRegistry` | `app/plugins/registry.py` | Eklentileri sırayla uygular |
| `PluginRegistration` | `app/plugins/base.py` | Uygulama sonucu (etkin mi, hangi araçlar) |
| `FunctionPlugin` | `app/plugins/base.py` | Basit bir kayıt fonksiyonunu eklentiye sarar |

## Pull request

- Küçük ve odaklı tutun; her PR tek bir konuyu ele alsın.
- Commit mesajları Türkçe ve açıklayıcı olsun.
- CI (`.github/workflows/ci.yml`) yeşil olmalı: ruff + mypy + pytest
  (coverage raporuyla) ve frontend derlemesi.
- Davranışı değiştiren bir değişiklikse testlerle kanıtlayın.
