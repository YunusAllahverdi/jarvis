"""Jarvis karar katmanı (Agent) — "şimdi ne olmalı?" sorusunu yanıtlayan katman.

Bu paket bilinçli olarak "hafif" bir `__init__` tutar: hiçbir somut depolama
implementasyonunu veya servisi burada import etmez, böylece paketi import
etmek asla I/O tetiklemez.

Katmanlar:
- models  : Intent, AgentAction, AgentDecision, ActionOutcome, AgentResult
- context : Sınırlandırılmış (bounded) bağlam inşası — AgentContext
- policy  : DecisionPolicy sözleşmesi ve deterministik kural tabanlı politika
- runner  : Kararın yürütülmesi; mevcut ToolExecutor sınırının üzerinde

Sorumluluk ayrımı:

    context → isteği ve ilgili bağlamı topla       (yan etkisiz, sınırlı)
    policy  → ne yapılacağına karar ver             (yapılandırılmış AgentDecision)
    runner  → kararı yürüt                          (ToolExecutor üzerinden, izole)
    result  → ne olduğunu yapılandırılmış biçimde döndür

Kavramsal sınır — mevcut katmanlarla ilişkisi:

    Memory      → Jarvis ne biliyor?
    Experience  → Ne oldu?
    Learning    → Neler deterministik olarak türetilebilir?
    User Model  → Jarvis kullanıcı hakkında ne düşünüyor?
    Agent       → Bütün bunlarla şimdi NE YAPILMALI?          (bu paket)

ÖNEMLİ: Bu katman gizli akıl yürütme (chain-of-thought) üretmez ve saklamaz.
Yalnızca yapılandırılmış kararlar ve sonuçlar üretir; `AgentDecision.reason`
alanı makine tarafından üretilmiş KISA ve olgusal bir gerekçedir (ör.
"aritmetik ifade tespit edildi"), bir düşünce dökümü değildir.
"""
