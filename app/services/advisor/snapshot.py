"""Snapshot AI Advisor v2 — satu-satunya loader DB mesin aturan (02-aturan.md §1 langkah 1, §14).

Semua data yang dibutuhkan metrik, sinyal, dan aturan dimuat SEKALI dengan query
berkelompok: jumlah query tetap (±12), tidak tumbuh per amplop atau per periode.
Hasilnya objek biasa (dataclass) tanpa sesi ORM, jadi `metrics.py` dan aturan
bisa diuji dengan fixture tanpa database.

Privasi household (`visibility.py`) ditegakkan di sini, bukan di pemakai:
- amplop: hanya bersama + pribadi milik viewer;
- deskripsi transaksi sudah disamarkan (`masked_description`), mentahnya tidak disimpan;
- alokasi ke amplop yang tidak terlihat tetap dimuat (untuk P3 "belum dijatah"),
  tapi `envelope_id`-nya dikosongkan;
- pemasukan anggota lain hanya nominal & tanggal, tanpa deskripsi.

Belum dimuat (menyusul di sesi yang memakainya): preferensi notifikasi dan status
dismiss (Redis) — S3/S16.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.advisor.formatting import _to_decimal

PERIODS_COUNT = 6
BILL_MARKER = "🔄 "  # deskripsi transaksi yang dibuat tombol Bayar langganan (web/bot)


@dataclass
class EnvelopeSnap:
    id: str
    name: str
    emoji: str = ""
    purpose: str = "expense"
    classification: str | None = None
    is_rollover: bool = True
    is_emergency: bool = False
    is_locked: bool = False
    owner_id: str | None = None
    budget_amount: Decimal = Decimal("0")
    daily_limit: Decimal | None = None
    jenis_grup: str | None = None      # envelope_groups.jenis: "harian" | "bulanan" | None (otomatis)

    @property
    def jenis(self) -> str:
        """Kolam jatah harian (02-aturan.md §3): jenis grup bila diisi; otomatis `debt` → bulanan,
        selain itu harian. Hanya bermakna untuk amplop belanja."""
        if self.jenis_grup in ("harian", "bulanan"):
            return self.jenis_grup
        return "bulanan" if self.purpose == "debt" else "harian"


@dataclass
class TransactionSnap:
    id: str
    envelope_id: str
    user_id: str
    amount: Decimal
    transaction_date: date
    description: str = ""          # sudah disamarkan untuk viewer
    created_at: datetime | None = None
    is_private: bool = False
    is_adjustment: bool = False    # penyesuaian cocokkan saldo
    bill_desc: str | None = None   # "🔄 X" → "X" (pembayaran langganan lewat tombol Bayar)


@dataclass
class IncomeSnap:
    id: str
    user_id: str
    amount: Decimal                # 0 = transfer antar amplop
    income_date: date
    created_at: datetime | None = None
    is_adjustment: bool = False


@dataclass
class AllocationSnap:
    income_id: str
    envelope_id: str | None        # None = amplop yang tidak terlihat viewer
    amount: Decimal
    income_date: date


@dataclass
class RecurringSnap:
    id: str
    envelope_id: str
    amount: Decimal
    description: str
    frequency: str                 # weekly | monthly | yearly
    next_run: date


@dataclass
class GoalSnap:
    id: str
    envelope_id: str
    name: str
    target_amount: Decimal
    target_date: date | None = None


@dataclass
class BalanceCheckSnap:
    created_on: date               # tanggal lokal user
    gap: Decimal


@dataclass
class Snapshot:
    viewer_id: str
    household_id: str | None
    today: date
    payday_day: int = 1
    income_type: str = "monthly"
    periods: list[tuple[date, date]] = field(default_factory=list)   # terlama dulu; terakhir = berjalan
    envelopes: list[EnvelopeSnap] = field(default_factory=list)
    transactions: list[TransactionSnap] = field(default_factory=list)
    incomes: list[IncomeSnap] = field(default_factory=list)
    allocations: list[AllocationSnap] = field(default_factory=list)
    recurring: list[RecurringSnap] = field(default_factory=list)
    goals: list[GoalSnap] = field(default_factory=list)
    rollover: dict[tuple[str, int, int], Decimal] = field(default_factory=dict)  # (env, tahun, bulan) periode asal
    lifetime_balance: dict[str, Decimal] = field(default_factory=dict)           # G1, amplop tabungan
    last_balance_check: BalanceCheckSnap | None = None
    last_viewer_txn_date: date | None = None
    member_names: dict[str, str] = field(default_factory=dict)
    now: datetime | None = None    # waktu muat (UTC); S14 "lebih dari 24 jam" — tanpa jam sistem di signals.py

    @property
    def current_period(self) -> tuple[date, date]:
        return self.periods[-1]


def bill_desc_of(description: str | None) -> str | None:
    if description and description.startswith(BILL_MARKER):
        return description[len(BILL_MARKER):]
    return None


def user_today(user) -> date:
    """Hari ini di zona waktu user (default Asia/Jakarta)."""
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(getattr(user, "timezone", None) or "Asia/Jakarta")
    except Exception:
        tz = ZoneInfo("Asia/Jakarta")
    return datetime.now(tz).date()


def _local_date(dt: datetime | None, user) -> date | None:
    if dt is None:
        return None
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(getattr(user, "timezone", None) or "Asia/Jakarta")
    except Exception:
        tz = ZoneInfo("Asia/Jakarta")
    if dt.tzinfo is None:
        return dt.date()
    return dt.astimezone(tz).date()


def _freq(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _sid(value) -> str | None:
    return None if value is None else str(value)


async def load_snapshot(user, db, today: date | None = None,
                        periods_count: int = PERIODS_COUNT, *, household_id) -> Snapshot:
    """Muat snapshot viewer `user` di ruang `household_id` untuk `today` (default: hari ini di
    zona waktu user). Ruang ditentukan pemanggil (`app/services/ruang.py`)."""
    from sqlalchemy import func, or_, select
    from app.core.period import get_last_n_periods
    from app.models.models import (
        Allocation, BalanceCheck, Envelope, EnvelopeGroup, Goal, HouseholdMember, Income, MonthlySnapshot,
        RecurringTransaction, Transaction, User,
    )
    from app.services.visibility import masked_description

    today = today or user_today(user)
    viewer_id = str(user.id)
    payday_day = getattr(user, "payday_day", 1) or 1
    income_type = getattr(user, "income_type", None)
    if income_type not in ("daily", "weekly", "irregular"):
        income_type = "monthly"
    periods = get_last_n_periods(payday_day, periods_count, today)
    snap = Snapshot(viewer_id=viewer_id, household_id=None, today=today,
                    payday_day=payday_day, income_type=income_type, periods=periods,
                    now=datetime.now(timezone.utc))

    # 1. household (ruang)
    hid = household_id
    if not hid:
        return snap
    snap.household_id = str(hid)

    # 2. anggota (nama untuk "Terisi dari {nama}")
    for uid, name in (await db.execute(
        select(User.id, User.name)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .where(HouseholdMember.household_id == hid)
    )).all():
        snap.member_names[str(uid)] = name

    # 3. amplop terlihat
    rows = (await db.execute(
        select(Envelope, EnvelopeGroup.jenis)
        .outerjoin(EnvelopeGroup, EnvelopeGroup.id == Envelope.group_id)
        .where(
            Envelope.household_id == hid,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
        .order_by(Envelope.created_at)
    )).all()
    envelopes = [e for e, _ in rows]
    snap.envelopes = [
        EnvelopeSnap(
            id=str(e.id), name=e.name, emoji=e.emoji or "", purpose=str(e.purpose or "expense"),
            classification=e.classification, is_rollover=bool(e.is_rollover),
            is_emergency=bool(getattr(e, "is_emergency", False)), is_locked=bool(e.is_locked),
            owner_id=_sid(e.owner_id), budget_amount=_to_decimal(e.budget_amount),
            daily_limit=None if e.daily_limit is None else _to_decimal(e.daily_limit),
            jenis_grup=jenis,
        )
        for e, jenis in rows
    ]
    env_ids = [e.id for e in envelopes]
    visible = {str(i) for i in env_ids}
    range_start, range_end = periods[0][0], periods[-1][1]

    # 4. pemasukan rumah tangga (termasuk transfer = Income 0) 6 periode
    for i in (await db.execute(
        select(Income.id, Income.user_id, Income.amount, Income.income_date,
               Income.created_at, Income.balance_check_id)
        .where(
            Income.household_id == hid,
            Income.income_date >= range_start,
            Income.income_date <= range_end,
        )
    )).all():
        snap.incomes.append(IncomeSnap(
            id=str(i.id), user_id=str(i.user_id), amount=_to_decimal(i.amount),
            income_date=i.income_date, created_at=i.created_at,
            is_adjustment=i.balance_check_id is not None,
        ))

    # 5. alokasi dari pemasukan itu (amplop tak terlihat → envelope_id None)
    for a in (await db.execute(
        select(Allocation.income_id, Allocation.envelope_id, Allocation.amount, Income.income_date)
        .join(Income, Allocation.income_id == Income.id)
        .where(
            Income.household_id == hid,
            Income.income_date >= range_start,
            Income.income_date <= range_end,
        )
    )).all():
        eid = str(a.envelope_id)
        snap.allocations.append(AllocationSnap(
            income_id=str(a.income_id), envelope_id=eid if eid in visible else None,
            amount=_to_decimal(a.amount), income_date=a.income_date,
        ))

    if env_ids:
        # 6. transaksi 6 periode di amplop terlihat (semua anggota — agregat menghitung semuanya)
        for t in (await db.execute(
            select(Transaction.id, Transaction.envelope_id, Transaction.user_id, Transaction.amount,
                   Transaction.transaction_date, Transaction.description, Transaction.created_at,
                   Transaction.is_private, Transaction.balance_check_id)
            .where(
                Transaction.envelope_id.in_(env_ids),
                Transaction.is_deleted == False,
                Transaction.transaction_date >= range_start,
                Transaction.transaction_date <= range_end,
            )
        )).all():
            masked = masked_description(
                user.id,
                SimpleNamespace(user_id=t.user_id, is_private=bool(t.is_private),
                                description=t.description),
            )
            snap.transactions.append(TransactionSnap(
                id=str(t.id), envelope_id=str(t.envelope_id), user_id=str(t.user_id),
                amount=_to_decimal(t.amount), transaction_date=t.transaction_date,
                description=masked, created_at=t.created_at, is_private=bool(t.is_private),
                is_adjustment=t.balance_check_id is not None,
                bill_desc=bill_desc_of(t.description),
            ))

        # 7. langganan aktif
        for r in (await db.execute(
            select(RecurringTransaction).where(
                RecurringTransaction.envelope_id.in_(env_ids),
                RecurringTransaction.is_active == True,
            )
        )).scalars().all():
            snap.recurring.append(RecurringSnap(
                id=str(r.id), envelope_id=str(r.envelope_id), amount=_to_decimal(r.amount),
                description=r.description, frequency=_freq(r.frequency), next_run=r.next_run,
            ))

        # 8. target tabungan
        for g in (await db.execute(select(Goal).where(Goal.envelope_id.in_(env_ids)))).scalars().all():
            snap.goals.append(GoalSnap(
                id=str(g.id), envelope_id=str(g.envelope_id), name=g.name,
                target_amount=_to_decimal(g.target_amount), target_date=g.target_date,
            ))

        # 9. snapshot rollover (periode asal = tahun/bulan awal periode sebelumnya)
        for s in (await db.execute(
            select(MonthlySnapshot.envelope_id, MonthlySnapshot.year, MonthlySnapshot.month,
                   MonthlySnapshot.rollover_amount)
            .where(MonthlySnapshot.envelope_id.in_(env_ids))
        )).all():
            snap.rollover[(str(s.envelope_id), s.year, s.month)] = _to_decimal(s.rollover_amount)

        # 10–11. saldo sepanjang waktu amplop tabungan (G1) — dua query berkelompok,
        # rumus sama dengan context.envelope_lifetime_balance.
        saving_ids = [e.id for e in envelopes if str(e.purpose) in ("saving", "sinking_fund")]
        if saving_ids:
            balances = {str(i): Decimal("0") for i in saving_ids}
            for eid, total in (await db.execute(
                select(Allocation.envelope_id, func.coalesce(func.sum(Allocation.amount), 0))
                .where(Allocation.envelope_id.in_(saving_ids))
                .group_by(Allocation.envelope_id)
            )).all():
                balances[str(eid)] += _to_decimal(total)
            for eid, total in (await db.execute(
                select(Transaction.envelope_id, func.coalesce(func.sum(Transaction.amount), 0))
                .where(Transaction.envelope_id.in_(saving_ids), Transaction.is_deleted == False)
                .group_by(Transaction.envelope_id)
            )).all():
                balances[str(eid)] -= _to_decimal(total)
            snap.lifetime_balance = balances

    # 12. cocokkan saldo terakhir yang tidak dibatalkan (K1, K2)
    check = (await db.execute(
        select(BalanceCheck.created_at, BalanceCheck.gap)
        .where(BalanceCheck.household_id == hid, BalanceCheck.undone_at.is_(None))
        .order_by(BalanceCheck.created_at.desc())
        .limit(1)
    )).first()
    if check is not None:
        snap.last_balance_check = BalanceCheckSnap(
            created_on=_local_date(check.created_at, user), gap=_to_decimal(check.gap),
        )

    # 13. transaksi terakhir viewer (K3), di luar jendela 6 periode juga
    snap.last_viewer_txn_date = (await db.execute(
        select(func.max(Transaction.transaction_date)).where(
            Transaction.user_id == user.id, Transaction.is_deleted == False,
        )
    )).scalar()

    return snap
