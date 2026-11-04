"""`PluginContext`: satu-satunya pintu plugin ke data inti (Plugin H2; AGENTS.md "Plugin dan ruang" aturan 4).

Plugin diperlakukan sebagai tamu (01-kajian.md "Penegakan"):

- **Izin di setiap panggilan.** Setiap metode baca memeriksa izinnya terhadap irisan izin yang disetujui saat
  pasang (`plugin_installations.granted_permissions`), izin manifest versi sekarang, dan `izin=` fungsi yang
  sedang berjalan. Izin yang bertambah di manifest baru tidak terbuka sebelum disetujui ulang (pulihkan/pasang).
- **Ruang dari host.** `ruang_id` ditetapkan host saat membuat konteks (ruang yang memasang plugin, keanggotaan
  sudah diperiksa); tidak ada metode yang menerima ruang dari plugin.
- **Kontrak visibilitas.** Amplop pribadi anggota lain tidak pernah terbaca; deskripsi transaksi lewat
  `visibility.masked_description`. Konteks tanpa user (job) hanya melihat amplop bersama dan semua deskripsi
  transaksi tersamar (fail-closed). Pemasukan anggota lain di ruang keluarga tersamar (keterangan dan pencatat),
  seperti inti yang hanya menampilkan pemasukan milik sendiri; nominalnya tetap ikut agregat (review #186 temuan 2).
  Di ruang usaha pemasukan adalah data usaha: owner, admin, dan job melihat semuanya.
- **Karyawan.** Di ruang usaha, peran `member` adalah karyawan (R5): data keuangan (amplop, transaksi, pemasukan)
  ditolak `khusus_admin` (ADR-P3), seperti tolak-bawaan R5 di route.
- **Audit.** Penolakan izin dan setiap kiriman yang sampai (notifikasi; tulis menyusul U2) dicatat di
  `plugin_audit_log` lewat sesi DB sendiri, supaya tetap tercatat walau permintaan pemanggil dibatalkan. Baca yang
  diizinkan tidak dicatat per panggilan (keputusan pemilik produk 4 Nov, H2). Penolakan yang sama dicatat sekali per
  jam per proses.
- **Keadaan di host.** Konteks tidak menyimpan sesi, ruang, peran, atau izin di dirinya (`app/plugins/host/keadaan.py`,
  review #186 temuan 3–4): plugin tidak bisa mengganti atau menyalinnya, dan `viewer` hanya `PenggunaView` beku, bukan
  objek ORM yang terikat sesi.
- **Kirim hanya dari job.** `notify` hanya untuk konteks tanpa user (job): konteks yang dipicu seorang user (kartu,
  cek, saran, perintah bot, field) bisa melihat data pribadinya, yang tidak boleh diteruskan ke anggota lain
  (review #186 temuan 1). Maksimal `MAKS_NOTIFY_PER_KONTEKS` panggilan per konteks.

Nominal berupa `Decimal`, tidak pernah float.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select

from app.plugins.host import keadaan as _host

log = logging.getLogger("jatahku.plugins")

PERAN_SISTEM = "sistem"          # job: tanpa user
IZIN_KEUANGAN = ("envelopes:read", "transactions:read", "incomes:read")
BATAS_BARIS = 1000               # baris maksimal per panggilan baca
MAKS_NOTIFY_PER_KONTEKS = 10
PEMASUKAN_PRIVAT = "Pemasukan anggota lain"


class IzinDitolak(Exception):
    """Plugin memanggil sesuatu di luar izinnya. `alasan`: `tanpa_izin` | `khusus_admin` | `jenis_tidak_dikenal` |
    `bukan_job` | `batas_notify`."""

    def __init__(self, izin: str, alasan: str = "tanpa_izin"):
        super().__init__(f"{izin}: {alasan}")
        self.izin, self.alasan = izin, alasan


class NilaiTidakSah(ValueError):
    """Dilempar fungsi `field_form` plugin; pesannya tampil ke user."""


# ── bentuk data untuk plugin ─────────────────────────────────────────────
@dataclass(frozen=True)
class PenggunaView:
    """User yang memicu panggilan (tanpa email, telegram, atau data akun lain)."""
    id: UUID
    nama: str
    zona_waktu: str


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
    user_id: UUID | None          # None = pemasukan anggota lain di ruang keluarga (tersamar)
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


def _k(ctx) -> "_host.Keadaan":
    """Keadaan host untuk konteks ini (bukan atribut konteks, supaya tidak terjangkau dari kode plugin)."""
    return _host.ambil(ctx)


class PluginContext:
    """Dibuat host (`app/plugins/host/titik.py` lewat `keadaan.buat`) untuk satu panggilan fungsi plugin; plugin tidak
    membuatnya. Semua keadaan ada di host: atribut di bawah hanya-baca, objek ini tidak bisa disalin atau diubah."""
    __slots__ = ("__weakref__",)

    def __init__(self, *a, **kw):
        raise TypeError("PluginContext hanya dibuat host")

    def __setattr__(self, nama, nilai):
        raise AttributeError("PluginContext hanya-baca")

    def __reduce__(self):
        raise TypeError("PluginContext tidak bisa disalin")

    __copy__ = __deepcopy__ = __reduce__

    # ── identitas ──
    @property
    def plugin_id(self) -> str:
        return _k(self).plugin_id

    @property
    def nama_plugin(self) -> str:
        return _k(self).nama_plugin

    @property
    def ruang_id(self) -> UUID:
        return _k(self).ruang_id

    @property
    def nama_ruang(self) -> str:
        return _k(self).nama_ruang

    @property
    def jenis_ruang(self) -> str:
        return _k(self).jenis_ruang

    @property
    def viewer(self) -> PenggunaView | None:
        return _k(self).viewer

    @property
    def user_id(self) -> UUID | None:
        return _k(self).viewer.id if _k(self).viewer is not None else None

    @property
    def peran(self) -> str:
        return _k(self).peran

    @property
    def izin(self) -> frozenset[str]:
        return _k(self).izin

    @property
    def sumber(self) -> str:
        return _k(self).sumber

    @property
    def karyawan(self) -> bool:
        return self.jenis_ruang == "usaha" and self.peran == "member"

    @property
    def admin(self) -> bool:
        return self.peran in ("owner", "admin")

    def settings(self) -> dict:
        return dict(_k(self).pengaturan)

    # ── izin ──
    async def _tolak(self, izin: str, alasan: str) -> None:
        k = _k(self)
        if _host.tolak_perlu_dicatat((k.ruang_id, k.plugin_id, izin, alasan, k.sumber)):
            await _host.catat_audit(k.ruang_id, k.plugin_id, self.user_id, f"tolak:{izin}",
                                    alasan=alasan, sumber=k.sumber)
        log.warning("plugin %s ditolak %s (%s) di %s", k.plugin_id, izin, alasan, k.sumber)
        raise IzinDitolak(izin, alasan)

    async def _perlu(self, izin: str) -> None:
        if izin not in _k(self).izin:
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
        rows = (await _k(self).db.execute(
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
        rows = (await _k(self).db.execute(
            q.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).limit(BATAS_BARIS)
        )).scalars().all()
        return [TransaksiView(id=t.id, amplop_id=t.envelope_id, user_id=t.user_id, jumlah=Decimal(t.amount),
                              deskripsi=masked_description(self.user_id, t), tanggal=t.transaction_date,
                              sumber=str(getattr(t.source, "value", t.source)),
                              milik_sendiri=self.user_id is not None and str(t.user_id) == str(self.user_id))
                for t in rows]

    async def incomes(self, mulai: date, akhir: date) -> list[PemasukanView]:
        """`incomes:read`: pemasukan ruang ini, `mulai` ≤ tanggal ≤ `akhir`. Di ruang keluarga, pemasukan anggota lain
        tersamar (keterangan dan pencatat); nominal tetap ada untuk agregat."""
        await self._perlu("incomes:read")
        from app.models.models import Income
        rows = (await _k(self).db.execute(
            select(Income).where(Income.household_id == self.ruang_id,
                                 Income.income_date >= mulai, Income.income_date <= akhir)
            .order_by(Income.income_date.desc(), Income.created_at.desc()).limit(BATAS_BARIS)
        )).scalars().all()
        return [self._pemasukan(i) for i in rows]

    async def income(self, income_id: UUID) -> PemasukanView | None:
        """`incomes:read`: satu pemasukan; None bila tidak ada atau milik ruang lain (tidak membedakan keduanya)."""
        await self._perlu("incomes:read")
        from app.models.models import Income
        i = (await _k(self).db.execute(
            select(Income).where(Income.id == income_id, Income.household_id == self.ruang_id)
        )).scalar_one_or_none()
        return self._pemasukan(i) if i is not None else None

    def _pemasukan(self, i) -> PemasukanView:
        utuh = self.jenis_ruang == "usaha" or (self.user_id is not None and str(i.user_id) == str(self.user_id))
        return PemasukanView(id=i.id, user_id=i.user_id if utuh else None, jumlah=Decimal(i.amount),
                             deskripsi=i.description if utuh else PEMASUKAN_PRIVAT, tanggal=i.income_date,
                             jenis=i.kind or "")

    async def members(self) -> list[AnggotaView]:
        """`members:read`: nama dan peran anggota ruang ini."""
        await self._perlu("members:read")
        from app.models.models import HouseholdMember, User
        rows = (await _k(self).db.execute(
            select(HouseholdMember.user_id, User.name, HouseholdMember.role)
            .join(User, User.id == HouseholdMember.user_id)
            .where(HouseholdMember.household_id == self.ruang_id).order_by(User.name)
        )).all()
        return [AnggotaView(user_id=uid, nama=nama or "", peran=str(getattr(r, "value", r))) for uid, nama, r in rows]

    # ── kirim ──
    async def notify(self, jenis: str, judul: str, isi: str, *, link: str | None = None,
                     kunci: str | None = None) -> int:
        """`notifications:send`, hanya dari job: notifikasi untuk owner/admin ruang ini, lewat penyaring jam tenang dan
        batas harian per plugin (seperti `proaktif.py`). Judul diawali nama ruang; `link` hanya ke `/p/<id>…`. `kunci`
        mencegah kiriman ganda hari itu (bawaan: `jenis`). Mengembalikan jumlah penerima yang terkirim."""
        await self._perlu("notifications:send")
        k = _k(self)
        if k.viewer is not None:
            await self._tolak("notifications:send", "bukan_job")
        if jenis not in k.jenis_notifikasi:
            await self._tolak(f"notif:{jenis}"[:40], "jenis_tidak_dikenal")
        if k.notify_dipakai >= MAKS_NOTIFY_PER_KONTEKS:
            await self._tolak("notifications:send", "batas_notify")
        k.notify_dipakai += 1
        from app.plugins.host import titik
        return await titik.kirim_notifikasi(self, jenis, judul, isi, link=link, kunci=kunci or jenis)
