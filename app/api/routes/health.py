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


@router.get("/api-stats")
async def public_stats():
    from app.core.database import AsyncSessionLocal
    from app.models.models import User, Transaction, Allocation, Income
    from sqlalchemy import select, func
    from datetime import date, timedelta

    def fmt(n):
        n = float(n)
        if n >= 1_000_000_000:
            return f"Rp {n/1_000_000_000:.1f} M"
        if n >= 1_000_000:
            return f"Rp {n/1_000_000:.1f} jt"
        if n >= 1_000:
            return f"Rp {int(n/1_000)} rb"
        return f"Rp {int(n)}"

    async with AsyncSessionLocal() as db:
        # Active users
        user_count = await db.execute(select(func.count(User.id)))
        users = user_count.scalar()

        today = date.today()
        week_ago = today - timedelta(days=7)

        # Total managed (all allocations ever)
        total_managed = await db.execute(
            select(func.coalesce(func.sum(Allocation.amount), 0))
        )
        managed = float(total_managed.scalar())

        # Today spending
        today_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.is_deleted == False,
                Transaction.transaction_date == today,
            )
        )
        today_total = float(today_result.scalar())

        # This week spending
        week_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.is_deleted == False,
                Transaction.transaction_date >= week_ago,
            )
        )
        week_total = float(week_result.scalar())

        # Total transactions
        txn_count = await db.execute(
            select(func.count(Transaction.id)).where(Transaction.is_deleted == False)
        )
        total_txns = txn_count.scalar()

    return {
        "users": users,
        "managed": fmt(managed),
        "today": fmt(today_total),
        "week": fmt(week_total),
        "txns": total_txns,
    }
