"""Jarvis FastAPI uygulamasının başlangıç noktası."""

import logging
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
from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.user_model import router as user_model_router
from app.config.settings import Settings, get_settings
from app.core.logging import configure_logging
from app.learning.sqlite_trait_store import SQLiteUserTraitStore
from app.learning.trait_store import UserTraitStore
from app.memory.experience_store import ExperienceStore
from app.memory.extractor import MemoryExtractor
from app.memory.sqlite_experience_store import SQLiteExperienceStore
from app.memory.sqlite_store import SQLiteMemoryStore
from app.memory.store import MemoryStore
from app.services.agent_service import AgentService
from app.services.conversation import ConversationStore, InMemoryConversationStore
from app.services.learning_service import LearningService
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.memory_service import MemoryWriteService
from app.services.memory_temporal import MemoryTemporalService
from app.services.orchestrator import ChatOrchestrator
from app.services.prompts import SystemPromptLoader
from app.services.user_model_service import UserModelService
from app.tools.base import PermissionLevel
from app.tools.defaults import build_default_tool_registry, register_context_tools
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


_AGENT_ALLOWED_PERMISSIONS = frozenset({PermissionLevel.READ})
"""Agent'ın onay istemeden çalıştırabileceği izin seviyeleri.

Bu kümenin dışındaki her tool, bağlama `requires_confirmation=True` ile girer
ve onay alınmadan ASLA çalıştırılmaz. Bu fazda yalnızca READ tool'ları vardır;
küme, ileride WRITE/DANGEROUS tool'lar eklendiğinde onay sınırının hazır
olduğu yerdir.
"""


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


def _build_agent_stack(
    *,
    conversation_store: ConversationStore,
    memory_retrieval: MemoryRetrievalService | None,
    experience_store: ExperienceStore | None,
    user_model: UserModelService | None,
    policy: DecisionPolicy | None = None,
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
    agent_registry = build_default_tool_registry()
    registered = register_context_tools(
        agent_registry, memory_retrieval=memory_retrieval, user_model=user_model
    )
    context_builder = ContextBuilder(
        tool_registry=agent_registry,
        allowed_permissions=_AGENT_ALLOWED_PERMISSIONS,
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
        runner=AgentRunner(
            tool_executor=ToolExecutor(
                agent_registry, allowed_permissions=_AGENT_ALLOWED_PERMISSIONS
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
    active_provider = provider if provider is not None else OllamaProvider(
        base_url=active_settings.ollama_base_url,
        model=active_settings.ollama_model,
        timeout_seconds=active_settings.ollama_timeout_seconds,
    )
    active_conversation_store = (
        conversation_store if conversation_store is not None else InMemoryConversationStore()
    )
    active_tool_registry = (
        tool_registry if tool_registry is not None else build_default_tool_registry()
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

    chat_orchestrator = ChatOrchestrator(
        provider=active_provider,
        conversation_store=active_conversation_store,
        prompt_loader=SystemPromptLoader(active_settings.system_prompt_file),
        tool_registry=active_tool_registry,
        tool_executor=ToolExecutor(active_tool_registry, allowed_permissions={PermissionLevel.READ}),
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

        if auto_wire_agent_on_startup:
            # Agent en son kurulur: bağlam kaynaklarının (bellek, deneyim,
            # kullanıcı modeli) tamamı yukarıdaki bloklarda oluşmuş olur.
            # Kurulmamış olan kaynak None geçilir; agent bunu sorunsuz karşılar.
            startup_agent = _build_agent_stack(
                conversation_store=active_conversation_store,
                memory_retrieval=app_instance.state.memory_retrieval,
                experience_store=app_instance.state.experience_store,
                user_model=app_instance.state.user_model_service,
                policy=_build_decision_policy(
                    policy_name=active_settings.agent_decision_policy,
                    provider=active_provider,
                    model_label=active_settings.ollama_model,
                ),
            )
            app_instance.state.agent_service = startup_agent
            # Sohbet entegrasyonu ayrı bir anahtardır: agent API'si açık
            # kalırken sohbet akışının agent'ı hiç çağırmaması istenebilir.
            if active_settings.agent_chat_integration:
                chat_orchestrator.set_agent_service(startup_agent)

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
        if hasattr(active_provider, "aclose"):
            await active_provider.aclose()
        logger.info("application_stopped", extra={"event": "application_stopped"})

    app = FastAPI(
        title=active_settings.app_name,
        version=active_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.state.chat_orchestrator = chat_orchestrator
    app.state.tool_registry = active_tool_registry
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
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api")
    app.include_router(user_model_router, prefix="/api")
    app.include_router(agent_router, prefix="/api")

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
