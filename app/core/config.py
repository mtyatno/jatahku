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

    # Email (SMTP terautentikasi, exim4 di VPS). Password HANYA dari /opt/jatahku/.env;
    # kosong = email tidak dikirim (dicatat di log), tidak pernah ada default di kode.
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = "noreply@jatahku.com"
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@jatahku.com"
    SMTP_FROM_NAME: str = "Jatahku"

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

    # Scan struk (OCR RapidOCR, tanpa LLM). Kuota scan per bulan untuk Basic;
    # Pro tanpa batas bulanan (tetap kena rate limit per jam di endpoint).
    # Tidak dipakai lagi sejak Kotak Struk; dipertahankan supaya .env lama tidak
    # membuat startup gagal.
    RECEIPT_SCAN_LIMIT_BASIC: int = 15

    # Kotak Struk ("Bagikan ke Jatahku"). KOTAK_HMAC_KEY: kunci HMAC untuk nomor
    # rekening/RRN (counterparty_key, ref_hash). KOTAK_DIR: folder berkas bukti
    # sementara.
    KOTAK_HMAC_KEY: str = ""
    KOTAK_DIR: str = "/var/lib/jatahku/kotak"

    # Fallback LLM (Groq vision) untuk struk yang gagal dibaca OCR.
    # MATI secara default. Biaya dikunci plafon bulanan global (rupiah) +
    # kuota per user; setelah plafon tercapai fallback berhenti sampai bulan depan.
    RECEIPT_LLM_ENABLED: bool = False
    RECEIPT_LLM_MODEL: str = "qwen/qwen3.8-27b"
    RECEIPT_LLM_API_URL: str = "https://api.groq.com/openai/v1/chat/completions"
    RECEIPT_LLM_MONTHLY_BUDGET_IDR: int = 100_000
    RECEIPT_LLM_USER_MONTHLY_BASIC: int = 3
    RECEIPT_LLM_USER_MONTHLY_PRO: int = 10
    RECEIPT_LLM_MAX_OUTPUT_TOKENS: int = 400
    # Harga per 1 juta token (USD) + kurs untuk estimasi biaya. Kurs dibuat
    # konservatif (lebih tinggi dari pasar) supaya plafon tidak terlampaui.
    RECEIPT_LLM_PRICE_IN_USD: float = 0.80
    RECEIPT_LLM_PRICE_OUT_USD: float = 4.00
    RECEIPT_LLM_USD_IDR: int = 17_500

    model_config = {"env_file": "/opt/jatahku/.env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
