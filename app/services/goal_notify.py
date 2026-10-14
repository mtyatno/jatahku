"""Notifikasi "🎯 Goal tercapai" — dikirim saat saldo amplop MELEWATI target goal.

Saldo goal = saldo kumulatif amplop (envelope_lifetime_balance, sama dengan
halaman Goals & advisor). Saldo hanya bisa naik melewati target ketika dana
MASUK ke amplop, jadi pengecekan dipasang di titik dana masuk, bukan saat
pengeluaran (pengeluaran justru menurunkan saldo):
- POST /incomes (alokasi pemasukan, termasuk sisa ke Tabungan)
- POST /envelopes/transfer dan geser dana / top-up di bot
- hapus amplop (sisa dipindah ke Tabungan)
Penyesuaian "cocokkan saldo" sengaja tidak dihitung: itu koreksi pembukuan.

Pola pakai:
    before = await goal_snapshot(db, household_id)   # sebelum dana masuk
    ... tulis alokasi, commit ...
    await notify_goals_reached(db, user, before)     # sesudah commit

Hanya transisi di-bawah-target → mencapai-target yang memicu notifikasi, jadi
tidak berulang di setiap transaksi. Best-effort: kegagalan tidak pernah
menggagalkan pencatatan dana.
"""
import logging
from decimal import Decimal

from sqlalchemy import select

from app.models.models import Envelope, Goal, NotificationType
from app.services.advisor.context import envelope_lifetime_balance

logger = logging.getLogger("jatahku.goals")


def _md(text) -> str:
    """Escape Markdown (v1) untuk pesan Telegram send_notification."""
    s = str(text or "")
    for ch in ("\\", "_", "*", "`", "["):
        s = s.replace(ch, "\\" + ch)
    return s


def _rupiah(amount) -> str:
    return f"Rp{int(amount):,}".replace(",", ".")


async def goal_snapshot(db, household_id) -> dict:
    """{goal_id: saldo saat ini} untuk goal di amplop aktif household."""
    try:
        goals = (await db.execute(
            select(Goal)
            .join(Envelope, Goal.envelope_id == Envelope.id)
            .where(Envelope.household_id == household_id, Envelope.is_active == True)
        )).scalars().all()
        return {g.id: await envelope_lifetime_balance(g.envelope_id, db) for g in goals}
    except Exception:
        logger.exception("goal_snapshot gagal")
        return {}


def crossed(before: Decimal, after: Decimal, target: Decimal) -> bool:
    """Saldo baru saja mencapai target (sebelumnya di bawah)."""
    return Decimal(before) < Decimal(target) <= Decimal(after)


async def notify_goals_reached(db, user, before: dict) -> list:
    """Kirim notifikasi untuk goal yang baru mencapai target. Mengembalikan goal itu."""
    if not before:
        return []
    reached = []
    try:
        from app.services.notification_service import send_notification
        goals = (await db.execute(select(Goal).where(Goal.id.in_(list(before))))).scalars().all()
        for goal in goals:
            after = await envelope_lifetime_balance(goal.envelope_id, db)
            if crossed(before[goal.id], after, goal.target_amount):
                reached.append(goal)
        for goal in reached:
            env = await db.get(Envelope, goal.envelope_id)
            emoji, name = (env.emoji or "") if env else "", env.name if env else ""
            target = _rupiah(goal.target_amount)
            await send_notification(
                user.id,
                notif_type=NotificationType.system,
                title="🎯 Goal tercapai!",
                message=f"{emoji} {name} sudah mencapai target {goal.name} sebesar {target}. Selamat!",
                link="/envelopes",
                telegram_text=(f"*🎯 Goal tercapai!*\n{emoji} {_md(name)} sudah mencapai target "
                               f"{_md(goal.name)} sebesar {target}. Selamat!"),
                db=db,
            )
    except Exception:
        logger.exception("notify_goals_reached gagal")
    return reached
