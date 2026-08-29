"""Güvenilmez metnin modele veri olarak sunulması.

Modelin bağlamına giren her metin ondan gelen bir talimat gibi okunabilir.
Saklanmış bir bellek kaydı, bir aday cevabı, ileride bir dosyanın içeriği —
hiçbiri güvenilir değildir; hepsi bir noktada kullanıcının ya da başka bir
modelin yazdığı metindir.

Savunma iki parçalıdır ve ikisi birlikte anlam taşır:

1. Metin etiketli bir bloğa konur ve prompt, blok içindekinin VERİ olduğunu
   söyler.
2. Metindeki açı parantezleri nötrleştirilir. Bu olmadan içerik sahte bir
   kapanış etiketi yazıp bloktan "çıkabilir" ve gerisini talimat gibi
   sunabilirdi.

Tanım burada tek kez durur. Daha önce aynı mantık üç ayrı modülde
kopyalanmıştı; biri sıkılaştırılıp diğerleri unutulduğunda savunma sessizce
zayıflardı.
"""

UNTRUSTED_OPEN = "<untrusted_data>"
UNTRUSTED_CLOSE = "</untrusted_data>"


def escape_untrusted(text: str) -> str:
    """Açı parantezlerini nötrleştirir (sahte blok sınırı üretilmesini engeller).

    Benzer görünen ama işlevsiz Unicode karakterler kullanılır: metin insan
    gözüne aynı görünür, modele de okunur kalır, ama artık etiket sınırı
    taklit edemez.
    """
    return text.replace("<", "‹").replace(">", "›")


def fence(label: str, body: str) -> str:
    """Güvenilmez bir metni etiketli, açıkça sınırlanmış bir bloğa koyar."""

    return f'{UNTRUSTED_OPEN} type="{label}"\n{escape_untrusted(body)}\n{UNTRUSTED_CLOSE}'
