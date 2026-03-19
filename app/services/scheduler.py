import logging
from datetime import date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.rollover import create_monthly_snapshots

logger = logging.getLogger("jatahku.scheduler")
scheduler = AsyncIOScheduler()


async def monthly_snapshot_job():
    """Run on the 1st of each month — snapshot the previous month."""
    now = date.today()
    if now.month == 1:
        target_year, target_month = now.year - 1, 12
    else:
        target_year, target_month = now.year, now.month - 1

    logger.info(f"Running monthly snapshot for {target_year}-{target_month:02d}")
    result = await create_monthly_snapshots(target_year, target_month)
    logger.info(f"Snapshot result: {result}")


def start_scheduler():
    """Start the APScheduler with monthly snapshot job."""
    scheduler.add_job(
        monthly_snapshot_job,
        trigger="cron",
        day=1,
        hour=0,
        minute=5,
        id="monthly_snapshot",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — monthly snapshot runs on 1st of each month at 00:05")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
