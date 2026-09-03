# Jarvis — vizyon ve karar defteri

Bu belge depoda durur ki, hangi cihazdan açılırsa açılsın her oturum projenin
ne olduğunu ve neden böyle olduğunu kendisi okuyabilsin. Kodun anlattığı şeyi
tekrar etmez; **kodun anlatamadığı kararları** taşır.

## Jarvis nedir

Bir sohbet botu değil. Hedef: işi alan, araştıran, planlayan, uygulayan, test
eden ve sonucu sunan kişisel bir AI çalışma katmanı. Uzun vadede bilgisayarı,
dosyaları, web'i, tasarım araçlarını ve 3B üretimi kullanabilmesi bekleniyor.

Öncelik sırası:

1. **Coding Agent** — Claude Code seviyesinde bir kodlama ajanı.
2. **Güvenlik** — ajan dosyalara ve terminale eriştiği için sonradan eklenecek
   bir özellik değil, ilk günden mimarinin parçası.
3. **Frontend** — kullanıcının kendi belgesinde öncelik dışı; yine de görsel
   kabuk ve yönetim paneli hayata geçti.

Bir yetenek ile bir güvenlik sınırı çatıştığında **sınır kazanır**.

## Kodun anlatamadığı ayrımlar

Bu projede birbirine benzeyen ama bilinçli olarak ayrı tutulan kavramlar var.
Birleştirilmeleri hâlinde ne kaybedileceği burada yazılıdır.

| Ayrı tutulan | Neden birleştirilmemeli |
|---|---|
| **Bellek** ve **Not** | Bellek Jarvis'in *çıkardığı* bilgidir, kendiliğinden eskir. Not *bilerek yazılmış* bir metindir. Tek tabloda bellek temizliği, kullanıcının yazdığı bir notu silebilirdi. |
| **Bellek** ve **Deneyim** | Bellek "ne biliyorsun?", Deneyim "ne oldu?" sorusunu yanıtlar. |
| **Okuma** ve **Yazma** izni | Kullanıcı ajanın deposunu incelemesini isteyip değiştirmesini istemeyebilir. |
| **Dosya**, **terminal**, **ağ** yetkileri | Farklı büyüklükte riskler; tek bir ayarla ifade edilemezler. |
| **`api_token`** ve **`admin_token`** | "Bu sunucuya erişebilir misin" ile "sağlayıcıyı ve anahtarları değiştirebilir misin" ayrı sorulardır. |
| **Doğrulama** ve **inceleme** | Doğrulama "çalışıyor mu?", inceleme "yapılmaması gereken bir şey mi yapıldı?" sorusudur. Sızmış bir anahtar da testleri geçer. |

## Değişmeyen kurallar

- **Tek yürütme sınırı.** Her araç çağrısı `ToolExecutor`'dan geçer. İzin
  kontrolü, şema doğrulaması ve denetim kaydı orada yapılır ve atlanamaz.
- **Model çıktısı veridir, talimat değil.** LLM'in ürettiği her plan
  deterministik olarak yeniden doğrulanır; `requires_confirmation` modelden
  hiç okunmaz, araç tanımından yeniden hesaplanır.
- **Katmanlar istisna fırlatmaz.** Her başarısızlık yapılandırılmış bir
  sonuca dönüşür; çağıran güvenle geri çekilebilir.
- **Her yetenek varsayılan kapalıdır.** Bir yetenek, kullanıcı açıkça
  yapılandırdığında var olur.
- **Kazanılmamış başarı iddia edilmez.** Kodlama döngüsü, gerçek bir doğrulama
  komutu sıfır dönmedikçe "tamamlandı" demez; arayüz de bu ayrımı korur.
- **Olmayan şey varmış gibi gösterilmez.** Ölçülemeyen bir değer "—" olur,
  boş bir liste boş görünür, açacak ekranı olmayan düğme çizilmez.

## İskelet ile zekâ ayrı iki eksen

Buradaki işin tamamı ajanın **ne yapmasına izin verildiğini** belirler, **ne
kadar iyi kod yazacağını** değil. Kod kalitesi tamamen arkadaki modelin
kalitesidir. Aynı iskeleti küçük bir yerel modele bağlarsan, iskelet kusursuz
olsa bile plan zayıf olur ve yanlış dosya düzeltilir.

Pratik sonuç: sistem ciddi bir modelle denenmeden, sorunun iskelette mi modelde
mi olduğu ayırt edilemez. Yönetim paneli tam da bunun için var.

## Bilinen borçlar

- **Konuşma geçmişi kalıcı ama bellek katmanıyla aynı dosyada.** Ölçek
  büyürse ayrılması gerekebilir.
- **Sesli komut yalnızca bas-konuş.** Tarayıcıda uyandırma kelimesi pratik
  değil; tam eller serbest için masaüstü uygulaması gerekir.
- **DNS yeniden bağlama penceresi.** `NetworkGuard` adresi istek anında
  çözer, sonra istemci yeniden çözer. Kapatmak için çözülmüş IP'ye doğrudan
  bağlanmak gerekir; mevcut tehdit modelinde maliyeti kazanca değmedi.
- **Harita paneli yok.** Google Maps anahtarı ve kota yönetimi gerektiriyor;
  200 $'lık genel kredi 1 Mart 2025'te kaldırıldı ve yerine ürün başına
  devredilmeyen kotalar geldi.
- **Tasarım–felsefe gerilimi.** Belge "dashboard olmasın" diyor; uygulanan
  tasarımda solda nav ve sağda paneller var.
