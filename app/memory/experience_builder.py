"""Phase 2B — Tamamlanmış bir konuşma turundan Experience inşası (yalnızca tasarım/saf fonksiyon).

Bu modül, `ChatOrchestrator.respond()`'un bir turun sonunda ZATEN elinde
bulunan verilerden (session_id, kullanıcı mesajı, asistan cevabı, tur
mesajları) deterministik bir `Experience` nesnesi inşa eden TEK bir saf
fonksiyon içerir.

Mimari kurallar:
- Saf fonksiyon: hiçbir LLM çağırmaz, hiçbir MemoryStore'a erişmez, hiçbir
  şeye yazmaz, hiçbir yan etkisi yoktur. `occurred_at` bile dışarıdan
  verilir — fonksiyon içinde `datetime.now()` çağrılmaz.
- Emotion/user-state çıkarımı YAPILMAZ — bu alanlar her zaman `None` kalır.
- Learning YAPILMAZ — `outcome` her zaman `ExperienceOutcome.UNKNOWN`,
  `derived_memory_ids` her zaman boş liste.
- ChatOrchestrator'a HENÜZ bağlanmadı — bu fonksiyon şu an hiçbir yerden
  çağrılmıyor. Bir sonraki, ayrı bir fazda orchestrator'ın zaten inşa ettiği
  `new_history` listesi `turn_messages` olarak doğrudan geçirilebilir;
  hiçbir yeni capture mantığı gerekmez.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.core.chat import ChatMessage
from app.memory.experience import Experience, ExperienceOutcome


def build_experience_from_turn(
    *,
    session_id: str,
    user_message: str,
    assistant_response: str,
    turn_messages: Sequence[ChatMessage],
    occurred_at: datetime,
    metadata: dict[str, Any] | None = None,
) -> Experience:
    """Tamamlanmış bir konuşma turundan deterministik bir Experience inşa eder.

    Args:
        session_id: Turun ait olduğu konuşma oturumu kimliği.
        user_message: Kullanıcının bu turdaki ham mesajı.
        assistant_response: Asistanın nihai (final) cevabı.
        turn_messages: Bu tura ait mesajlar (ör. orchestrator'ın `new_history`
            listesi) — kullanıcı mesajı, ara tool-call/tool-result mesajları
            ve nihai asistan mesajını içerebilir. Yalnızca `role="assistant"`
            olan ve `tool_calls` taşıyan mesajlardaki araç adları okunur;
            argümanlar ve tool sonuçları yok sayılır.
        occurred_at: Bu etkileşimin ne zaman gerçekleştiği. Fonksiyon saat
            tutmaz — bu değer aynen kopyalanır.
        metadata: İsteğe bağlı ek veri. Verilmezse izole boş bir sözlük
            kullanılır; verilirse kopyalanır (çağıranın sözlüğü daha sonra
            değiştirilse bile Experience etkilenmez).

    Returns:
        Yeni bir Experience. `id` alanı Experience'ın kendi varsayılan UUID
        üretecine bırakılır. `user_state`, `emotional_context` her zaman
        `None`; `outcome` her zaman `ExperienceOutcome.UNKNOWN`;
        `derived_memory_ids` her zaman boş liste.
    """
    tool_call_names = [
        call.name
        for message in turn_messages
        if message.role == "assistant"
        for call in message.tool_calls
    ]

    return Experience(
        session_id=session_id,
        occurred_at=occurred_at,
        user_message=user_message,
        assistant_response=assistant_response,
        tool_calls=tool_call_names,
        user_state=None,
        emotional_context=None,
        outcome=ExperienceOutcome.UNKNOWN,
        derived_memory_ids=[],
        metadata=dict(metadata) if metadata is not None else {},
    )
