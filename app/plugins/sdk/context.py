"""`PluginContext`: satu-satunya pintu plugin ke data inti (Plugin H2; AGENTS.md "Plugin dan ruang" aturan 4).

Plugin diperlakukan sebagai tamu (01-kajian.md "Penegakan"):

- **Izin di setiap panggilan.** Setiap metode baca memeriksa izinnya terhadap irisan izin yang disetujui saat
  pasang (`plugin_installations.granted_permissions`), izin manifest versi sekarang, dan `izin=` fungsi yang
  sedang berjalan. Izin yang bertambah di manifest baru tidak terbuka sebelum disetujui ulang (pulihkan/pasang).
- **Ruang dari host.** `ruang_id` ditetapkan host saat membuat konteks (ruang yang memasang plugin, keanggotaan
  sudah diperiksa); tidak ada metode yang menerima ruang dari plugin.
- **Kontrak visibilitas.** Amplop pribadi anggota lain tidak pernah terbaca; deskripsi transaksi lewat
  `visibility.masked_description`. Konteks tanpa user (job) hanya melihat amplop bersama dan semua deskripsi
  transaksi tersamar (fail-closed).
- **Karyawan.** Di ruang usaha, peran `member` adalah karyawan (R5): data keuangan (amplop, transaksi, pemasukan)
  ditolak `khusus_admin` (ADR-P3), seperti tolak-bawaan R5 di route.
- **Audit.** Penolakan izin dan setiap kiriman (notifikasi; tulis menyusul U2) dicatat di `plugin_audit_log` lewat
  sesi DB sendiri, supaya tetap tercatat walau permintaan pemanggil dibatalkan. Baca yang diizinkan tidak dicatat
  per panggilan (keputusan pemilik produk 4 Nov, H2). Penolakan yang sama dicatat sekali per jam per proses.

Nominal berupa `Decimal`, tidak pernah float.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

log = logging.getLogger("jatahku.plugins")

PERAN_SISTEM = "sistem"          # job: tanpa user
IZIN_KEUANGAN = ("envelopes:read", "transactions:read", "incomes:read")
BATAS_BARIS = 1000               # baris maksimal per panggilan baca


class IzinDitolak(Exception):
    """Plugin memanggil sesuatu di luar izinnya. `alasan`: `tanpa_izin` | `khusus_admin` | `jenis_tidak_dikenal`."""

    def __init__(self, izin: str, alasan: str = "tanpa_izin"):
        super().__init__(f"{izin}: {alasan}")
        self.izin, self.alasan = izin, alasan


class NilaiTidakSah(ValueError):
    """Dilempar fungsi `field_form` plugin; pesannya tampil ke user."""


# ── bentuk data untuk plugin ─────────────────────────────────────────────
@dataclass(frozen=True)
class AmplopView:
    id: UUID
    nama: str
    emoji: str
    tujuan: str                   # expense | saving | sinking_fund
    anggaran: Decimal
    pribadi: bool                 # amplop pribadi milik viewer
    dikunci: bool


@dataclass(frozen=True)
class TransaksiView:
    id: UUID
    amplop_id: UUID
    user_id: UUID
    jumlah: Decimal
    deskripsi: str                # sudah lewat masked_description
    tanggal: date
    sumber: str
    milik_sendiri: bool


@dataclass(frozen=True)
class PemasukanView:
    id: UUID
    user_id: UUID
    jumlah: Decimal
    deskripsi: str
    tanggal: date
    jenis: str                    # incomes.kind (mis. "prive")


@dataclass(frozen=True)
class AnggotaView:
    user_id: UUID
    nama: str
    peran: str                    # owner | admin | member


@dataclass(frozen=True)
class RencanaPengeluaran:
    """Masukan fungsi `cek`: pengeluaran yang akan dicatat (belum tersimpan)."""
    amplop_id: UUID
    jumlah: Decimal
    deskripsi: str


@dataclass(frozen=True)
class AksiRoute:
    """Tombol yang hanya membuka halaman plugin (`/p/<id>…`)."""
    label: str
    ke: str


@dataclass(frozen=True)
class Saran:
    """Keluaran aturan advisor plugin. Teks sudah dirakit dari templat plugin (aturan 7)."""
    entitas: str
    tone: str                     # danger | warn | info | ok
    judul: str
    isi: str
    chip: str = ""
    fakta: tuple[tuple[str, str], ...] = ()
    aksi: tuple[AksiRoute, ...] = ()
    rupiah: Decimal = Decimal("0")
    urgensi: Decimal = Decimal("0.2")
    keyakinan: str = "tinggi"


# ── sesi DB tambahan (audit, notifikasi, job) ────────────────────────────
_SESI = None


def sesi():
    """Pabrik sesi untuk tulisan host yang harus berdiri sendiri. Tes menggantinya lewat `pakai_sesi`."""
    if _SESI is not None:
        return _SESI()
    from app.core.database import AsyncSessionLocal
    return AsyncSessionLocal()


@contextmanager
def pakai_sesi(pabrik):
    global _SESI
    lama, _SESI = _SESI, pabrik
    try:
        yield
    finally:
        _SESI = lama


_TOLAK_TERCATAT: dict[tuple, float] = {}
_TOLAK_MAKS = 10_000


async def catat_audit(household_id, plugin_id: str, actor_id, aksi: str, **detail) -> None:
    """Satu baris `plugin_audit_log` lewat sesi sendiri. Gagal → log, tidak pernah melempar."""
    from app.models.models import PluginAuditLog
    try:
        async with sesi() as db:
            db.add(PluginAuditLog(household_id=household_id, plugin_id=plugin_id, actor_id=actor_id,
                                  action=aksi[:30], detail=detail))
            await db.commit()
    except Exception:
        log.exception("audit plugin %s %s gagal dicatat", plugin_id, aksi)


@dataclass(frozen=True)
class PluginContext:
    """Dibuat host (`app/plugins/host/titik.py`) untuk satu panggilan fungsi plugin. Plugin tidak membuatnya.
    Beku: plugin tidak bisa mengganti izin, ruang, atau perannya sendiri. Sesi DB privat (`_db`); tabel plugin sendiri
    dibuka lewat SDK bersama tabel pertamanya (U1), bukan lewat sesi ini."""
    _db: Any
    plugin_id: str
    nama_plugin: str
    ruang_id: UUID                                 # = household_id di database
    nama_ruang: str
    jenis_ruang: str
    viewer: Any = None                             # User, atau None untuk job
    peran: str = PERAN_SISTEM                      # owner | admin | member | sistem
    izin: frozenset[str] = frozenset()             # granted ∩ manifest ∩ izin fungsi
    jenis_notifikasi: frozenset[str] = frozenset()
    pengaturan: dict = field(default_factory=dict)
    sumber: str = ""                               # mis. "kartu:buku_usaha.omzet", "job:pengingat"

    # ── identitas ──
    @property
    def user_id(self) -> UUID | None:
        return getattr(self.viewer, "id", None)

    @property
    def karyawan(self) -> bool:
        return self.jenis_ruang == "usaha" and self.peran == "member"

    @property
    def admin(self) -> bool:
        return self.peran in ("owner", "admin")

    def settings(self) -> dict:
        return dict(self.pengaturan)

    # ── izin ──
    async def _tolak(self, izin: str, alasan: str) -> None:
        kunci = (self.ruang_id, self.plugin_id, izin, alasan, self.sumber)
        sekarang = time.monotonic()
        if len(_TOLAK_TERCATAT) > _TOLAK_MAKS:
            _TOLAK_TERCATAT.clear()
        if sekarang - _TOLAK_TERCATAT.get(kunci, -1e9) >= 3600:
            _TOLAK_TERCATAT[kunci] = sekarang
            await catat_audit(self.ruang_id, self.plugin_id, self.user_id, f"tolak:{izin}",
                              alasan=alasan, sumber=self.sumber)
        log.warning("plugin %s ditolak %s (%s) di %s", self.plugin_id, izin, alasan, self.sumber)
        raise IzinDitolak(izin, alasan)

    async def _perlu(self, izin: str) -> None:
        if izin not in self.izin:
            await self._tolak(izin, "tanpa_izin")
        if izin in IZIN_KEUANGAN and self.karyawan:
            await self._tolak(izin, "khusus_admin")

    def _amplop_terlihat(self, Envelope):
        """Amplop bersama, plus amplop pribadi milik viewer (bila ada viewer)."""
        if self.user_id is None:
            return Envelope.owner_id.is_(None)
        return or_(Envelope.owner_id.is_(None), Envelope.owner_id == self.user_id)

    # ── baca ──
    async def envelopes(self) -> list[AmplopView]:
        """`envelopes:read`: amplop aktif ruang ini yang boleh dilihat viewer."""
        await self._perlu("envelopes:read")
        from app.models.models import Envelope
        rows = (await self._db.execute(
            select(Envelope).where(Envelope.household_id == self.ruang_id, Envelope.is_active.is_(True),
                                   self._amplop_terlihat(Envelope))
            .order_by(Envelope.name).limit(BATAS_BARIS)
        )).scalars().all()
        return [AmplopView(id=e.id, nama=e.name, emoji=e.emoji or "",
                           tujuan=str(getattr(e.purpose, "value", e.purpose) or "expense"),
                           anggaran=Decimal(e.budget_amount or 0), pribadi=e.owner_id is not None,
                           dikunci=bool(e.is_locked)) for e in rows]

    async def transactions(self, mulai: date, akhir: date, *, amplop_id: UUID | None = None) -> list[TransaksiView]:
        """`transactions:read`: transaksi (tidak terhapus) di amplop yang boleh dilihat, `mulai` ≤ tanggal ≤ `akhir`.
        Deskripsi privat anggota lain tersamar; agregat (nominal) tetap utuh (kontrak visibilitas)."""
        await self._perlu("transactions:read")
        from app.models.models import Envelope, Transaction
        from app.services.visibility import masked_description
        q = (select(Transaction).join(Envelope, Envelope.id == Transaction.envelope_id)
             .where(Envelope.household_id == self.ruang_id, self._amplop_terlihat(Envelope),
                    Transaction.is_deleted.is_(False),
                    Transaction.transaction_date >= mulai, Transaction.transaction_date <= akhir))
        if amplop_id is not None:
            q = q.where(Transaction.envelope_id == amplop_id)
        rows = (await self._db.execute(
            q.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).limit(BATAS_BARIS)
        )).scalars().all()
        return [TransaksiView(id=t.id, amplop_id=t.envelope_id, user_id=t.user_id, jumlah=Decimal(t.amount),
                              deskripsi=masked_description(self.user_id, t), tanggal=t.transaction_date,
                              sumber=str(getattr(t.source, "value", t.source)),
                              milik_sendiri=self.user_id is not None and str(t.user_id) == str(self.user_id))
                for t in rows]

    async def incomes(self, mulai: date, akhir: date) -> list[PemasukanView]:
        """`incomes:read`: pemasukan ruang ini, `mulai` ≤ tanggal ≤ `akhir`."""
        await self._perlu("incomes:read")
        from app.models.models import Income
        rows = (await self._db.execute(
            select(Income).where(Income.household_id == self.ruang_id,
                                 Income.income_date >= mulai, Income.income_date <= akhir)
            .order_by(Income.income_date.desc(), Income.created_at.desc()).limit(BATAS_BARIS)
        )).scalars().all()
        return [self._pemasukan(i) for i in rows]

    async def income(self, income_id: UUID) -> PemasukanView | None:
        """`incomes:read`: satu pemasukan; None bila tidak ada atau milik ruang lain (tidak membedakan keduanya)."""
        await self._perlu("incomes:read")
        from app.models.models import Income
        i = (await self._db.execute(
            select(Income).where(Income.id == income_id, Income.household_id == self.ruang_id)
        )).scalar_one_or_none()
        return self._pemasukan(i) if i is not None else None

    @staticmethod
    def _pemasukan(i) -> PemasukanView:
        return PemasukanView(id=i.id, user_id=i.user_id, jumlah=Decimal(i.amount), deskripsi=i.description,
                             tanggal=i.income_date, jenis=i.kind or "")

    async def members(self) -> list[AnggotaView]:
        """`members:read`: nama dan peran anggota ruang ini."""
        await self._perlu("members:read")
        from app.models.models import HouseholdMember, User
        rows = (await self._db.execute(
            select(HouseholdMember.user_id, User.name, HouseholdMember.role)
            .join(User, User.id == HouseholdMember.user_id)
            .where(HouseholdMember.household_id == self.ruang_id).order_by(User.name)
        )).all()
        return [AnggotaView(user_id=uid, nama=nama or "", peran=str(getattr(r, "value", r))) for uid, nama, r in rows]

    # ── kirim ──
    async def notify(self, jenis: str, judul: str, isi: str, *, link: str | None = None,
                     kunci: str | None = None) -> int:
        """`notifications:send`: notifikasi untuk owner/admin ruang ini, lewat penyaring jam tenang dan batas harian
        per plugin (seperti `proaktif.py`). Judul diawali nama ruang; `link` hanya ke `/p/<id>…`. `kunci` mencegah
        kiriman ganda hari itu (bawaan: `jenis`). Mengembalikan jumlah penerima yang terkirim."""
        await self._perlu("notifications:send")
        if jenis not in self.jenis_notifikasi:
            await self._tolak(f"notif:{jenis}"[:40], "jenis_tidak_dikenal")
        from app.plugins.host import titik
        return await titik.kirim_notifikasi(self, jenis, judul, isi, link=link, kunci=kunci or jenis)
