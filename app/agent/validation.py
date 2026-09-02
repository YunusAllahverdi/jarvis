"""Model çıktısının deterministik doğrulanması — tek tanım noktası.

Bir LLM'in ürettiği plan VERİDİR, talimat değil. Bu modül, o veriye
güvenilmeden önce uygulanan iki denetimi barındırır:

1. Argüman anahtarları tool'un şemasında tanımlı mı?
2. Adımlar arası başvurular yalnızca GERİYE mi bakıyor?

Tanımlar burada tek kez durur. Aynı mantık hem karar politikasında
(`app.agent.llm_policy`) hem kodlama planlayıcısında (`app.coding.planner`)
gerekir; iki kopya bırakılsaydı biri sıkılaştırıldığında diğeri sessizce
zayıf kalırdı — `app.security.fencing` aynı gerekçeyle tek noktaya
toplanmıştı.

Bu modül hiçbir I/O yapmaz ve hiçbir istisna fırlatmaz: her denetim bir
boolean döndürür, kararı çağıran verir.
"""

from __future__ import annotations

from typing import Any

from app.agent.references import is_reference


def arguments_match_schema(arguments: dict[str, Any], schema: dict[str, Any]) -> bool:
    """Argüman anahtarlarının şemada tanımlı olup olmadığını denetler.

    Bu TAM bir JSON Schema doğrulaması DEĞİLDİR ve öyle olduğu iddia edilmez:
    tip ve zorunluluk denetimi, tool'un pydantic input modeliyle
    `ToolExecutor` içinde yapılır ve o sınır atlanamaz. Buradaki denetim,
    modellerin en sık yaptığı hatayı (uydurulmuş argüman adı) karar anında
    yakalar — tüm tool input modelleri `extra="forbid"` olduğundan bu
    denetim şemayla tutarlıdır.

    Şema özellik tanımı içermiyorsa denetim atlanır (yanlış pozitif
    üretmemek için muhafazakâr davranılır).
    """
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return True
    return all(key in properties for key in arguments)


def references_point_backwards(value: Any, step_index: int) -> bool:
    """Argümanlardaki adım başvurularının yalnızca geriye baktığını doğrular.

    İleriye veya kendine yapılan başvuru, yürütme sırasında zaten
    reddedilirdi; burada karar anında yakalanır, böylece hiç yürütülmez.
    """
    if is_reference(value):
        spec = value["$from"]
        if not isinstance(spec, dict):
            return False
        step = spec.get("step")
        if not isinstance(step, int) or isinstance(step, bool):
            return False
        return 0 <= step < step_index
    if isinstance(value, dict):
        return all(references_point_backwards(item, step_index) for item in value.values())
    if isinstance(value, list):
        return all(references_point_backwards(item, step_index) for item in value)
    return True
