# Mimari notları

Bu başlangıç iskeleti, entegrasyon sınırlarını şimdiden ayırır:

- `app/api`: HTTP taşıma katmanı ve endpoint'ler.
- `app/services`: Uygulama iş akışları.
- `app/adapters`: Home Assistant, model sağlayıcıları veya cihazlar gibi dış sistem köprüleri. Step 1'de yalnızca Ollama LLM adapter'ı bulunur.
- `app/tools`: Registry, Pydantic input doğrulaması, permission denetimi ve güvenli built-in tool'lar.
- `app/memory`: Kalıcı veya geçici bellek sağlayıcıları.
- `app/core`: logging gibi ortak teknik altyapı.
- `app/config`: ortam değişkenleri ve doğrulanmış ayarlar.

Step 2'deki akış `API → orchestrator → LLMProvider → ToolRegistry → ToolExecutor → LLM` şeklinde genişletildi. Conversation geçmişi yalnızca RAM'de tutulur ve system prompt `app/prompts/jarvis.txt` dosyasından yüklenir. LLM, Home Assistant, ses, vision, memory ve computer automation gibi yeni yetenekler eklenirken endpoint, servis ve adapter sorumlulukları birbirinden ayrı tutulmalıdır.
