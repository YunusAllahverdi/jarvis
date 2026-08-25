import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_settings_reads_prefixed_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_APP_NAME", "Test Jarvis")
    monkeypatch.setenv("JARVIS_PORT", "9010")
    monkeypatch.setenv("JARVIS_ENVIRONMENT", "test")

    settings = Settings()

    assert settings.app_name == "Test Jarvis"
    assert settings.port == 9010
    assert settings.environment == "test"


def test_settings_rejects_invalid_port() -> None:
    with pytest.raises(ValidationError):
        Settings(port=70000)
