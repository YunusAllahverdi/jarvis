"""Jarvis öğrenme katmanı — Memory ve Experience üzerinden türetilen kullanıcı modeli.

Bu paket bilinçli olarak "hafif" bir `__init__` tutar: hiçbir somut depolama
implementasyonunu (SQLite vb.) burada import etmez, böylece paketi import
etmek asla dosya sistemine dokunmaz.

Katmanlar:
- trait            : UserTrait veri modeli ve kanıt→güven (confidence) fonksiyonu
- trait_store      : UserTraitStore soyut sözleşmesi (Protocol)
- sqlite_trait_store: SQLite tabanlı somut implementasyon
- analyzer         : Experience geçmişi üzerinde deterministik analiz (saf fonksiyonlar)

Kavramsal sınır:
    Memory    → "Jarvis ne biliyor?"       (tekil gerçekler)
    Experience→ "Ne oldu?"                  (etkileşim günlüğü)
    Trait     → "Kullanıcı nasıl biri?"     (ikisinden TÜRETİLEN kalıcı model)

Trait'ler türetilmiş veridir: her öğrenme geçişinde kaynaklardan yeniden
hesaplanabilirler. Bu yüzden bir trait'in kaybolması veri kaybı değildir —
kaynak Memory ve Experience kayıtları her zaman gerçeğin tek kaynağıdır.
"""
