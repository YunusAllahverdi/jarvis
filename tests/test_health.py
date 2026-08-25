from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    # memory_db_path izole edilir; aksi halde uygulama gerçekten başlatıldığında
    # (lifespan) gerçek kullanıcı dizinindeki varsayılan bellek veritabanına dokunur.
    settings = Settings(
        app_name="Jarvis Test",
        app_version="test-1",
        environment="test",
        memory_db_path=str(tmp_path / "memory.db"),
    )
    app = create_app(settings)
    return TestClient(app)


def test_root_returns_service_metadata(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Jarvis Test",
        "version": "test-1",
        "environment": "test",
    }


def test_health_endpoint_returns_ok(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Jarvis Test",
        "version": "test-1",
        "environment": "test",
    }
