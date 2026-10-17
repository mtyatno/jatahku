import html
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import (
    RecurringTransaction, RecurringFrequency, Envelope, User, HouseholdMember
)
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from app.core.config import get_settings
from app.bot.handlers import format_currency

settings = get_settings()
logger = logging.getLogger("jatahku.recurring")


def _next_date(current: date, freq: RecurringFrequency) -> date:
    if freq == RecurringFrequency.weekly:
        return current + timedelta(weeks=1)
    elif freq == RecurringFrequency.monthly:
        month = current.month + 1 if current.month < 12 else 1
        year = current.year if current.month < 12 else current.year + 1
        day = min(current.day, 28)
        return date(year, month, day)
    elif freq == RecurringFrequency.yearly:
        return date(current.year + 1, current.month, current.day)
    return current + timedelta(days=30)


def _local_now(user, now_utc: datetime) -> datetime:
    try:
        tz = ZoneInfo(getattr(user, "timezone", None) or "Asia/Jakarta")
    except Exception:
        tz = ZoneInfo("Asia/Jakarta")
    return now_utc.astimezone(tz)


def reminder_text(rec, envelope) -> str:
    freq_label = {"weekly": "mingguan", "monthly": "bulanan", "yearly": "tahunan"}
    emoji = envelope.emoji or "📁"
    return (
        f"🔔 Jatuh tempo langganan!\n\n"
        f"🔄 {rec.description}\n"
        f"{format_currency(rec.amount)} · {freq_label.get(rec.frequency.value, rec.frequency.value)}\n"
        f"Amplop: {emoji} {envelope.name}\n\n"
        f"Sudah bayar? Atau mau skip/berhenti?"
    )


def reminder_keyboard(rec) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Bayar & catat", callback_data=f"recpay_{rec.id}")],
        [InlineKeyboardButton("⏭️ Skip bulan ini", callback_data=f"recskip_{rec.id}")],
        [InlineKeyboardButton("❌ Berhenti langganan", callback_data=f"recstop_{rec.id}")],
    ])


async def _recipients(db, envelope) -> list:
    """Pemilik untuk amplop pribadi, semua anggota household untuk amplop bersama."""
    if envelope.owner_id is not None:
        q = select(User).where(User.id == envelope.owner_id)
    else:
        q = (select(User).join(HouseholdMember, HouseholdMember.user_id == User.id)
             .where(HouseholdMember.household_id == envelope.household_id))
    return list((await db.execute(q)).scalars().all())


def reminder_surfaces(user, prefs) -> list[str]:
    """Preferensi notifikasi (02-aturan.md §9): `subscription_due_tg` / `subscription_due_web`."""
    out = []
    if user.telegram_id and getattr(prefs, "subscription_due_tg", True):
        out.append("telegram")
    if getattr(prefs, "subscription_due_web", True):
        out.append("web")
    return out


async def process_recurring_transactions(now_utc: datetime | None = None):
    """Pengingat langganan jatuh tempo (dipanggil tiap jam). User yang konfirmasi bayar.

    S16 (02-aturan.md §9): per user — tanggal & jam lokal user, mulai 07.00 (jam tenang
    21.00–07.00 tidak berlaku untuk pagi itu, sisa hari tetap boleh), patuh preferensi
    `subscription_due_tg`/`_web`, dan hanya SEKALI per (langganan, jatuh tempo, user):
    tagihan telat yang belum dibayar tidak diingatkan lagi tiap hari (sudah tampil sebagai
    TAG-01 di AI Advisor). Pengingat dicatat di buku proaktif (hal `TAG:{id}`) supaya
    peringatan advisor untuk tagihan yang sama tidak menambah permukaan ketiga."""
    from app.services.advisor import proaktif
    from app.services.notification_service import get_or_create_prefs, kirim
    from app.models.models import NotificationType

    now_utc = now_utc or datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        recs = (await db.execute(
            select(RecurringTransaction).where(
                RecurringTransaction.is_active == True,
                # Lebih longgar sehari: zona waktu user bisa sudah "besok" dibanding UTC.
                RecurringTransaction.next_run <= now_utc.date() + timedelta(days=1),
            )
        )).scalars().all()

        for rec in recs:
            try:
                envelope = (await db.execute(
                    select(Envelope).where(Envelope.id == rec.envelope_id)
                )).scalar_one_or_none()
                if not envelope:
                    continue
                for user in await _recipients(db, envelope):
                    user_now = _local_now(user, now_utc)
                    if rec.next_run > user_now.date() or proaktif.jam_tenang(user_now):
                        continue
                    prefs = await get_or_create_prefs(user.id, db)
                    surfaces = reminder_surfaces(user, prefs)
                    if not surfaces:
                        continue
                    if await proaktif.klaim_pengingat_tagihan(rec.id, rec.next_run, user.id) is not True:
                        continue
                    text = reminder_text(rec, envelope)
                    sent = await kirim(
                        user, NotificationType.subscription_due,
                        f"🔔 Jatuh tempo: {rec.description}",
                        f"{format_currency(rec.amount)} — Amplop: {envelope.emoji or '📁'} {envelope.name}",
                        link="/langganan", telegram_html=html.escape(text, quote=False),
                        reply_markup=reminder_keyboard(rec), permukaan=surfaces,
                    )
                    buku = await proaktif.muat_buku(user.id, user_now.date())
                    if buku is not None:
                        await proaktif.catat(user.id, buku, proaktif.hal_tagihan(rec.id), sent, advisor=False)
                    logger.info(f"Recurring reminder {rec.description} → {user.id} ({','.join(sorted(sent))})")
            except Exception as e:
                logger.error(f"Failed recurring {rec.id}: {e}")
