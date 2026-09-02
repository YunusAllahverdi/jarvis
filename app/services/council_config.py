"""Council üyelerinin ÜYE BAŞINA sağlayıcı yapılandırması.

Council'ın kendisi çoktan çok modelliydi, ama tek bir sağlayıcı üzerinden
farklı model ADLARI kullanıyordu. "Her üye kendi anahtarıyla farklı bir
servise gitsin" isteği için gereken tek şey buydu: tek satırlık bir
yapılandırma kaydının üye listesine genişlemesi. Council çekirdeği hiç
değişmez.

Mimari kurallar:
- Sağlayıcı kurulumu YENİDEN YAZILMAZ: `app.services.llm_config`'teki tek
  tanım (`build_llm_provider`) kullanılır. İki kopya olsaydı, yeni bir
  sağlayıcı türü eklendiğinde Council sessizce eski türlerle sınırlı
  kalabilirdi.
- API ANAHTARI GERİ OKUNMAZ. Tekil sağlayıcı yapılandırmasında olduğu gibi
  dışarıya yalnızca "tanımlı mı" bilgisi verilir ve anahtar yalnızca
  sağlayıcı kurulurken okunur.
- MODEL ADI COUNCIL ÇEKİRDEĞİNE ULAŞMAZ. Üyeler Council'a `member-N`
  biçiminde OPAQUE kimliklerle verilir. Bu bir isimlendirme tercihi değil,
  akran değerlendirmesinin (Stage 2) çalışma şartıdır: üyeler birbirinin
  hangi model olduğunu bilirse, değerlendirme cevabın kendisine değil
  modelin ününe göre yapılabilir.
- Depo, diğer kalıcı depolarla AYNI SQLite dosyasını kullanır; ayrı bir
  veritabanı dosyası oluşmaz.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, Field

from app.adapters.llm.base import LLMProvider
from app.council.models import CouncilMember
from app.services.llm_config import LLMProviderKind, build_llm_provider

logger = logging.getLogger(__name__)

MEMBER_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
"""Üye etiketleri için desen.

Kullanıcının seçtiği, insan tarafından okunabilir bir etikettir ("openai-4o",
"yerel-llama"). Council'ın gördüğü opaque kimlikle KARIŞTIRILMAMALIDIR.
"""

MAX_MEMBERS = 8
"""Saklanabilecek en fazla üye.

`council_max_members` ayarından bağımsız bir üst sınırdır: o ayar kaç
üyenin ÇALIŞACAĞINI, bu sınır kaç üyenin TANIMLANABİLECEĞİNİ belirler.
Sınırsız bir liste, tek bir istekte sınırsız sayıda dış servise çağrı
yapılabilmesi demek olurdu.
"""


class CouncilMemberConfig(BaseModel):
    """Bir Council üyesinin anahtar İÇERMEYEN görünümü.

    Anahtar bilerek bu modelde yoktur: yanlışlıkla loglanacak veya API
    yanıtına konacak bir yer bırakmamak için.
    """

    member_id: str = Field(pattern=MEMBER_ID_PATTERN)
    kind: LLMProviderKind = LLMProviderKind.OLLAMA
    base_url: str = Field(default="http://127.0.0.1:11434", max_length=500)
    model: str | None = Field(default=None, max_length=200)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    is_chairman: bool = False
    """Sentezi bu üye üretir. En fazla bir üye chairman olabilir."""

    enabled: bool = True
    """Kapalı üye hiç kurulmaz — silmeden geçici olarak devre dışı bırakmak için."""

    has_api_key: bool = False


_DDL_MEMBERS = """
CREATE TABLE IF NOT EXISTS council_members (
    member_id       TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    model           TEXT,
    timeout_seconds REAL NOT NULL DEFAULT 60.0,
    is_chairman     INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    api_key         TEXT,
    position        INTEGER NOT NULL DEFAULT 0
);
"""


class CouncilMemberStore:
    """Council üyelerini üye başına sağlayıcı bilgisiyle kalıcı olarak saklar."""

    def __init__(self, db_path: str) -> None:
        """
        Args:
            db_path: SQLite dosyasının yolu — diğer depolarla aynı dosya.
        """
        self._db_path = db_path
        self._lock = RLock()
        self._ensure_dir()
        self._initialize_schema()

    def _ensure_dir(self) -> None:
        if self._db_path == ":memory:":
            return
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_DDL_MEMBERS)

    # ------------------------------------------------------------------
    # Okuma
    # ------------------------------------------------------------------

    def list(self) -> list[CouncilMemberConfig]:
        """Tanımlı üyeleri ekleniş sırasıyla döndürür (anahtar hariç)."""
        return [self._to_config(row) for row in self._rows()]

    def enabled_members(self) -> list[CouncilMemberConfig]:
        """Yalnızca etkin üyeleri döndürür."""
        return [config for config in self.list() if config.enabled]

    # ------------------------------------------------------------------
    # Yazma
    # ------------------------------------------------------------------

    def upsert(
        self,
        *,
        member_id: str,
        kind: LLMProviderKind,
        base_url: str,
        model: str | None,
        timeout_seconds: float = 60.0,
        is_chairman: bool = False,
        enabled: bool = True,
        api_key: str | None = None,
        clear_api_key: bool = False,
    ) -> CouncilMemberConfig:
        """Bir üyeyi ekler veya günceller.

        Args:
            api_key: Yeni anahtar. **None verilirse mevcut anahtar korunur** —
                panel anahtarı geri okuyamadığı için, her kaydetmede yeniden
                girilmesini istemek kullanıcıyı anahtarı bir yerde saklamaya
                zorlardı.
            clear_api_key: Anahtarı silmek için açıkça kullanılır.

        Raises:
            ValueError: Üye sınırı dolduysa.
        """
        with self._lock:
            existing = self._row(member_id)
            if existing is None and len(self._rows()) >= MAX_MEMBERS:
                raise ValueError(f"En fazla {MAX_MEMBERS} üye tanımlanabilir.")

            if clear_api_key:
                stored_key: str | None = None
            elif api_key is not None:
                stored_key = api_key.strip() or None
            else:
                stored_key = existing["api_key"] if existing else None

            position = existing["position"] if existing else self._next_position()

            with self._connect() as conn:
                # Chairman TEKTİR: yeni bir chairman atandığında eskisi
                # sessizce sıradan üyeye döner. İki chairman'lı bir durum
                # oluşsaydı, sentezi hangisinin ürettiği belirsiz kalırdı.
                if is_chairman:
                    conn.execute(
                        "UPDATE council_members SET is_chairman = 0 WHERE member_id != ?",
                        (member_id,),
                    )
                conn.execute(
                    """
                    INSERT INTO council_members (
                        member_id, kind, base_url, model, timeout_seconds,
                        is_chairman, enabled, api_key, position
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(member_id) DO UPDATE SET
                        kind = excluded.kind,
                        base_url = excluded.base_url,
                        model = excluded.model,
                        timeout_seconds = excluded.timeout_seconds,
                        is_chairman = excluded.is_chairman,
                        enabled = excluded.enabled,
                        api_key = excluded.api_key
                    """,
                    (
                        member_id,
                        str(kind),
                        base_url,
                        model,
                        timeout_seconds,
                        int(is_chairman),
                        int(enabled),
                        stored_key,
                        position,
                    ),
                )

        config = self._to_config(self._row(member_id))
        logger.info(
            "council_member_saved",
            extra={
                "member_id": member_id,
                "kind": str(kind),
                "is_chairman": is_chairman,
                "enabled": enabled,
                "has_api_key": config.has_api_key,
            },
        )
        return config

    def delete(self, member_id: str) -> bool:
        """Üyeyi siler. Kayıt yoksa False döner."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM council_members WHERE member_id = ?", (member_id,)
            )
        removed = cursor.rowcount > 0
        if removed:
            logger.info("council_member_deleted", extra={"member_id": member_id})
        return removed

    # ------------------------------------------------------------------
    # Sağlayıcı kurulumu
    # ------------------------------------------------------------------

    def build_members(
        self, *, max_members: int = MAX_MEMBERS
    ) -> tuple[list[CouncilMember], CouncilMember | None, list[LLMProvider]]:
        """Etkin üyelerden Council üyelerini ve chairman'ı kurar.

        Her üye KENDİ sağlayıcı örneğini alır; farklı adreslere ve farklı
        anahtarlara giden üyeler bu sayede mümkün olur.

        Council'a verilen kimlikler OPAQUE'tir (`member-1`, `member-2`, ...).
        Kullanıcının seçtiği etiket ve model adı Council çekirdeğine hiç
        ulaşmaz — akran değerlendirmesinin anonimliği buna bağlıdır.

        Chairman işaretli üye yoksa İLK üye chairman olur ve AYNI sağlayıcı
        örneği yeniden kullanılır; gereksiz ikinci bir HTTP istemcisi
        açılmaz.

        Returns:
            `(üyeler, chairman, kapatılacak_sağlayıcılar)`. Etkin üye yoksa
            `([], None, [])` döner — bu bir hata değildir.
        """
        configs = self.enabled_members()[:max_members]
        if not configs:
            return [], None, []

        members: list[CouncilMember] = []
        providers: list[LLMProvider] = []
        chairman: CouncilMember | None = None

        for index, config in enumerate(configs, start=1):
            provider = self._provider_for(config)
            providers.append(provider)
            member = CouncilMember(member_id=f"member-{index}", provider=provider)
            members.append(member)
            if config.is_chairman:
                chairman = CouncilMember(member_id="chairman", provider=provider)

        if chairman is None:
            chairman = CouncilMember(member_id="chairman", provider=members[0].provider)

        logger.info(
            "council_members_built",
            extra={"member_count": len(members), "provider_count": len(providers)},
        )
        return members, chairman, providers

    def _provider_for(self, config: CouncilMemberConfig) -> LLMProvider:
        """Bir üye için sağlayıcı kurar; anahtar yalnızca burada okunur."""
        row = self._row(config.member_id)
        return build_llm_provider(
            kind=config.kind,
            base_url=config.base_url,
            model=config.model,
            api_key=row["api_key"] if row else None,
            timeout_seconds=config.timeout_seconds,
        )

    # ------------------------------------------------------------------
    # Satır yardımcıları
    # ------------------------------------------------------------------

    def _rows(self) -> list[sqlite3.Row]:
        with self._lock, self._connect() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM council_members ORDER BY position, member_id"
                )
            )

    def _row(self, member_id: str) -> sqlite3.Row | None:
        with self._lock, self._connect() as conn:
            return conn.execute(
                "SELECT * FROM council_members WHERE member_id = ?", (member_id,)
            ).fetchone()

    def _next_position(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM council_members"
            ).fetchone()
        return int(row["next"])

    @staticmethod
    def _to_config(row: sqlite3.Row) -> CouncilMemberConfig:
        return CouncilMemberConfig(
            member_id=row["member_id"],
            kind=LLMProviderKind(row["kind"]),
            base_url=row["base_url"],
            model=row["model"],
            timeout_seconds=row["timeout_seconds"],
            is_chairman=bool(row["is_chairman"]),
            enabled=bool(row["enabled"]),
            has_api_key=bool(row["api_key"]),
        )
