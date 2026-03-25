from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.core.config import get_settings
from app.services.scheduler import start_scheduler, stop_scheduler
from app.api.routes import health, auth, envelopes, transactions, incomes, webhook, link, snapshots, household, export, recurring, analytics, notifications, user_settings, admin, payment

settings = get_settings()
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"🚀 {settings.APP_NAME} starting...")
    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()
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
app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
app.include_router(user_settings.router, prefix="/user", tags=["user"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(payment.router, prefix="/payment", tags=["payment"])
app.include_router(webhook.router, tags=["webhook"])


from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)
