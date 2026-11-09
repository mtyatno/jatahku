"""Tulis data inti atas nama plugin (Plugin U2; AGENTS.md "Plugin dan ruang" aturan 4).

Satu-satunya jalan plugin menulis tabel inti. Saat ini hanya pemasukan (`incomes:write`, `ctx.catat_pemasukan`):

- hanya dari endpoint plugin non-GET (`boleh_tulis`), dengan user pemicu (bukan job), owner/admin (karyawan ditolak
  `khusus_admin`, lapis kedua sesudah gerbang rute);
- ruang selalu ruang konteks; setiap amplop pembagian harus amplop aktif di ruang itu yang boleh dilihat viewer
  (bersama, atau pribadi miliknya) — lainnya = `NilaiTidakSah`, tidak pernah lintas ruang;
- pembagian harus persis sama dengan jumlah (tidak ada sisa otomatis ke Tabungan di ruang usaha);
- lewat jalur pemasukan inti yang sama (`routes.incomes.catat_pemasukan`, batasan R5 ikut berlaku) dengan
  `commit=False`: pemasukan, pembagian, dan tulisan plugin ke tabelnya sendiri masuk dalam SATU commit milik route
  `/p/<id>/…`; bila fungsi plugin gagal sesudahnya, semuanya batal;
- diaudit `inti:pemasukan` tanpa nominal atau keterangan, di sesi yang sama (ikut commit atau ikut batal).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from app.plugins.host import keadaan

MAKS_PEMBAGIAN = 20
MAKS_NOMINAL = Decimal("9999999999999.99")       # Numeric(15, 2)
HARI_MUNDUR_MAKS = 366
MAKS_KETERANGAN = 500


def _galat(pesan: str):
    from app.plugins.sdk.context import NilaiTidakSah
    return NilaiTidakSah(pesan)


def _nominal(v, nama: str) -> Decimal:
    if isinstance(v, (bool, float)) or not isinstance(v, (int, str, Decimal)):
        raise _galat(f"{nama} harus angka (bukan pecahan biner).")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise _galat(f"{nama} harus angka.")
    if not d.is_finite() or d != d.quantize(Decimal("0.01")):
        raise _galat(f"{nama} paling banyak dua angka di belakang koma.")
    return d


def hari_ini(zona: str | None) -> date:
    try:
        return datetime.now(ZoneInfo(zona or "Asia/Jakarta")).date()
    except Exception:
        return datetime.now(ZoneInfo("Asia/Jakarta")).date()


async def catat_pemasukan(ctx, *, jumlah, keterangan: str, tanggal: date | None, pembagian) -> dict:
    """Dipanggil `PluginContext.catat_pemasukan`. Mengembalikan `{"income_id", "jumlah", "tanggal", "pembagian":
    [{"envelope_id", "nama", "jumlah"}]}`."""
    k = keadaan.ambil(ctx)
    await keadaan.perlu(k, "incomes:write")
    if k.viewer is None:
        await keadaan.tolak(k, "incomes:write", "bukan_rute")
    if not k.boleh_tulis:
        await keadaan.tolak(k, "incomes:write", "hanya_baca")
    if keadaan.karyawan(k) or k.peran not in ("owner", "admin"):
        await keadaan.tolak(k, "incomes:write", "khusus_admin")

    total = _nominal(jumlah, "Jumlah")
    if total <= 0 or total > MAKS_NOMINAL:
        raise _galat("Jumlah harus lebih dari nol.")
    if not isinstance(keterangan, str) or not keterangan.strip():
        raise _galat("Keterangan wajib diisi.")
    keterangan = " ".join(keterangan.split())[:MAKS_KETERANGAN]
    sekarang = hari_ini(k.viewer.zona_waktu)
    if tanggal is None:
        tanggal = sekarang
    if not isinstance(tanggal, date) or isinstance(tanggal, datetime):
        raise _galat("Tanggal tidak terbaca.")
    if tanggal > sekarang:
        raise _galat("Tanggal tidak boleh sesudah hari ini.")
    if tanggal < sekarang - timedelta(days=HARI_MUNDUR_MAKS):
        raise _galat("Tanggal paling lama satu tahun ke belakang.")

    if not isinstance(pembagian, (list, tuple)) or not pembagian or len(pembagian) > MAKS_PEMBAGIAN:
        raise _galat("Pembagian ke amplop wajib diisi.")
    baris: dict[UUID, Decimal] = {}
    for item in pembagian:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise _galat("Pembagian tidak terbaca.")
        try:
            eid = item[0] if isinstance(item[0], UUID) else UUID(str(item[0]))
        except ValueError:
            raise _galat("Amplop tidak dikenali.")
        n = _nominal(item[1], "Pembagian")
        if n < 0:
            raise _galat("Pembagian tidak boleh negatif.")
        if eid in baris:
            raise _galat("Amplop yang sama muncul dua kali.")
        baris[eid] = n
    if sum(baris.values()) != total:
        raise _galat("Jumlah pembagian harus sama dengan jumlah pemasukan.")

    from app.models.models import Envelope, Income, User
    uid = k.viewer.id
    amplop = {e.id: e for e in (await k.db.execute(
        select(Envelope).where(Envelope.id.in_(list(baris)), Envelope.household_id == k.ruang_id,
                               Envelope.is_active.is_(True),
                               or_(Envelope.owner_id.is_(None), Envelope.owner_id == uid))
    )).scalars().all()}
    if set(amplop) != set(baris):
        raise _galat("Amplop tidak ditemukan di ruang ini.")
    user = (await k.db.execute(select(User).where(User.id == uid))).scalar_one()

    from fastapi import HTTPException
    from app.api.routes.incomes import (AllocationItem, IncomeCreate, IncomeResponse,
                                        catat_pemasukan as _catat)
    from app.services.ruang import RuangDitolak
    req = IncomeCreate(amount=total, source=keterangan, kind="pemasukan",
                       allocations=[AllocationItem(envelope_id=e, amount=n) for e, n in baris.items() if n > 0])
    try:
        hasil = await _catat(req, user, k.db, k.ruang_id, commit=False, income_date=tanggal)
    except (HTTPException, RuangDitolak) as exc:
        raise _galat(str(getattr(exc, "detail", "")) or "Pemasukan tidak bisa dicatat.")
    if not isinstance(hasil, IncomeResponse):
        # Draf persetujuan (202) hanya untuk karyawan, yang sudah ditolak di atas: tidak pernah sampai sini.
        raise _galat("Pemasukan tidak bisa dicatat.")
    income = (await k.db.execute(select(Income).where(Income.id == hasil.id))).scalar_one()
    # Audit di sesi yang sama (seperti `data:*`): tercatat bila dan hanya bila pemasukannya ikut ter-commit.
    from app.models.models import PluginAuditLog
    k.db.add(PluginAuditLog(household_id=k.ruang_id, plugin_id=k.plugin_id, actor_id=uid, action="inti:pemasukan",
                            detail={"income_id": str(income.id), "amplop": len(baris), "sumber": k.sumber}))
    return {
        "income_id": income.id, "jumlah": total, "tanggal": tanggal,
        "pembagian": [{"envelope_id": e, "nama": amplop[e].name, "jumlah": n} for e, n in baris.items()],
    }
