"""Yapılandırma ve gözlemlenebilirlik katmanının testleri.

Kapsar:
1. Request-id middleware — üretim, koruma, temizleme, yanıt başlığı
2. Log biçimleri (JSON ve metin) ve request_id iliştirme
3. Tutarlı hata zarfı — 404, 405, 422 ve uç özel kodları
4. `log_format` ayarı
"""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from app.api.errors import error_body
from app.config.settings import Settings
from app.core.logging import JsonFormatter, TextFormatter, build_formatter
from app.core.request_context import REQUEST_ID_HEADER, current_request_id
from app.main import create_app


def _client(**overrides: object) -> TestClient:
    settings = Settings(environment="test", frontend_dir="does-not-exist", **overrides)
    return TestClient(create_app(settings=settings), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. Request-id
# ---------------------------------------------------------------------------


class TestRequestIdMiddleware:
    def test_response_always_carries_a_request_id(self) -> None:
        with _client() as client:
            response = client.get("/api/v1/health")

        assert response.status_code == 200
        assert response.headers[REQUEST_ID_HEADER]

    def test_incoming_request_id_is_preserved(self) -> None:
        with _client() as client:
            response = client.get(
                "/api/v1/health",
                headers={REQUEST_ID_HEADER: "trace-abc.123"},
            )

        assert response.headers[REQUEST_ID_HEADER] == "trace-abc.123"

    def test_unsafe_request_id_is_replaced(self) -> None:
        with _client() as client:
            response = client.get(
                "/api/v1/health",
                headers={REQUEST_ID_HEADER: "bad id\nwith-newline"},
            )

        generated = response.headers[REQUEST_ID_HEADER]
        assert generated != "bad id\nwith-newline"
        assert "\n" not in generated

    def test_request_id_is_available_in_handler_context(self) -> None:
        app = create_app(settings=Settings(environment="test", frontend_dir="none"))

        @app.get("/api/_probe")
        async def _probe() -> dict[str, str | None]:  # pragma: no cover - trivial
            return {"request_id": current_request_id()}

        with TestClient(app) as client:
            response = client.get("/api/_probe")

        assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]

    def test_request_id_is_not_leaked_between_requests(self) -> None:
        with _client() as client:
            first = client.get("/api/v1/health").headers[REQUEST_ID_HEADER]
            second = client.get("/api/v1/health").headers[REQUEST_ID_HEADER]

        assert first != second


# ---------------------------------------------------------------------------
# 2. Log biçimleri
# ---------------------------------------------------------------------------


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="jarvis.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="event_happened",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestLogFormatters:
    def test_json_formatter_keeps_structured_extras(self) -> None:
        payload = json.loads(JsonFormatter().format(_record(request_id="r-1", path="/x")))

        assert payload["message"] == "event_happened"
        assert payload["request_id"] == "r-1"
        assert payload["path"] == "/x"

    def test_text_formatter_is_readable_and_includes_request_id(self) -> None:
        rendered = TextFormatter().format(_record(request_id="r-2"))

        assert "event_happened" in rendered
        assert "request_id=r-2" in rendered
        assert not rendered.startswith("{")

    def test_build_formatter_selects_by_name(self) -> None:
        assert isinstance(build_formatter("json"), JsonFormatter)
        assert isinstance(build_formatter("text"), TextFormatter)
        assert isinstance(build_formatter("unknown"), JsonFormatter)

    def test_log_format_setting_defaults_to_json(self) -> None:
        assert Settings(environment="test").log_format == "json"
        assert Settings(environment="test", log_format="text").log_format == "text"


# ---------------------------------------------------------------------------
# 3. Tutarlı hata zarfı
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    def test_error_body_shape(self) -> None:
        assert error_body("x", "y") == {"detail": {"code": "x", "message": "y"}}

    def test_unknown_route_returns_consistent_envelope(self) -> None:
        with _client() as client:
            response = client.get("/api/does-not-exist")

        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["code"] == "not_found"
        assert detail["message"]

    def test_method_not_allowed_returns_consistent_envelope(self) -> None:
        with _client() as client:
            response = client.delete("/api/v1/health")

        assert response.status_code == 405
        assert response.json()["detail"]["code"] == "method_not_allowed"

    def test_validation_error_returns_consistent_envelope(self) -> None:
        with _client() as client:
            response = client.post("/api/chat", json={})

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "validation_error"

    def test_endpoint_specific_code_is_preserved(self) -> None:
        """Uçların kendi kodları çerçeve zarflamasıyla EZİLMEZ."""

        with _client() as client:
            response = client.post("/api/chat", json={"message": "merhaba"})

        # Sağlayıcı yok; uç kendi kodunu döndürmeli.
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "llm_unavailable"

    def test_all_error_responses_carry_request_id_header(self) -> None:
        with _client() as client:
            for response in (
                client.get("/api/does-not-exist"),
                client.delete("/api/v1/health"),
                client.post("/api/chat", json={}),
            ):
                assert response.headers.get(REQUEST_ID_HEADER)
