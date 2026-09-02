"""Kabuğun okuduğu salt-okunur görünümler: bellek, deneyim ve sistem durumu.

Bu uçlar YENİ BİR YETENEK EKLEMEZ. Depolarda zaten duran veriyi arayüze
açarlar; kabuktaki panellerin sabit örnek verilerle doldurulmuş olması, var
olmayan bir şeyi varmış gibi göstermek anlamına geliyordu.

Mimari kurallar:
- HEPSİ SALT OKUNURDUR. Hiçbir uç bir kayıt oluşturmaz, değiştirmez veya
  silmez; yazma yolları bilinçli olarak burada değildir.
- Yalnızca PUBLIC depo arayüzleri kullanılır (`MemoryStore`,
  `ExperienceStore` Protocol'leri). Somut SQLite sınıflarına erişilmez.
- Depo bağlı değilse uç 503 ve makine tarafından okunabilir bir `code`
  döndürür — mevcut chat, agent ve user-model uçlarıyla aynı hata biçimi.
- İçerik KIRPILIR. Bir bellek kaydı veya kullanıcı mesajı sınırsız uzunlukta
  olabilir; kabuk bunları liste hâlinde gösterdiği için sınır burada
  uygulanır, tarayıcıda değil.

GÜVENLİK NOTU: Bu uçlar da uygulamanın geri kalanı gibi KİMLİK DOĞRULAMASIZDIR
ve kullanıcının kişisel bellek kayıtlarını döndürürler. Sunucu yerel adres
dışına açılmadan önce genel bir kimlik katmanı şarttır; bu, projenin bilinen
ve kabul edilmiş borçlarından biridir.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.memory.experience_store import ExperienceStore
from app.memory.record import MemoryType
from app.memory.store import MemoryStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["insight"])

MAX_CONTENT_CHARS = 400
"""Listede taşınacak en fazla karakter.

Kırpma sunucuda yapılır: kabuk bu kayıtları yan yana gösterir ve tek bir uzun
kaydın listeyi ele geçirmesi, tarayıcıda çözülecek bir sorun değildir.
"""


def _clip(text: str | None) -> str:
    if not text:
        return ""
    return text if len(text) <= MAX_CONTENT_CHARS else f"{text[:MAX_CONTENT_CHARS]}…"


def _unavailable(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": code, "message": message},
    )


# ---------------------------------------------------------------------------
# Bellek
# ---------------------------------------------------------------------------


class MemoryRecordView(BaseModel):
    """Bir bellek kaydının arayüze açılan, kırpılmış görünümü."""

    id: str
    memory_type: str
    content: str
    valid_at: datetime
    importance: float
    source_session_id: str | None = None


class MemoryListResponse(BaseModel):
    records: list[MemoryRecordView]
    count: int


def _memory_store(request: Request) -> MemoryStore:
    store = getattr(request.app.state, "memory_store", None)
    if store is None:
        raise _unavailable("memory_unavailable", "Bellek deposu bu örnekte bağlı değil.")
    return store


@router.get("/memory/records", response_model=MemoryListResponse)
async def list_memory_records(
    request: Request,
    query: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    memory_type: str | None = Query(default=None, max_length=32),
) -> MemoryListResponse:
    """Aktif bellek kayıtlarını döndürür; `query` verilirse arar.

    Arama ile listeleme AYNI uçtadır: kabuk için ikisi de "bellekte ne var?"
    sorusunun aynı cevabıdır ve iki ayrı uç, iki ayrı boş-durum demek olurdu.
    """
    store = _memory_store(request)

    parsed_type: MemoryType | None = None
    if memory_type:
        try:
            parsed_type = MemoryType(memory_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "memory_type_invalid", "message": "Bilinmeyen bellek türü."},
            ) from None

    try:
        records = (
            store.search(query.strip(), memory_type=parsed_type, limit=limit)
            if query.strip()
            else store.list_active(memory_type=parsed_type, limit=limit)
        )
    except Exception:  # noqa: BLE001
        logger.exception("memory_list_failed")
        raise _unavailable("memory_read_failed", "Bellek okunamadı.") from None

    views = [
        MemoryRecordView(
            id=record.id,
            memory_type=str(record.memory_type),
            content=_clip(record.content),
            valid_at=record.valid_at,
            importance=record.importance,
            source_session_id=record.source_session_id,
        )
        for record in records
    ]
    return MemoryListResponse(records=views, count=len(views))


# ---------------------------------------------------------------------------
# Deneyimler
# ---------------------------------------------------------------------------


class ExperienceView(BaseModel):
    """Bir deneyimin arayüze açılan, kırpılmış görünümü."""

    id: str
    occurred_at: datetime
    user_message: str
    assistant_response: str = ""
    outcome: str
    tool_calls: list[str] = Field(default_factory=list)
    session_id: str | None = None


class ExperienceListResponse(BaseModel):
    experiences: list[ExperienceView]
    count: int


def _experience_store(request: Request) -> ExperienceStore:
    store = getattr(request.app.state, "experience_store", None)
    if store is None:
        raise _unavailable("experience_unavailable", "Deneyim deposu bu örnekte bağlı değil.")
    return store


@router.get("/experiences", response_model=ExperienceListResponse)
async def list_experiences(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    session_id: str | None = Query(default=None, max_length=128),
) -> ExperienceListResponse:
    """Son deneyimleri döndürür; oturum verilirse o oturuma daraltır."""
    store = _experience_store(request)

    try:
        experiences = (
            store.list_by_session(session_id, limit=limit)
            if session_id
            else store.list_recent(limit=limit)
        )
    except Exception:  # noqa: BLE001
        logger.exception("experience_list_failed")
        raise _unavailable("experience_read_failed", "Deneyimler okunamadı.") from None

    views = [
        ExperienceView(
            id=item.id,
            occurred_at=item.occurred_at,
            user_message=_clip(item.user_message),
            assistant_response=_clip(item.assistant_response),
            outcome=str(item.outcome),
            tool_calls=list(item.tool_calls),
            session_id=item.session_id,
        )
        for item in experiences
    ]
    return ExperienceListResponse(experiences=views, count=len(views))


# ---------------------------------------------------------------------------
# Sistem durumu
# ---------------------------------------------------------------------------


class SystemStatusResponse(BaseModel):
    """Sunucunun ölçülen kaynak kullanımı."""

    cpu_percent: float
    memory_percent: float
    memory_total_bytes: int
    memory_available_bytes: int
    disk_percent: float
    disk_total_bytes: int
    disk_free_bytes: int

    is_local: bool
    """Sunucu kullanıcının kendi makinesinde mi çalışıyor?

    Bu alan bir SÜSLEME DEĞİL, bir uyarıdır: bulutta çalışan bir örnek
    container'ın kaynaklarını raporlar, kullanıcının bilgisayarınınkini değil.
    Arayüz bu ayrımı gösterebilsin diye taşınır — aksi hâlde kullanıcı, başka
    bir makinenin CPU'suna bakıp kendi makinesini ölçtüğünü sanırdı.
    """


@router.get("/system/status", response_model=SystemStatusResponse)
async def read_system_status(request: Request) -> SystemStatusResponse:
    """Sunucunun anlık kaynak kullanımını döndürür.

    Mevcut `system_status` aracıyla AYNI kaynağı (psutil) okur; araç ajan
    için, bu uç arayüz içindir. Ölçüm yapan tek bir kütüphane vardır,
    dolayısıyla iki yol farklı sayılar üretemez.
    """
    try:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(Path.cwd().anchor or "/")
    except Exception:  # noqa: BLE001
        logger.exception("system_status_failed")
        raise _unavailable("system_status_failed", "Sistem durumu okunamadı.") from None

    settings: Any = request.app.state.settings
    host = str(getattr(settings, "host", "127.0.0.1")).strip().lower()

    return SystemStatusResponse(
        cpu_percent=psutil.cpu_percent(interval=None),
        memory_percent=memory.percent,
        memory_total_bytes=memory.total,
        memory_available_bytes=memory.available,
        disk_percent=disk.percent,
        disk_total_bytes=disk.total,
        disk_free_bytes=disk.free,
        is_local=host in {"127.0.0.1", "localhost", "::1"},
    )
