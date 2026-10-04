from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Jatahku"
    APP_ENV: str = "production"
    APP_URL: str = "https://jatahku.com"
    API_URL: str = "https://api.jatahku.com"

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT Auth
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_URL: str = ""
    TELEGRAM_BOT_USERNAME: str = "JatahkuBot"
    TELEGRAM_WEBHOOK_SECRET: str = ""

    # Admin
    ADMIN_SECRET: str = ""
    ADMIN_TELEGRAM_ID: str = ""

    # Google Sign-In — kosong = tombol Google disembunyikan
    GOOGLE_CLIENT_ID: str = ""

    # GitHub OAuth (for Decap CMS)
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # Timezone
    TZ: str = "Asia/Jakarta"

    # Voice transcription — provider dipilih via WHISPER_PROVIDER.
    # "groq" = Groq API (whisper-large-v3-turbo); "selfhosted" = private whisper
    # server (future). Kode spesifik provider ditandai "# WHISPER-PROVIDER:<name>".
    WHISPER_PROVIDER: str = "groq"
    # WHISPER-PROVIDER:groq — env di bawah tidak dipakai saat selfhosted aktif.
    GROQ_API_KEY: str = ""
    GROQ_WHISPER_MODEL: str = "whisper-large-v3-turbo"
    GROQ_API_URL: str = "https://api.groq.com/openai/v1/audio/transcriptions"
    # Disiapkan untuk provider selfhosted (private whisper server) — belum dipakai.
    WHISPER_API_URL: str = ""
    WHISPER_API_KEY: str = ""

    model_config = {"env_file": "/opt/jatahku/.env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
