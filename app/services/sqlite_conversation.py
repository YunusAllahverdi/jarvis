"""SQLite tabanlı kalıcı konuşma deposu.

`InMemoryConversationStore` yerini ALMAZ, onun yanında yaşar ve hangisinin
kullanılacağı bağımlılık enjeksiyonuyla seçilir — testler hâlâ RAM deposunu
kullanır ve hiçbir dosyaya dokunmaz.

Çözdüğü sorun somuttu: açık sohbetler her yeniden başlatmada sıfırlanıyordu.
Kalıcı bellek (`memories`) etkilenmiyordu ama konuşmanın kendisi kayboluyordu,
yani Jarvis kullanıcıyı hatırlıyor fakat az önce ne konuştuklarını
hatırlamıyordu.

Tasarım kararları:
- Mesajlar SATIR BAŞINA BİR tutulur, tek bir JSON sütununda değil. Böylece
  son N mesajı okumak tüm konuşmayı belleğe almadan mümkün olur.
- `ChatMessage`'ın tool alanları da saklanır. Yalnızca metin saklansaydı,
  yeniden başlatmadan sonra bir tool turu yarım kalmış görünürdü.
- Diğer kalıcı depolarla AYNI SQLite dosyası kullanılır; ayrı bir veritabanı
  dosyası oluşmaz.
- Okuma sırasında bozuk bir satır bulunursa o satır ATLANIR, konuşma
  yüklenmeye devam eder. Tek bir bozuk kaydın bütün geçmişi erişilemez
  kılması, kaybı büyütmek olurdu.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.core.chat import ChatMessage, ToolCall
from app.services.conversation import Conversation

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_LIMIT = 200
"""Bir oturumdan okunacak en fazla mesaj.

Sınırsız okuma, aylar süren bir oturumun tamamını her istekte belleğe almak
demek olurdu. Orchestrator zaten kendi bağlam sınırını ayrıca uygular; bu
sınır depodan çıkan veriyi sınırlar, prompt'a gireni değil.
"""

_DDL_MESSAGES = """
CREATE TABLE IF NOT EXISTS conversation_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    tool_name   TEXT,
    tool_calls  TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_DDL_IDX_SESSION = """
CREATE INDEX IF NOT EXISTS idx_conversation_messages_session
    ON conversation_messages (session_id, id);
"""


class SQLiteConversationStore:
    """Konuşma geçmişini kalıcı olarak saklar; `ConversationStore` uygular."""

    def __init__(self, db_path: str, *, history_limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        """
        Args:
            db_path: SQLite dosyasının yolu — diğer depolarla aynı dosya.
            history_limit: Bir oturumdan okunacak en fazla mesaj (en yeniler).
        """
        self._db_path = db_path
        self._history_limit = max(1, history_limit)
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
            conn.execute(_DDL_MESSAGES)
            conn.execute(_DDL_IDX_SESSION)
        logger.info("conversation_store_initialized", extra={"db_path": self._db_path})

    # ------------------------------------------------------------------
    # ConversationStore sözleşmesi
    # ------------------------------------------------------------------

    def get_or_create(self, session_id: str | None = None) -> Conversation:
        """Var olan oturumu döndürür; yoksa yeni bir kimlikle boş oturum.

        Yeni oturum için satır YAZILMAZ: boş bir konuşma, veritabanında
        varlığıyla yer kaplaması gereken bir şey değildir. İlk mesaj
        eklendiğinde kendiliğinden oluşur.
        """
        active_session_id = session_id or str(uuid4())
        return Conversation(
            session_id=active_session_id,
            messages=self._load_messages(active_session_id),
        )

    def append_messages(self, session_id: str, messages: Iterable[ChatMessage]) -> None:
        """Mesajları oturuma atomik olarak ekler."""
        rows = [
            (
                session_id,
                message.role,
                message.content,
                message.tool_name,
                json.dumps(
                    [call.model_dump() for call in message.tool_calls],
                    ensure_ascii=False,
                    default=str,
                ),
            )
            for message in messages
        ]
        if not rows:
            return

        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO conversation_messages
                    (session_id, role, content, tool_name, tool_calls)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def _load_messages(self, session_id: str) -> list[ChatMessage]:
        """Oturumun son mesajlarını kronolojik sırayla döndürür."""
        with self._lock, self._connect() as conn:
            rows = list(
                conn.execute(
                    """
                    SELECT role, content, tool_name, tool_calls
                    FROM conversation_messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (session_id, self._history_limit),
                )
            )

        messages: list[ChatMessage] = []
        # DESC okundu (en yeniler alınsın diye), kronolojik sıraya çevrilir.
        for row in reversed(rows):
            message = _row_to_message(row)
            if message is not None:
                messages.append(message)
        return messages


def _row_to_message(row: sqlite3.Row) -> ChatMessage | None:
    """Bir satırı `ChatMessage`'a çevirir; bozuksa None.

    None dönmesi bilinçlidir: `ChatMessage` kendi biçim kurallarını doğrular
    ve eski bir sürümden kalmış ya da yarım yazılmış bir satır bu doğrulamayı
    geçemeyebilir. O satırı atlamak, tüm konuşmayı erişilemez kılmaktan
    iyidir — kayıp zaten olmuştur, büyütülmemelidir.
    """
    try:
        raw_calls = json.loads(row["tool_calls"] or "[]")
        tool_calls = [ToolCall.model_validate(item) for item in raw_calls]
        return ChatMessage(
            role=row["role"],
            content=row["content"] or "",
            tool_name=row["tool_name"],
            tool_calls=tool_calls,
        )
    except Exception:  # noqa: BLE001
        logger.warning("conversation_row_skipped", extra={"role": row["role"]})
        return None
