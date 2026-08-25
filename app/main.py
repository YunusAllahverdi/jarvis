"""Jarvis FastAPI uygulamasının başlangıç noktası."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.adapters.llm.base import LLMProvider
from app.adapters.llm.ollama import OllamaProvider
from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.config.settings import Settings, get_settings
from app.core.logging import configure_logging
from app.memory.extractor import MemoryExtractor
from app.memory.sqlite_store import SQLiteMemoryStore
from app.services.conversation import ConversationStore, InMemoryConversationStore
from app.services.memory_retrieval import MemoryRetrievalService
from app.services.memory_service import MemoryWriteService
from app.services.orchestrator import ChatOrchestrator
from app.services.prompts import SystemPromptLoader
from app.tools.base import PermissionLevel
from app.tools.defaults import build_default_tool_registry
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ServiceInfo(BaseModel):
    """Kök endpoint için temel servis bilgisi."""

    name: str
    version: str
    environment: str


def create_app(
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    conversation_store: ConversationStore | None = None,
    tool_registry: ToolRegistry | None = None,
    memory_service: MemoryWriteService | None = None,
    memory_retrieval: MemoryRetrievalService | None = None,
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

    chat_orchestrator = ChatOrchestrator(
        provider=active_provider,
        conversation_store=active_conversation_store,
        prompt_loader=SystemPromptLoader(active_settings.system_prompt_file),
        tool_registry=active_tool_registry,
        tool_executor=ToolExecutor(active_tool_registry, allowed_permissions={PermissionLevel.READ}),
        memory_service=initial_memory_service,
        memory_retrieval=initial_memory_retrieval,
        context_message_limit=active_settings.conversation_context_limit,
    )

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        if auto_wire_memory_on_startup:
            memory_store = SQLiteMemoryStore(active_settings.memory_db_path)
            memory_extractor = MemoryExtractor(provider=active_provider)
            startup_memory_service = MemoryWriteService(extractor=memory_extractor, store=memory_store)
            startup_memory_retrieval = MemoryRetrievalService(store=memory_store)
            chat_orchestrator.set_memory_service(startup_memory_service)
            chat_orchestrator.set_memory_retrieval(startup_memory_retrieval)
            app_instance.state.memory_store = memory_store
            app_instance.state.memory_service = startup_memory_service
            app_instance.state.memory_retrieval = startup_memory_retrieval

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
    # auto_wire_memory_on_startup ise bu üçü lifespan başlayana kadar None kalır.
    app.state.memory_service = initial_memory_service
    app.state.memory_retrieval = initial_memory_retrieval
    app.state.memory_store = None
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api")

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
