"""Masadaki Dosyalar penceresinin okuduğu uç.

SALT OKUNUR olması bir eksiklik değil, kararın kendisidir. Bu uç bir
tarayıcı penceresinden çağrılır; tarayıcıda açık duran bir sayfa,
kullanıcının farkında olmadığı bir istek gönderebilecek en kolay yerdir.
Silme ya da yazma buradan geçseydi, o riskin karşılığı yalnızca "dosya
gezginini biraz daha kullanışlı yapmak" olurdu.

Ajanın dosya araçlarıyla AYNI `PathGuard` kullanılır. İkinci bir yol
denetimi yazmak, iki kuralın zamanla ayrışması demekti: biri `.env`'i
gizlerken diğeri göstermeye devam ederdi.

Bekçi kurulu değilse (çalışma kökü ayarlanmamışsa) uç 503 döner. Kök
olmadan "her yeri listele"ye düşmek, kapalı bir yeteneği sessizce açmak
olurdu.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.security.paths import PathGuard, PathNotAllowedError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"], prefix="/files")

MAX_ENTRIES = 500
"""Tek bir yanıtta dönecek en fazla girdi.

Bir dizinde on binlerce dosya olabilir; sınırsız liste, tarayıcıyı
kilitleyecek bir yanıt üretebilirdi.
"""

_UNAVAILABLE_DETAIL = {
    "code": "workspace_unavailable",
    "message": "Çalışma kökü ayarlanmamış; dosya gezgini kapalı.",
}


class FileEntry(BaseModel):
    """Listelenen tek bir dosya ya da klasör."""

    name: str
    """Yalnızca ad. Tam yol bilerek dönmez: kullanıcının makinesindeki
    dizin yapısı, arayüzün işine yaramayan ama sızabilecek bir bilgidir."""

    path: str
    """Köke GÖRELİ yol. İstemci bir sonraki listelemede bunu geri verir."""

    is_dir: bool
    size_bytes: int | None = None
    """Klasörlerde None. Bir klasörün boyutunu hesaplamak ağacın tamamını
    gezmek demekti ve liste açılışını yavaşlatırdı."""

    modified_at: datetime | None = None


class FileListResponse(BaseModel):
    """Bir dizinin içeriği."""

    path: str
    """Listelenen dizinin köke göreli yolu; kök için boş dize."""

    parent: str | None = None
    """Bir üst dizin, köke göreli. Kökteyken None — yukarı çıkılamaz."""

    entries: list[FileEntry] = Field(default_factory=list)
    truncated: bool = False


def _guard(request: Request) -> PathGuard:
    guard = getattr(request.app.state, "workspace_guard", None)
    if guard is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE_DETAIL
        )
    return guard


def _relative(guard: PathGuard, target: Path) -> str:
    """Kök altındaki yolu ileri eğik çizgili göreli metne çevirir.

    Windows'ta `Path` ters eğik çizgi üretir; istemci bunu URL'ye koyacağı
    için biçim platformdan bağımsız olmalıdır.
    """
    if target == guard.root:
        return ""
    return target.relative_to(guard.root).as_posix()


def _entry(guard: PathGuard, child: Path) -> FileEntry | None:
    """Bir dizin girdisini modele çevirir; okunamayan girdiyi atlar.

    `stat()` erişim hatası verebilir (izin, kırık sembolik bağ). Tek bir
    okunamayan girdi yüzünden tüm listelemeyi hataya çevirmek, kullanıcının
    okuyabildiği dosyaları da görememesi demek olurdu.
    """
    try:
        stat = child.stat()
        is_dir = child.is_dir()
    except OSError:
        return None

    return FileEntry(
        name=child.name,
        path=_relative(guard, child),
        is_dir=is_dir,
        size_bytes=None if is_dir else stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


@router.get("", response_model=FileListResponse)
async def list_files(
    request: Request,
    path: str = Query(default="", max_length=1024),
    limit: int = Query(default=200, ge=1, le=MAX_ENTRIES),
) -> FileListResponse:
    """Çalışma kökü altındaki bir dizini listeler."""
    guard = _guard(request)

    try:
        target = guard.resolve(path or ".")
    except PathNotAllowedError as exc:
        # Kökün dışı ile "yasak ad" ayrımı kullanıcıya YAPILMAZ: ikisinin
        # farklı yanıt vermesi, kökün dışında neyin var olduğunu sorgu
        # sorgu deneyerek öğrenmeye yarardı.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "path_not_allowed", "message": str(exc)},
        ) from exc

    if not target.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_a_directory", "message": "Böyle bir klasör yok."},
        )

    try:
        children = sorted(
            target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "path_not_readable", "message": "Klasör okunamadı."},
        ) from exc

    entries: list[FileEntry] = []
    for child in children:
        # Bekçiden geçmeyen girdiler (`.env`, `.git/`) listede HİÇ görünmez.
        # Görünüp açılamamaları, var olduklarını söylemek olurdu.
        if not guard.is_allowed(child):
            continue
        entry = _entry(guard, child)
        if entry is not None:
            entries.append(entry)
        if len(entries) >= limit:
            break

    parent = None if target == guard.root else _relative(guard, target.parent)
    return FileListResponse(
        path=_relative(guard, target),
        parent=parent,
        entries=entries,
        truncated=len(entries) >= limit,
    )
