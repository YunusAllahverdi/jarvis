"""Kodlama döngüsü: anla → planla → uygula → doğrula → teşhis et → düzelt.

Bu paket, karar katmanının (`app.agent`) üzerine oturan bir ÜST katmandır ve
onun yerini almaz. Fark, döngünün kendisidir: karar katmanı bir plan üretip
yürütür ve orada durur; kodlama döngüsü yürütmenin SONUCUNU doğrular, hatayı
okur ve sınırlı sayıda düzeltme turu dener.

Mimari kurallar:
- Ayrı bir yürütme mekanizması İCAT EDİLMEZ. Her adım mevcut `ToolExecutor`
  sınırından geçer; izin kontrolü, şema doğrulaması ve denetim kaydı orada
  yapılır ve bu paket o sınırı atlamaz.
- Ayrı bir plan/eylem vokabüleri icat edilmez: adımlar `AgentAction`,
  sonuçlar `ActionOutcome` olarak taşınır. İki ayrı "eylem" kavramı
  oluşsaydı, biri sıkılaştırıldığında diğeri geride kalabilirdi.
- LLM ÇIKTISI VERİDİR. Plan da, düzeltme planı da deterministik olarak
  doğrulanır; `requires_confirmation` modelden HİÇ okunmaz.
- Doğrulama ve teşhis DETERMİNİSTİKTİR: testin geçip geçmediğine bir model
  değil, çıkış kodu karar verir.
- Hiçbir katman istisna fırlatmaz; her başarısızlık yapılandırılmış bir
  sonuca dönüşür.
"""
