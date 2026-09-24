"""Settings: defaults, parity with .env.example, and secrets that never leak."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from intake.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
# Values in .env.example that are placeholders to replace, not defaults.
PLACEHOLDERS = {"livekit_url", "public_phone_number", "database_url"}


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide the real environment, so each test sees only the values it sets."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def test_defaults_need_no_environment():
    settings = Settings(_env_file=None)

    assert settings.agent_name == "patient-intake"
    assert settings.clinic_name == "Riverside Family Clinic"
    assert settings.agent_persona_name == "Maya"
    assert settings.clinic_timezone == "America/New_York"
    assert settings.max_call_minutes == 12
    assert settings.log_level == "INFO"
    assert settings.simulate_db_failure is False
    assert settings.database_url is None
    assert settings.cors_origins == ["http://localhost:5173"]


def test_env_example_lists_exactly_the_settings_fields():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    keys = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))

    assert keys == {name.upper() for name in Settings.model_fields}


def test_env_example_values_are_the_defaults():
    from_example = Settings(_env_file=ENV_EXAMPLE).model_dump(exclude=PLACEHOLDERS)

    assert from_example == Settings(_env_file=None).model_dump(exclude=PLACEHOLDERS)


def test_blank_values_fall_back_to_defaults(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPGRAM_TTS_VOICE_ES=\nMAX_CALL_MINUTES=\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.deepgram_tts_voice_es is None
    assert settings.max_call_minutes == 12


def test_environment_overrides_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CLINIC_NAME=From File\n", encoding="utf-8")
    monkeypatch.setenv("CLINIC_NAME", "From Environment")

    assert Settings(_env_file=env_file).clinic_name == "From Environment"


def test_secrets_are_masked(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:s3cret@db.example.com/intake")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-fake-key")

    settings = Settings(_env_file=None)

    for rendered in (repr(settings), str(settings), settings.model_dump_json()):
        assert "s3cret" not in rendered
        assert "gsk-fake-key" not in rendered
    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "gsk-fake-key"


def test_invalid_values_are_not_echoed_in_errors(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_CALL_MINUTES", "not-a-number-s3cret")

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    assert "s3cret" not in str(excinfo.value)


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")

    assert Settings(_env_file=None).log_level == "DEBUG"


def test_cors_origins_split_on_commas(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_CORS_ORIGINS", "http://localhost:5173, https://app.example.com,")

    assert Settings(_env_file=None).cors_origins == [
        "http://localhost:5173",
        "https://app.example.com",
    ]


def test_clinic_timezone_must_be_a_known_zone(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLINIC_TIMEZONE", "America/Chicago")
    assert str(Settings(_env_file=None).clinic_zone) == "America/Chicago"

    monkeypatch.setenv("CLINIC_TIMEZONE", "Mars/Olympus_Mons")
    with pytest.raises(ValidationError, match="clinic_timezone"):
        Settings(_env_file=None)


def test_simulate_db_failure_parses_booleans(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SIMULATE_DB_FAILURE", "true")

    assert Settings(_env_file=None).simulate_db_failure is True
