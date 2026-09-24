"""Application settings: the single source of environment configuration.

Values come from the process environment first, then from ``.env`` in the working
directory. Secrets are ``SecretStr``, so they never appear in reprs, logs or
validation errors; call ``get_secret_value()`` only where the secret is used.
"""

from functools import lru_cache
from typing import Literal

from pydantic import PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5433/intake_test"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Typed view of every variable in ``.env.example``.

    Service credentials are optional so the API and the test suite start without
    them; the component that needs a credential checks for it when it starts.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # "KEY=" means "use the default"
        extra="ignore",
        hide_input_in_errors=True,  # a bad value is never echoed into an error message
    )

    # LiveKit: telephony, agent hosting, and LiveKit Inference for the primary LLM.
    livekit_url: str | None = None
    livekit_api_key: SecretStr | None = None
    livekit_api_secret: SecretStr | None = None
    agent_name: str = "patient-intake"
    public_phone_number: str | None = None

    # Deepgram: speech-to-text and the fallback voice.
    deepgram_api_key: SecretStr | None = None
    deepgram_stt_model: str = "nova-3"
    deepgram_tts_voice_en: str | None = None
    deepgram_tts_voice_es: str | None = None

    # Cartesia: the primary voice.
    cartesia_api_key: SecretStr | None = None
    cartesia_tts_model: str = "sonic-3"
    cartesia_voice_en: str | None = None
    cartesia_voice_es: str | None = None

    # LLM: LiveKit Inference primary, Groq fallback.
    llm_primary_model: str = "openai/gpt-4.1-mini"
    groq_api_key: SecretStr | None = None
    llm_fallback_model: str = "llama-3.3-70b-versatile"

    # Database. The test suite only ever connects to test_database_url.
    database_url: SecretStr | None = None
    test_database_url: SecretStr = SecretStr(LOCAL_TEST_DATABASE_URL)

    # App.
    clinic_name: str = "Riverside Family Clinic"
    agent_persona_name: str = "Maya"
    clinic_timezone: str = "America/New_York"
    max_call_minutes: PositiveInt = 12
    api_cors_origins: str = "http://localhost:5173"
    public_api_base_url: str = "http://localhost:8000"
    log_level: LogLevel = "INFO"
    simulate_db_failure: bool = False

    @field_validator("log_level", mode="before")
    @classmethod
    def _uppercase_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @property
    def cors_origins(self) -> list[str]:
        """``API_CORS_ORIGINS`` split on commas, with blank entries dropped."""
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once on first use."""
    return Settings()
