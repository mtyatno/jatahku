from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.services.scheduler import start_scheduler, stop_scheduler
from app.api.routes import health, auth, envelopes, transactions, incomes, webhook, link, snapshots, household

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
    allow_origins=[settings.APP_URL, "http://localhost:5173"],
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
app.include_router(webhook.router, tags=["webhook"])
