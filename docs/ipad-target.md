# Hedef platform: saf on-device iPad

Jarvis'in çalışacağı yer, M1 iPad Pro (8 GB) üzerinde iPadOS'tur. Başka bir makine,
sunucu ya da ev ağında çalışan bir "runner" yoktur. Bu belge, o kararın mimariye ne
yaptığını yazar: neyin imkânsız olduğunu, neyin yerine ne geçtiğini ve mevcut kodun
hangi kısmının olduğu gibi taşındığını.

Bu belge bir yol haritası değil, bir kısıt listesidir. Yol haritası kısıtlardan çıkar.

## Değişmeyen üç fizik kuralı

**1. iOS uygulaması alt süreç çalıştıramaz.** CPython'un resmî iOS belgeleri bunu
şöyle koyar: bir iOS uygulaması hiçbir biçimde subprocess, multiprocessing veya
süreçler arası iletişim kullanamaz; denerse ya kilitlenir ya çöker. Bu bir izin
meselesi değil, çekirdek düzeyinde bir sınırdır ve jailbreak dışında aşılamaz.

Bunun bedeli doğrudan bizim kodumuza düşer. `app/tools/builtin/terminal.py` ve
`app/tools/builtin/git_tools.py` bugün `asyncio.create_subprocess_exec` üzerine
kuruludur. İkisi de bu cihazda **çalışamaz**. `pytest`, `ruff`, `git`, `npm`, `node`
— hiçbiri bir işlem olarak var olamaz.

**2. Bellek tavanı yaklaşık 5 GB'dır.** M1 iPad Pro'da üçüncü parti bir uygulamaya,
"Increased Memory Limit" hakkı alınmış olsa bile, pratikte ~5 GB'ın üstü verilmez.
Cihazın 8 GB olması bunu değiştirmez. Model, KV cache, uygulama ve arayüz bu tavanı
paylaşır.

Bunun anlamı: 4-bit quantize edilmiş **4B sınıfı bir model** tavandır (~2.5 GB), 7B
değil. Bağlam penceresi de aynı bütçeden yer — 8k–16k gerçekçi, 200k değil.

**3. İnternet vardır.** Ağ erişimi kısıtlanmamıştır. Araştırma, dokümantasyon okuma,
GitHub API'si ve paket metadata'sı sorunsuz çalışır. Kısıt hesaplamada ve süreçtedir,
bağlantıda değil.

## Buna rağmen mümkün olanlar

Kısıtlar sanıldığı kadar geniş bir alanı kesmiyor. Cihazda gerçekten çalışabilecekler:

- **Gömülü CPython.** PEP 730'dan beri iOS, CPython'un desteklediği bir platform.
  Yalnızca "embedded" modda: REPL yok, `pip` yok, ikili modüller framework olarak
  paketlenmek zorunda. Ama `app/` paketinin kendisi uygulamanın içinde çalışabilir.
- **Yerel model.** MLX ile cihaz üstü inference gerçek ve çalışıyor. Model katmanı
  `LLMProvider` arayüzünün arkasına, Ollama'nın yanına bir sağlayıcı olarak girer.
- **Git.** libgit2 bir kütüphanedir, bir program değil. Klonlama, diff, commit, branch
  ve push süreç açmadan yapılabilir. GitHub akışı (vizyon md. 8) neredeyse tamamen ayakta kalır.
- **Kod çalıştırma — tek bir yoldan.** WKWebView kendi sürecinde çalışır ve JIT hakkına
  sahiptir. JavaScript ve WebAssembly cihazda meşru biçimde çalıştırılabilir. Bu,
  elimizdeki **tek** yürütme motorudur.
- **Statik analiz.** Secret taraması, tehlikeli desen tespiti, bağımlılık CVE sorgusu —
  hepsi ya saf Python ya da ağ çağrısıdır. Olduğu gibi çalışır.

## Yürütme sandbox'ı: WKWebView

Alt süreç yoksa ama JS/WASM varsa, yürütme motoru WKWebView'dır.

- **JavaScript / TypeScript**: doğrudan ve hızlı çalışır. Web tasarımı da aynı yerde
  hem çalışır hem görünür. Bu, "yaz → çalıştır → gör → düzelt" döngüsünün cihazda
  eksiksiz kapandığı tek yığındır.
- **Python**: Pyodide (WASM'e derlenmiş CPython) ile mümkün *görünüyor*, ancak iOS'ta
  belgelenmiş çökme ve uyumluluk sorunları var. **Varsayım değil, doğrulanacak bir
  iddiadır**; zamanı sınırlı bir denemeyle test edilmeli.
- **Rust tabanlı araçlar** (ör. ruff) WASM hedefine derlenebildiği ölçüde aynı sandbox'ta
  çalışabilir.

Bunun güzel yanı şu: WKWebView zaten yalıtılmış bir ortam. Güvenlik modelimizle
çatışmıyor, onu güçlendiriyor.

## Kalıcı olarak kapsam dışı

Cihazda hiçbir koşulda olmayacaklar, açıkça yazılsın:

Blender · Unreal Engine · Unity · Docker · native derleme · sistem ikililerinin
çalıştırılması.

Vizyondaki 3D (md. 10) ve oyun geliştirme (md. 11) maddeleri bu hedefte Jarvis'in
*yazabildiği ama çalıştıramadığı* işler sınıfına girer. Jarvis bir Blender Python
script'i üretebilir; onu çalıştıracak olan sensin.

## Mevcut koda etkisi

Kritik nokta: mimari bu değişimi zaten kaldırıyor. Terminal ve git, `Tool` arayüzünün
arkasında duruyor; değişecek olan araçların *arka ucu*, sözleşmesi değil.

| Katman | Durum |
|---|---|
| `app/security/*` (izin, onay, denetim, path guard, checkpoint) | **Olduğu gibi taşınır.** Güvenlik tasarımı platformdan bağımsız. |
| `app/memory`, `app/learning`, `app/council` | **Olduğu gibi taşınır.** Saf hesaplama + SQLite. |
| `app/agent`, `app/services` | **Olduğu gibi taşınır.** |
| `app/adapters/llm` | Genişler: Ollama'nın yanına MLX sağlayıcısı. Arayüz değişmez. |
| `frontend/` (React + WebGL orb) | **Korunur.** WKWebView'da çalışır; SwiftUI'ye çevirmeye gerek yok. |
| `app/tools/builtin/terminal.py` | Arka uç değişir: subprocess yerine WASM sandbox. `CommandPolicy` ve onay akışı aynı kalır. |
| `app/tools/builtin/git_tools.py` | Arka uç değişir: subprocess git yerine libgit2. |
| `pydantic-core` (Rust) | **Açık risk.** iOS için derlenmiş bir ikilik gerekir. Bugün bilinen en büyük teknik belirsizlik. |

## Sıralamayı belirleyen tespit

Vizyonun birinci önceliği Coding Agent. İşin şansı şu: **Coding Agent'ın istenen
yeteneklerinin büyük çoğunluğu alt süreç gerektirmiyor.**

Depoyu okumak, mimariyi çıkarmak, dosyalar arası ilişkileri ve bağımlılıkları
anlamak, görevi task'a çevirmek, plan yapmak, araştırma yapmak, dokümantasyon okumak,
çözümleri karşılaştırmak, kod yazmak, diff üretmek, değişikliği açıklamak, secret
taraması yapmak, checkpoint almak, commit etmek — bunların hepsi hem masaüstünde hem
iPad'de aynı şekilde çalışır.

Platform sorusu yalnızca **tek bir adımda** ısırıyor: "testi çalıştır, hatayı oku,
kendini düzelt."

Dolayısıyla doğru sıra, platform bağımsız olanı önce ve tam yapmaktır. O iş iPad'e
değiştirilmeden taşınır ve şimdi yazılabilir. Yürütme katmanı ayrı bir soyutlamanın
(`ExecutionBackend`) arkasına alınır; masaüstünde subprocess, iPad'de WASM.

## Pratik önkoşul

iPadOS uygulaması derlemek için Xcode kurulu bir Mac gerekir; iPad kendi kendine
kendi uygulamasını üretemez. İmzalama iki türlüdür: ücretsiz provisioning 7 günde bir
yeniden imzalama ister, Apple Developer Program (yıllık $99) bir yıl geçerli profil
verir. Bu, kodla çözülebilecek bir sorun değildir ve planlamada veri olarak durmalıdır.

## Kaynaklar

- [Using Python on iOS — CPython](https://docs.python.org/3.13/using/ios.html)
- [PEP 730 – Adding iOS as a supported platform](https://peps.python.org/pep-0730/)
- [M1 iPad Pro üçüncü parti uygulama bellek sınırı](https://www.notebookcheck.net/Fancy-the-2021-M1-iPad-Pro-with-8-GB-or-16-GB-RAM-Current-iPadOS-limits-potential-by-allowing-just-5-GB-memory-for-third-party-apps.541367.0.html)
- [MLX Swift — LLMEval örneği](https://github.com/ml-explore/mlx-swift-examples/blob/main/Applications/LLMEval/README.md)
- [Pyodide](https://github.com/pyodide/pyodide)
