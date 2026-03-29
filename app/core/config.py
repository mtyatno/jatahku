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

    # Timezone
    TZ: str = "Asia/Jakarta"

    model_config = {"env_file": "/opt/jatahku/.env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
