"""Yapılandırılabilir uygulama logları.

İki biçim desteklenir:

- ``json``  : her satır bir JSON nesnesi (üretim ve makine tüketimi için).
- ``text``  : insan tarafından okunabilir tek satır (yerel geliştirme için).

Biçim `JARVIS_LOG_FORMAT` ile seçilir. Her iki biçimde de bir isteğe ait
log satırları `request_id` alanıyla ilişkilendirilir (bkz.
`app.core.request_context`).
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import current_request_id


class _RequestIdFilter(logging.Filter):
    """Aktif istek kimliğini her kayda iliştirir.

    Kimlik burada, kayıt üretilirken eklenir; çağıranların her seferinde
    `extra={"request_id": ...}` yazması gerekmez ve bir tanesinin unutması
    korelasyonu bozmaz.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            request_id = current_request_id()
            if request_id is not None:
                record.request_id = request_id
        return True


class JsonFormatter(logging.Formatter):
    """Log kayıtlarını makine tarafından okunabilir JSON satırlarına dönüştürür."""

    _standard_attributes: frozenset[str] = frozenset(logging.makeLogRecord({}).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in self._standard_attributes and not key.startswith("_")
            }
        )
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """İnsan tarafından okunabilir, tek satırlık log biçimi."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(UTC).isoformat()
        line = f"{timestamp} {record.levelname:<8} {record.name}: {record.getMessage()}"

        request_id = getattr(record, "request_id", None)
        if request_id:
            line += f" [request_id={request_id}]"

        # JSON biçiminde ek alanlar üst düzeye taşınır; burada da okunabilir
        # kalsınlar diye sonda `key=value` olarak eklenir.
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in JsonFormatter._standard_attributes
            and not key.startswith("_")
            and key != "request_id"
        }
        if extras:
            rendered = " ".join(f"{key}={value!r}" for key, value in extras.items())
            line += f" {rendered}"

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def build_formatter(log_format: str) -> logging.Formatter:
    """`log_format` adına göre biçimlendirici döndürür; bilinmeyen ad JSON'a düşer."""

    if log_format.strip().lower() == "text":
        return TextFormatter()
    return JsonFormatter()


def configure_logging(level: str = "INFO", log_format: str = "json") -> None:
    """Kök logger'ı tek bir stream handler ile yapılandırır."""

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    handler = logging.StreamHandler()
    handler.setFormatter(build_formatter(log_format))
    handler.addFilter(_RequestIdFilter())

    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.access", "fastapi"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
