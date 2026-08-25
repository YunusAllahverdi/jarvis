from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app


def make_client() -> TestClient:
    app = create_app(Settings(app_name="Jarvis Test", app_version="test-1", environment="test"))
    return TestClient(app)


def test_root_returns_service_metadata() -> None:
    with make_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Jarvis Test",
        "version": "test-1",
        "environment": "test",
    }


def test_health_endpoint_returns_ok() -> None:
    with make_client() as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Jarvis Test",
        "version": "test-1",
        "environment": "test",
    }
