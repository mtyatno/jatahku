import logging
import uuid
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.rollover import create_monthly_snapshots
from app.services.summary import send_daily_summary, send_weekly_summary
from app.services.recurring_processor import process_recurring_transactions
from app.services.visibility import masked_description

logger = logging.getLogger("jatahku.scheduler")
scheduler = AsyncIOScheduler()


# How many recently-closed periods the daily job backfills. Covers short
# outages; use the /snapshots/recompute endpoint for longer gaps or repairs.
CATCH_UP_PERIODS = 3


def household_runs(
    rows: list[tuple[uuid.UUID, int]], today: date, catch_up: int
) -> list[tuple[uuid.UUID, int, list[tuple[date, date]]]]:
    """Rencana snapshot harian: untuk tiap `(household_id, payday)` sampai `catch_up` periode tertutup terakhir
    menurut tanggal gajian household itu sendiri, oldest-first. Urutan input dipertahankan.

    Murni (tanpa IO), supaya rencananya bisa diuji tanpa DB. Satu household satu jendela: household campuran (anggota
    dengan tanggal gajian berbeda) tidak lagi diproses sekali per tanggal. Job memanggilnya per household, dengan
    tanggal yang dibaca ulang di dalam `household_lock`."""
    from app.core.period import get_closed_periods

    return [(hid, payday, get_closed_periods(payday, today, catch_up)) for hid, payday in rows]


async def payday_snapshot_job():
    """Jalan harian: pastikan snapshot periode anggaran yang baru tutup ada, per household.

    Siklus anggaran milik household (`households.payday_day`), jadi tiap household yang punya anggota diproses SEKALI
    dengan satu tanggal gajiannya; household tanpa anggota (sisa yang ditinggalkan user yang pindah) dilewati.

    Tahap pertama, satu sesi: tiap household diisi tanggalnya bila masih NULL (`household_payday`) dan
    `users.payday_day` anggota yang menyimpang diselaraskan (`heal`), lalu commit dan sesi ditutup. Snapshot dibuat
    `create_monthly_snapshots` lewat sesinya sendiri, yang tidak boleh berhadapan dengan UPDATE yang belum di-commit.

    Tahap kedua, per household, di dalam `household_lock` (kunci yang sama dengan `recompute_history`: recompute
    menghapus lalu menyisipkan ulang kunci snapshot yang juga ditulis di sini, jadi keduanya tidak boleh berjalan
    bersamaan). Tanggal gajian DIBACA ULANG di dalam kunci (`current_payday`) dan jendela dibangun darinya, bukan dari
    tahap pertama: pemilik bisa mengubah tanggal selagi job mengerjakan household lain, dan recompute-nya lalu membangun
    ulang riwayat serta membuang kunci periode berjalan menurut tanggal baru. Jendela basi akan menulis kunci itu lagi
    dengan angka periode lama, dan job (tanpa `force`) tidak pernah menimpanya, jadi rollover yang salah terbawa terus.
    Household yang sudah dihapus (merge, penghapusan akun) dilewati dengan peringatan.

    Periode tertutup terakhir (`CATCH_UP_PERIODS`) ditelusuri oldest-first, supaya rollover tiap periode melihat
    pendahulunya yang sudah dibuat, dan yang belum ada dibuat. Tanpa `force`: snapshot yang sudah ada tidak disentuh,
    jadi run yang terlewat terkejar tanpa merusak rantai rollover."""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.models import Household, HouseholdMember
    from app.services.household_cycle import current_payday, heal, household_lock, household_payday

    today = date.today()

    async with AsyncSessionLocal() as db:
        households = (await db.execute(
            select(Household).where(Household.id.in_(select(HouseholdMember.household_id)))
        )).scalars().all()
        hids: list[uuid.UUID] = []
        for household in households:
            # Urutan penting: `household_payday` mengisi tanggal yang NULL, dan `heal` melewati household yang
            # tanggalnya belum terisi. Nilai kembaliannya sengaja tidak dipakai: jendela memakai tanggal yang dibaca
            # ulang di dalam kunci (tahap kedua).
            await household_payday(db, household)
            await heal(db, household)
            hids.append(household.id)
        await db.commit()

    for hid in hids:
        async with household_lock(hid):
            payday = await current_payday(hid)
            if payday is None:
                logger.warning("household=%s sudah tidak ada saat gilirannya; snapshot dilewati", hid)
                continue
            [(_, _, periods)] = household_runs([(hid, payday)], today, CATCH_UP_PERIODS)  # rencana satu household
            for period_start, period_end in periods:
                result = await create_monthly_snapshots(period_start, period_end, household_ids=[hid])
                if result["snapshots_created"]:
                    logger.info(
                        "household=%s payday=%s period %s → %s: %s snapshots created, %s errors",
                        hid, payday, period_start, period_end,
                        result["snapshots_created"], len(result["errors"]),
                    )


async def check_pending_reminders():
    """Check for pending transactions ready to confirm, send Telegram reminder."""
    from datetime import datetime, timezone
    from sqlalchemy import select, update
    from app.core.database import AsyncSessionLocal
    from app.models.models import PendingTransaction, PendingTransactionStatus, User, Envelope
    import redis.asyncio as aioredis
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.TELEGRAM_BOT_TOKEN:
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        # Find pending transactions that are past confirm_after and not yet reminded
        result = await db.execute(
            select(PendingTransaction, User, Envelope)
            .join(User, PendingTransaction.user_id == User.id)
            .join(Envelope, PendingTransaction.envelope_id == Envelope.id)
            .where(
                PendingTransaction.status == PendingTransactionStatus.pending,
                PendingTransaction.confirm_after <= now,
            )
        )
        rows = result.all()

        r = aioredis.from_url(settings.REDIS_URL)
        for pending, user, envelope in rows:
            # Check if already reminded (use Redis to track)
            reminded_key = f"reminded:{pending.id}"
            already = await r.get(reminded_key)
            if already:
                continue

            if user.telegram_id:
                try:
                    emoji = envelope.emoji or "📁"
                    from app.bot.handlers import format_currency
                    keyboard = [
                        [InlineKeyboardButton("✅ Konfirmasi", callback_data=f"cool_confirm_{pending.id}")],
                        [InlineKeyboardButton("❌ Batalkan", callback_data=f"cool_cancel_{pending.id}")],
                    ]
                    await bot.send_message(
                        chat_id=int(user.telegram_id),
                        text=(
                            f"🔔 Cooling period selesai!\n\n"
                            f"{format_currency(pending.amount)} — {masked_description(user.id, pending)}\n"
                            f"Amplop: {emoji} {envelope.name}\n\n"
                            f"Masih mau beli? Konfirmasi atau batalkan."
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                    # Mark as reminded (expire in 48h)
                    await r.set(reminded_key, "1", ex=172800)
                    logger.info(f"Sent cooling reminder to {user.telegram_id} for pending {pending.id}")
                except Exception as e:
                    logger.error(f"Failed to send reminder: {e}")

        # Auto-expire old pending transactions
        expired = await db.execute(
            select(PendingTransaction).where(
                PendingTransaction.status == PendingTransactionStatus.pending,
                PendingTransaction.expires_at < now,
            )
        )
        for p in expired.scalars().all():
            p.status = PendingTransactionStatus.expired
            logger.info(f"Auto-expired pending transaction {p.id}")

        await db.commit()
        await r.close()


async def run_user_summaries():
    """Check each user's timezone + preferred time, send if it matches now."""
    from datetime import datetime, timezone as tz
    from zoneinfo import ZoneInfo
    from sqlalchemy import or_, select
    from app.core.database import AsyncSessionLocal
    from app.models.models import User, NotificationPreference

    now_utc = datetime.now(tz.utc)

    async with AsyncSessionLocal() as db:
        # Semua user aktif: lonceng web & peringatan advisor juga untuk user tanpa Telegram (S16).
        result = await db.execute(select(User).where(
            or_(User.email == None, ~or_(User.email.startswith("deleted_"), User.email.startswith("banned_")))
        ))
        users = result.scalars().all()

        for user in users:
            try:
                user_tz = ZoneInfo(getattr(user, 'timezone', 'Asia/Jakarta') or 'Asia/Jakarta')
            except:
                user_tz = ZoneInfo('Asia/Jakarta')

            user_now = now_utc.astimezone(user_tz)
            user_hour = f"{user_now.hour:02d}:00"

            # Get preferences
            prefs_r = await db.execute(
                select(NotificationPreference).where(NotificationPreference.user_id == user.id)
            )
            prefs = prefs_r.scalar_one_or_none()

            daily_time = getattr(prefs, 'daily_summary_time', '20:00') or '20:00' if prefs else '20:00'
            weekly_time = getattr(prefs, 'weekly_summary_time', '08:00') or '08:00' if prefs else '08:00'

            # AI Advisor: peringatan danger (item #1), maks 1/hari, di luar jam tenang (S16).
            # Sebelum ringkasan: bila ringkasan harian jalan di jam yang sama, kuota dipakai sekali.
            try:
                from app.services.advisor.proaktif import kirim_peringatan
                await kirim_peringatan(user, prefs, user_now)
            except Exception as e:
                logger.error(f"Advisor warning failed for {user.id}: {e}")

            # Daily summary (Telegram dan/atau lonceng web, sesuai preferensi)
            daily_tg = bool(prefs and prefs.daily_summary_tg and user.telegram_id)
            daily_web = bool(prefs and prefs.daily_summary_web)
            if (daily_tg or daily_web) and user_hour == daily_time.split(':')[0] + ':00':
                try:
                    await send_daily_summary(user_id=user.id, telegram=daily_tg, web=daily_web)
                except Exception as e:
                    logger.error(f"Daily summary failed for {user.id}: {e}")

            # Weekly summary (Monday only)
            weekly_tg = bool(prefs and prefs.weekly_summary_tg and user.telegram_id)
            weekly_web = bool(prefs and prefs.weekly_summary_web)
            if user_now.weekday() == 0 and (weekly_tg or weekly_web) and user_hour == weekly_time.split(':')[0] + ':00':
                try:
                    await send_weekly_summary(user_id=user.id, telegram=weekly_tg, web=weekly_web)
                except Exception as e:
                    logger.error(f"Weekly summary failed for {user.id}: {e}")

            # Payday allocation reminder (08:00 local, first 3 days of period)
            if user_hour == "08:00":
                try:
                    from app.services.payday_reminder import send_payday_reminder
                    await send_payday_reminder(user, user_now, prefs, db)
                except Exception as e:
                    logger.error(f"Payday reminder failed for {user.id}: {e}")

            # Daily check-in nudge — if user hasn't logged anything today by
            # their preferred hour, gently ask them to (keeps the habit alive).
            checkin_time = (getattr(prefs, 'checkin_nudge_time', '21:00') or '21:00') if prefs else '21:00'
            checkin_on = getattr(prefs, 'checkin_nudge_tg', True) if prefs else True
            if checkin_on and user_hour == checkin_time.split(':')[0] + ':00':
                try:
                    await send_checkin_nudge(user, user_now.date(), db)
                except Exception as e:
                    logger.error(f"Check-in nudge failed for {user.id}: {e}")

    logger.info(f"User summaries check complete at {now_utc.isoformat()}")


async def send_checkin_nudge(user, local_today, db):
    """Send a once-a-day Telegram nudge if the user hasn't logged today.

    No-ops when: the user has no Telegram, has no envelopes yet (can't log),
    already logged activity today, or a nudge was already sent today (anti-spam). The 'no spending' button keeps the
    streak alive without forcing a transaction."""
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from app.models.models import UserStreak
    from app.core.config import get_settings

    if not user.telegram_id:
        return

    settings = get_settings()
    if not settings.TELEGRAM_BOT_TOKEN:
        return

    # Belum punya amplop → pencatatan diblok; jangan diminta mencatat tiap malam.
    from app.bot.handlers import _is_setup_complete
    setup_ok, _ = await _is_setup_complete(user, db)
    if not setup_ok:
        return

    streak = await db.get(UserStreak, user.id)
    # Already logged today → no nudge needed.
    if streak and streak.last_log_date == local_today:
        return
    # Already nudged today → don't spam.
    if streak and streak.last_checkin_date == local_today:
        return

    streak_hint = ""
    if streak and streak.current_streak >= 2 and streak.last_log_date == local_today - timedelta(days=1):
        streak_hint = f"\n\nStreak kamu {streak.current_streak} hari — jangan putus ya 🔥"

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    keyboard = [[InlineKeyboardButton("✅ Gak ada pengeluaran hari ini", callback_data="checkin_none")]]
    try:
        await bot.send_message(
            chat_id=int(user.telegram_id),
            text=(
                "👋 Belum ada catatan hari ini.\n\n"
                "Lagi hemat, atau lupa nyatat? Kirim aja pengeluaranmu "
                "(misal: <i>kopi 25k</i>), atau tekan tombol kalau memang "
                f"gak ada pengeluaran.{streak_hint}"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        # Record that we nudged today (create row if needed).
        if streak is None:
            streak = UserStreak(user_id=user.id)
            db.add(streak)
        streak.last_checkin_date = local_today
        await db.commit()
        logger.info(f"Sent check-in nudge to {user.telegram_id}")
    except Exception as e:
        logger.error(f"Failed to send check-in nudge to {user.id}: {e}")


async def purge_receipt_ocr_text():
    """Privasi: hapus teks OCR struk yang tidak pernah diberi feedback (>24 jam)."""
    from app.core.database import AsyncSessionLocal
    from app.services.receipt_scan import purge_stale_ocr_text
    try:
        async with AsyncSessionLocal() as db:
            n = await purge_stale_ocr_text(db)
        if n:
            logger.info(f"Purged OCR text from {n} stale receipt scans")
    except Exception as e:
        logger.error(f"purge_receipt_ocr_text failed: {e}")


async def kotak_maintenance():
    """Kotak Struk, tiap jam di menit 17 (spec 2026-10-26 §2d): item siap/gagal yang lewat masa simpan → kedaluwarsa, lalu
    berkas yatim di folder sementara dihapus, lalu kerangka tata letak item selesai yang dibaca > 24 jam lalu dihapus
    (spec 2026-11-01 §3a). Tiap langkah memakai sesinya sendiri dan blok try sendiri: satu langkah gagal tidak
    melewatkan yang lain. Galat hanya dicatat."""
    from datetime import datetime, timezone
    from app.core.config import get_settings
    from app.core.database import AsyncSessionLocal
    from app.services.kotak_struk import maintenance

    try:
        async with AsyncSessionLocal() as db:
            n = await maintenance.expire_items(db, now=datetime.now(timezone.utc))
        if n:
            logger.info(f"Kotak Struk: {n} item kedaluwarsa")
    except Exception:
        logger.exception("kotak_maintenance: expire_items gagal")

    try:
        async with AsyncSessionLocal() as db:
            n = await maintenance.delete_orphan_files(get_settings().KOTAK_DIR, db, now=datetime.now(timezone.utc))
        if n:
            logger.info(f"Kotak Struk: {n} berkas yatim dihapus")
    except Exception:
        logger.exception("kotak_maintenance: delete_orphan_files gagal")

    try:
        async with AsyncSessionLocal() as db:
            n = await maintenance.purge_layouts(db, now=datetime.now(timezone.utc))
        if n:
            logger.info(f"Kotak Struk: kerangka tata letak {n} item dihapus")
    except Exception:
        logger.exception("kotak_maintenance: purge_layouts gagal")


def start_scheduler():
    """Start the APScheduler with monthly snapshot job."""
    scheduler.add_job(
        payday_snapshot_job,
        trigger="cron",
        hour=0,
        minute=5,
        id="payday_snapshot",
        replace_existing=True,
    )
    scheduler.add_job(
        check_pending_reminders,
        trigger="interval",
        minutes=5,
        id="pending_reminders",
        replace_existing=True,
    )
    scheduler.add_job(
        run_user_summaries,
        trigger="cron",
        minute=0,  # Every hour, check which users need summary
        id="user_summaries",
        replace_existing=True,
    )
    scheduler.add_job(
        process_recurring_transactions,
        trigger="cron",
        minute=1,  # tiap jam; per user mulai 07.00 lokal, sekali per jatuh tempo (S16)
        id="recurring_transactions",
        replace_existing=True,
    )
    scheduler.add_job(
        purge_receipt_ocr_text,
        trigger="interval",
        hours=1,
        id="purge_receipt_ocr_text",
        replace_existing=True,
    )
    scheduler.add_job(
        kotak_maintenance,
        trigger="cron",
        minute=17,  # tiap jam di menit tetap: interval baru jalan 1 jam setelah tiap restart; :17 menghindari job :00
        id="kotak_maintenance",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — monthly snapshot + pending reminders + hourly user summaries + recurring")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
