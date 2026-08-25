import json
import logging

from app.core.logging import JsonFormatter


def test_json_formatter_outputs_structured_log() -> None:
    record = logging.LogRecord(
        name="jarvis.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="health_checked",
        args=(),
        exc_info=None,
    )
    record.request_id = "request-123"  # type: ignore[attr-defined]

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "health_checked"
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "request-123"
    assert "timestamp" in payload
