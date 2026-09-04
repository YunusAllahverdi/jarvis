"""Jarvis FastAPI uygulamasının başlangıç noktası."""

import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.adapters.llm.base import LLMProvider
from app.adapters.llm.ollama import OllamaProvider
from app.agent.context import ContextBuilder
from app.agent.llm_policy import LLMDecisionPolicy
from app.agent.policy import DecisionPolicy, RuleBasedDecisionPolicy
from app.agent.runner import AgentRunner
from app.api.routes.agent import router as agent_router
from app.api.routes.approvals import router as approvals_router
from app.api.routes.admin import router as admin_router
from app.api.routes.chat import router as chat_router
from app.api.routes.checkpoints import router as checkpoints_router
from app.api.routes.coding import router as coding_router
from app.api.routes.health import router as health_router
from app.api.routes.insight import router as insight_router
from app.api.routes.notes import router as notes_router
from app.api.routes.ui import router as ui_router
from app.api.static import mount_frontend
from app.notes.store import NoteStore
from app.security.network import NetworkGuard
from app.ui.actions import UIActionBus
from app.api.routes.user_model import router as user_model_router
from app.coding.loop import CodingLoop
from app.coding.planner import CodingPlanner
from app.coding.review import CodeReviewer
from app.coding.verification import Verifier
from app.config.settings import Settings, get_settings
from app.core.logging import configure_logging
from app.council.gate import CouncilGate
from app.council.models import CouncilMember
from app.learning.sqlite_trait_store import SQLiteUserTraitStore
from app.learning.trait_store import UserTraitStore
from app.memory.experience_store import ExperienceStore
from app.memory.extractor import MemoryExtractor
from app.memory.sqlite_experience_store import SQLiteExperienceStore
from app.memory.sqlite_store import SQLiteMemoryStore
from app.memory.store import MemoryStore
from app.services.agent_service import AgentService
from app.services.coding_service import CodingService
from app.services.conversation import ConversationStore, InMemoryConversationStore
from app.services.council_config import CouncilMemberStore
from app.services.sqlite_conversation import SQLiteConversationStore
from app.security.auth import ApiTokenMiddleware
from app.services.llm_config import LLMConfigStore, SwitchableProvider
from app.services.council_service import CouncilService
from app.services.learning_service import LearningService
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.memory_service import MemoryWriteService
from app.services.memory_temporal import MemoryTemporalService
from app.services.orchestrator import ChatOrchestrator
from app.services.prompts import SystemPromptLoader
from app.services.user_model_service import UserModelService
from app.security.approvals import ApprovalService
from app.security.audit import AuditLog, InMemoryAuditLog, SQLiteAuditLog
from app.security.checkpoints import SQLiteCheckpointStore
from app.security.commands import CommandNotAllowedError, CommandPolicy
from app.security.paths import PathGuard
from app.security.permissions import ToolPermissionPolicy
from app.tools.base import PermissionLevel
from app.tools.defaults import (
    build_default_tool_registry,
    register_context_tools,
    register_filesystem_tools,
    register_maps_tools,
    register_note_tools,
    register_research_tool,
    register_terminal_tool,
    register_ui_tool,
)
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ServiceInfo(BaseModel):
    """Kök endpoint için temel servis bilgisi."""

    name: str
    version: str
    environment: str


def _build_user_model_stack(
    *,
    trait_store: UserTraitStore | None,
    memory_store: MemoryStore | None,
    experience_store: ExperienceStore | None,
) -> tuple[LearningService | None, UserModelService | None]:
    """Öğrenme/kullanıcı modeli servislerini mevcut depolardan kurar.

    Trait deposu yoksa kullanıcı modeli hiç kurulmaz (ikisi de None döner) —
    yazacak yeri olmayan bir öğrenme servisi anlamsızdır. Kaynak depolar
    (bellek/deneyim) ise isteğe bağlıdır: eksik olan kaynak yalnızca ilgili
    trait ailesinin üretilmemesi anlamına gelir, hata değildir.
    """
    if trait_store is None:
        return None, None
    learning_service = LearningService(
        trait_store=trait_store,
        memory_store=memory_store,
        experience_store=experience_store,
    )
    user_model_service = UserModelService(
        trait_store=trait_store,
        experience_store=experience_store,
    )
    return learning_service, user_model_service


def _resolve_audit_db_path(settings: Settings) -> str:
    """Denetim kaydının yazılacağı veritabanı yolunu belirler.

    Varsayılan olarak bellek veritabanının AYNISIDIR; denetim olayları orada
    ayrı bir tabloda durur. Proje tek bir kullanıcı veri dosyası tutmayı
    tercih ediyor — ikinci bir dosya, yedeklemede unutulabilecek ikinci bir
    şey demek olurdu.
    """
    return settings.audit_db_path or settings.memory_db_path


def _build_workspace_guard(settings: Settings) -> PathGuard | None:
    """Yapılandırılmışsa çalışma kökü bekçisini kurar.

    Ayar boşsa None döner ve dosya araçları hiç kaydedilmez. Yol geçersizse
    de None döner: bozuk bir ayar yüzünden uygulamayı düşürmek yerine,
    yeteneği kapalı bırakıp durumu loglamak daha güvenli bir başarısızlıktır.
    """
    if not settings.workspace_root:
        return None
    try:
        return PathGuard(settings.workspace_root)
    except ValueError:
        logger.warning(
            "workspace_root_invalid",
            extra={"event": "workspace_root_invalid", "workspace_root": settings.workspace_root},
        )
        return None


def _build_command_policy(settings: Settings) -> CommandPolicy:
    """Komut politikasını ayarlardan kurar; liste boşsa varsayılan küme."""

    if settings.terminal_allowed_commands:
        return CommandPolicy(allowed_commands=settings.terminal_allowed_commands)
    return CommandPolicy()


def _build_agent_policy(settings: Settings) -> ToolPermissionPolicy:
    """Uygulamanın araç izin duruşunu ayarlardan kurar — tek beyan noktası.

    READ her zaman serbesttir. WRITE her zaman kullanıcı onayına tabidir.
    DANGEROUS ise yalnızca terminal AÇIKÇA etkinleştirildiğinde onaya
    tabidir; kapalıyken reddedilir.

    Bu ayrım bilinçlidir: reddedilen bir seviye, onaylanabilir bir seviyeden
    farklıdır. Terminal kapalıyken DANGEROUS bir aracın var olması bile
    çalıştırılabilmesi anlamına gelmez — kullanıcı yanlışlıkla onaylayarak
    açamaz, önce ayarı değiştirmesi gerekir.
    """
    approval_levels = {PermissionLevel.WRITE}
    if settings.terminal_enabled:
        approval_levels.add(PermissionLevel.DANGEROUS)
    return ToolPermissionPolicy(
        allowed={PermissionLevel.READ},
        requires_approval=approval_levels,
    )
"""Uygulamanın araç izin duruşu — tek beyan noktası.

READ serbesttir, WRITE kullanıcı onayına tabidir, DANGEROUS reddedilir. Bu fazda o
seviyelerde tool yoktur, dolayısıyla ret pratikte bir şeyi engellemiyor —
ama varsayılanı burada açıkça yazmak, ileride bir tool eklendiğinde onun
sessizce serbest kalmamasını garanti eder.

Onay akışı devreye girdiğinde WRITE bu politikada `requires_approval`
listesine taşınacak; hem executor hem agent bağlamı aynı örneği kullandığı
için değişiklik tek yerden yapılır.
"""


_DEFAULT_VERIFICATION_COMMANDS: tuple[str, ...] = (
    "pytest -q",
    "python -m pytest -q",
    "npm test",
)
"""Doğrulama komutu adaylarının varsayılan kümesi.

Kısa ve tanıdıktır: ajanın kendi değişikliğini doğrulaması için gereken en
yaygın komutlar. Kullanılmadan önce komut politikasının tanıdıklarıyla
KESİŞTİRİLİR — politikanın çalıştırmayacağı bir komutu modele önermek,
kesin başarısız olacak bir tur harcatmak olurdu.
"""


def _resolve_verification_commands(
    settings: Settings, command_policy: CommandPolicy
) -> tuple[str, ...]:
    """Görev modelinin seçebileceği doğrulama komutlarını belirler.

    Kullanıcı açıkça bir liste verdiyse o kullanılır; vermediyse varsayılan
    küme kullanılır. Her iki durumda da politika süzgeci uygulanır: model
    yalnızca gerçekten çalıştırılabilecek bir komut seçebilir.
    """
    candidates = settings.coding_verification_commands or list(_DEFAULT_VERIFICATION_COMMANDS)
    allowed: list[str] = []
    for command in candidates:
        normalized = command.strip()
        if not normalized:
            continue
        try:
            command_policy.parse(normalized)
        except CommandNotAllowedError:
            logger.debug(
                "coding_verification_command_filtered",
                extra={"command": normalized[:120]},
            )
            continue
        if normalized not in allowed:
            allowed.append(normalized)
    return tuple(allowed)


def _build_coding_service(
    settings: Settings,
    *,
    agent: AgentService,
    provider: LLMProvider,
    command_policy: CommandPolicy,
    approval_service: ApprovalService | None,
    council_service: CouncilService | None = None,
) -> CodingService | None:
    """Kodlama döngüsünü kurar; şartlar sağlanmıyorsa None döner.

    DÖRT ŞART BİRDEN gerekir ve hiçbiri diğerinin yerine geçmez:
    açık bir etkinleştirme, bir çalışma kökü, yazma yetkisi ve terminal.
    Döngü, ajanın dosya değiştirip komut çalıştırdığı en yetkili yoldur;
    tek bir anahtarla açılmaması bilinçlidir. Şartlardan biri eksikse
    servis hiç var olmaz — kayıtlı ama çalışmayan bir uç, kullanıcıya
    sahip olmadığı bir yeteneği varmış gibi gösterirdi.

    AJANIN YÜRÜTME SINIRI YENİDEN KULLANILIR: ikinci bir `ToolExecutor`
    kurulsaydı, izin politikası veya denetim kaydı ikisinde ayrışabilirdi.
    Araç kaydı da o sınırdan okunur, böylece planlanabilen ile
    çalıştırılabilen küme aynı kalır.
    """
    if not settings.coding_loop_enabled:
        return None
    if not (settings.workspace_root and settings.workspace_writable and settings.terminal_enabled):
        logger.info(
            "coding_loop_not_built",
            extra={
                "has_workspace": bool(settings.workspace_root),
                "writable": settings.workspace_writable,
                "terminal_enabled": settings.terminal_enabled,
            },
        )
        return None

    executor = agent.tool_executor
    commands = _resolve_verification_commands(settings, command_policy)
    if not commands:
        logger.warning("coding_loop_no_verification_commands")

    loop = CodingLoop(
        planner=CodingPlanner(provider=provider, model_label=settings.ollama_model),
        verifier=Verifier(
            tool_executor=executor,
            timeout_seconds=settings.coding_verification_timeout_seconds,
        ),
        tool_executor=executor,
        approval_service=approval_service,
        # İnceleme Council'a bağlıdır: üye başına farklı sağlayıcı
        # yapılandırılabildiği için diff'i, kodu yazandan BAŞKA modellere
        # inceletmek mümkündür. Kendi işini inceleyen bir model, kendi kör
        # noktasını da taşır.
        reviewer=(
            CodeReviewer(council_service=council_service)
            if council_service is not None and settings.coding_review_enabled
            else None
        ),
        verification_candidates=commands,
        max_iterations=settings.coding_max_iterations,
    )
    logger.info(
        "coding_loop_built",
        extra={
            "max_iterations": settings.coding_max_iterations,
            "verification_command_count": len(commands),
            "review_enabled": council_service is not None and settings.coding_review_enabled,
        },
    )
    return CodingService(loop=loop)


def _build_decision_policy(
    *, policy_name: str, provider: LLMProvider, model_label: str | None
) -> DecisionPolicy:
    """Ayarlara göre karar politikasını seçer.

    `RuleBasedDecisionPolicy` her durumda korunur: "llm" seçildiğinde bile
    yedek (fallback) politika olarak verilir, böylece sağlayıcı erişilemez
    olduğunda veya çıktısı reddedildiğinde sistem deterministik davranışa
    düşer. Yeni bir LLM istemcisi yazılmaz; mevcut `LLMProvider` soyutlaması
    olduğu gibi kullanılır.
    """
    rule_based = RuleBasedDecisionPolicy()
    if policy_name != "llm":
        return rule_based
    return LLMDecisionPolicy(
        provider=provider, fallback=rule_based, model_label=model_label
    )


def _build_council_service(
    settings: Settings,
) -> tuple[CouncilService | None, list[LLMProvider]]:
    """Yapılandırmadan Council'ı kurar ve kapatılması gereken sağlayıcıları döndürür.

    Model başına BİR sağlayıcı örneği kurulur ve `member-N` biçiminde opaque
    kimliklerle Council'a verilir — model adı Council çekirdeğine hiç ulaşmaz.

    Chairman, üyelerden biriyle aynı modelse AYNI sağlayıcı örneği yeniden
    kullanılır (gereksiz ikinci HTTP istemcisi açılmaz). Farklıysa yalnızca
    onun için ek bir örnek kurulur.

    Returns:
        `(servis, kapatılacak_sağlayıcılar)`. Council kapalıysa veya yeterli
        üye yapılandırılmamışsa `(None, [])` döner — bu bir hata değildir.
    """
    if not settings.council_enabled:
        return None, []

    names = settings.council_models[: settings.council_max_members]
    if len(names) < settings.council_min_candidates:
        logger.warning(
            "council_not_built_insufficient_models",
            extra={
                "configured": len(settings.council_models),
                "required": settings.council_min_candidates,
            },
        )
        return None, []

    def _provider_for(model_name: str) -> LLMProvider:
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=model_name,
            timeout_seconds=settings.council_member_timeout_seconds,
        )

    providers_by_model: dict[str, LLMProvider] = {}
    members: list[CouncilMember] = []
    for index, model_name in enumerate(names, start=1):
        provider = _provider_for(model_name)
        providers_by_model[model_name] = provider
        members.append(CouncilMember(member_id=f"member-{index}", provider=provider))

    chairman_model = settings.council_chairman_model or names[0]
    chairman_provider = providers_by_model.get(chairman_model)
    if chairman_provider is None:
        chairman_provider = _provider_for(chairman_model)
        providers_by_model[chairman_model] = chairman_provider
    chairman = CouncilMember(member_id="chairman", provider=chairman_provider)

    logger.info(
        "council_built",
        extra={
            "member_count": len(members),
            "provider_count": len(providers_by_model),
            "review_enabled": settings.council_review_enabled,
        },
    )
    service = CouncilService(
        members=members,
        chairman=chairman,
        min_candidates=settings.council_min_candidates,
        review_enabled=settings.council_review_enabled,
        member_timeout_seconds=settings.council_member_timeout_seconds,
        total_timeout_seconds=settings.council_total_timeout_seconds,
        max_concurrency=settings.council_max_concurrency,
        max_candidate_chars=settings.council_max_candidate_chars,
        max_review_chars=settings.council_max_review_chars,
    )
    return service, list(providers_by_model.values())


def _build_council_from_store(
    settings: Settings, store: CouncilMemberStore
) -> tuple[CouncilService | None, list[LLMProvider]]:
    """Üye deposundan Council'ı kurar; yeterli üye yoksa `(None, [])`.

    `_build_council_service`'ten farkı, üyelerin AYRI sağlayıcılara ve ayrı
    anahtarlara gidebilmesidir — "birden fazla ajan, birden fazla anahtar"
    isteğinin karşılığı budur. Council çekirdeği bu farkı hiç görmez;
    ona yine yalnızca opaque kimlikli üyeler verilir.

    Depo boşsa bu bir hata DEĞİLDİR: kullanıcı üye tanımlamamıştır ve
    yapılandırma yolundan gelen Council (varsa) geçerli kalır.
    """
    members, chairman, providers = store.build_members(
        max_members=settings.council_max_members
    )
    if chairman is None or len(members) < settings.council_min_candidates:
        if members:
            logger.warning(
                "council_store_insufficient_members",
                extra={
                    "configured": len(members),
                    "required": settings.council_min_candidates,
                },
            )
        return None, []

    logger.info(
        "council_built_from_store",
        extra={"member_count": len(members), "provider_count": len(providers)},
    )
    return (
        CouncilService(
            members=members,
            chairman=chairman,
            min_candidates=settings.council_min_candidates,
            review_enabled=settings.council_review_enabled,
            member_timeout_seconds=settings.council_member_timeout_seconds,
            total_timeout_seconds=settings.council_total_timeout_seconds,
            max_concurrency=settings.council_max_concurrency,
            max_candidate_chars=settings.council_max_candidate_chars,
            max_review_chars=settings.council_max_review_chars,
        ),
        providers,
    )


def _build_agent_stack(
    *,
    conversation_store: ConversationStore,
    memory_retrieval: MemoryRetrievalService | None,
    experience_store: ExperienceStore | None,
    user_model: UserModelService | None,
    policy: DecisionPolicy | None = None,
    council_service: CouncilService | None = None,
    council_gate: CouncilGate | None = None,
    audit_log: AuditLog | None = None,
    workspace_guard: PathGuard | None = None,
    workspace_writable: bool = False,
    change_journal: object | None = None,
    approval_service: ApprovalService | None = None,
    policy_boundary: ToolPermissionPolicy,
    note_store: NoteStore | None = None,
    notes_writable: bool = True,
    network_guard: NetworkGuard | None = None,
    research_timeout_seconds: float = 20.0,
    ui_action_bus: UIActionBus | None = None,
    terminal_enabled: bool = False,
    command_policy: CommandPolicy | None = None,
    terminal_timeout_seconds: float = 60.0,
    timezone_name: str | None = None,
    maps_api_key: str = "",
) -> AgentService:
    """Agent karar katmanını mevcut public servislerden kurar.

    ÖNEMLİ — AYRI TOOL REGISTRY: Agent kendi `ToolRegistry` ÖRNEĞİNİ alır
    (ayrı bir soyutlama değil, aynı sınıfın ikinci örneği). Böylece agent'a
    eklenen `memory_search`/`user_profile` tool'ları, LLM'in normal sohbet
    sırasında gördüğü tool yüzeyini DEĞİŞTİRMEZ ve mevcut sohbet davranışı
    bit düzeyinde korunur. İleride tek bir registry'de birleştirmek istenirse
    bu, tek satırlık bir değişikliktir.

    Kaynak servisler isteğe bağlıdır: verilmeyen kaynak yalnızca ilgili
    bağlam bölümünün boş kalmasına ve ilgili tool'un kaydedilmemesine yol açar.
    """
    agent_registry = build_default_tool_registry(timezone_name=timezone_name)
    registered = register_context_tools(
        agent_registry, memory_retrieval=memory_retrieval, user_model=user_model
    )
    # Dosya araçları YALNIZCA agent registry'sine eklenir; sohbetin LLM'e
    # sunduğu tool yüzeyi değişmez.
    registered += register_filesystem_tools(
        agent_registry,
        guard=workspace_guard,
        writable=workspace_writable,
        journal=change_journal,
    )
    # Notlar ve araştırma da yalnızca agent registry'sine eklenir; sohbetin
    # LLM'e sunduğu tool yüzeyi değişmez.
    registered += register_note_tools(
        agent_registry, store=note_store, writable=notes_writable
    )
    registered += register_research_tool(
        agent_registry, guard=network_guard, timeout_seconds=research_timeout_seconds
    )
    registered += register_ui_tool(agent_registry, bus=ui_action_bus)
    registered += register_terminal_tool(
        agent_registry,
        guard=workspace_guard,
        command_policy=command_policy,
        enabled=terminal_enabled,
        max_timeout_seconds=terminal_timeout_seconds,
    )
    registered += register_maps_tools(agent_registry, api_key=maps_api_key)
    context_builder = ContextBuilder(
        tool_registry=agent_registry,
        policy=policy_boundary,
        conversation_store=conversation_store,
        memory_retrieval=memory_retrieval,
        experience_store=experience_store,
        user_model=user_model,
    )
    logger.info(
        "agent_stack_built",
        extra={
            "context_tools": registered,
            "tool_count": len(agent_registry.list_tools()),
        },
    )
    return AgentService(
        context_builder=context_builder,
        policy=policy or RuleBasedDecisionPolicy(),
        council_service=council_service,
        council_gate=council_gate,
        approval_service=approval_service,
        runner=AgentRunner(
            tool_executor=ToolExecutor(
                agent_registry, policy=policy_boundary, audit_log=audit_log
            )
        ),
    )


def create_app(
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    conversation_store: ConversationStore | None = None,
    tool_registry: ToolRegistry | None = None,
    memory_service: MemoryWriteService | None = None,
    memory_retrieval: MemoryRetrievalService | None = None,
    experience_store: ExperienceStore | None = None,
    memory_store: MemoryStore | None = None,
    user_trait_store: UserTraitStore | None = None,
    agent_service: AgentService | None = None,
    council_service: CouncilService | None = None,
) -> FastAPI:
    """Bağımlılıkları enjekte edilebilir bir FastAPI uygulaması oluşturur."""

    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)

    # provider enjekte edilmediyse gerçek (üretim) Ollama sağlayıcısı kurulur.
    # Bellek yığınının otomatik bağlanması da yalnızca bu durumda yapılır: bir
    # test/çağıran kendi sahte sağlayıcısını enjekte ettiğinde, bu sağlayıcı
    # bellek çıkarımına da sessizce bağlanmaz. Bu sayede mevcut testler
    # (memory_service enjekte etmeyen tüm testler) hiç etkilenmeden eskisi
    # gibi çalışmaya devam eder; bellek istenen testler memory_service'i
    # açıkça enjekte eder.
    using_default_provider = provider is None
    # Varsayılan sağlayıcı değiştirilebilir bir sarmalayıcıya alınır: sohbet,
    # bellek çıkarımı ve ajan hep AYNI nesneyi tutar, dolayısıyla yönetim
    # panelinden yapılan değişiklik hepsinde birden geçerli olur.
    active_provider = provider if provider is not None else SwitchableProvider(OllamaProvider(
        base_url=active_settings.ollama_base_url,
        model=active_settings.ollama_model,
        timeout_seconds=active_settings.ollama_timeout_seconds,
    ))
    active_conversation_store = (
        conversation_store if conversation_store is not None else InMemoryConversationStore()
    )
    # Kalıcı konuşma deposu bir SQLite dosyası açar; diğer depolarla aynı
    # gerekçeyle create_app() içinde DEĞİL, uygulama fiilen başlatıldığında
    # kurulur ve orchestrator'a geç bağlanır. Böylece `app.main`'i içe
    # aktarmak tek başına kullanıcının veritabanına asla dokunmaz.
    auto_wire_conversation_on_startup = (
        conversation_store is None
        and using_default_provider
        and active_settings.conversation_persistence
    )

    active_tool_registry = (
        tool_registry
        if tool_registry is not None
        else build_default_tool_registry(timezone_name=active_settings.timezone or None)
    )

    # Çağıran memory_service ve/veya memory_retrieval'i açıkça verdiyse hemen
    # kullanılır (I/O maliyetini zaten çağıran üstlenmiştir). Aksi halde —
    # provider enjekte edilmemiş VE her ikisi de verilmemişse — gerçek bellek
    # yığını (yazma + getirme) kurulacaktır, ANCAK bu kurulum SQLite dosyasına
    # dokunduğundan create_app() içinde hemen değil, uygulama fiilen
    # başlatıldığında (lifespan startup, aşağıda) yapılır. Bu ayrım sayesinde
    # `app.main`'i içe aktarmak (import) — modül seviyesindeki `app = create_app()`
    # satırı dahil — kullanıcının kalıcı bellek veritabanını asla oluşturmaz;
    # veritabanı yalnızca uygulama gerçekten sunuma başladığında oluşur.
    #
    # Yazma ve getirme servisleri her zaman BİRLİKTE kurulur ve AYNI
    # SQLiteMemoryStore örneğini paylaşır — iki ayrı SQLite bağlantı mimarisi
    # oluşmaz. Çağıran yalnızca birini elle vermek isterse, ikisini de açıkça
    # sağlamalıdır; otomatik kurulum yalnızca ikisi de None olduğunda devreye girer.
    initial_memory_service = memory_service
    initial_memory_retrieval = memory_retrieval
    auto_wire_memory_on_startup = (
        initial_memory_service is None
        and initial_memory_retrieval is None
        and using_default_provider
    )

    # Experience kalıcılaştırması, Memory'den BAĞIMSIZ bir sınırdır: Memory
    # "Jarvis ne biliyor?" sorusunu, Experience ise "ne oldu?" sorusunu
    # yanıtlar. Bu yüzden otomatik kurulum bayrağı bilinçli olarak
    # memory_service/memory_retrieval'e BAĞLANMAZ — çağıran yalnızca bellek
    # yığınını elle verdi diye Experience kalıcılaştırması sessizce kapanmaz.
    #
    # `using_default_provider` koşulu ise şarttır: sahte bir sağlayıcı enjekte
    # eden testlerde uygulamanın başlatılması, yalnızca başlatıldığı için
    # kullanıcının SQLite dosyasını oluşturmamalıdır (bellek yığını için de
    # geçerli olan aynı ilke).
    initial_experience_store = experience_store
    auto_wire_experience_on_startup = (
        initial_experience_store is None and using_default_provider
    )

    # Öğrenme/kullanıcı modeli katmanı da aynı ilkeyi izler ve Memory ile
    # Experience'tan BAĞIMSIZ bir bayrağa sahiptir. Kullanıcı modeli türetilmiş
    # bir katmandır: kaynakları (bellek/deneyim) eksik olsa bile kurulabilir,
    # yalnızca üretebildiği trait ailesi daralır.
    initial_memory_store = memory_store
    initial_user_trait_store = user_trait_store
    auto_wire_user_model_on_startup = (
        initial_user_trait_store is None and using_default_provider
    )

    # Çağıran depoları açıkça verdiyse kullanıcı modeli hemen kurulur; aksi
    # halde (otomatik kurulum yolunda) lifespan startup'ta kurulacaktır.
    initial_learning_service, initial_user_model_service = _build_user_model_stack(
        trait_store=initial_user_trait_store,
        memory_store=initial_memory_store,
        experience_store=initial_experience_store,
    )

    # Agent karar katmanı. Sohbet akışının PARÇASI DEĞİLDİR: ChatOrchestrator
    # bu servisi hiç tanımaz, dolayısıyla agent katmanındaki bir sorun normal
    # sohbet cevabını hiçbir koşulda etkileyemez. Çağıran açıkça bir agent
    # verdiyse o kullanılır; aksi halde lifespan startup'ta kurulur.
    initial_agent_service = agent_service
    auto_wire_agent_on_startup = initial_agent_service is None and using_default_provider

    # Council. Varsayılan kapalı olduğundan bu blok normalde hiç çalışmaz ve
    # sistem davranışı Council eklenmeden önceki hâliyle aynı kalır.
    # Sağlayıcı örnekleri burada kurulur ve lifespan sonunda kapatılır.
    initial_council_service = council_service
    council_providers: list[LLMProvider] = []
    if initial_council_service is None:
        initial_council_service, council_providers = _build_council_service(active_settings)
    # Kapının `enabled`'ı, ayarın kendisi değil BİR SERVİSİN VAR OLMASIDIR:
    # `council_enabled` zaten servisin kurulup kurulmayacağını belirler ve
    # çağıran açıkça bir servis enjekte ettiyse Council'ı istiyor demektir.
    council_gate = (
        CouncilGate(
            enabled=True,
            member_count=initial_council_service.member_count,
            min_candidates=active_settings.council_min_candidates,
        )
        if initial_council_service is not None
        else None
    )

    # Council, lifespan sırasında üye deposundan YENİDEN kurulabilir; o an
    # hangi servisin ve hangi sağlayıcıların geçerli olduğunu tek yerde
    # tutmak için değiştirilebilir bir kayıt kullanılır. İki ayrı yerel
    # değişken bırakılsaydı, kapatma adımı eski sağlayıcı listesini kapatıp
    # yenisini sızdırabilirdi.
    active_council: dict[str, object] = {
        "service": initial_council_service,
        "gate": council_gate,
        "providers": council_providers,
    }

    # Başlangıçta bellek içi: kalıcı kayıt bir dosya açar ve bu, uygulama
    # fiilen başlayana kadar yapılmamalıdır (lifespan içinde takas edilir).
    initial_audit_log = InMemoryAuditLog()
    agent_policy = _build_agent_policy(active_settings)
    chat_tool_executor = ToolExecutor(
        active_tool_registry, policy=agent_policy, audit_log=initial_audit_log
    )

    chat_orchestrator = ChatOrchestrator(
        provider=active_provider,
        conversation_store=active_conversation_store,
        prompt_loader=SystemPromptLoader(active_settings.system_prompt_file),
        tool_registry=active_tool_registry,
        tool_executor=chat_tool_executor,
        memory_service=initial_memory_service,
        memory_retrieval=initial_memory_retrieval,
        experience_store=initial_experience_store,
        # Sohbet entegrasyonu ayarla kapatılabilir: agent API'si açık kalırken
        # sohbet akışının karar katmanını hiç çağırmaması istenebilir.
        agent_service=(
            initial_agent_service if active_settings.agent_chat_integration else None
        ),
        context_message_limit=active_settings.conversation_context_limit,
    )

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        if auto_wire_conversation_on_startup:
            # Konuşma geçmişi artık yeniden başlatmayı atlatır. Ajan da AYNI
            # örneği alır (aşağıda), yoksa sohbet ile ajan farklı geçmişlere
            # bakardı ve ajanın bağlamı yeniden başlatmada boşalırdı.
            startup_conversations = SQLiteConversationStore(active_settings.memory_db_path)
            chat_orchestrator.set_conversation_store(startup_conversations)
            app_instance.state.conversation_store = startup_conversations

        if using_default_provider and active_settings.notes_enabled:
            # Not deposu da bir dosya açar; diğer kalıcı depolarla aynı
            # gerekçeyle burada kurulur.
            app_instance.state.note_store = NoteStore(active_settings.memory_db_path)

        if auto_wire_memory_on_startup:
            # Tek bir SQLiteMemoryStore örneği kurulur ve zamansal (temporal)
            # ile getirme (retrieval) servisleri arasında paylaşılır — iki
            # ayrı SQLite bağlantı mimarisi oluşmaz. ChatOrchestrator, temporal
            # servisi hiç bilmez: temporal servis yalnızca MemoryWriteService'in
            # İÇİNDE, yazma yolunu dolaylı olarak zenginleştiren bir bileşendir.
            memory_store = SQLiteMemoryStore(active_settings.memory_db_path)
            memory_extractor = MemoryExtractor(provider=active_provider)
            memory_temporal = MemoryTemporalService(store=memory_store)
            startup_memory_service = MemoryWriteService(
                extractor=memory_extractor,
                store=memory_store,
                temporal_service=memory_temporal,
            )
            startup_memory_retrieval = MemoryRetrievalService(store=memory_store)
            chat_orchestrator.set_memory_service(startup_memory_service)
            chat_orchestrator.set_memory_retrieval(startup_memory_retrieval)
            app_instance.state.memory_store = memory_store
            app_instance.state.memory_temporal = memory_temporal
            app_instance.state.memory_service = startup_memory_service
            app_instance.state.memory_retrieval = startup_memory_retrieval

        if auto_wire_experience_on_startup:
            # Bellek yığınından TAMAMEN ayrı bir blok: Experience deposu kendi
            # tablosunu (`experiences`) kendi başına yönetir, MemoryStore'u hiç
            # bilmez. Yine de AYNI fiziksel SQLite dosyası kullanılır — ikinci
            # bir veritabanı dosyası oluşturulmaz.
            #
            # SQLiteMemoryStore ile aynı gerekçeyle burada, yani uygulama
            # fiilen başlatıldığında kurulur; create_app() veya `app.main`
            # importu tek başına kullanıcının veritabanına asla dokunmaz.
            startup_experience_store = SQLiteExperienceStore(active_settings.memory_db_path)
            chat_orchestrator.set_experience_store(startup_experience_store)
            app_instance.state.experience_store = startup_experience_store

        if auto_wire_user_model_on_startup:
            # Öğrenme katmanı en son kurulur çünkü kaynakları (bellek ve
            # deneyim depoları) yukarıdaki bloklarda oluşur — burada artık
            # app_instance.state üzerinden hazır hâlde okunabilirler.
            # Kaynaklardan biri kurulmamışsa (çağıran elle enjekte ettiği
            # için) None geçilir; öğrenme servisi bunu sorunsuz karşılar.
            #
            # Trait deposu da AYNI fiziksel SQLite dosyasını kullanır —
            # üçüncü bir veritabanı dosyası oluşturulmaz.
            startup_trait_store = SQLiteUserTraitStore(active_settings.memory_db_path)
            startup_learning, startup_user_model = _build_user_model_stack(
                trait_store=startup_trait_store,
                memory_store=app_instance.state.memory_store,
                experience_store=app_instance.state.experience_store,
            )
            app_instance.state.user_trait_store = startup_trait_store
            app_instance.state.learning_service = startup_learning
            app_instance.state.user_model_service = startup_user_model

        if using_default_provider and auto_wire_memory_on_startup:
            # Yapılandırma deposu diğer kalıcı depolarla aynı dosyayı
            # paylaşır ve yalnızca veritabanına zaten dokunulan kurulumlarda
            # açılır.
            startup_llm_config = LLMConfigStore(
                _resolve_audit_db_path(active_settings)
            )
            app_instance.state.llm_config_store = startup_llm_config
            if startup_llm_config.get() != startup_llm_config._default:
                await active_provider.switch(startup_llm_config.build_provider())

            # Üye başına sağlayıcı deposu. Tanımlı üye varsa Council BURADAN
            # kurulur ve `council_models` ayarı yok sayılır: ikisi birden
            # geçerli olsaydı, panelden üye silen kullanıcı ayardan gelen
            # üyelerin sessizce devam ettiğini görürdü.
            startup_council_store = CouncilMemberStore(
                _resolve_audit_db_path(active_settings)
            )
            app_instance.state.council_member_store = startup_council_store
            stored_service, stored_providers = _build_council_from_store(
                active_settings, startup_council_store
            )
            if stored_service is not None:
                # Ayardan gelen Council varsa sağlayıcıları sızdırılmadan
                # bırakılır: bu noktada henüz hiçbir istek görmediler.
                for superseded in active_council["providers"]:  # type: ignore[union-attr]
                    closer = getattr(superseded, "aclose", None)
                    if closer is None:
                        continue
                    try:
                        await closer()
                    except Exception:  # noqa: BLE001
                        logger.exception("provider_close_failed")
                active_council["service"] = stored_service
                active_council["providers"] = stored_providers
                active_council["gate"] = CouncilGate(
                    enabled=True,
                    member_count=stored_service.member_count,
                    min_candidates=active_settings.council_min_candidates,
                )

        # Kalıcı denetim kaydı yalnızca veritabanına zaten dokunulan
        # kurulumlarda açılır. Sağlayıcı enjekte edildiğinde hiçbir dosya
        # oluşturulmaz; o durumda kayıt bellekte kalır.
        startup_audit_log: AuditLog = initial_audit_log
        if auto_wire_memory_on_startup:
            startup_audit_log = SQLiteAuditLog(_resolve_audit_db_path(active_settings))
            app_instance.state.audit_log = startup_audit_log
            chat_tool_executor.set_audit_log(startup_audit_log)

        workspace_guard = _build_workspace_guard(active_settings)
        if workspace_guard is not None and auto_wire_memory_on_startup:
            app_instance.state.checkpoint_store = SQLiteCheckpointStore(
                _resolve_audit_db_path(active_settings), root=workspace_guard.root
            )

        command_policy = _build_command_policy(active_settings)

        if auto_wire_agent_on_startup:
            # Agent en son kurulur: bağlam kaynaklarının (bellek, deneyim,
            # kullanıcı modeli) tamamı yukarıdaki bloklarda oluşmuş olur.
            # Kurulmamış olan kaynak None geçilir; agent bunu sorunsuz karşılar.
            startup_agent = _build_agent_stack(
                # Sohbetle AYNI depo: ayrı örnekler olsaydı ajanın gördüğü
                # geçmiş, kullanıcının gördüğünden farklı olurdu.
                conversation_store=getattr(
                    app_instance.state, "conversation_store", active_conversation_store
                ),
                memory_retrieval=app_instance.state.memory_retrieval,
                experience_store=app_instance.state.experience_store,
                user_model=app_instance.state.user_model_service,
                policy=_build_decision_policy(
                    policy_name=active_settings.agent_decision_policy,
                    provider=active_provider,
                    model_label=active_settings.ollama_model,
                ),
                council_service=active_council["service"],  # type: ignore[arg-type]
                council_gate=active_council["gate"],  # type: ignore[arg-type]
                audit_log=startup_audit_log,
                workspace_guard=workspace_guard,
                change_journal=app_instance.state.checkpoint_store,
                workspace_writable=active_settings.workspace_writable,
                approval_service=app_instance.state.approval_service,
                policy_boundary=agent_policy,
                note_store=getattr(app_instance.state, "note_store", None),
                notes_writable=active_settings.notes_writable,
                network_guard=(
                    NetworkGuard(
                        allowed_domains=active_settings.research_allowed_domains
                    )
                    if active_settings.research_enabled
                    else None
                ),
                research_timeout_seconds=active_settings.research_timeout_seconds,
                ui_action_bus=app_instance.state.ui_action_bus,
                terminal_enabled=active_settings.terminal_enabled,
                command_policy=command_policy,
                terminal_timeout_seconds=active_settings.terminal_timeout_seconds,
                timezone_name=active_settings.timezone or None,
                maps_api_key=active_settings.maps_api_key,
            )
            app_instance.state.agent_service = startup_agent
            app_instance.state.approval_executor = startup_agent.tool_executor
            # Yönetim uçları Council'ı yeniden kurduğunda buradaki durumu da
            # günceller; başlangıçta ikisi tutarlı olmalıdır.
            app_instance.state.council_service = active_council["service"]
            app_instance.state.council_gate = active_council["gate"]
            app_instance.state.council_providers = active_council["providers"]
            # Sohbet entegrasyonu ayrı bir anahtardır: agent API'si açık
            # kalırken sohbet akışının agent'ı hiç çağırmaması istenebilir.
            if active_settings.agent_chat_integration:
                chat_orchestrator.set_agent_service(startup_agent)

            # Kodlama döngüsü ajandan SONRA kurulur: ajanın yürütme sınırını
            # ve araç kaydını yeniden kullanır, dolayısıyla ajan olmadan
            # kurulamaz. Sohbet akışına BAĞLANMAZ — döngüdeki bir sorun
            # normal sohbeti hiçbir koşulda etkileyemez.
            app_instance.state.coding_service = _build_coding_service(
                active_settings,
                agent=startup_agent,
                provider=active_provider,
                command_policy=command_policy,
                approval_service=app_instance.state.approval_service,
                council_service=active_council["service"],  # type: ignore[arg-type]
            )

        logger.info(
            "application_started",
            extra={
                "event": "application_started",
                "environment": active_settings.environment,
                "version": active_settings.app_version,
            },
        )
        yield
        # OllamaProvider gibi kapatılabilir provider'ları düzgün kapat.
        # Council üyeleri için model başına ayrı birer HTTP istemcisi açılır;
        # hiçbiri sızdırılmamalıdır. Bir kapatmanın başarısız olması diğerlerini
        # engellememeli, bu yüzden her biri ayrı ayrı korunur.
        # Kapatılacak Council sağlayıcıları, uygulamanın SON durumundan
        # okunur: yönetim panelinden üye değiştirildiyse liste başlangıçtaki
        # liste değildir ve eskisini kapatmak yenisini sızdırmak olurdu.
        closing_council = (
            getattr(app_instance.state, "council_providers", None)
            or active_council["providers"]
        )
        for closable in (active_provider, *closing_council):  # type: ignore[misc]
            if not hasattr(closable, "aclose"):
                continue
            try:
                await closable.aclose()
            except Exception:  # noqa: BLE001
                logger.exception("provider_close_failed")
        logger.info("application_stopped", extra={"event": "application_stopped"})

    app = FastAPI(
        title=active_settings.app_name,
        version=active_settings.app_version,
        lifespan=lifespan,
    )
    # Kimlik katmanı EN DIŞTA durur: yönlendirmeden önce çalışır, dolayısıyla
    # sonradan eklenen bir router'ı korumak için ayrıca bir şey yapılması
    # gerekmez — muaf tutmak için yapılması gerekir.
    app.add_middleware(
        ApiTokenMiddleware,
        token=active_settings.api_token,
        host=active_settings.host,
    )
    app.state.settings = active_settings
    app.state.chat_orchestrator = chat_orchestrator
    # Kalıcı depo lifespan'de takas edilir; o ana kadar RAM deposu geçerlidir.
    app.state.conversation_store = active_conversation_store
    app.state.tool_registry = active_tool_registry
    app.state.approval_service = ApprovalService(
        ttl_seconds=active_settings.approval_ttl_seconds,
        max_pending=active_settings.approval_max_pending,
    )
    # Onaylı çağrının geçeceği sınır, ajan yığını kurulduğunda atanır.
    app.state.approval_executor = None
    app.state.audit_log = initial_audit_log
    # Geri alma kaydı bir çalışma kökü gerektirir; lifespan'de kurulur.
    app.state.checkpoint_store = None
    app.state.llm_config_store = None
    # Üye başına Council yapılandırması: diğer kalıcı depolarla aynı gerekçeyle
    # lifespan'de kurulur, o ana kadar None kalır ve yönetim ucu 503 döner.
    app.state.council_member_store = None
    # Not deposu da lifespan'de kurulur; o ana kadar uç 503 döner.
    app.state.note_store = None
    # UI aksiyon kanalı bellek içidir ve hiçbir dosyaya dokunmaz, bu yüzden
    # lifespan beklemeden burada kurulabilir. Kalıcı olmaması bilinçlidir:
    # bir panel açma isteği ANLIK bir niyettir ve yeniden başlatmadan sonra
    # açılması, bağlamı çoktan kaybolmuş bir pencere göstermek olurdu.
    app.state.ui_action_bus = UIActionBus()
    app.state.llm_provider = active_provider if using_default_provider else None
    app.state.chat_tool_executor = chat_tool_executor
    # auto_wire_memory_on_startup ise bu dördü lifespan başlayana kadar None kalır.
    app.state.memory_service = initial_memory_service
    app.state.memory_retrieval = initial_memory_retrieval
    app.state.memory_store = initial_memory_store
    app.state.memory_temporal = None
    # Aynı şekilde: auto_wire_experience_on_startup ise lifespan başlayana kadar None kalır.
    app.state.experience_store = initial_experience_store
    # Öğrenme/kullanıcı modeli katmanı: auto_wire_user_model_on_startup ise
    # lifespan başlayana kadar None kalır. API uçları None durumunda 503 döner.
    app.state.user_trait_store = initial_user_trait_store
    app.state.learning_service = initial_learning_service
    app.state.user_model_service = initial_user_model_service
    # Agent: auto_wire_agent_on_startup ise lifespan başlayana kadar None kalır.
    # API uçları None durumunda 503 döner.
    app.state.agent_service = initial_agent_service
    # Kodlama döngüsü ajanın yığınına bağlı olduğundan yalnızca lifespan'de
    # kurulabilir; o ana kadar None kalır ve uç 503 döner.
    app.state.coding_service = None
    app.state.council_service = initial_council_service
    app.state.council_gate = council_gate
    app.state.council_providers = council_providers
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api")
    app.include_router(user_model_router, prefix="/api")
    app.include_router(agent_router, prefix="/api")
    app.include_router(approvals_router, prefix="/api")
    app.include_router(checkpoints_router, prefix="/api")
    app.include_router(coding_router, prefix="/api")
    app.include_router(insight_router, prefix="/api")
    app.include_router(notes_router, prefix="/api")
    app.include_router(ui_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")

    # Kabuk EN SON monte edilir: `/api` router'ları önce eşleşmelidir, aksi
    # hâlde kök altındaki her yol statik sunucuya gider ve API kaybolurdu.
    # Monte edilirse kök adresi de o karşılar, bu yüzden `/` uç noktası
    # yalnızca kabuk YOKKEN tanımlanır.
    if not mount_frontend(app, active_settings.frontend_dir):

        @app.get("/", response_model=ServiceInfo, tags=["system"])
        async def root() -> ServiceInfo:
            return ServiceInfo(
                name=active_settings.app_name,
                version=active_settings.app_version,
                environment=active_settings.environment,
            )

    return app


app = create_app()


def run() -> None:
    """Yerel geliştirme sunucusunu başlatır."""

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
