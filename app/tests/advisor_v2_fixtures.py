"""Fixture snapshot AI Advisor v2 (metrics.py / aturan) — tanpa database.

`SnapshotBuilder` merakit `app.services.advisor.snapshot.Snapshot` dengan id
string yang mudah dibaca. `contoh_15_okt()` = contoh lengkap 02-aturan.md §12
(periode 27 Sep – 26 Okt 2026, hari ini 15 Okt). Nama orang fiktif.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from itertools import count

from app.core.period import get_last_n_periods
from app.services.advisor.snapshot import (
    AllocationSnap, BalanceCheckSnap, EnvelopeSnap, GoalSnap, IncomeSnap, RecurringSnap,
    Snapshot, TransactionSnap, bill_desc_of,
)

VIEWER = "u-saya"
PARTNER = "u-rina"


class SnapshotBuilder:
    def __init__(self, today: date, payday_day: int = 1, income_type: str = "monthly",
                 viewer: str = VIEWER, periods: int = 6):
        self.snap = Snapshot(
            viewer_id=viewer, household_id="hh-1", today=today, payday_day=payday_day,
            income_type=income_type, periods=get_last_n_periods(payday_day, periods, today),
            member_names={VIEWER: "Saya", PARTNER: "Rina"},
        )
        self._seq = count(1)

    @property
    def ps(self) -> date:
        return self.snap.periods[-1][0]

    def _id(self, prefix):
        return f"{prefix}-{next(self._seq)}"

    def envelope(self, id, name=None, purpose="expense", **kw):
        self.snap.envelopes.append(EnvelopeSnap(id=id, name=name or id, purpose=purpose, **kw))
        return self

    def income(self, amount, on=None, user=VIEWER, alloc=None, id=None, adjustment=False, created_at=None):
        """Pemasukan + alokasinya. alloc = {env_id | None: jumlah}; None = amplop tak terlihat."""
        on = on or self.ps
        iid = id or self._id("inc")
        self.snap.incomes.append(IncomeSnap(id=iid, user_id=user, amount=D(amount), income_date=on,
                                            created_at=created_at, is_adjustment=adjustment))
        for env_id, amt in (alloc or {}).items():
            self.snap.allocations.append(AllocationSnap(income_id=iid, envelope_id=env_id,
                                                        amount=D(amt), income_date=on))
        return iid

    def fund(self, env_id, amount, on=None, user=VIEWER):
        return self.income(amount, on=on, user=user, alloc={env_id: amount})

    def transfer(self, src, dst, amount, on=None, user=VIEWER):
        return self.income(0, on=on, user=user, alloc={src: -D(amount), dst: amount})

    def txn(self, env_id, amount, on=None, desc="belanja", user=VIEWER, adjustment=False,
            created_at=None, id=None, private=False):
        on = on or self.snap.today
        tid = id or self._id("txn")
        self.snap.transactions.append(TransactionSnap(
            id=tid, envelope_id=env_id, user_id=user, amount=D(amount), transaction_date=on,
            description=desc, is_adjustment=adjustment, is_private=private,
            created_at=created_at or datetime(on.year, on.month, on.day, 12, tzinfo=timezone.utc),
            bill_desc=bill_desc_of(desc),
        ))
        return tid

    def recurring(self, env_id, amount, desc, next_run, frequency="monthly", id=None):
        rid = id or self._id("rec")
        self.snap.recurring.append(RecurringSnap(id=rid, envelope_id=env_id, amount=D(amount),
                                                 description=desc, frequency=frequency, next_run=next_run))
        return rid

    def goal(self, env_id, name, target, target_date=None):
        self.snap.goals.append(GoalSnap(id=self._id("goal"), envelope_id=env_id, name=name,
                                        target_amount=D(target), target_date=target_date))
        return self

    def lifetime(self, env_id, amount):
        self.snap.lifetime_balance[env_id] = D(amount)
        return self

    def balance_check(self, on, gap):
        self.snap.last_balance_check = BalanceCheckSnap(created_on=on, gap=D(gap))
        return self

    def build(self) -> Snapshot:
        return self.snap


# Belanja 7 hari terakhir di contoh §12 (9–15 Okt), dalam ribuan rupiah.
LAST7 = [0, 370_000, 0, 400_000, 140_000, 200_000, 297_100]


def contoh_15_okt() -> SnapshotBuilder:
    """02-aturan.md §12: T1 Rp11.285.200, T2 Rp8.000.000, KPR Rp1.600.000 telat 9 hari."""
    today = date(2026, 10, 15)
    b = SnapshotBuilder(today, payday_day=27)
    b.envelope("belanja", "Makan & Jajan", classification="needs")
    b.envelope("tagihan", "Tagihan & Cicilan", purpose="debt")
    b.envelope("darurat", "Dana Darurat", purpose="saving", is_emergency=True)
    b.income(12_485_200, on=b.ps, alloc={"belanja": 9_685_200, "tagihan": 1_600_000, "darurat": 1_200_000},
             id="gaji")
    # 6.592.900 tersebar 27 Sep – 8 Okt (12 hari), tanpa outlier
    early = D("6592900")
    per_day = (early / 12).quantize(D("1"))
    for i in range(12):
        amt = per_day if i < 11 else early - per_day * 11
        b.txn("belanja", amt, on=b.ps + timedelta(days=i))
    for j, amt in enumerate(LAST7):
        if amt:
            b.txn("belanja", amt, on=today - timedelta(days=6 - j))
    b.recurring("tagihan", 1_600_000, "KPR Rumah", date(2026, 10, 6), id="kpr")
    b.lifetime("darurat", 1_210_000)
    return b
