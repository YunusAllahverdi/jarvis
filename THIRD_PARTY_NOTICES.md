# Üçüncü taraf bildirimleri

Bu proje, ileride başka açık kaynak projelerden alınan kodları içerebilir.
Bu dosya, alınan her kod parçasının **kaynağını, lisansını ve atfını**
kaydeder. Yeni bir açık kaynak projeden kod (bir dosya, bir işlev, bir
algoritma) alındığında buraya bir kayıt eklenmelidir.

## Nasıl kayıt eklenir

Aşağıdaki şablonu kullanın ve **en yeni kaydı en üste** ekleyin:

```markdown
### <proje adı> — <alınan kısım>

- Kaynak: <depo URL'si> (<sürüm/commit>)
- Lisans: <SPDX kimliği, ör. MIT, Apache-2.0, BSD-3-Clause>
- Telif: Copyright (c) <yıl> <sahip>
- Alınan dosyalar: <bu depodaki yollar>
- Notlar: <değişiklik yapıldıysa açıklama>
- Lisans metni: <tam metin nerede saklanıyor, ör. licenses/<ad>.txt>
```

Lisansın tam metni, değiştirilmeden saklanmalıdır (ör. `licenses/`
klasöründe). Yalnızca izin veren lisanslar (MIT, Apache-2.0, BSD, ISC,
MPL-2.0 gibi) kabul edilir; **GPL/AGPL gibi bulaşıcı lisanslar** bu projenin
(MIT) lisansıyla uyumsuz olduğundan alınmamalıdır. Emin değilseniz almadan
önce sorun.

---

## Kayıtlar

### Jarvis'in kendi bağımlılıkları

Aşağıdaki çalışma zamanı bağımlılıkları `pyproject.toml`'da listelenir ve
kendi lisanslarına tabidir. Bunlar bu depoya kopyalanmaz; paket yöneticisi
tarafından kurulur. Tam lisans metinleri ilgili paketlerin içinde bulunur.

| Paket | Lisans |
|---|---|
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| Pydantic / pydantic-settings | MIT |
| httpx | BSD-3-Clause |
| psutil | BSD-3-Clause |
| python-dotenv | BSD-3-Clause |
| tzdata | Apache-2.0 |

Frontend bağımlılıkları `frontend/package.json`'da listelenir ve kendi
lisanslarına tabidir (ağırlıklı olarak MIT).

---

## Tasarım esin kaynakları (kod kopyalanmadı)

Yetenek kaydı (parça 2) tasarlanırken aşağıdaki MIT lisanslı depolar
incelendi. **Hiçbirinden kod kopyalanmadı ya da uyarlanmadı**; yalnızca
kavramsal desenler (sağlayıcı/toolset soyutlaması, onay politikası, risk
sınıflandırması) fikir olarak alındı ve bu deponun kendi mimarisine göre
sıfırdan yazıldı. Bu yüzden bu dosyaların başına atıf başlığı eklenmedi ve
kaynak kod bu depoya girmedi.

| Depo | Lisans | İncelenen kısım | Alınan |
|---|---|---|---|
| [OpenHands software-agent-sdk](https://github.com/OpenHands/software-agent-sdk) | MIT | `sdk/tool/`, `sdk/security/{risk,confirmation_policy,analyzer,llm_analyzer}.py` | Yalnızca desen (fikir) |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | MIT | `pydantic_ai/toolsets/` (Filtered/Prefixed/Combined) | Yalnızca desen (fikir) |
| [openai/openai-agents-python](https://github.com/openai/openai-agents-python) | MIT | `src/agents/guardrail.py`, `src/agents/tool.py` | Yalnızca desen (fikir) |
| [leon-ai/leon](https://github.com/leon-ai/leon) | MIT | `skills/` manifest yapısı | Yalnızca desen (fikir) |

İleride bu depolardan fiilen kod uyarlanırsa, yukarıdaki şablona göre bir kayıt
eklenmeli ve uyarlanan dosyanın başına
`# Adapted from <repo> (<lisans>) — <url> @ <commit-sha>; değişiklikler: <kısa>`
başlığı konmalıdır.

---

_Bu dosyada henüz bu depoya kopyalanmış üçüncü taraf kod kaydı yoktur._
