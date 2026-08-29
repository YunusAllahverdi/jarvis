"""Ajanın hangi dosyalara dokunabileceğine karar veren bekçi.

Üç ayrı kaçış yolu vardır ve üçü de burada kapatılır:

1. **Dizin dışına çıkma** — `../../etc/passwd`. Yol normalleştirilip köke
   göre kontrol edilir.
2. **Sembolik bağ** — çalışma dizini içinde duran ama dışarıyı gösteren bir
   bağlantı. Bu yüzden karşılaştırma, bağlar çözüldükten SONRA yapılır.
3. **Hassas dosya** — `.env`, özel anahtarlar, kimlik bilgileri. Kök içinde
   olsalar bile yasaktır.

Bekçi yalnızca "izin var mı" sorusunu cevaplar; dosyayı okumaz, yazmaz.
Böylece aynı karar hem okuma hem yazma araçları tarafından kullanılabilir
ve iki araç farklı sonuca varamaz.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from pathlib import Path

DEFAULT_DENIED_NAMES: tuple[str, ...] = (
    # Ayar ve gizli değer dosyaları
    ".env",
    ".env.*",
    "*.env",
    "secrets.*",
    "credentials",
    "credentials.*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".htpasswd",
    # Anahtarlar ve sertifikalar
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    # Kimlik doğrulama durumu
    ".git-credentials",
)
"""Adı tek başına yasaklamaya yeten dosyalar."""

ALLOWED_EXCEPTIONS: tuple[str, ...] = (
    ".env.example",
    ".env.sample",
    ".env.template",
)
"""Yasak kalıba uyan ama bilerek serbest bırakılan adlar.

Bunlar şablon dosyalardır: hangi ayarların var olduğunu gösterirler,
değerlerini değil. Ajanın projeyi anlayabilmesi için okunabilir olmaları
gerekir ve okunmalarında bir sakınca yoktur.

Liste kalıplardan ÖNCE bakılır; yoksa `.env.example` `.env.*` kalıbına
takılırdı.
"""

DEFAULT_DENIED_DIRS: tuple[str, ...] = (
    ".ssh",
    ".gnupg",
    ".aws",
    ".kube",
    ".docker",
)
"""İçindeki her şeyin yasak olduğu dizinler."""


class PathNotAllowedError(PermissionError):
    """Yol, bekçinin kurallarından birine takıldı.

    Mesaj hangi kurala takıldığını söyler ama çözülmüş tam yolu vermez:
    reddedilen bir istek, dosya sisteminin haritasını çıkarmaya
    yaramamalıdır.
    """


class PathGuard:
    """Bir kök dizine hapsedilmiş, hassas dosyaları dışlayan yol denetimi."""

    def __init__(
        self,
        root: str | Path,
        *,
        denied_names: Iterable[str] = DEFAULT_DENIED_NAMES,
        denied_dirs: Iterable[str] = DEFAULT_DENIED_DIRS,
        allowed_exceptions: Iterable[str] = ALLOWED_EXCEPTIONS,
    ) -> None:
        """
        Args:
            root: Ajanın çalışabileceği dizin. Bu ağacın dışı kapalıdır.
            denied_names: Yasak dosya adı kalıpları (fnmatch).
            denied_dirs: İçindeki her şeyin yasak olduğu dizin adları.
            allowed_exceptions: Yasak kalıba uysa da serbest bırakılacak
                adlar; kalıplardan önce değerlendirilir.

        Raises:
            ValueError: Kök mevcut bir dizin değilse. Var olmayan bir köke
                hapsetmek, hapsetmemekle aynı kapıya çıkardı.
        """
        resolved_root = Path(root).expanduser().resolve()
        if not resolved_root.is_dir():
            raise ValueError(f"Çalışma kökü bir dizin olmalıdır: {root}")

        self._root = resolved_root
        self._denied_names = tuple(denied_names)
        self._denied_dirs = frozenset(name.lower() for name in denied_dirs)
        self._allowed_exceptions = frozenset(name.lower() for name in allowed_exceptions)

    @property
    def root(self) -> Path:
        """Ajanın hapsedildiği kök dizin."""

        return self._root

    def is_allowed(self, path: str | Path) -> bool:
        """Yolun kullanılabilir olup olmadığını söyler; hata fırlatmaz."""

        try:
            self.resolve(path)
        except PathNotAllowedError:
            return False
        return True

    def resolve(self, path: str | Path) -> Path:
        """Yolu doğrular ve çözülmüş hâlini döndürür.

        Dönen yol, aracın gerçekten kullanması gereken yoldur. Aracın
        kendisi ham girdiyi kullanmamalıdır: doğrulanan ile açılan farklı
        olursa kontrol anlamını yitirir.

        Raises:
            PathNotAllowedError: Yol kökün dışındaysa veya yasak bir ada
                ya da dizine denk geliyorsa.
        """
        candidate = Path(path).expanduser()

        # Bağları çözerek normalleştir. Var olmayan bir hedef için de
        # çalışır (yazma durumu): mevcut olan en yakın üst dizin çözülür.
        try:
            resolved = (self._root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        except OSError as exc:  # döngüsel bağ gibi durumlar
            raise PathNotAllowedError("Yol çözümlenemedi.") from exc

        self._require_inside_root(resolved)
        self._require_not_sensitive(resolved)
        return resolved

    # ── kurallar ─────────────────────────────────────────────

    def _require_inside_root(self, resolved: Path) -> None:
        """Çözülmüş yolun kök ağacında kaldığını doğrular.

        Karşılaştırma çözümden SONRA yapılır; aksi hâlde kök içinde duran
        ama dışarıyı gösteren bir sembolik bağ kontrolü atlatırdı.
        """
        if resolved != self._root and self._root not in resolved.parents:
            raise PathNotAllowedError("Yol çalışma dizininin dışında.")

    def _require_not_sensitive(self, resolved: Path) -> None:
        """Yasak ad ve dizin kurallarını uygular."""

        relative = resolved.relative_to(self._root) if resolved != self._root else Path()

        for part in relative.parts[:-1] if relative.parts else ():
            if part.lower() in self._denied_dirs:
                raise PathNotAllowedError(f"'{part}' dizini kapalı.")

        name = resolved.name
        # Windows'ta dosya adları büyük/küçük harf duyarsızdır; kural da öyle
        # davranmalı, yoksa ".ENV" korumayı atlatırdı.
        lowered = name.lower()

        if lowered in self._allowed_exceptions:
            return

        for pattern in self._denied_names:
            if fnmatch.fnmatch(lowered, pattern.lower()):
                raise PathNotAllowedError(f"'{name}' hassas bir dosya.")

        if lowered in self._denied_dirs:
            raise PathNotAllowedError(f"'{name}' dizini kapalı.")
