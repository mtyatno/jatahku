"""Peran, batasan, dan antrean persetujuan ruang usaha (Plugin R5; 04-kontrak-api.md §2, §7; ADR-P4, P17, P18).

Siapa dibatasi: hanya peran `member` (UI: Karyawan) di ruang **usaha**. Owner dan admin tidak dibatasi; ruang
keluarga tidak pernah dibatasi, jadi perilaku household yang sekarang tidak berubah.

Penegakan ada di dua lapis, keduanya di server (AGENTS.md "Plugin dan ruang" aturan 3):

1. **Tolak-bawaan.** Karyawan hanya boleh memakai route yang memang untuk mencatat. `ruang_aktif` dan pembantu ruang
   objek (`app/services/ruang.py`) menolak semua route lain dengan 403 `khusus_admin`, dan menolak ruang usaha di
   luar jam kerja dengan 403 `di_luar_jam_kerja` (+ `buka_lagi`). Route baru otomatis tertolak untuk karyawan.
2. **Batasan per catatan** (`cek_catat`), dipanggil route yang lolos lapis 1: jenis catatan, amplop yang diizinkan,
   foto nota, dan batas nominal. Di atas batas nominal catatan menjadi draf (`buat_draf`), bukan transaksi.

Draf disetujui lewat jalur pencatatan yang sama atas nama pencatat asli, di dalam `atas_izin_pengelola()` supaya
batasan pencatat tidak menahan catatan yang sudah disetujui admin.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Household, HouseholdMember, HouseholdRole, HouseholdType, RuangAudit, RuangBatasan, RuangDraf,
)

JENIS_PENGELUARAN = "pengeluaran"
JENIS_PENJUALAN = "penjualan"
JENIS_SEMUA = (JENIS_PENGELUARAN, JENIS_PENJUALAN)
JENDELA = ("hari_sama", "tidak_boleh")
ZONA_BAWAAN = "Asia/Jakarta"

ST_MENUNGGU, ST_DIPROSES, ST_DISETUJUI, ST_DITOLAK, ST_DIBATALKAN = (
    "menunggu", "diproses", "disetujui", "ditolak", "dibatalkan")

# Teks siap tampil (`detail`), kode untuk mesin (`kode`, §7).
PESAN = {
    "khusus_admin": "Bagian ini hanya untuk pemilik dan admin ruang.",
    "amplop_tidak_diizinkan": "Amplop ini tidak termasuk yang diizinkan admin untukmu.",
    "jenis_tidak_diizinkan": "Admin belum mengizinkanmu mencatat jenis ini di ruang ini.",
    "jendela_ubah_lewat": "Catatan ini sudah tidak bisa diubah atau dihapus. Minta admin bila perlu.",
}


class PeranDitolak(Exception):
    """Dipetakan ke `RuangDitolak` oleh pemanggil HTTP (`app/services/ruang.py`); dipisah supaya modul ini tidak
    bergantung pada FastAPI dan bisa dipakai per baris di antrean offline."""

    def __init__(self, kode: str, detail: str | None = None, status_code: int = 403, extra: dict | None = None):
        super().__init__(kode)
        self.kode = kode
        self.detail = detail or PESAN.get(kode, "Tidak diizinkan.")
        self.status_code = status_code
        self.extra = extra or {}


# ── Izin pengelola untuk menyetujui draf ───────────────────────────────────
_izin_pengelola: contextvars.ContextVar[bool] = contextvars.ContextVar("izin_pengelola", default=False)


@contextmanager
def atas_izin_pengelola():
    """Selama blok ini batasan karyawan tidak diperiksa: draf yang disetujui admin dicatat atas nama pencatat asli
    lewat jalur yang sama (ADR-P18), tanpa dibatasi lagi oleh batas nominal atau jam kerja pencatat."""
    token = _izin_pengelola.set(True)
    try:
        yield
    finally:
        _izin_pengelola.reset(token)


def izin_pengelola_aktif() -> bool:
    return _izin_pengelola.get()


# ── Batasan ───────────────────────────────────────────────────────────────
@dataclass
class Batasan:
    jenis_catatan: list[str] = field(default_factory=lambda: list(JENIS_SEMUA))
    amplop_ids: list[str] | None = None
    batas_nominal: Decimal | None = None
    foto_nota_di_atas: Decimal | None = None
    jendela_ubah: str = "hari_sama"
    lihat_saldo: bool = False
    jam_kerja: dict | None = None

    def boleh_amplop(self, envelope_id) -> bool:
        return self.amplop_ids is None or str(envelope_id) in {str(a) for a in self.amplop_ids}

    def ke_api(self) -> dict:
        return {
            "jenis_catatan": list(self.jenis_catatan),
            "amplop_ids": None if self.amplop_ids is None else [str(a) for a in self.amplop_ids],
            "batas_nominal": None if self.batas_nominal is None else int(self.batas_nominal),
            "foto_nota_di_atas": None if self.foto_nota_di_atas is None else int(self.foto_nota_di_atas),
            "jendela_ubah": self.jendela_ubah,
            "lihat_saldo": self.lihat_saldo,
            "jam_kerja": self.jam_kerja,
        }


def _dari_baris(row: RuangBatasan | None) -> Batasan:
    if row is None:
        return Batasan()
    return Batasan(
        jenis_catatan=list(row.jenis_catatan or []),
        amplop_ids=None if row.amplop_ids is None else [str(a) for a in row.amplop_ids],
        batas_nominal=row.batas_nominal,
        foto_nota_di_atas=row.foto_nota_di_atas,
        jendela_ubah=row.jendela_ubah or "hari_sama",
        lihat_saldo=bool(row.lihat_saldo),
        jam_kerja=row.jam_kerja,
    )


async def peran_di_ruang(db: AsyncSession, user_id, household_id) -> tuple[str | None, str | None]:
    """(peran, jenis ruang) untuk user di ruang itu; (None, None) bila bukan anggota."""
    if household_id is None:
        return None, None
    row = (await db.execute(
        select(HouseholdMember.role, Household.type)
        .join(Household, Household.id == HouseholdMember.household_id)
        .where(HouseholdMember.user_id == user_id, HouseholdMember.household_id == household_id)
        .limit(1)
    )).first()
    if row is None:
        return None, None
    role = row[0].value if isinstance(row[0], HouseholdRole) else str(row[0])
    return role, str(row[1])


async def batasan_karyawan(db: AsyncSession, user_id, household_id) -> Batasan | None:
    """Batasan yang berlaku untuk user di ruang ini, atau None bila tidak dibatasi (ruang keluarga, owner, admin,
    bukan anggota, atau sedang menyetujui draf)."""
    if izin_pengelola_aktif():
        return None
    role, jenis = await peran_di_ruang(db, user_id, household_id)
    if role != HouseholdRole.member.value or jenis != HouseholdType.USAHA:
        return None
    row = (await db.execute(
        select(RuangBatasan).where(RuangBatasan.household_id == household_id, RuangBatasan.user_id == user_id)
    )).scalar_one_or_none()
    return _dari_baris(row)


# ── Jam kerja (ADR-P17) ─────────────────────────────────────────────────────
def _jam(teks: str) -> time:
    h, m = teks.split(":")
    return time(int(h), int(m))


def validasi_jam_kerja(jk: dict | None, zona_bawaan: str = ZONA_BAWAAN) -> dict | None:
    """Normalkan `{"mulai": "07:00", "selesai": "15:00", "hari": [1..7], "zona"?}` (hari ISO, 1 = Senin).
    `selesai` ≤ `mulai` = sif lewat tengah malam. ValueError bila tidak sah."""
    if jk is None:
        return None
    if not isinstance(jk, dict):
        raise ValueError("jam_kerja harus objek")
    mulai, selesai = _jam(str(jk.get("mulai", ""))), _jam(str(jk.get("selesai", "")))
    hari = sorted({int(h) for h in (jk.get("hari") or [1, 2, 3, 4, 5, 6, 7])})
    if not hari or any(h < 1 or h > 7 for h in hari):
        raise ValueError("hari harus 1–7")
    if mulai == selesai:
        raise ValueError("jam mulai dan selesai tidak boleh sama")
    zona = str(jk.get("zona") or zona_bawaan)
    ZoneInfo(zona)  # galat bila zona tidak dikenal
    return {"mulai": mulai.strftime("%H:%M"), "selesai": selesai.strftime("%H:%M"), "hari": hari, "zona": zona}


def _buka_pada(jk: dict, lokal: datetime) -> bool:
    mulai, selesai, hari = _jam(jk["mulai"]), _jam(jk["selesai"]), set(jk["hari"])
    t, d = lokal.time(), lokal.isoweekday()
    if mulai < selesai:
        return d in hari and mulai <= t < selesai
    kemarin = 7 if d == 1 else d - 1
    return (d in hari and t >= mulai) or (kemarin in hari and t < selesai)


def buka_lagi(jk: dict | None, sekarang: datetime | None = None) -> datetime | None:
    """None bila ruang sedang boleh dibuka; selain itu waktu buka berikutnya (zona jam kerja)."""
    if not jk:
        return None
    zona = ZoneInfo(jk.get("zona") or ZONA_BAWAAN)
    lokal = (sekarang or datetime.now(timezone.utc)).astimezone(zona)
    if _buka_pada(jk, lokal):
        return None
    mulai = _jam(jk["mulai"])
    for i in range(0, 8):
        hari = (lokal + timedelta(days=i)).date()
        kandidat = datetime.combine(hari, mulai, tzinfo=zona)
        if kandidat > lokal and hari.isoweekday() in set(jk["hari"]):
            return kandidat
    return None


def cek_jam_kerja(batasan: Batasan | None, sekarang: datetime | None = None) -> None:
    if batasan is None or not batasan.jam_kerja:
        return
    nanti = buka_lagi(batasan.jam_kerja, sekarang)
    if nanti is not None:
        raise PeranDitolak(
            "di_luar_jam_kerja",
            f"Ruang ini dibuka lagi {nanti.strftime('%d/%m %H:%M')} sesuai jam kerja dari admin.",
            extra={"buka_lagi": nanti.isoformat()},
        )


# ── Batasan per catatan ───────────────────────────────────────────────────
def _rp(x) -> str:
    return f"Rp{int(x):,}".replace(",", ".")


def cek_catat(batasan: Batasan | None, *, jenis: str, amplop_ids, jumlah: Decimal, ada_foto: bool) -> bool:
    """Batasan satu catatan karyawan. Melempar `PeranDitolak` (jenis, amplop, foto); mengembalikan True bila
    catatan harus menjadi draf menunggu persetujuan (di atas batas nominal). None = tidak dibatasi."""
    if batasan is None:
        return False
    if jenis not in batasan.jenis_catatan:
        raise PeranDitolak("jenis_tidak_diizinkan")
    for a in amplop_ids:
        if a is not None and not batasan.boleh_amplop(a):
            raise PeranDitolak("amplop_tidak_diizinkan")
    if batasan.foto_nota_di_atas is not None and jumlah > batasan.foto_nota_di_atas and not ada_foto:
        raise PeranDitolak("perlu_foto_nota",
                           f"Wajib foto nota untuk catatan di atas {_rp(batasan.foto_nota_di_atas)}.",
                           status_code=422)
    return batasan.batas_nominal is not None and jumlah > batasan.batas_nominal


def pesan_persetujuan(batasan: Batasan) -> str:
    return f"Batas catatanmu {_rp(batasan.batas_nominal)}. Catatan ini menunggu persetujuan admin."


def cek_jendela_ubah(batasan: Batasan | None, *, milik_sendiri: bool, dibuat: datetime | None,
                     sekarang: datetime | None = None) -> None:
    """Karyawan hanya mengubah/menghapus catatannya sendiri, di hari yang sama (zona jam kerja atau WIB)."""
    if batasan is None:
        return
    if not milik_sendiri or batasan.jendela_ubah == "tidak_boleh" or dibuat is None:
        raise PeranDitolak("jendela_ubah_lewat")
    zona = ZoneInfo((batasan.jam_kerja or {}).get("zona") or ZONA_BAWAAN)
    if dibuat.tzinfo is None:
        dibuat = dibuat.replace(tzinfo=timezone.utc)
    hari_ini = (sekarang or datetime.now(timezone.utc)).astimezone(zona).date()
    if dibuat.astimezone(zona).date() != hari_ini:
        raise PeranDitolak("jendela_ubah_lewat")


# ── Pesan galat pencatatan untuk karyawan (review keamanan PR #175, temuan 1) ─────
_PESAN_TANPA_ANGKA = {
    "insufficient": "Dana amplop ini tidak cukup untuk catatan ini. Minta admin mengisi amplopnya.",
    "not_funded": "Amplop ini belum diisi. Minta admin mengisi amplopnya.",
    "daily_limit": "Catatan ini melebihi batas harian amplop. Minta admin bila perlu.",
}


def pesan_cek_karyawan(batasan: "Batasan | None", check_type: str | None) -> str | None:
    """Pesan pengganti tanpa angka (sisa dana, limit, terpakai) untuk karyawan yang tidak boleh melihat saldo, supaya
    saldo tidak bisa dibaca lewat percobaan nominal. None = pakai pesan biasa."""
    if batasan is None or batasan.lihat_saldo:
        return None
    return _PESAN_TANPA_ANGKA.get(check_type or "")


def boleh_naikkan_limit(batasan: "Batasan | None") -> bool:
    """Karyawan tidak bisa menaikkan limit harian yang dipasang admin (temuan 2); `raise_daily_limit` diabaikan."""
    return batasan is None


async def owner_ruang(db: AsyncSession, household_id):
    """User pemilik ruang (penerima notifikasi pengganti karyawan, temuan 4)."""
    from app.models.models import User
    return (await db.execute(
        select(User).join(HouseholdMember, HouseholdMember.user_id == User.id)
        .where(HouseholdMember.household_id == household_id, HouseholdMember.role == HouseholdRole.owner)
        .order_by(HouseholdMember.created_at).limit(1)
    )).scalar_one_or_none()


# ── Draf ───────────────────────────────────────────────────────────────────
async def draf_dari_ref(db: AsyncSession, user_id, client_ref: str | None) -> RuangDraf | None:
    if not client_ref:
        return None
    return (await db.execute(
        select(RuangDraf).where(RuangDraf.user_id == user_id, RuangDraf.client_ref == client_ref)
    )).scalar_one_or_none()


async def buat_draf(db: AsyncSession, *, household_id, user_id, jenis: str, amount: Decimal, description: str,
                    envelope_id=None, tanggal=None, source: str = "webapp", is_private: bool = False,
                    receipt_item_id=None, client_ref: str | None = None, rincian: dict | None = None) -> RuangDraf:
    """Simpan draf (idempoten per `client_ref`: kiriman ulang mendapat draf yang sama)."""
    lama = await draf_dari_ref(db, user_id, client_ref)
    if lama is not None:
        return lama
    draf = RuangDraf(
        household_id=household_id, user_id=user_id, jenis=jenis, envelope_id=envelope_id, amount=amount,
        description=description[:500], tanggal=tanggal, source=source, is_private=is_private,
        receipt_item_id=receipt_item_id, client_ref=client_ref, rincian=rincian or {}, status=ST_MENUNGGU,
    )
    db.add(draf)
    try:
        await db.commit()
    except IntegrityError:   # kiriman ulang yang balapan dengan yang pertama
        await db.rollback()
        lama = await draf_dari_ref(db, user_id, client_ref)
        if lama is not None:
            return lama
        raise
    await db.refresh(draf)
    return draf


async def batalkan_draf_anggota(db: AsyncSession, household_id, user_id) -> int:
    """Anggota keluar/dikeluarkan: draf yang masih menunggu dibatalkan (dipanggil sebelum commit pemanggil)."""
    rows = (await db.execute(select(RuangDraf).where(
        RuangDraf.household_id == household_id, RuangDraf.user_id == user_id, RuangDraf.status == ST_MENUNGGU,
    ))).scalars().all()
    for d in rows:
        d.status = ST_DIBATALKAN
        d.diputus_at = datetime.now(timezone.utc)
    return len(rows)


# ── Audit ──────────────────────────────────────────────────────────────────
def audit(db: AsyncSession, household_id, actor_id, aksi: str, target_user_id=None, **rincian) -> None:
    """Tambah baris audit ke sesi pemanggil (ikut commit pemanggil)."""
    db.add(RuangAudit(household_id=household_id, actor_id=actor_id, aksi=aksi, target_user_id=target_user_id,
                      rincian={k: (str(v) if isinstance(v, (UUID, Decimal)) else v) for k, v in rincian.items()}))
