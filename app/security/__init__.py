"""Ajanın yetki sınırlarını tanımlayan güvenlik katmanı.

Bu paket, bir aracın çalıştırılıp çalıştırılamayacağına dair kararın tek
sahibidir. Araçlar kendi izinlerini belirlemez, çağıran taraf da kendi
kuralını uydurmaz: herkes buradaki politikayı sorar.
"""

from app.security.approvals import (
    ApprovalAlreadyDecidedError,
    ApprovalError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalRequest,
    ApprovalService,
    ApprovalStatus,
)
from app.security.permissions import (
    AUDIT_PERMISSION_DOWNGRADE,
    AUDIT_TOOL_OVERRIDE,
    OverridePlan,
    PermissionDecision,
    ToolOverride,
    ToolPermissionPolicy,
    plan_override,
)
from app.security.tool_overrides import ToolOverrideStore

__all__ = [
    "AUDIT_PERMISSION_DOWNGRADE",
    "AUDIT_TOOL_OVERRIDE",
    "ApprovalAlreadyDecidedError",
    "ApprovalError",
    "ApprovalExpiredError",
    "ApprovalNotFoundError",
    "ApprovalRequest",
    "ApprovalService",
    "ApprovalStatus",
    "OverridePlan",
    "PermissionDecision",
    "ToolOverride",
    "ToolOverrideStore",
    "ToolPermissionPolicy",
    "plan_override",
]
