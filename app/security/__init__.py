"""Ajanın yetki sınırlarını tanımlayan güvenlik katmanı.

Bu paket, bir aracın çalıştırılıp çalıştırılamayacağına dair kararın tek
sahibidir. Araçlar kendi izinlerini belirlemez, çağıran taraf da kendi
kuralını uydurmaz: herkes buradaki politikayı sorar.
"""

from app.security.permissions import PermissionDecision, ToolPermissionPolicy

__all__ = ["PermissionDecision", "ToolPermissionPolicy"]
