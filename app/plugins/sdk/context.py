"""`PluginContext`: satu-satunya pintu plugin ke data inti (Plugin H2; AGENTS.md "Plugin dan ruang" aturan 4).

Plugin diperlakukan sebagai tamu (01-kajian.md "Penegakan"):

- **Izin di setiap panggilan.** Setiap metode baca memeriksa izinnya terhadap irisan izin yang disetujui saat
  pasang (`plugin_installations.granted_permissions`), izin manifest versi sekarang, dan `izin=` fungsi yang
  sedang berjalan. Izin yang bertambah di manifest baru tidak terbuka sebelum disetujui ulang (pulihkan/pasang).
- **Ruang dari host.** `ruang_id` ditetapkan host saat membuat konteks (ruang yang memasang plugin, keanggotaan
  sudah diperiksa); tidak ada metode yang menerima ruang dari plugin.
- **Kontrak visibilitas.** Amplop pribadi anggota lain tidak pernah terbaca; deskripsi transaksi lewat
  `visibility.masked_description`. Konteks tanpa user (job) hanya melihat amplop bersama dan semua deskripsi
  transaksi tersamar (fail-closed). Di ruang keluarga plugin hanya membaca pemasukan milik viewer, seperti
  `GET /incomes/`; job tanpa user tidak membaca pemasukan ruang keluarga (review #186 temuan 2, review ulang no. 5).
  Di ruang usaha pemasukan adalah data usaha: owner, admin, dan job melihat semuanya.
- **Karyawan.** Di ruang usaha, peran `member` adalah karyawan (R5): data keuangan (amplop, transaksi, pemasukan)
  ditolak `khusus_admin` (ADR-P3), seperti tolak-bawaan R5 di route.
- **Audit.** Penolakan izin, setiap kiriman yang sampai (notifikasi), dan setiap tulisan inti (U2: pemasukan) dicatat di
  `plugin_audit_log` lewat sesi DB sendiri, supaya tetap tercatat walau permintaan pemanggil dibatalkan. Baca yang
  diizinkan tidak dicatat per panggilan (keputusan pemilik produk 4 Nov, H2). Penolakan yang sama dicatat sekali per
  jam per proses.
- **Keadaan di host.** Konteks tidak menyimpan sesi, ruang, peran, atau izin di dirinya (`app/plugins/host/keadaan.py`,
  review #186 temuan 3–4): plugin tidak bisa mengganti atau menyalinnya, dan `viewer` hanya `PenggunaView` beku, bukan
  objek ORM yang terikat sesi. Pemeriksaan izin adalah fungsi host, dan kelas `PluginContext` tidak bisa ditambal atau
  diturunkan (review ulang #186 temuan 1, 3); setiap metode membaca ruang, viewer, dan peran dari keadaan host.
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
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

from app.plugins.host import keadaan as _host
from app.plugins.sdk.plugin import _KelasBeku

log = logging.getLogger("jatahku.plugins")

PERAN_SISTEM = "sistem"          # job: tanpa user
BATAS_BARIS = 1000               # baris maksimal per panggilan baca
MAKS_NOTIFY_PER_KONTEKS = 10


class IzinDitolak(Exception):
    """Plugin memanggil sesuatu di luar izinnya. `alasan`: `tanpa_izin` | `khusus_admin` | `jenis_tidak_dikenal` |
    `bukan_job` | `bukan_user` | `batas_notify`."""

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
    sisa: Decimal | None = None   # U4: sisa periode berjalan (rumus saldo inti), hanya dari `envelopes(saldo=True)`


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
    meta: dict | None = None      # U3: baris tabel pendamping plugin (`pendamping=`), None bila tidak ada/tersamar


@dataclass(frozen=True)
class PemasukanView:
    id: UUID
    user_id: UUID
    jumlah: Decimal
    deskripsi: str
    tanggal: date
    jenis: str                    # incomes.kind (mis. "prive")
    meta: dict | None = None      # U3: baris tabel pendamping plugin (`pendamping=`), None bila tidak ada


@dataclass(frozen=True)
class RingkasanView:
    """Satu kelompok `ctx.ringkas_transaksi` / `ctx.ringkas_pemasukan` (U3): nilai kelompok sesuai urutan `per`,
    jumlah nominal, banyak catatan, dan (pemasukan) jumlah alokasinya."""
    kunci: tuple
    jumlah: Decimal
    banyak: int
    dialokasikan: Decimal = Decimal("0")


@dataclass(frozen=True)
class AnggotaView:
    user_id: UUID
    nama: str
    peran: str                    # owner | admin | member


@dataclass(frozen=True)
class PeriodeView:
    """Periode yang diminta kartu Beranda (salinan beku; review ulang #186 no. 4)."""
    start: date
    end: date
    berjalan: bool


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
class Permintaan:
    """Masukan fungsi `rute` (endpoint plugin, U1): bagian path sesudah pola, query, dan body JSON (dict atau None).
    Ruang, user, dan peran ada di konteks; `ruang_id` di body/query tidak pernah dipakai (aturan 1)."""
    metode: str
    path: dict[str, str]
    query: dict[str, str]
    body: Any


@dataclass(frozen=True)
class Jawaban:
    """Keluaran fungsi `rute` bila status atau header perlu diatur; selain itu fungsi cukup mengembalikan data JSON."""
    data: Any
    status: int = 200


@dataclass(frozen=True)
class TabelLaporan:
    """Satu tabel di `Laporan` (U3). Sel: teks, `Decimal` (rupiah), `int` (banyak), `date`, atau None (kosong).
    `total` = baris penutup bercetak tebal (opsional)."""
    judul: str
    kolom: tuple
    baris: tuple = ()
    total: tuple | None = None
    catatan: str = ""


@dataclass(frozen=True)
class Laporan:
    """Keluaran `rute` GET berupa berkas unduhan (U3). Plugin hanya memberi isi; host menggambarnya menjadi PDF (teks
    PDF lewat fpdf2, bukan HTML) atau CSV (anti formula-injection, PR #136) dan mengirimnya sebagai lampiran
    (`app/plugins/host/berkas.py`). `nama_berkas` tanpa ekstensi; host merapikannya dan menambah awalan `jatahku-`.
    `ringkasan` = pasangan (label, nilai) di kepala laporan; nilai berupa sel seperti di `TabelLaporan`."""
    format: str                   # "pdf" | "csv"
    nama_berkas: str
    judul: str
    subjudul: str = ""
    ringkasan: tuple = ()
    tabel: tuple = ()
    catatan: tuple = ()


class GalatRute(Exception):
    """Fungsi `rute` menolak permintaan dengan `kode` mesin dan `detail` siap tampil (04-kontrak-api.md aturan 6)."""

    def __init__(self, status: int, kode: str, detail: str):
        super().__init__(f"{status} {kode}: {detail}")
        self.status, self.kode, self.detail = status, kode, detail


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


def _uid(k) -> UUID | None:
    return k.viewer.id if k.viewer is not None else None


def _amplop_terlihat(k, Envelope):
    """Amplop bersama, plus amplop pribadi milik viewer (bila ada viewer)."""
    uid = _uid(k)
    if uid is None:
        return Envelope.owner_id.is_(None)
    return or_(Envelope.owner_id.is_(None), Envelope.owner_id == uid)


def _pemasukan_terlihat(k, Income):
    """Ruang usaha: semua (data usaha; karyawan sudah ditolak). Ruang keluarga: hanya milik viewer; tanpa viewer: tidak ada."""
    if k.jenis_ruang == "usaha":
        return Income.household_id == k.ruang_id
    uid = _uid(k)
    if uid is None:
        return Income.id.is_(None)
    return Income.user_id == uid


def _pemasukan(i, meta: dict | None = None) -> PemasukanView:
    return PemasukanView(id=i.id, user_id=i.user_id, jumlah=Decimal(i.amount), deskripsi=i.description,
                         tanggal=i.income_date, jenis=i.kind or "", meta=meta)


class PluginContext(metaclass=_KelasBeku):
    """Dibuat host (`app/plugins/host/titik.py` lewat `keadaan.buat`) untuk satu panggilan fungsi plugin; plugin tidak
    membuatnya. Semua keadaan ada di host: atribut di bawah hanya-baca, objek dan kelasnya tidak bisa disalin, diubah,
    atau diturunkan."""
    __slots__ = ("__weakref__",)

    def __init_subclass__(cls, **kw):
        raise TypeError("PluginContext tidak bisa diturunkan")

    def __init__(self, *a, **kw):
        raise TypeError("PluginContext hanya dibuat host")

    def __setattr__(self, nama, nilai):
        raise AttributeError("PluginContext hanya-baca")

    def __delattr__(self, nama):
        raise AttributeError("PluginContext hanya-baca")

    def __reduce__(self):
        raise TypeError("PluginContext tidak bisa disalin")

    __copy__ = __deepcopy__ = __reduce__

    # ── identitas (hanya-baca, dari keadaan host) ──
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
        return _uid(_k(self))

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
        return _host.karyawan(_k(self))

    @property
    def admin(self) -> bool:
        return _k(self).peran in ("owner", "admin")

    def settings(self) -> dict:
        return dict(_k(self).pengaturan)

    # ── data plugin sendiri (U1) ──
    def data(self, entitas: str) -> "DataPlugin":
        """Tabel plugin ini (`p_<id>_<entitas>`, manifest `entities`): selalu ruang konteks ini. Tulis hanya dari
        fungsi `rute` non-GET; karyawan tidak membaca. Kolom `id`, `household_id`, `created_by`, waktu, dan
        `deleted_at` milik host (`app/plugins/host/data.py`)."""
        return DataPlugin(self, entitas)

    # ── baca ──
    async def envelopes(self, *, saldo: bool = False) -> list[AmplopView]:
        """`envelopes:read`: amplop aktif ruang ini yang boleh dilihat viewer.

        U4: `saldo=True` mengisi `sisa` = sisa amplop di periode berjalan ruang ini, dari rumus saldo inti
        (`envelope_balance.py`: alokasi + rollover − terpakai), sama dengan halaman Amplop."""
        k = _k(self)
        await _host.perlu(k, "envelopes:read")
        from app.models.models import Envelope
        rows = (await k.db.execute(
            select(Envelope).where(Envelope.household_id == k.ruang_id, Envelope.is_active.is_(True),
                                   _amplop_terlihat(k, Envelope))
            .order_by(Envelope.name).limit(BATAS_BARIS)
        )).scalars().all()
        sisa = await _host.saldo_amplop(k) if saldo else {}
        return [AmplopView(id=e.id, nama=e.name, emoji=e.emoji or "",
                           tujuan=str(getattr(e.purpose, "value", e.purpose) or "expense"),
                           anggaran=Decimal(e.budget_amount or 0), pribadi=e.owner_id is not None,
                           dikunci=bool(e.is_locked), sisa=sisa.get(e.id)) for e in rows]

    async def transactions(self, mulai: date, akhir: date, *, amplop_id: UUID | None = None,
                           pendamping: str | None = None, hanya_bersama: bool = False) -> list[TransaksiView]:
        """`transactions:read`: transaksi (tidak terhapus) di amplop yang boleh dilihat, `mulai` ≤ tanggal ≤ `akhir`,
        terbaru dulu, paling banyak `BATAS_BARIS`. Deskripsi privat anggota lain tersamar; agregat (nominal) tetap utuh
        (kontrak visibilitas). Untuk angka pakai `ringkas_transaksi` (tidak terpotong).

        U3: `pendamping` = entitas plugin ini yang 1:1 dengan transaksi (mis. "txn_meta"): barisnya (tanpa kolom host)
        di `meta`; None bila tidak ada atau deskripsinya tersamar. `hanya_bersama` = amplop bersama saja."""
        k = _k(self)
        await _host.perlu(k, "transactions:read")
        from app.models.models import Envelope, Transaction
        from app.services.visibility import masked_description
        uid = _uid(k)
        terlihat = Envelope.owner_id.is_(None) if hanya_bersama else _amplop_terlihat(k, Envelope)
        q = (select(Transaction).join(Envelope, Envelope.id == Transaction.envelope_id)
             .where(Envelope.household_id == k.ruang_id, terlihat,
                    Transaction.is_deleted.is_(False),
                    Transaction.transaction_date >= mulai, Transaction.transaction_date <= akhir))
        if amplop_id is not None:
            q = q.where(Transaction.envelope_id == amplop_id)
        from app.plugins.host import ringkas
        q, ambil_meta = ringkas.gabung_pendamping(k, q, pendamping, "transactions", Transaction.id)
        rows = (await k.db.execute(
            q.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).limit(BATAS_BARIS)
        )).all()
        return [TransaksiView(id=t.id, amplop_id=t.envelope_id, user_id=t.user_id, jumlah=Decimal(t.amount),
                              deskripsi=masked_description(uid, t), tanggal=t.transaction_date,
                              sumber=str(getattr(t.source, "value", t.source)),
                              milik_sendiri=uid is not None and str(t.user_id) == str(uid),
                              meta=None if ringkas.privat_orang_lain(uid, t) else ambil_meta(r))
                for r in rows for t in (r[0],)]

    async def incomes(self, mulai: date, akhir: date, *, pendamping: str | None = None) -> list[PemasukanView]:
        """`incomes:read`: pemasukan ruang ini, `mulai` ≤ tanggal ≤ `akhir`, terbaru dulu, paling banyak `BATAS_BARIS`.
        Di ruang keluarga hanya milik viewer. U3: `pendamping` = entitas plugin ini yang 1:1 dengan pemasukan (mis.
        "income_meta"), barisnya di `meta`."""
        k = _k(self)
        await _host.perlu(k, "incomes:read")
        from app.models.models import Income
        from app.plugins.host import ringkas
        q = select(Income).where(Income.household_id == k.ruang_id, _pemasukan_terlihat(k, Income),
                                 Income.income_date >= mulai, Income.income_date <= akhir)
        q, ambil_meta = ringkas.gabung_pendamping(k, q, pendamping, "incomes", Income.id)
        rows = (await k.db.execute(
            q.order_by(Income.income_date.desc(), Income.created_at.desc()).limit(BATAS_BARIS)
        )).all()
        return [_pemasukan(r[0], ambil_meta(r)) for r in rows]

    async def ringkas_transaksi(self, mulai: date, akhir: date, *, per=(),
                                hanya_bersama: bool = False) -> list[RingkasanView]:
        """`transactions:read` (U3): jumlah dan banyak transaksi per kelompok, dihitung database (tidak terpotong).
        `per`: "bulan", "amplop", atau "<entitas pendamping>.<kolom>" (mis. "txn_meta.akun"), paling banyak 3.
        Kelompok pendamping transaksi yang tersamar bagi viewer bernilai None. Lihat `app/plugins/host/ringkas.py`."""
        k = _k(self)
        await _host.perlu(k, "transactions:read")
        from app.plugins.host import ringkas
        return await ringkas.ringkas_transaksi(k, mulai, akhir, per=per, hanya_bersama=hanya_bersama)

    async def ringkas_pemasukan(self, mulai: date, akhir: date, *, per=()) -> list[RingkasanView]:
        """`incomes:read` (U3): jumlah, banyak, dan jumlah alokasi pemasukan per kelompok. `per`: "bulan", "jenis"
        (`incomes.kind`), atau "<entitas pendamping>.<kolom>" (mis. "income_meta.jenis"), paling banyak 3."""
        k = _k(self)
        await _host.perlu(k, "incomes:read")
        from app.plugins.host import ringkas
        return await ringkas.ringkas_pemasukan(k, mulai, akhir, per=per)

    async def ringkas_pemasukan_saya(self, mulai: date, akhir: date, *, per=()) -> list[RingkasanView]:
        """`incomes:read` (U4): seperti `ringkas_pemasukan`, tetapi hanya pemasukan yang dicatat **viewer sendiri** di
        ruang ini. Satu-satunya baca keuangan yang terbuka untuk karyawan (kartu `untuk: "karyawan"`): ia hanya
        melihat catatannya sendiri, tidak pernah angka ruang. Konteks tanpa user (job) ditolak `bukan_user`."""
        k = _k(self)
        await _host.perlu(k, "incomes:read", milik_sendiri=True)
        from app.plugins.host import ringkas
        return await ringkas.ringkas_pemasukan(k, mulai, akhir, per=per, milik=k.viewer.id)

    async def income(self, income_id: UUID) -> PemasukanView | None:
        """`incomes:read`: satu pemasukan yang boleh dilihat; None bila tidak ada, milik ruang lain, atau (di ruang
        keluarga) milik anggota lain — ketiganya tidak dibedakan."""
        k = _k(self)
        await _host.perlu(k, "incomes:read")
        from app.models.models import Income
        i = (await k.db.execute(
            select(Income).where(Income.id == income_id, Income.household_id == k.ruang_id,
                                 _pemasukan_terlihat(k, Income))
        )).scalar_one_or_none()
        return _pemasukan(i) if i is not None else None

    async def members(self) -> list[AnggotaView]:
        """`members:read`: nama dan peran anggota ruang ini."""
        k = _k(self)
        await _host.perlu(k, "members:read")
        from app.models.models import HouseholdMember, User
        rows = (await k.db.execute(
            select(HouseholdMember.user_id, User.name, HouseholdMember.role)
            .join(User, User.id == HouseholdMember.user_id)
            .where(HouseholdMember.household_id == k.ruang_id).order_by(User.name)
        )).all()
        return [AnggotaView(user_id=uid, nama=nama or "", peran=str(getattr(r, "value", r))) for uid, nama, r in rows]

    # ── tulis inti (U2) ──
    async def catat_pemasukan(self, *, jumlah: Decimal, keterangan: str, tanggal: date | None = None,
                              pembagian: list[tuple[UUID, Decimal]], client_ref: str | None = None) -> dict:
        """`incomes:write`, hanya dari `rute` non-GET oleh owner/admin: satu pemasukan di ruang ini lewat jalur
        pemasukan inti, dibagi persis ke `pembagian` [(envelope_id, jumlah)] (total harus sama dengan `jumlah`; amplop
        harus amplop aktif ruang ini yang terlihat viewer). Masuk dalam commit yang sama dengan tulisan `ctx.data()`
        di rute itu. `tanggal` None = hari ini; tidak boleh sesudah hari ini atau lebih dari setahun ke belakang.
        Mengembalikan `{"income_id", "jumlah", "tanggal", "pembagian": [{"envelope_id", "nama", "jumlah"}],
        "ulang"}`; isian salah → `NilaiTidakSah`. `client_ref` (1–64 huruf, angka, `_.:-`) = kunci kirim ulang dari
        klien: bila sudah tercatat, pemasukan lama dikembalikan dengan `ulang: True` dan plugin tidak boleh menulis
        datanya lagi; bila masih diproses → 409 `sedang_diproses`."""
        from app.plugins.host import inti
        return await inti.catat_pemasukan(self, jumlah=jumlah, keterangan=keterangan, tanggal=tanggal,
                                          pembagian=pembagian, client_ref=client_ref)

    # ── kirim ──
    async def notify(self, jenis: str, judul: str, isi: str, *, link: str | None = None,
                     kunci: str | None = None) -> int:
        """`notifications:send`, hanya dari job: notifikasi untuk owner/admin ruang ini, lewat penyaring jam tenang dan
        batas harian per plugin (seperti `proaktif.py`). Judul diawali nama ruang; `link` hanya ke `/p/<id>…`. `kunci`
        mencegah kiriman ganda hari itu (bawaan: `jenis`). Mengembalikan jumlah penerima yang terkirim."""
        k = _k(self)
        await _host.perlu(k, "notifications:send")
        if k.viewer is not None:
            await _host.tolak(k, "notifications:send", "bukan_job")
        if jenis not in k.jenis_notifikasi:
            await _host.tolak(k, f"notif:{jenis}"[:40], "jenis_tidak_dikenal")
        if k.penghitung["notify"] >= MAKS_NOTIFY_PER_KONTEKS:
            await _host.tolak(k, "notifications:send", "batas_notify")
        k.penghitung["notify"] += 1
        from app.plugins.host import titik
        return await titik.kirim_notifikasi(self, jenis, judul, isi, link=link, kunci=kunci or jenis, now=k.sekarang)


class DataPlugin(metaclass=_KelasBeku):
    """Pegangan satu tabel plugin untuk satu panggilan (`ctx.data("kontak")`). Tidak menyimpan apa pun selain konteks
    dan nama entitas; setiap metode membaca keadaan host lagi (konteks yang sudah ditutup gagal)."""
    __slots__ = ("_ctx", "_entitas")

    def __init_subclass__(cls, **kw):
        raise TypeError("DataPlugin tidak bisa diturunkan")

    def __init__(self, ctx: PluginContext, entitas: str):
        object.__setattr__(self, "_ctx", ctx)
        object.__setattr__(self, "_entitas", entitas)

    def __setattr__(self, nama, nilai):
        raise AttributeError("DataPlugin hanya-baca")

    def __reduce__(self):
        raise TypeError("DataPlugin tidak bisa disalin")

    __copy__ = __deepcopy__ = __reduce__

    async def cari(self, *, saring: dict | None = None, teks: str | None = None, kolom_teks=(), urut=(),
                   batas: int = 200) -> list[dict]:
        """Baris hidup ruang ini: `saring` = kolom → nilai (persis), `teks` dicari di `kolom_teks` (tanpa peka huruf),
        `urut` = nama kolom (awalan `-` = menurun), `batas` ≤ 1000."""
        from app.plugins.host import data
        return await data.cari(_k(self._ctx), self._entitas, saring=saring, teks=teks, kolom_teks=kolom_teks,
                               urut=urut, batas=batas)

    async def ambil(self, id_baris) -> dict | None:
        """Satu baris hidup ruang ini, atau None (tidak ada, terhapus, atau milik ruang lain — tidak dibedakan)."""
        from app.plugins.host import data
        return await data.ambil(_k(self._ctx), self._entitas, id_baris)

    async def hitung(self, *, saring: dict | None = None) -> int:
        from app.plugins.host import data
        return await data.hitung(_k(self._ctx), self._entitas, saring=saring)

    async def tambah(self, nilai: dict) -> dict:
        """Baris baru (`created_by` = user pemicu). Nilai salah → `NilaiTidakSah` (422 di endpoint)."""
        from app.plugins.host import data
        return await data.tambah(_k(self._ctx), self._entitas, nilai)

    async def ubah(self, id_baris, nilai: dict) -> dict | None:
        from app.plugins.host import data
        return await data.ubah(_k(self._ctx), self._entitas, id_baris, nilai)

    async def hapus(self, id_baris) -> bool:
        """Hapus lunak; False bila baris tidak ada di ruang ini."""
        from app.plugins.host import data
        return await data.hapus(_k(self._ctx), self._entitas, id_baris)
