"""Yetenek kaydı uçları.

İki yüz vardır ve bilinçli olarak ayrıdır:

- `/api/admin/capabilities` — yönetim yüzü. Sağlayıcı ve araç listesini
  gösterir; araç başına aç/kapa ve izin override'ı KABUL eder. `admin_token`
  kuralı (`_require_admin`) burada geçerlidir.
- `/api/v1/capabilities` — salt-okunur yüz. Yalnızca hangi yetenek ailesinin
  açık olduğunu ve kaç araç sağladığını bildirir; anahtar, gizli bilgi ya da
  araç argümanı taşımaz.

Gizlilik kuralı: yanıtlarda hiçbir zaman API anahtarı, token ya da araç
argümanı görünmez. Sağlayıcı görünümü yalnızca kimlik, açıklama, etkinlik ve
araç sayısı taşır.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.api.routes.admin import _require_admin
from app.security.audit import (
    AuditAction,
    AuditEvent,
    AuditOutcome,
    safe_record,
)
from app.security.permissions import (
    AUDIT_TOOL_OVERRIDE,
    ToolOverride,
    plan_override,
)
from app.skills.models import skill_override_key
from app.tools.base import PermissionLevel
from app.tools.capabilities import CapabilityRegistry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["capabilities"])

PUBLIC_READER = "reader"
"""Salt-okunur uçların gerektirdiği asgari erişim; kimlik doğrulaması yok."""


class CapabilityToolView(BaseModel):
    """Bir aracın arayüz için güvenli görünümü."""

    name: str
    description: str
    source: str
    category: str
    risk_tags: list[str]
    permission: PermissionLevel
    declared_permission: PermissionLevel
    enabled: bool
    requires_approval: bool
    untrusted_output: bool
    timeout_seconds: float | None = None
    max_output_chars: int | None = None


class CapabilityProviderView(BaseModel):
    """Bir sağlayıcının arayüz için güvenli görünümü."""

    id: str
    description: str
    enabled: bool
    tool_count: int
    ok: bool
    detail: str


class CapabilitySkillView(BaseModel):
    """Bir skill'in arayüz için güvenli görünümü (gövde içermez)."""

    name: str
    description: str
    slug: str
    license: str
    source: str
    source_sha: str
    enabled: bool
    override_key: str


class CapabilitiesResponse(BaseModel):
    """Yönetim yanıtı: sağlayıcılar, araçlar, skill'ler ve yapılandırma sorunları."""

    providers: list[CapabilityProviderView]
    tools: list[CapabilityToolView]
    skills: list[CapabilitySkillView] = []
    errors: list[str]


class ToolOverrideRequest(BaseModel):
    """Bir araç için aç/kapa ve izin override isteği."""

    enabled: bool = True

    permission: PermissionLevel | None = None
    """İstenen izin seviyesi; None ise yalnızca aç/kapa uygulanır."""

    allow_downgrade: bool = False
    """Yetki DÜŞÜREN bir değişiklik için açık kullanıcı onayı.

    Bu bayrak olmadan düşürme reddedilir: sessiz bir `WRITE → READ` bir yetki
    genişlemesidir ve açık istek olmadan kabul edilmemelidir.
    """


class ToolOverrideResponse(BaseModel):
    """Override değerlendirmesinin sonucu."""

    tool_name: str
    accepted: bool
    reason: str
    enabled: bool | None = None
    permission: PermissionLevel | None = None
    audit_action: str | None = None


class PublicCapabilityFamily(BaseModel):
    """Salt-okunur görünümde bir yetenek ailesi — gizli bilgi içermez."""

    id: str
    enabled: bool
    tool_count: int


class PublicCapabilitiesResponse(BaseModel):
    """Salt-okunur yetenek özeti: hangi aile açık, kaç araç sağlıyor."""

    families: list[PublicCapabilityFamily]
    total_tools: int


def _registry(request: Request) -> CapabilityRegistry:
    """Yetenek kaydını döndürür; kurulu değilse 503."""

    registry = getattr(request.app.state, "capability_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "capability_registry_unavailable",
                "message": "Yetenek kaydı kurulu değil.",
            },
        )
    return registry


def _override_store(request: Request) -> Any:
    """Override deposunu döndürür; kurulu değilse 503."""

    store = getattr(request.app.state, "tool_override_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "tool_override_store_unavailable",
                "message": "Araç izin deposu kurulu değil.",
            },
        )
    return store


def _audit_action(name: str) -> AuditAction:
    """Denetim eylemi adını enum üyesine çevirir."""

    return (
        AuditAction.PERMISSION_DOWNGRADE
        if name == "permission_downgrade"
        else AuditAction.TOOL_OVERRIDE
    )


def _to_tool_view(tool: Any) -> CapabilityToolView:
    return CapabilityToolView(
        name=tool.name,
        description=tool.description,
        source=tool.source,
        category=tool.category,
        risk_tags=list(tool.risk_tags),
        permission=tool.permission,
        declared_permission=tool.declared_permission,
        enabled=tool.enabled,
        requires_approval=tool.requires_approval,
        untrusted_output=tool.untrusted_output,
        timeout_seconds=tool.timeout_seconds,
        max_output_chars=tool.max_output_chars,
    )


@router.get(
    "/admin/capabilities",
    response_model=CapabilitiesResponse,
    status_code=status.HTTP_200_OK,
)
async def read_capabilities(request: Request) -> CapabilitiesResponse:
    """Sağlayıcıları, araçları ve kayıt sorunlarını döndürür."""

    _require_admin(request)
    registry = _registry(request)
    snapshot = await registry.describe()
    return CapabilitiesResponse(
        providers=[
            CapabilityProviderView(
                id=provider.id,
                description=provider.description,
                enabled=provider.enabled,
                tool_count=provider.tool_count,
                ok=provider.ok,
                detail=provider.detail,
            )
            for provider in snapshot.providers
        ],
        tools=[_to_tool_view(tool) for tool in snapshot.tools],
        skills=[
            CapabilitySkillView(
                name=skill.name,
                description=skill.description,
                slug=skill.slug,
                license=skill.license,
                source=skill.source,
                source_sha=skill.source_sha,
                enabled=skill.enabled,
                override_key=skill.override_key,
            )
            for skill in snapshot.skills
        ],
        errors=list(snapshot.errors),
    )


@router.put(
    "/admin/capabilities/tools/{name}",
    response_model=ToolOverrideResponse,
    status_code=status.HTTP_200_OK,
)
async def update_tool_capability(
    name: str, body: ToolOverrideRequest, request: Request
) -> ToolOverrideResponse:
    """Bir aracın aç/kapa ve izin override'ını uygular.

    Karar `plan_override` ile TEK bir yerde verilir; bu uç yalnızca kabul
    edilen kararı kalıcılaştırır, denetim kaydına yazar ve kaydı yeniden
    kurar. DANGEROUS düşürme deterministik olarak reddedilir.
    """

    _require_admin(request)
    registry = _registry(request)
    store = _override_store(request)

    tool = registry.registry.get(name)
    if tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tool_not_found", "message": f"'{name}' adlı araç kayıtlı değil."},
        )

    plan = plan_override(
        name,
        tool.effective_permission,
        enabled=body.enabled,
        permission=body.permission,
        allow_downgrade=body.allow_downgrade,
    )

    if not plan.accepted or plan.override is None:
        # Reddedilen istek de iz bırakır: kim, neyi denedi ve neden reddedildi.
        safe_record(
            getattr(request.app.state, "audit_log", None),
            AuditEvent(
                action=AuditAction.TOOL_OVERRIDE,
                outcome=AuditOutcome.BLOCKED,
                tool_name=name,
                arguments={
                    "requested_permission": str(body.permission) if body.permission else None,
                    "enabled": body.enabled,
                    "allow_downgrade": body.allow_downgrade,
                    "reason": plan.reason,
                },
            ),
        )
        return ToolOverrideResponse(
            tool_name=name,
            accepted=False,
            reason=plan.reason,
            audit_action=None,
        )

    store.set(plan.override)
    safe_record(
        getattr(request.app.state, "audit_log", None),
        AuditEvent(
            action=_audit_action(plan.audit_action or "tool_override"),
            outcome=AuditOutcome.SUCCESS,
            tool_name=name,
            arguments={
                "enabled": plan.override.enabled,
                "permission": str(plan.override.permission) if plan.override.permission else None,
                "reason": plan.reason,
            },
        ),
    )

    await registry.rebuild()

    return ToolOverrideResponse(
        tool_name=name,
        accepted=True,
        reason=plan.reason,
        enabled=plan.override.enabled,
        permission=plan.override.permission,
        audit_action=plan.audit_action,
    )


@router.put(
    "/admin/capabilities/skills/{slug}",
    response_model=ToolOverrideResponse,
    status_code=status.HTTP_200_OK,
)
async def update_skill_capability(
    slug: str, body: ToolOverrideRequest, request: Request
) -> ToolOverrideResponse:
    """Bir skill'i açar/kapatır.

    Mevcut `ToolOverrideStore` mekanizması KULLANILIR: anahtar `skill_<slug>`
    biçimindedir. Skill'ler yalnızca aç/kapa edilebilir; izin seviyesi
    kavramı yoktur (izin, skill'in araçlarının kendi seviyesinden gelir ve
    ayrı override edilir). İzin alanı verilirse yok sayılır.
    """

    _require_admin(request)
    registry = _registry(request)
    store = _override_store(request)

    known = {skill.slug for skill in (await registry.describe()).skills}
    if slug not in known:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "skill_not_found", "message": f"'{slug}' adlı skill kayıtlı değil."},
        )

    override = ToolOverride(
        tool_name=skill_override_key(slug),
        enabled=body.enabled,
        permission=None,
    )
    store.set(override)
    safe_record(
        getattr(request.app.state, "audit_log", None),
        AuditEvent(
            action=AuditAction.TOOL_OVERRIDE,
            outcome=AuditOutcome.SUCCESS,
            tool_name=override.tool_name,
            arguments={"enabled": body.enabled, "reason": "skill override"},
        ),
    )

    await registry.rebuild()

    return ToolOverrideResponse(
        tool_name=override.tool_name,
        accepted=True,
        reason="Skill açıldı." if body.enabled else "Skill kapatıldı.",
        enabled=body.enabled,
        permission=None,
        audit_action=AUDIT_TOOL_OVERRIDE,
    )


@router.get(
    "/v1/capabilities",
    response_model=PublicCapabilitiesResponse,
    status_code=status.HTTP_200_OK,
)
async def read_public_capabilities(request: Request) -> PublicCapabilitiesResponse:
    """Hangi yetenek ailesinin açık olduğunu bildirir — gizli bilgi yok.

    Kimlik doğrulaması gerektirmez ve yalnızca özet taşır: aile kimliği,
    açık/kapalı durumu ve araç sayısı. Anahtar, adres, argüman ya da araç
    açıklaması içermez.
    """

    registry = _registry(request)
    snapshot = await registry.describe()
    return PublicCapabilitiesResponse(
        families=[
            PublicCapabilityFamily(
                id=provider.id, enabled=provider.enabled, tool_count=provider.tool_count
            )
            for provider in snapshot.providers
        ],
        total_tools=len(snapshot.tools),
    )
