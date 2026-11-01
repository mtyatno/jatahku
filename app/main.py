import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.core.config import get_settings
from app.services.scheduler import start_scheduler, stop_scheduler
from app.api.routes import health, auth, envelopes, transactions, incomes, webhook, link, snapshots, household, export, recurring, analytics, advisor, notifications, user_settings, admin, payment, cms_oauth, goals, balance_check, bot_chat, app_config, kotak_struk, dashboard
from app.api.routes import ruang as ruang_routes

settings = get_settings()
limiter = Limiter(key_func=get_remote_address)
log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — create any missing tables (safe, skips existing)
    from app.core.database import engine
    from app.models.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all makes new *tables* but never ALTERs existing ones. Deploy
        # doesn't run alembic, so additively backfill new columns here to keep
        # the schema self-healing. Idempotent; Postgres only.
        if conn.dialect.name == "postgresql":
            from sqlalchemy import text
            await conn.execute(text(
                "ALTER TABLE notification_preferences "
                "ADD COLUMN IF NOT EXISTS checkin_nudge_tg BOOLEAN NOT NULL DEFAULT true"
            ))
            await conn.execute(text(
                "ALTER TABLE notification_preferences "
                "ADD COLUMN IF NOT EXISTS checkin_nudge_time VARCHAR(5) DEFAULT '21:00'"
            ))
            await conn.execute(text(
                "ALTER TABLE envelopes ADD COLUMN IF NOT EXISTS purpose VARCHAR(20) NOT NULL DEFAULT 'expense'"
            ))
            await conn.execute(text(
                "ALTER TABLE envelopes ALTER COLUMN purpose TYPE VARCHAR(20) USING COALESCE(purpose::VARCHAR(20), 'expense')"
            ))
            await conn.execute(text(
                "UPDATE envelopes SET purpose = 'saving' WHERE LOWER(name) = 'tabungan' AND purpose = 'expense'"
            ))
            await conn.execute(text(
                "UPDATE envelopes e SET budget_amount = sub.allocated "
                "FROM (SELECT a.envelope_id, COALESCE(SUM(a.amount), 0) AS allocated "
                "FROM allocations a GROUP BY a.envelope_id) sub "
                "WHERE e.id = sub.envelope_id AND e.purpose = 'expense' "
                "AND e.budget_amount = 0 AND sub.allocated > 0"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255)"
            ))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id)"
            ))
            # Cocokkan saldo (spec 2026-09-30): create_all di atas sudah membuat
            # tabel balance_checks; tambah FK nullable ke transactions & incomes.
            for _tbl in ("transactions", "incomes"):
                await conn.execute(text(
                    f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS balance_check_id UUID "
                    "REFERENCES balance_checks(id)"
                ))
                await conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS ix_{_tbl}_balance_check_id "
                    f"ON {_tbl} (balance_check_id)"
                ))
            # Income type untuk daily/weekly/irregular earners (spec 2026-10-05):
            # safe_daily calculation adjusts per income_type.
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS income_type VARCHAR(20) DEFAULT 'monthly'"
            ))
            # Kotak Struk (spec 2026-10-26): perluas receipt_scans (tabel baru
            # household_merchants & merchant_envelope_map dibuat create_all).
            from app.services.kotak_struk.schema import KOTAK_DDL
            for stmt in KOTAK_DDL:
                await conn.execute(text(stmt))
            # Plugin R1 (model ruang): households.type, incomes.kind. Backfill dan
            # constraint unik keanggotaan hanya di migrasi 1c7e5a9d3b20.
            from app.services.ruang_schema import RUANG_DDL
            for stmt in RUANG_DDL:
                await conn.execute(text(stmt))
            # Siklus anggaran household (spec 2026-10-31): households.payday_day dan
            # allocated/spent di monthly_snapshots, lalu backfill payday dari owner.
            from app.services.household_cycle_schema import HOUSEHOLD_CYCLE_DDL
            for stmt in HOUSEHOLD_CYCLE_DDL:
                await conn.execute(text(stmt))
    print(f"🚀 {settings.APP_NAME} starting...")
    from app.services import email_service
    email_service.check_configured()
    # AI Advisor v2: commit yang mengubah data keuangan menghapus cache dashboard household itu.
    from app.services.advisor import advisor_cache
    advisor_cache.install()
    start_scheduler()
    # Kotak Struk (spec 2026-10-26): worker pembaca bukti berjalan sebagai tugas asyncio di
    # proses API, di samping scheduler. Gagal menyalakannya tidak boleh menjatuhkan API.
    kotak_stop = asyncio.Event()
    kotak_task = None
    try:
        from app.services.kotak_struk.worker import run_worker
        kotak_task = asyncio.create_task(run_worker(kotak_stop))
    except Exception:
        log.exception("worker Kotak Struk tidak bisa dijalankan")
    yield
    # Shutdown
    stop_scheduler()
    if kotak_task is not None:
        kotak_stop.set()
        try:
            await asyncio.wait_for(kotak_task, 10)
        except Exception:  # termasuk TimeoutError: tugas dibatalkan, item `diproses` dipulihkan saat start berikutnya
            log.exception("worker Kotak Struk tidak berhenti dengan rapi")
    print(f"👋 {settings.APP_NAME} shutting down...")
app = FastAPI(
    title=settings.APP_NAME,
    description="Setiap rupiah ada jatahnya. Envelope budgeting + behavior control.",
    version="0.1.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
    lifespan=lifespan,
)
# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.APP_URL, "https://jatahku.com", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Plugin R2: 403 ruang_tidak_diizinkan membawa field `kode` (docs/plugin/04-kontrak-api.md §7)
from app.services import ruang as _ruang
_ruang.install(app)
# Routes
app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(envelopes.router, prefix="/envelopes", tags=["envelopes"])
app.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
app.include_router(incomes.router, prefix="/incomes", tags=["incomes"])
app.include_router(link.router, prefix="/auth", tags=["link"])
app.include_router(snapshots.router, prefix="/snapshots", tags=["snapshots"])
app.include_router(household.router, prefix="/household", tags=["household"])
app.include_router(export.router, prefix="/export", tags=["export"])
app.include_router(recurring.router, prefix="/recurring", tags=["recurring"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(advisor.router, prefix="/advisor", tags=["advisor"])
app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
app.include_router(user_settings.router, prefix="/user", tags=["user"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(payment.router, prefix="/payment", tags=["payment"])
app.include_router(webhook.router, tags=["webhook"])
app.include_router(cms_oauth.router, tags=["cms"])
app.include_router(goals.router, prefix="/goals", tags=["goals"])
app.include_router(balance_check.router, prefix="/balance-check", tags=["balance-check"])
app.include_router(bot_chat.router, prefix="/bot/chat", tags=["bot-chat"])
app.include_router(app_config.router, prefix="/app", tags=["app"])
app.include_router(kotak_struk.router, prefix="/kotak-struk", tags=["kotak-struk"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(ruang_routes.router, prefix="/ruang", tags=["ruang"])


from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Wire slowapi rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
