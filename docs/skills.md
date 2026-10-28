# Agent Skills (SKILL.md)

Bu belge, Jarvis'in **Agent Skills** desteğini anlatır: bir klasörde duran
`SKILL.md` dosyasının nasıl keşfedildiğini, modele nasıl sunulduğunu ve nasıl
güvenli biçimde çalıştırıldığını. Yeni bir skill eklemek isteyen ya da
güvenlik sınırını denetleyen biri için yazılmıştır.

## Skill nedir?

Skill, [agentskills.io](https://agentskills.io) spesifikasyonuna göre
biçimlendirilmiş bir `SKILL.md` dosyası ve yanındaki referans/script
dosyalarından oluşan bir **klasördür**. Jarvis bir skill'i çalıştırmaz;
onun talimatlarını modele sunar ve skill içindeki dosyalara/script'lere
erişim için üç araç sağlar.

```
skills/
  geo-sleuth/
    SKILL.md            # YAML ön yüz + Markdown gövde
    LICENSE             # vendorlanan skill'lerde zorunlu
    .skill-source.json  # vendorlanan skill'lerde kaynak/commit kaydı
    references/         # modele okutulabilecek referans dosyaları
    scripts/            # yalnızca onaylı terminal yoluyla çalışan script'ler
```

## SKILL.md biçimi

Dosya `---` ile çevrili bir YAML ön yüzüyle başlar:

```markdown
---
name: ornek-skill
description: Ne zaman kullanılacağını anlatan tek bir paragraf.
license: MIT            # opsiyonel
compatibility: ...      # opsiyonel; diğer alanlar metadata'ya alınır
---

# Gövde

Skill'in modele verilecek talimatları burada.
```

Zorunlu alanlar:

- **`name`**: `^[a-z0-9][a-z0-9_-]{0,63}$` desenine uymalıdır (küçük harf,
  rakam, tire, alt çizgi).
- **`description`**: ne yaptığını ve ne zaman kullanılacağını anlatır.

Diğer tüm alanlar (ör. `license`, `compatibility`, `metadata`) korunur;
bilinmeyenler `SkillInfo.metadata` içinde tutulur.

**Bozuk ön yüz uygulamayı çökertmez.** Ayraç eksikse, YAML çözülemiyorsa ya da
`name`/`description` yoksa o skill atlanır ve neden `skill_frontmatter_invalid`
gibi bir olay olarak loglanır; diğer skill'ler keşfedilmeye devam eder.

## İlerici açıklama (progressive disclosure)

Sistem prompt'una **yalnızca skill adları ve açıklamaları** girer — gövdeler
girmez. Bu, prompt'u küçük tutar ve yüzlerce skill olsa bile bağlamı
şişirmez.

- **`load_skill(name)`** — SKILL.md gövdesini döndürür. Model bir skill'i
  kullanmadan önce bunu çağırır.
- **`read_skill_file(name, path)`** — skill klasöründeki bir referans dosyayı
  okur (`path` skill klasörüne göredir, ör. `references/sky.md`).
- **`run_skill_script(name, path, args)`** — skill klasöründeki bir script'i
  çalıştırır (bkz. aşağıdaki güvenlik notu).

Üçünün de çıktısı **güvenilmez (untrusted)** olarak işaretlenir: skill
dosyaları dış kaynaklı olabilir ve modele talimat gibi görünen içerik
taşıyabilir. Jarvis bu çıktıyı veri olarak çerçeveler.

## Güvenlik sınırları

1. **Path traversal engellenir.** `read_skill_file` ve `run_skill_script`
   yolları skill köküne göre çözülür; `..`, mutlak yol ve kök dışına çıkan
   sembolik bağlar reddedilir.
2. **Script'ler yeni bir izin yolu AÇMAZ.** `run_skill_script` var olan onay
   gerektiren terminal aracına (`RunCommandTool`) DELEGE eder: aynı komut
   politikası (kabuk yok, yalnızca tanınan programlar) ve aynı onay kapısı
   uygulanır. Terminal kapalıyken `DANGEROUS` reddedilir; terminal açıkken
   her çağrı tek tek onaylanır. Tek fark çalışma dizinidir: skill klasörü.
3. **Yalnızca bilinen yorumlayıcılar.** Bir script yalnızca uzantısına göre
   (`*.py` → `python`, `*.mjs`/`*.js` → `node`) çalıştırılır. Model keyfi bir
   program seçemez.
4. **Skill çıktısı güvenilmezdir.** Gövde, referans dosyalar ve script
   çıktısı `untrusted` olarak işaretlenir.

> **Yalnızca güvenilir kaynaklardan skill ekleyin.** Bir skill'in gövdesi ve
> referans dosyaları modele ulaşan metinlerdir; kötü niyetli bir skill, modele
> talimat enjekte etmeye çalışabilir. Skill'i çalıştırmadan önce içeriğini
> gözden geçirin. Script'ler onay gerektirse de, onaylayacağınız şeyin ne
> yaptığını bilmelisiniz.

## Yeni bir skill eklemek

En basit yol:

1. Skill klasörünü `skills/` altına kopyalayın:

   ```bash
   cp -r /yol/yeni-skill skills/yeni-skill
   ```

   Klasörün içinde geçerli ön yüzlü bir `SKILL.md` bulunmalıdır.

2. Ek bir klasörden keşfetmek isterseniz `JARVIS_SKILLS_DIRS` ayarını
   kullanın (virgülle ayrılmış yollar):

   ```dotenv
   JARVIS_SKILLS_DIRS=skills,/opt/paylasilan-skilller
   ```

3. Jarvis'i yeniden başlatın; skill yetenek panelinde **Skill'ler** grubunda
   görünür.

4. Gerekirse tek tek açıp kapatın (bkz. aşağıdaki bölüm).

### Vendorlama (dış kaynaktan skill alma)

Dış bir depodan skill alıyorsanız:

1. **Lisansı doğrulayın.** Yalnızca izin veren lisanslar kabul edilir:
   MIT, Apache-2.0, BSD, ISC, MPL-2.0 gibi. **GPL/AGPL gibi bulaşıcı
   lisanslı** skill'ler bu projenin (MIT) lisansıyla uyumsuzdur ve
   **eklenmemelidir.**
2. **`LICENSE` dosyasını koruyun.** Skill klasöründe kalmalıdır.
3. **Kaynağı kaydedin.** Klasöre bir `.skill-source.json` yan dosyası koyun:

   ```json
   {
     "source": "https://github.com/ornek/skill",
     "source_sha": "<40 karakterlik commit SHA>",
     "license": "MIT",
     "vendored_from": ".",
     "note": "Kısa not."
   }
   ```

   Bu alanlar yetenek panelinde ve denetimde görünür.

4. **`THIRD_PARTY_NOTICES.md`'ye kayıt ekleyin** (kaynak, commit, lisans,
   alınan dosyalar).

5. Ağır bağımlılık gerekiyorsa ana kuruluma eklemek yerine
   `pyproject.toml`'da bir **opsiyonel extra** tanımlayın (ör.
   `skills-geo-sleuth`), böylece `pip install jarvis-local` şişmez.

## Skill'leri açma/kapatma

Yetenek panelinde (**Yetenek Kaydı → Skill'ler**) her skill tek tek açılıp
kapatılabilir. Kapatma, mevcut `tool_overrides` mekanizmasını kullanır:
anahtar `skill_<slug>` biçimindedir (ör. `skill_geo-sleuth`). Kapalı bir
skill ne sistem prompt'unda görünür ne de `load_skill` ile yüklenebilir.

Yalnızca **aç/kapa** vardır; izin seviyesi override'ı yoktur. Çünkü skill'in
izni kendi araçlarından gelir: okuma araçları `READ`, script çalıştırma
`DANGEROUS`. Skill'in script çalıştırmasını engellemek için terminali kapatın.

Ayar dosyası üzerinden tüm skill'leri kapatmak için:

```dotenv
JARVIS_SKILLS_ENABLED=false
```

## Sağlayıcı sözleşmesi

`SkillProvider`, Parça 1'deki yetenek kaydına (`CapabilityRegistry`) bir
`ToolProvider` olarak takılır:

- `id = "skills"`,
- `tools()` üç aracı üretir (`load_skill`, `read_skill_file`,
  `run_skill_script`),
- `skills()` keşfedilen skill'lerin salt-okunur görünümlerini verir
  (panel ve prompt bunu kullanır),
- `health()` keşfedilen skill sayısını bildirir.

Ayrıntılar için `app/skills/` paketine ve `docs/tools.md`'ye bakın.
