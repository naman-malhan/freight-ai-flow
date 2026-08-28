from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://freight:freight@localhost:5432/freight_ai"
    database_url_sync: str = "postgresql+psycopg2://freight:freight@localhost:5432/freight_ai"
    app_timezone: str = "Asia/Kolkata"
    draft_expiry_hours: int = 24
    openai_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"

    # Primary STT: local faster-whisper (free / open-source)
    faster_whisper_enabled: bool = True
    faster_whisper_model: str = "large-v3"
    faster_whisper_device: str = "cpu"
    faster_whisper_compute_type: str = "int8"

    # Fallback STT: Groq cloud
    groq_api_key: str | None = None
    groq_stt_model: str = "whisper-large-v3-turbo"

    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_verify_token: str = "freightai_webhook_verify_2026"
    whatsapp_api_version: str = "v21.0"
    public_api_base_url: str | None = None


settings = Settings()
