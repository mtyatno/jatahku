"""Pemuat bahan laporan berkala (spec 2026-11-01-laporan-berkala-design, bagian 2c-2d): SATU-SATUNYA pembaca
database untuk isi laporan. Membaca satu penerima dan satu periode anggaran yang sudah tutup menjadi
`susun.BahanLaporan` (objek biasa, tanpa sesi ORM); `susun_bulanan` yang murni menjadikannya `data` beku.

Privasi (kontrak visibilitas household, AGENTS.md) ditegakkan di sini, bukan di penyusun, halaman, atau PDF:
- lingkup amplop: amplop household itu yang bersama (`owner_id` NULL) atau pribadi milik penerima, aktif atau tidak.
  Amplop pribadi anggota lain tidak pernah dibaca, juga tidak untuk total pembanding;
- keterangan transaksi hanya lewat `visibility.masked_description`; penanda tombol Bayar (`BILL_MARKER`) hanya dibaca
  dari keterangan yang boleh dilihat penerima, supaya awalan keterangan privat anggota lain tidak bocor;
- pemasukan hanya yang dicatat penerima sendiri (`pemasukan.filter_pemasukan_user`, definisi yang sama dengan
  analitik), dan hanya pemasukan nyata (nominal di atas 0, jadi bukan transfer antar-amplop).
Agregat (terpakai, alokasi) menghitung semua transaksi di amplop lingkup, termasuk yang privat dan penyesuaian.

Angka ("satu sumber angka", tanpa rumus baru): per amplop dari `monthly_snapshots` kunci (tahun, bulan) awal periode;
kolom `allocated_amount`/`spent_amount` yang NULL (snapshot lama) dihitung `rollover.calculate_envelope_balance`.
Amplop yang ditutup di tengah periode tidak punya snapshot dan dihitung dengan fungsi penulis snapshot
(`get_previous_rollover`, `calculate_envelope_balance`, `snapshot_values`).

Baris amplop:
- amplop lingkup yang punya snapshot kunci periode itu, `ditutup=False` walau kini nonaktif: snapshot hanya ditulis
  untuk amplop yang aktif saat periode tutup, jadi amplop itu baru ditutup sesudah periodenya;
- amplop lingkup nonaktif tanpa snapshot itu yang punya transaksi (tidak terhapus) atau alokasi di jendela,
  `ditutup=True`;
- amplop aktif tanpa snapshot (dibuat sesudah periode) tidak ikut;
- amplop yang tanggal UTC `created_at`-nya sesudah akhir periode tidak pernah jadi baris, walau punya snapshot kunci
  itu (Ruling R8: refresh paksa snapshot sebelum laporan dibangun memberinya snapshot nol).
Transaksi, alokasi per hari, tagihan periode berikutnya, dan target hanya untuk amplop baris (`susun` menolak
transaksi dan target yang menunjuk amplop di luar baris). `terpakai_lalu_total` sebaliknya meliputi SEMUA amplop
lingkup yang punya angka periode itu, termasuk yang bukan baris.

Streak saat terbit dibaca lewat `streak.get_streak`, pembaca yang sama dengan aplikasi: streak yang sudah putus
(catatan terakhir sebelum kemarin, zona waktu user) bernilai 0, bukan angka basi di `user_streaks.current_streak`.

Urutan, supaya laporan yang sama selalu tersusun sama: amplop menurut `created_at` (seperti daftar amplop), transaksi
dan pemasukan menurut tanggal lalu waktu dicatat, tagihan menurut `next_run`, target menurut `created_at`; `id`
memutus seri.
"""
from collections import defaultdict
from datetime import date, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, func, or_, select

from app.core.period import get_budget_period, get_closed_periods
from app.models.models import (
    Allocation, Envelope, Goal, Income, MonthlySnapshot, RecurringTransaction, Transaction, User,
)
from app.services.advisor.snapshot import BILL_MARKER
from app.services.laporan.susun import (
    JUMLAH_PERIODE_BANDING, AmplopPeriode, BahanLaporan, PemasukanPeriode, TagihanBerikut, TargetTabungan,
    TransaksiPeriode,
)
from app.services.pemasukan import filter_pemasukan_user
from app.services.rollover import SnapshotValues, calculate_envelope_balance, get_previous_rollover, snapshot_values
from app.services.streak import get_streak
from app.services.visibility import can_view_description, masked_description

_NOL = Decimal(0)


async def muat_bahan(db, user, household, period_start: date, period_end: date, payday: int,
                     angka_per: date) -> BahanLaporan:
    """Bahan laporan bulanan `user` di ruang `household` untuk periode `period_start`..`period_end` (satu periode
    tanggal gajian `payday`); `angka_per` = tanggal terbit. Jendela yang bukan satu periode gajian itu ditolak
    (`ValueError`): kunci snapshot dan periode pembanding diturunkan dari `payday`, dan laporan yang terbit tidak
    pernah diubah lagi."""
    if get_budget_period(payday, period_start) != (period_start, period_end):
        raise ValueError(f"jendela {period_start}..{period_end} bukan satu periode gajian tanggal {payday}")
    kunci = (period_start.year, period_start.month)
    kunci_lalu = [(awal.year, awal.month)
                  for awal, _ in get_closed_periods(payday, period_start, JUMLAH_PERIODE_BANDING)]

    lingkup = (await db.execute(
        select(Envelope)
        .where(
            Envelope.household_id == household.id,
            or_(Envelope.owner_id.is_(None), Envelope.owner_id == user.id),
        )
        .order_by(Envelope.created_at, Envelope.id)
    )).scalars().all()
    snapshot = await _snapshot(db, [env.id for env in lingkup], [kunci, *kunci_lalu])
    baris = await _baris(db, lingkup, snapshot, kunci, period_start, period_end)
    baris_ids = [env.id for env, _, _ in baris]
    per_hari = await _alokasi_per_hari(db, baris_ids, period_start, period_end)

    amplop = [
        AmplopPeriode(
            id=str(env.id), nama=env.name, emoji=env.emoji or "", pribadi=env.owner_id is not None,
            tujuan=str(getattr(env.purpose, "value", env.purpose)),
            awal=angka.opening, alokasi=angka.allocated, terpakai=angka.spent, akhir=angka.closing,
            rollover=angka.rollover, ditutup=ditutup, alokasi_per_hari=per_hari.get(env.id, {}),
            terpakai_lalu=[_terpakai(snapshot.get((env.id, *k))) for k in kunci_lalu],
        )
        for env, angka, ditutup in baris
    ]
    return BahanLaporan(
        penerima_nama=user.name,
        rumah_nama=household.name,
        periode_mulai=period_start,
        periode_akhir=period_end,
        payday=payday,
        angka_per=angka_per,
        amplop=amplop,
        transaksi=await _transaksi(db, user, baris_ids, period_start, period_end),
        pemasukan=await _pemasukan(db, user, household, period_start, period_end),
        tagihan_berikut=await _tagihan_berikut(db, baris_ids, payday, period_end),
        target=await _target(db, baris_ids),
        streak_saat_ini=(await get_streak(db, user.id, getattr(user, "timezone", None))).current_streak,
        terpakai_lalu_total=[_total_terpakai(snapshot.values(), k) for k in kunci_lalu],
    )


async def _snapshot(db, env_ids: list, kunci: list[tuple[int, int]]) -> dict:
    """Snapshot amplop `env_ids` pada kunci (tahun, bulan) `kunci`, menurut (envelope_id, tahun, bulan)."""
    if not env_ids:
        return {}
    hasil = (await db.execute(
        select(MonthlySnapshot).where(
            MonthlySnapshot.envelope_id.in_(env_ids),
            or_(*(and_(MonthlySnapshot.year == tahun, MonthlySnapshot.month == bulan) for tahun, bulan in kunci)),
        )
    )).scalars().all()
    return {(s.envelope_id, s.year, s.month): s for s in hasil}


def _terpakai(s) -> Decimal | None:
    """Terpakai satu snapshot; None bila tidak ada snapshot atau kolomnya NULL (tidak dikenal, bukan nol)."""
    return None if s is None or s.spent_amount is None else s.spent_amount


def _total_terpakai(semua_snapshot, kunci: tuple[int, int]) -> Decimal | None:
    """Jumlah terpakai semua snapshot lingkup pada `kunci` yang angkanya dikenal; None bila tak satu pun."""
    nilai = [s.spent_amount for s in semua_snapshot if (s.year, s.month) == kunci and s.spent_amount is not None]
    return sum(nilai, _NOL) if nilai else None


def _tanggal_dibuat(env) -> date:
    """Tanggal UTC `created_at` amplop (asyncpg memberi datetime berzona; SQLite tanpa zona, sudah UTC)."""
    dibuat = env.created_at
    if dibuat.tzinfo is not None:
        dibuat = dibuat.astimezone(timezone.utc)
    return dibuat.date()


async def _baris(db, lingkup, snapshot: dict, kunci: tuple[int, int], ps: date, pe: date) -> list[tuple]:
    """(amplop, angka `SnapshotValues`, ditutup) untuk setiap baris amplop, dalam urutan `lingkup`. Amplop yang
    dibuat sesudah `pe` (tanggal UTC `created_at`) tidak pernah jadi baris, walau punya snapshot kunci itu (Ruling
    R8): refresh paksa snapshot sebelum laporan dibangun memberinya snapshot nol."""
    calon = [env for env in lingkup if _tanggal_dibuat(env) <= pe]
    calon_ditutup = [env.id for env in calon if not env.is_active and (env.id, *kunci) not in snapshot]
    beraktivitas = await _beraktivitas(db, calon_ditutup, ps, pe)
    baris = []
    for env in calon:
        s = snapshot.get((env.id, *kunci))
        if s is not None:
            baris.append((env, await _angka_snapshot(db, env.id, s, ps, pe), False))
        elif env.id in beraktivitas:
            rollover_masuk = await get_previous_rollover(env.id, ps.year, ps.month, db)
            saldo = await calculate_envelope_balance(env.id, ps, pe, db)
            angka = snapshot_values(rollover_masuk, saldo["allocated"], saldo["spent"], env.is_rollover)
            baris.append((env, angka, True))
    return baris


async def _beraktivitas(db, env_ids: list, ps: date, pe: date) -> set:
    """Amplop di `env_ids` yang punya transaksi tidak terhapus atau alokasi (menurut `income_date`) di jendela:
    himpunan yang sama dengan yang dijumlahkan `calculate_envelope_balance`."""
    if not env_ids:
        return set()
    transaksi = select(Transaction.envelope_id).where(
        Transaction.envelope_id.in_(env_ids),
        Transaction.is_deleted == False,
        Transaction.transaction_date >= ps,
        Transaction.transaction_date <= pe,
    )
    alokasi = (
        select(Allocation.envelope_id)
        .join(Income, Allocation.income_id == Income.id)
        .where(Allocation.envelope_id.in_(env_ids), Income.income_date >= ps, Income.income_date <= pe)
    )
    return set((await db.execute(transaksi.union(alokasi))).scalars().all())


async def _angka_snapshot(db, env_id, s, ps: date, pe: date) -> SnapshotValues:
    """Angka snapshot apa adanya; hanya kolom alokasi/terpakai yang NULL dihitung `calculate_envelope_balance`."""
    alokasi, terpakai = s.allocated_amount, s.spent_amount
    if alokasi is None or terpakai is None:
        saldo = await calculate_envelope_balance(env_id, ps, pe, db)
        alokasi = saldo["allocated"] if alokasi is None else alokasi
        terpakai = saldo["spent"] if terpakai is None else terpakai
    return SnapshotValues(opening=s.opening_balance, closing=s.closing_balance, rollover=s.rollover_amount,
                          allocated=alokasi, spent=terpakai)


async def _alokasi_per_hari(db, env_ids: list, ps: date, pe: date) -> dict:
    """{envelope_id: {income_date: jumlah alokasi}} di jendela, gabungan dan saringan yang sama dengan
    `calculate_envelope_balance` (jadi jumlahnya = alokasi periode itu)."""
    hasil: dict = defaultdict(dict)
    if not env_ids:
        return hasil
    for env_id, tanggal, jumlah in (await db.execute(
        select(Allocation.envelope_id, Income.income_date, func.sum(Allocation.amount))
        .join(Income, Allocation.income_id == Income.id)
        .where(Allocation.envelope_id.in_(env_ids), Income.income_date >= ps, Income.income_date <= pe)
        .group_by(Allocation.envelope_id, Income.income_date)
        .order_by(Income.income_date)
    )).all():
        hasil[env_id][tanggal] = jumlah
    return hasil


async def _transaksi(db, user, env_ids: list, ps: date, pe: date) -> list[TransaksiPeriode]:
    """Transaksi tidak terhapus di amplop baris dalam jendela (himpunan `calculate_envelope_balance`), keterangan
    sudah disamarkan untuk `user`. Gabungan ke `users` untuk nama pencatat tidak membuang baris: `user_id` wajib
    dan ber-FK (hapus akun memindahkan catatan ke "Mantan anggota")."""
    if not env_ids:
        return []
    hasil = []
    for txn, pencatat in (await db.execute(
        select(Transaction, User.name)
        .join(User, User.id == Transaction.user_id)
        .where(
            Transaction.envelope_id.in_(env_ids),
            Transaction.is_deleted == False,
            Transaction.transaction_date >= ps,
            Transaction.transaction_date <= pe,
        )
        .order_by(Transaction.transaction_date, Transaction.created_at, Transaction.id)
    )).all():
        hasil.append(TransaksiPeriode(
            id=str(txn.id),
            amplop_id=str(txn.envelope_id),
            tanggal=txn.transaction_date,
            jumlah=txn.amount,
            keterangan=masked_description(user.id, txn),
            pencatat=pencatat,
            milik_penerima=str(txn.user_id) == str(user.id),
            penyesuaian=txn.balance_check_id is not None,
            tagihan=can_view_description(user.id, txn) and (txn.description or "").startswith(BILL_MARKER),
        ))
    return hasil


async def _pemasukan(db, user, household, ps: date, pe: date) -> list[PemasukanPeriode]:
    return [
        PemasukanPeriode(tanggal=inc.income_date, jumlah=inc.amount, keterangan=inc.description)
        for inc in (await db.execute(
            select(Income)
            .where(*filter_pemasukan_user(household.id, user.id, ps, pe), Income.amount > 0)
            .order_by(Income.income_date, Income.created_at, Income.id)
        )).scalars().all()
    ]


async def _tagihan_berikut(db, env_ids: list, payday: int, pe: date) -> list[TagihanBerikut]:
    """Langganan aktif di amplop baris yang `next_run`-nya di periode sesudah `pe` (Ruling R2: amplop tanpa baris,
    mis. dibuat sesudah periode, tidak ikut)."""
    if not env_ids:
        return []
    mulai, akhir = get_budget_period(payday, pe + timedelta(days=1))
    return [
        TagihanBerikut(tanggal=r.next_run, nama=r.description, amplop_id=str(r.envelope_id), jumlah=r.amount)
        for r in (await db.execute(
            select(RecurringTransaction)
            .where(
                RecurringTransaction.envelope_id.in_(env_ids),
                RecurringTransaction.is_active == True,
                RecurringTransaction.next_run >= mulai,
                RecurringTransaction.next_run <= akhir,
            )
            .order_by(RecurringTransaction.next_run, RecurringTransaction.created_at, RecurringTransaction.id)
        )).scalars().all()
    ]


async def _target(db, env_ids: list) -> list[TargetTabungan]:
    if not env_ids:
        return []
    return [
        TargetTabungan(nama=g.name, amplop_id=str(g.envelope_id), target=g.target_amount)
        for g in (await db.execute(
            select(Goal).where(Goal.envelope_id.in_(env_ids)).order_by(Goal.created_at, Goal.id)
        )).scalars().all()
    ]
