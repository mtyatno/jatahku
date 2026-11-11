"""Baca agregat untuk plugin: jumlah dan banyak catatan per kelompok, dihitung database (Plugin U3).

`ctx.transactions()` dan `ctx.incomes()` mengembalikan paling banyak `BATAS_BARIS` baris, jadi angka laporan yang
dijumlahkan dari baris itu diam-diam terpotong di ruang yang ramai. Untuk angka (laba rugi, kartu, laporan) plugin
memakai `ctx.ringkas_transaksi` / `ctx.ringkas_pemasukan`, yang menjumlahkan di database dan tidak pernah terpotong:
bila kelompoknya lebih dari `MAKS_KELOMPOK`, panggilan gagal (`ValueError`), bukan memotong.

Aturan yang sama dengan baca baris (`sdk/context.py`):

- **Ruang dan visibilitas dari host.** Ruang konteks saja; transaksi hanya di amplop yang boleh dilihat viewer (amplop
  bersama + amplop pribadi viewer; job: amplop bersama). `hanya_bersama=True` membuang amplop pribadi viewer juga.
  Pemasukan mengikuti `_pemasukan_terlihat` (ruang usaha: semua; ruang keluarga: milik viewer).
- **Izin** `transactions:read` / `incomes:read`; karyawan ditolak `khusus_admin` (pemeriksaan di metode konteks).
- **Kelompok** (`per`, paling banyak `MAKS_PER`): `bulan` ("YYYY-MM" tanggal catatan), `tanggal` (`date` tanggal
  catatan; U4, untuk deret harian/mingguan yang dirangkai plugin); transaksi juga `amplop` (UUID); pemasukan juga
  `jenis` (`incomes.kind`). Selain itu `"<entitas>.<kolom>"` dari tabel **pendamping** plugin itu sendiri
  (1:1 dengan `transactions`/`incomes`, mis. `txn_meta.akun`, `income_meta.jenis`): left join ke baris hidup di ruang
  yang sama. Kolom milik host (`WAJIB`) dan kolom rujukan ke induknya tidak boleh dipakai sebagai kelompok.
- **Privasi.** Kelompok dari tabel pendamping untuk transaksi yang deskripsinya tersamar bagi viewer (privat milik
  anggota lain; job: semua privat) bernilai `None`, seperti `masked_description`: nominal tetap ikut dijumlah (kontrak
  visibilitas: agregat utuh), kategorinya tidak terbaca.
- **Milik sendiri** (U4): `ringkas_pemasukan(..., milik=<user_id>)` hanya menjumlah pemasukan yang dicatat user itu di
  ruang konteks. Dipakai `ctx.ringkas_pemasukan_saya`, satu-satunya baca keuangan yang terbuka untuk karyawan.
- **Pemasukan** juga mengembalikan `dialokasikan` = jumlah alokasinya. Gerakan internal bernominal 0 (prive keluar,
  transfer) hanya terbaca lewat angka ini (R8: prive keluar = alokasi negatif).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Table, and_, case, extract, func, literal, null, or_, select

from app.plugins.host import data as data_host

MAKS_PER = 3
MAKS_KELOMPOK = 1000
NOL = Decimal("0")


@dataclass(frozen=True)
class _Pendamping:
    tabel: Table
    kolom: Any        # kolom kelompok
    rujukan: Any      # kolom FK ke induk (transactions.id / incomes.id)


def _rujukan_induk(t: Table, induk: str):
    """Kolom FK tabel pendamping ke `induk` (bagian indeks unik hidup household_id + rujukan), atau None."""
    for ix in t.indexes:
        if not ix.unique:
            continue
        kolom = [c for c in ix.columns if c.name != "household_id"]
        if len(kolom) == 1 and any(fk.column.table.name == induk for fk in kolom[0].foreign_keys):
            return kolom[0]
    return None


def _pendamping(k, spek: str, induk: str) -> _Pendamping:
    entitas, titik, kolom = spek.partition(".")
    if not titik or not kolom:
        raise ValueError(f"kelompok '{spek}' tidak dikenal")
    t = data_host._tabel(k, entitas)                 # entitas milik plugin ini (manifest), atau ValueError
    rujukan = _rujukan_induk(t, induk)
    if rujukan is None:
        raise ValueError(f"'{t.name}' bukan tabel pendamping {induk}")
    if kolom not in t.c or kolom in data_host.WAJIB or kolom == rujukan.name:
        raise ValueError(f"kolom '{kolom}' tidak bisa dipakai sebagai kelompok")
    return _Pendamping(tabel=t, kolom=t.c[kolom], rujukan=rujukan)


def privat_orang_lain(uid, t) -> bool:
    """Transaksi privat (atau `is_private` kosong: fail-closed) yang bukan milik viewer; job: semua yang privat.
    Kelompok dan `meta` pendampingnya tidak terbaca (nominal tetap)."""
    if t.is_private is False:
        return False
    return uid is None or t.user_id is None or str(t.user_id) != str(uid)


def gabung_pendamping(k, q, entitas: str | None, induk: str, kolom_id):
    """`select(Model)` + left join baris hidup tabel pendamping `entitas` (ruang konteks) → (kueri, fungsi baris →
    meta). `meta` = kolom tabel tanpa kolom host dan tanpa rujukan ke induk; None bila tidak ada barisnya."""
    if entitas is None:
        return q, lambda r: None
    t = data_host._tabel(k, entitas)
    rujukan = _rujukan_induk(t, induk)
    if rujukan is None:
        raise ValueError(f"'{t.name}' bukan tabel pendamping {induk}")
    kolom = [c for c in t.c if c.name not in data_host.WAJIB and c.name != rujukan.name]
    q = q.add_columns(t.c.id, *kolom).outerjoin(
        t, and_(rujukan == kolom_id, t.c.household_id == k.ruang_id, t.c.deleted_at.is_(None)))

    def ambil(r):
        if r[1] is None:
            return None
        return {c.name: v for c, v in zip(kolom, r[2:2 + len(kolom)])}
    return q, ambil


def _per(per) -> tuple[str, ...]:
    if isinstance(per, str):
        per = (per,)
    per = tuple(per or ())
    if len(per) > MAKS_PER or len(set(per)) != len(per) or not all(isinstance(p, str) for p in per):
        raise ValueError(f"per: paling banyak {MAKS_PER} kelompok berbeda")
    return per


def _rentang(mulai, akhir) -> None:
    if not isinstance(mulai, date) or not isinstance(akhir, date) or mulai > akhir:
        raise ValueError("rentang tanggal tidak sah")


def _nilai_kunci(jenis: str, v):
    if v is None:
        return None
    if jenis == "jenis":
        return str(v)
    return v


def _uang(v) -> Decimal:
    return NOL if v is None else Decimal(str(v))


async def ringkas_transaksi(k, mulai: date, akhir: date, *, per=(), hanya_bersama: bool = False) -> list:
    from app.models.models import Envelope, Transaction
    from app.plugins.sdk.context import RingkasanView, _amplop_terlihat, _uid
    _rentang(mulai, akhir)
    per = _per(per)
    uid = _uid(k)
    privat = or_(Transaction.is_private.is_(None), Transaction.is_private.is_(True))
    tersamar = privat if uid is None else and_(
        privat, or_(Transaction.user_id.is_(None), Transaction.user_id != uid))
    kelompok: list[tuple[str, list]] = []
    gabung: dict[str, _Pendamping] = {}
    for p in per:
        if p == "bulan":
            kelompok.append(("bulan", [extract("year", Transaction.transaction_date),
                                       extract("month", Transaction.transaction_date)]))
        elif p == "tanggal":
            kelompok.append(("tanggal", [Transaction.transaction_date]))
        elif p == "amplop":
            kelompok.append(("amplop", [Transaction.envelope_id]))
        else:
            pd = _pendamping(k, p, "transactions")
            gabung.setdefault(pd.tabel.name, pd)
            kelompok.append((p, [case((tersamar, null()), else_=pd.kolom)]))
    terlihat = Envelope.owner_id.is_(None) if hanya_bersama else _amplop_terlihat(k, Envelope)
    q = (select(*[c for _, cs in kelompok for c in cs],
                func.coalesce(func.sum(Transaction.amount), literal(0)), func.count(Transaction.id))
         .select_from(Transaction).join(Envelope, Envelope.id == Transaction.envelope_id))
    for pd in gabung.values():
        t = pd.tabel
        q = q.outerjoin(t, and_(pd.rujukan == Transaction.id, t.c.household_id == k.ruang_id,
                                t.c.deleted_at.is_(None)))
    q = q.where(Envelope.household_id == k.ruang_id, terlihat, Transaction.is_deleted.is_(False),
                Transaction.transaction_date >= mulai, Transaction.transaction_date <= akhir)
    kolom_grup = [c for _, cs in kelompok for c in cs]
    if kolom_grup:
        q = q.group_by(*kolom_grup)
    rows = await _baris(k, q)
    return [RingkasanView(kunci=kunci, jumlah=_uang(v[0]), banyak=int(v[1] or 0), dialokasikan=NOL)
            for kunci, v in _urai(rows, kelompok)]


async def ringkas_pemasukan(k, mulai: date, akhir: date, *, per=(), milik=None) -> list:
    from app.models.models import Allocation, Income
    from app.plugins.sdk.context import RingkasanView, _pemasukan_terlihat
    _rentang(mulai, akhir)
    per = _per(per)
    dasar = and_(Income.household_id == k.ruang_id, _pemasukan_terlihat(k, Income),
                 Income.income_date >= mulai, Income.income_date <= akhir)
    if milik is not None:
        dasar = and_(dasar, Income.user_id == milik)
    alok = (select(Allocation.income_id.label("income_id"), func.sum(Allocation.amount).label("jumlah"))
            .join(Income, Income.id == Allocation.income_id).where(dasar)
            .group_by(Allocation.income_id).subquery())
    kelompok: list[tuple[str, list]] = []
    gabung: dict[str, _Pendamping] = {}
    for p in per:
        if p == "bulan":
            kelompok.append(("bulan", [extract("year", Income.income_date), extract("month", Income.income_date)]))
        elif p == "tanggal":
            kelompok.append(("tanggal", [Income.income_date]))
        elif p == "jenis":
            kelompok.append(("jenis", [Income.kind]))
        else:
            pd = _pendamping(k, p, "incomes")
            gabung.setdefault(pd.tabel.name, pd)
            kelompok.append((p, [pd.kolom]))
    q = (select(*[c for _, cs in kelompok for c in cs],
                func.coalesce(func.sum(Income.amount), literal(0)), func.count(Income.id),
                func.coalesce(func.sum(alok.c.jumlah), literal(0)))
         .select_from(Income).outerjoin(alok, alok.c.income_id == Income.id))
    for pd in gabung.values():
        t = pd.tabel
        q = q.outerjoin(t, and_(pd.rujukan == Income.id, t.c.household_id == k.ruang_id, t.c.deleted_at.is_(None)))
    q = q.where(dasar)
    kolom_grup = [c for _, cs in kelompok for c in cs]
    if kolom_grup:
        q = q.group_by(*kolom_grup)
    rows = await _baris(k, q)
    return [RingkasanView(kunci=kunci, jumlah=_uang(v[0]), banyak=int(v[1] or 0), dialokasikan=_uang(v[2]))
            for kunci, v in _urai(rows, kelompok)]


async def _baris(k, q) -> list[tuple]:
    rows = (await k.db.execute(q.limit(MAKS_KELOMPOK + 1))).all()
    if len(rows) > MAKS_KELOMPOK:
        raise ValueError(f"lebih dari {MAKS_KELOMPOK} kelompok; persempit rentang atau kelompoknya")
    return [tuple(r) for r in rows]


def _urai(rows: list[tuple], kelompok: list[tuple[str, list]]) -> list[tuple[tuple, list]]:
    """Baris kueri → [(kunci, [nilai agregat])], urut kunci (hasil tetap sama di SQLite dan PostgreSQL)."""
    hasil = []
    for r in rows:
        i, kunci = 0, []
        for jenis, cs in kelompok:
            if jenis == "bulan":
                th, bl = r[i], r[i + 1]
                kunci.append(None if th is None else f"{int(th):04d}-{int(bl):02d}")
            else:
                kunci.append(_nilai_kunci(jenis, r[i]))
            i += len(cs)
        hasil.append((tuple(kunci), list(r[i:])))
    hasil.sort(key=lambda x: tuple("" if v is None else str(v) for v in x[0]))
    return hasil
