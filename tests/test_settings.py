import re
from pathlib import Path

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


# ---------------------------------------------------------------------------
# .env.example ile Settings arasındaki tutarlılık
# ---------------------------------------------------------------------------


def _settings_field_names() -> set[str]:
    return set(Settings.model_fields)


def _documented_env_names(env_example_text: str) -> set[str]:
    """`.env.example` içinde geçen `JARVIS_*` adlarını Settings alanına çevirir."""

    names = re.findall(r"JARVIS_([A-Z0-9_]+)", env_example_text)
    return {name.lower() for name in names}


def test_env_example_documents_every_setting() -> None:
    """Yeni bir ayar eklenip `.env.example`'a yazılmazsa bu test kırmızıya döner.

    Şablonun eksik kalması sessiz bir tuzaktır: kullanıcı ayarın VAR
    OLDUĞUNU hiç öğrenemez. Eksiksizliği elle değil burada koruyoruz.
    """

    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    documented = _documented_env_names(env_example.read_text(encoding="utf-8"))

    missing = _settings_field_names() - documented
    assert not missing, f".env.example eksik ayarlar: {sorted(missing)}"


def test_env_example_has_no_unknown_variables() -> None:
    """`.env.example`'da Settings'te karşılığı olmayan değişken olmamalı."""

    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    documented = _documented_env_names(env_example.read_text(encoding="utf-8"))

    unknown = documented - _settings_field_names()
    assert not unknown, f".env.example'da tanınmayan değişkenler: {sorted(unknown)}"
