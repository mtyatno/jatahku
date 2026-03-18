from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db
from app.core.config import get_settings
import redis.asyncio as aioredis

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "tagline": "Setiap rupiah ada jatahnya.",
        "status": "running",
        "version": "0.1.0",
    }


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    checks = {"api": "ok", "database": "error", "redis": "error"}

    # Check PostgreSQL
    try:
        result = await db.execute(text("SELECT 1"))
        if result.scalar() == 1:
            checks["database"] = "ok"
    except Exception as e:
        checks["database"] = str(e)

    # Check Redis
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        pong = await r.ping()
        if pong:
            checks["redis"] = "ok"
        await r.close()
    except Exception as e:
        checks["redis"] = str(e)

    status = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
