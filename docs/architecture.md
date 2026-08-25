# Mimari notları

Bu başlangıç iskeleti, entegrasyon sınırlarını şimdiden ayırır:

- `app/api`: HTTP taşıma katmanı ve endpoint'ler.
- `app/services`: Uygulama iş akışları.
- `app/adapters`: Home Assistant, model sağlayıcıları veya cihazlar gibi dış sistem köprüleri.
- `app/tools`: Asistanın ileride çağıracağı araç tanımları.
- `app/memory`: Kalıcı veya geçici bellek sağlayıcıları.
- `app/core`: logging gibi ortak teknik altyapı.
- `app/config`: ortam değişkenleri ve doğrulanmış ayarlar.

Şu an bu sınırlarda gerçek entegrasyon veya AI davranışı yoktur. Yeni bir yetenek eklenirken endpoint, servis ve adapter sorumlulukları birbirinden ayrı tutulmalıdır.
