"""Kalıcı notlar: Jarvis'in yazabildiği, kullanıcının okuduğu ortak yüzey.

Bellekten (`app.memory`) BİLİNÇLİ OLARAK ayrıdır ve birleştirilmemelidir:

- Bellek, Jarvis'in kullanıcı hakkında ÇIKARDIĞI bilgidir. Konuşmadan
  otomatik üretilir, kullanıcı onu doğrudan yazmaz ve zamanla geçersizleşir.
- Not, kullanıcının ya da ajanın BİLEREK yazdığı bir metindir. Kimse onu
  çıkarmaz, kendiliğinden geçersizleşmez ve silinmesi kullanıcının kararıdır.

İkisi tek tabloda toplansaydı, bellek temizliği kullanıcının yazdığı bir notu
"artık geçerli değil" diye silebilirdi.
"""
