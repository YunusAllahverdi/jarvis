"""LLM Council — birden fazla modelin birlikte cevap ürettiği müzakere katmanı.

Bu paket bilinçli olarak "hafif" bir `__init__` tutar: hiçbir servis, depo veya
sağlayıcı burada import edilmez, böylece paketi import etmek asla I/O tetiklemez.

Katmanlar:
- models     : CouncilMember, CouncilCandidate, CouncilReview, CouncilResult
- anonymizer : Müzakere başına üretilen kimlik ↔ etiket eşlemesi
- prompts    : Üç aşamanın prompt'ları ve güvenilmez-veri sınırlama
- stages     : Aşamaların orkestrasyonu (paralellik, timeout, doğrulama)
- gate       : Council'ın ne zaman çalışacağına dair DETERMİNİSTİK karar

Üç aşama:

    Stage 1  N üye AYNI görevi bağımsız çözer (birbirini görmez)
    Stage 2  Her üye DİĞER adayları anonim etiketlerle değerlendirir
    Stage 3  Chairman adayları ve değerlendirmeleri sentezler

MİMARİ SINIRLAR (bu paket tarafından yapısal olarak korunur):
- Council YALNIZCA `LLMProvider` soyutlamasını bilir. Somut sağlayıcı, model
  adı, HTTP istemcisi veya API anahtarı bu pakete hiç girmez.
- Council hiçbir tool çalıştıramaz: `ToolRegistry`, `ToolExecutor`,
  `AgentRunner` ve `AgentService` bu paketten HİÇ import edilmez. Bu sayede
  Council → Agent → Council özyinelemesi yapısal olarak imkânsızdır.
- Council'ın gördüğü her şey veridir; ürettiği hiçbir metin kod olarak
  çalıştırılmaz.
- Chairman çıktısı doğrudan kullanıcı cevabı DEĞİLDİR; normal cevap
  üretimine sınırlanmış VERİ olarak aktarılır.
"""
