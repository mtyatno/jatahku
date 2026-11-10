"""Data plugin di tabelnya sendiri (`p_<id>_*`) lewat `ctx.data("<entitas>")` (Plugin U1; AGENTS.md "Plugin dan ruang"
aturan 4–5, 01-kajian.md "Aturan wajib untuk setiap tabel plugin").

Plugin tidak mengimpor model atau SQLAlchemy (validator AST). Tabelnya dibuat migrasi seperti tabel inti dan dideklarasikan
di manifest (`entities`); semua baca-tulis lewat fungsi di modul ini, yang menegakkan:

- **Ruang dari host.** Setiap kueri disaring `household_id` = ruang konteks dan `deleted_at IS NULL`; baris ruang lain
  tidak pernah terbaca, terubah, atau terhapus walau plugin tahu ID-nya (sama dengan "tidak ada").
- **Hanya tabel sendiri.** Nama entitas harus ada di `entities` manifest plugin itu (awalan `p_<id>_`).
- **Kolom wajib milik host.** `id`, `household_id`, `created_by`, `created_at`, `updated_at`, `deleted_at` tidak bisa
  diisi plugin; `created_by` = user pemicu. Hapus = lunak (`deleted_at`); hapus permanen hanya oleh host (pembersih arsip
  90 hari, hapus ruang, hapus akun).
- **Rujukan diperiksa.** Nilai kolom ber-FK harus menunjuk baris di ruang yang sama (tabel plugin sendiri, amplop yang
  boleh dilihat viewer, pemasukan, transaksi, anggota ruang); selain itu `NilaiTidakSah` (422).
- **Tulis hanya dari endpoint plugin** (`rute` non-GET, dipicu owner/admin) dan diaudit di `plugin_audit_log` dalam
  transaksi database yang sama (tanpa nilai kolom). Kartu, cek, saran, perintah bot, field form, dan job hanya membaca.
- **Hapus lunak berbatas waktu.** Baris `deleted_at` dibuang permanen sesudah `HARI_SIMPAN_TERHAPUS` hari oleh
  `siklus.bersihkan_terhapus` (job tiap jam); batas baris per ruang menghitung baris terhapus juga, supaya tambah-hapus
  berulang tidak menumpuk data pribadi.
- **Karyawan tidak membaca data plugin** (`khusus_admin`), seperti data keuangan di `PluginContext` (ADR-P3): kontak
  pelanggan dan pemasok adalah data usaha.
"""
from __future__ import annotations

import re
import uuid as _uuid_mod
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, Integer, Numeric, String, Table, Uuid, delete, \
    func, insert, select, update

from app.core.database import Base
from app.plugins.host import keadaan

WAJIB = ("id", "household_id", "created_by", "created_at", "updated_at", "deleted_at")
TERSEMBUNYI = ("household_id", "deleted_at")          # tidak pernah dikembalikan ke plugin atau ekspor
FK_INTI = {"households", "users", "envelopes", "transactions", "incomes"}
BATAS_BARIS = 1000                                    # baris maksimal per panggilan baca
BATAS_BARIS_RUANG = 20_000                            # baris (termasuk yang dihapus lunak) maksimal per tabel per ruang
# Tabel pendamping 1:1 data inti (unik hidup per `transactions`/`incomes`, mis. `txn_meta`, `income_meta`) tidak kena
# batas per ruang: jumlah barisnya mengikuti data inti (yang punya kuota sendiri), dan menolaknya justru membatalkan
# pencatatan inti sesudah ±20.000 transaksi (review PR #201 temuan T1).
INDUK_PENDAMPING = {"transactions", "incomes"}
HARI_SIMPAN_TERHAPUS = 30                             # baris hapus lunak dibuang permanen sesudah ini (review #196 temuan 3)


def _tabel_ada(nama: str) -> Table | None:
    import app.models.models  # noqa: F401 — daftarkan tabel ke metadata
    return Base.metadata.tables.get(nama)


def pendamping_inti(t: Table) -> bool:
    """Tabel berisi paling banyak satu baris hidup per baris `transactions`/`incomes`: ada indeks unik (household_id,
    kolom FK ke tabel itu). Lihat `INDUK_PENDAMPING`."""
    for ix in t.indexes:
        if not ix.unique:
            continue
        kolom = [c for c in ix.columns if c.name != "household_id"]
        if len(kolom) == 1 and any(fk.column.table.name in INDUK_PENDAMPING for fk in kolom[0].foreign_keys):
            return True
    return False


# ── aturan tabel (dicek saat memuat manifest dan di tes) ─────────────────
def aturan_tabel(t: Table, plugin_id: str) -> list[str]:
    """Galat aturan 5 untuk satu tabel plugin (kosong = sah)."""
    galat = []
    n = t.name
    if not n.startswith(f"p_{plugin_id}_"):
        galat.append(f"{n}: harus berawalan p_{plugin_id}_")
    for k in WAJIB:
        if k not in t.c:
            galat.append(f"{n}: kolom wajib '{k}' tidak ada")
    if "household_id" in t.c:
        fk = [f for f in t.c.household_id.foreign_keys]
        if len(fk) != 1 or fk[0].column.table.name != "households" or fk[0].ondelete != "CASCADE":
            galat.append(f"{n}: household_id harus FK households ON DELETE CASCADE")
    if "created_by" in t.c:
        fk = [f for f in t.c.created_by.foreign_keys]
        if not t.c.created_by.nullable or len(fk) != 1 or fk[0].column.table.name != "users" \
                or fk[0].ondelete != "SET NULL":
            galat.append(f"{n}: created_by harus FK users ON DELETE SET NULL, boleh NULL")
    if [c.name for c in t.primary_key.columns] != ["id"]:
        galat.append(f"{n}: kunci utama harus 'id'")
    for ix in t.indexes:
        kolom = [c.name for c in ix.columns]
        if not kolom or kolom[0] != "household_id":
            galat.append(f"{n}: indeks {ix.name} harus diawali household_id")
    for uc in t.constraints:
        if uc.__class__.__name__ == "UniqueConstraint":
            kolom = [c.name for c in uc.columns]
            if not kolom or kolom[0] != "household_id":
                galat.append(f"{n}: unik {uc.name} harus diawali household_id")
    for c in t.c:
        if isinstance(c.type, SAEnum):
            galat.append(f"{n}.{c.name}: enum memakai String, bukan SAEnum")
        for fk in c.foreign_keys:
            tujuan = fk.column.table.name
            if tujuan not in FK_INTI and not tujuan.startswith(f"p_{plugin_id}_"):
                galat.append(f"{n}.{c.name}: FK ke '{tujuan}' tidak boleh (hanya inti {sorted(FK_INTI)} atau tabel "
                             f"plugin sendiri)")
            if c.name not in ("household_id", "created_by") and tujuan in ("households", "users") and \
                    fk.ondelete not in ("SET NULL", "CASCADE"):
                galat.append(f"{n}.{c.name}: FK ke {tujuan} butuh ON DELETE SET NULL/CASCADE")
    return galat


def periksa_entitas(m) -> list[str]:
    """Setiap `entities` manifest ada di metadata model dan memenuhi aturan tabel plugin."""
    galat = []
    for nama in m.entities:
        t = _tabel_ada(nama)
        if t is None:
            galat.append(f"entitas '{nama}' tidak ada di app/models (tabel plugin dibuat migrasi, bukan saat pasang)")
            continue
        galat.extend(aturan_tabel(t, m.id))
    return galat


# ── nilai ────────────────────────────────────────────────────────────────
class _Galat:
    """Pembuat exception SDK (impor lambat: SDK mengimpor host)."""

    @staticmethod
    def nilai(pesan: str):
        from app.plugins.sdk.context import NilaiTidakSah
        return NilaiTidakSah(pesan)


def _tabel(k: keadaan.Keadaan, nama: str) -> Table:
    """Entitas plugin konteks ini. Nama pendek (`kontak`) atau penuh (`p_buku_usaha_kontak`)."""
    if not isinstance(nama, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", nama):
        raise ValueError(f"nama entitas '{nama}' tidak sah")
    penuh = nama if nama.startswith("p_") else f"p_{k.plugin_id}_{nama}"
    if penuh not in k.entitas:
        raise ValueError(f"entitas '{penuh}' bukan milik plugin {k.plugin_id} (manifest entities)")
    t = _tabel_ada(penuh)
    if t is None:
        raise ValueError(f"tabel '{penuh}' tidak ada")
    return t


def _kolom_boleh(t: Table) -> set[str]:
    return {c.name for c in t.c if c.name not in WAJIB}


def _uuid(v, kolom: str) -> UUID:
    if isinstance(v, UUID):
        return v
    try:
        return UUID(str(v))
    except (ValueError, TypeError, AttributeError):
        raise _Galat.nilai(f"{kolom} tidak dikenal.")


def _rapikan_nilai(t: Table, nilai: dict) -> dict:
    """Validasi tipe dasar per kolom. Kunci asing atau kolom wajib = bug plugin (ValueError → 500)."""
    if not isinstance(nilai, dict):
        raise ValueError("nilai harus dict")
    asing = set(nilai) - _kolom_boleh(t)
    if asing:
        raise ValueError(f"kolom {sorted(asing)} tidak boleh diisi plugin di {t.name}")
    out = {}
    for nama, v in nilai.items():
        c = t.c[nama]
        if v is None:
            if not c.nullable:
                raise _Galat.nilai(f"{nama} wajib diisi.")
            out[nama] = None
            continue
        jenis = c.type
        if isinstance(v, float):
            raise ValueError(f"{t.name}.{nama}: nominal float tidak boleh, pakai Decimal")
        if c.foreign_keys or isinstance(jenis, Uuid):
            out[nama] = _uuid(v, nama)
        elif isinstance(jenis, String):
            if not isinstance(v, str):
                raise ValueError(f"{t.name}.{nama}: harus teks")
            if jenis.length and len(v) > jenis.length:
                raise _Galat.nilai(f"{nama} paling banyak {jenis.length} karakter.")
            out[nama] = v
        elif isinstance(jenis, Boolean):
            if not isinstance(v, bool):
                raise ValueError(f"{t.name}.{nama}: harus bool")
            out[nama] = v
        elif isinstance(jenis, Numeric):
            if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
                raise ValueError(f"{t.name}.{nama}: harus int atau Decimal")
            try:
                d = Decimal(v)
            except InvalidOperation:
                raise _Galat.nilai(f"{nama} bukan angka.")
            if not d.is_finite():
                raise _Galat.nilai(f"{nama} bukan angka.")
            if jenis.precision and abs(d) >= Decimal(10) ** (jenis.precision - (jenis.scale or 0)):
                raise _Galat.nilai(f"{nama} terlalu besar.")
            out[nama] = d
        elif isinstance(jenis, Integer):
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(f"{t.name}.{nama}: harus int")
            out[nama] = v
        elif isinstance(jenis, DateTime):
            if not isinstance(v, datetime):
                raise ValueError(f"{t.name}.{nama}: harus datetime")
            out[nama] = v
        elif isinstance(jenis, Date):
            if not isinstance(v, date) or isinstance(v, datetime):
                raise ValueError(f"{t.name}.{nama}: harus date")
            out[nama] = v
        else:
            raise ValueError(f"{t.name}.{nama}: tipe kolom belum didukung")
    return out


async def _cek_rujukan(k: keadaan.Keadaan, t: Table, nilai: dict) -> None:
    """Nilai FK harus menunjuk baris di ruang konteks (dan yang boleh dilihat viewer)."""
    from sqlalchemy import or_
    from app.models.models import Envelope, HouseholdMember, Income, Transaction
    uid = k.viewer.id if k.viewer is not None else None
    for nama, v in nilai.items():
        if v is None:
            continue
        for fk in t.c[nama].foreign_keys:
            tujuan = fk.column.table.name
            if tujuan.startswith("p_"):
                if tujuan not in k.entitas:
                    raise ValueError(f"{t.name}.{nama}: rujukan ke tabel plugin lain")
                tt = _tabel_ada(tujuan)
                q = select(tt.c.id).where(tt.c.id == v, tt.c.household_id == k.ruang_id, tt.c.deleted_at.is_(None))
            elif tujuan == "envelopes":
                terlihat = Envelope.owner_id.is_(None) if uid is None else \
                    or_(Envelope.owner_id.is_(None), Envelope.owner_id == uid)
                q = select(Envelope.id).where(Envelope.id == v, Envelope.household_id == k.ruang_id,
                                              Envelope.is_active.is_(True), terlihat)
            elif tujuan == "incomes":
                q = select(Income.id).where(Income.id == v, Income.household_id == k.ruang_id)
            elif tujuan == "transactions":
                terlihat = Envelope.owner_id.is_(None) if uid is None else \
                    or_(Envelope.owner_id.is_(None), Envelope.owner_id == uid)
                q = (select(Transaction.id).join(Envelope, Envelope.id == Transaction.envelope_id)
                     .where(Transaction.id == v, Envelope.household_id == k.ruang_id,
                            Transaction.is_deleted.is_(False), terlihat))
            elif tujuan == "users":
                q = select(HouseholdMember.id).where(HouseholdMember.household_id == k.ruang_id,
                                                     HouseholdMember.user_id == v)
            else:
                raise ValueError(f"{t.name}.{nama}: rujukan ke '{tujuan}' tidak boleh")
            if (await k.db.execute(q.limit(1))).first() is None:
                raise _Galat.nilai(f"{nama}: data yang dirujuk tidak ada di ruang ini.")


def _baris(t: Table, row) -> dict:
    """`id` dulu, lalu kolom plugin, lalu `created_by`, `created_at`, `updated_at`; tanpa kolom tersembunyi."""
    m = row._mapping
    urutan = ["id"] + [c.name for c in t.c if c.name not in WAJIB] + ["created_by", "created_at", "updated_at"]
    return {c: m[c] for c in urutan if c in m and c not in TERSEMBUNYI}


def _hidup(t: Table, k: keadaan.Keadaan):
    return (t.c.household_id == k.ruang_id) & t.c.deleted_at.is_(None)


def _pendek(k: keadaan.Keadaan, nama: str) -> str:
    """Nama entitas tanpa awalan `p_<id>_` untuk audit (`action` ≤ 30 huruf; review #196 saran 5)."""
    awalan = f"p_{k.plugin_id}_"
    return nama[len(awalan):] if nama.startswith(awalan) else nama


async def _boleh_baca(k: keadaan.Keadaan, nama: str) -> None:
    if keadaan.karyawan(k):
        await keadaan.tolak(k, f"data:{_pendek(k, nama)}"[:24], "khusus_admin")


async def _boleh_tulis(k: keadaan.Keadaan, nama: str) -> None:
    await _boleh_baca(k, nama)
    if not k.boleh_tulis or k.viewer is None:
        await keadaan.tolak(k, f"data:{_pendek(k, nama)}"[:24], "hanya_baca")


def _audit(k: keadaan.Keadaan, aksi: str, t: Table, id_baris, kolom=()) -> None:
    from app.models.models import PluginAuditLog
    k.db.add(PluginAuditLog(household_id=k.ruang_id, plugin_id=k.plugin_id, actor_id=k.viewer.id,
                            action=f"data:{aksi}", detail={"tabel": t.name, "id": str(id_baris),
                                                           "kolom": sorted(kolom), "sumber": k.sumber}))


# ── baca ─────────────────────────────────────────────────────────────────
def _saring(t: Table, saring: dict | None):
    syarat = []
    for nama, v in (saring or {}).items():
        if nama not in t.c or nama in TERSEMBUNYI:
            raise ValueError(f"saring '{nama}' bukan kolom {t.name}")
        if isinstance(v, float) or isinstance(v, (dict, list, tuple, set)):
            raise ValueError(f"saring '{nama}': nilai harus tunggal, bukan float")
        c = t.c[nama]
        if v is None:
            syarat.append(c.is_(None))
            continue
        if c.foreign_keys or nama in ("id", "created_by"):
            try:
                v = _uuid(v, nama)
            except Exception:
                syarat.append(c.is_(None) & c.is_not(None))     # bukan UUID → tidak ada yang cocok
                continue
        syarat.append(c == v)
    return syarat


async def cari(k, nama: str, *, saring: dict | None = None, teks: str | None = None, kolom_teks=(),
               urut=(), batas: int = 200) -> list[dict]:
    t = _tabel(k, nama)
    await _boleh_baca(k, t.name)
    q = select(t).where(_hidup(t, k), *_saring(t, saring))
    if teks:
        if not isinstance(teks, str) or len(teks) > 100:
            raise _Galat.nilai("Kata pencarian terlalu panjang.")
        pola = "%" + teks.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        kolom = [t.c[x] for x in kolom_teks if x in t.c and isinstance(t.c[x].type, String) and x not in TERSEMBUNYI]
        if not kolom:
            raise ValueError("teks butuh kolom_teks berupa kolom teks")
        from sqlalchemy import or_
        q = q.where(or_(*[func.lower(c).like(pola, escape="\\") for c in kolom]))
    susun = []
    for u in urut or ("created_at", "id"):
        turun = u.startswith("-")
        n = u.lstrip("-")
        if n not in t.c or n in TERSEMBUNYI:
            raise ValueError(f"urut '{n}' bukan kolom {t.name}")
        susun.append(t.c[n].desc() if turun else t.c[n].asc())
    batas = max(1, min(int(batas), BATAS_BARIS))
    rows = (await k.db.execute(q.order_by(*susun, t.c.id).limit(batas))).all()
    return [_baris(t, r) for r in rows]


async def ambil(k, nama: str, id_baris) -> dict | None:
    t = _tabel(k, nama)
    await _boleh_baca(k, t.name)
    try:
        rid = _uuid(id_baris, "id")
    except Exception:
        return None
    row = (await k.db.execute(select(t).where(t.c.id == rid, _hidup(t, k)))).first()
    return _baris(t, row) if row is not None else None


async def hitung(k, nama: str, *, saring: dict | None = None) -> int:
    t = _tabel(k, nama)
    await _boleh_baca(k, t.name)
    return int((await k.db.execute(
        select(func.count()).select_from(t).where(_hidup(t, k), *_saring(t, saring))
    )).scalar() or 0)


# ── tulis ────────────────────────────────────────────────────────────────
def _sekarang() -> datetime:
    return datetime.now(timezone.utc)


async def tambah(k, nama: str, nilai: dict) -> dict:
    t = _tabel(k, nama)
    await _boleh_tulis(k, t.name)
    bersih = _rapikan_nilai(t, nilai)
    for c in t.c:
        if c.name not in WAJIB and not c.nullable and c.default is None and c.server_default is None \
                and c.name not in bersih:
            raise _Galat.nilai(f"{c.name} wajib diisi.")
    await _cek_rujukan(k, t, bersih)
    if not pendamping_inti(t):
        ada = int((await k.db.execute(
            select(func.count()).select_from(t).where(t.c.household_id == k.ruang_id)   # termasuk yang dihapus lunak
        )).scalar() or 0)
        if ada >= BATAS_BARIS_RUANG:
            raise _Galat.nilai("Data ini sudah mencapai batas untuk satu ruang.")
    rid = _uuid_mod.uuid4()
    sekarang = _sekarang()
    await k.db.execute(insert(t).values(id=rid, household_id=k.ruang_id, created_by=k.viewer.id,
                                        created_at=sekarang, updated_at=sekarang, **bersih))
    _audit(k, "tambah", t, rid, bersih)
    row = (await k.db.execute(select(t).where(t.c.id == rid))).first()
    return _baris(t, row)


async def ubah(k, nama: str, id_baris, nilai: dict) -> dict | None:
    t = _tabel(k, nama)
    await _boleh_tulis(k, t.name)
    try:
        rid = _uuid(id_baris, "id")
    except Exception:
        return None
    bersih = _rapikan_nilai(t, nilai)
    if not bersih:
        raise ValueError("ubah tanpa kolom")
    await _cek_rujukan(k, t, bersih)
    hasil = await k.db.execute(update(t).where(t.c.id == rid, _hidup(t, k)).values(updated_at=_sekarang(), **bersih))
    if not hasil.rowcount:
        return None
    _audit(k, "ubah", t, rid, bersih)
    row = (await k.db.execute(select(t).where(t.c.id == rid))).first()
    return _baris(t, row)


async def hapus(k, nama: str, id_baris) -> bool:
    """Hapus lunak: baris hilang dari semua baca plugin dan ekspor; dihapus permanen bersama arsip/ruang."""
    t = _tabel(k, nama)
    await _boleh_tulis(k, t.name)
    try:
        rid = _uuid(id_baris, "id")
    except Exception:
        return False
    sekarang = _sekarang()
    hasil = await k.db.execute(update(t).where(t.c.id == rid, _hidup(t, k)).values(deleted_at=sekarang,
                                                                                   updated_at=sekarang))
    if not hasil.rowcount:
        return False
    _audit(k, "hapus", t, rid)
    return True


# ── host saja: ekspor, pembersih arsip, hapus ruang/akun ──────────────────
def tabel_plugin(m) -> list[Table]:
    """Tabel `entities` plugin, urut induk dulu (untuk ekspor) — hapus memakai urutan terbalik."""
    nama = set(m.entities)
    return [t for t in Base.metadata.sorted_tables if t.name in nama]


def _semua_tabel_plugin() -> list[Table]:
    import app.models.models  # noqa: F401
    return [t for t in Base.metadata.sorted_tables if t.name.startswith("p_")]


async def ekspor(db, m, household_id) -> dict[str, list[dict]]:
    """Semua baris hidup tabel plugin di satu ruang, per tabel (nama tanpa awalan). Tanpa `household_id`/`deleted_at`."""
    out = {}
    awalan = f"p_{m.id}_"
    for t in tabel_plugin(m):
        rows = (await db.execute(
            select(t).where(t.c.household_id == household_id, t.c.deleted_at.is_(None))
            .order_by(t.c.created_at, t.c.id)
        )).all()
        out[t.name[len(awalan):]] = [_baris(t, r) for r in rows]
    return out


async def hapus_data_ruang(db, m, household_id) -> int:
    """Hapus permanen semua data plugin `m` di satu ruang (pembersih arsip, ADR-P15). Mengembalikan jumlah baris."""
    n = 0
    for t in reversed(tabel_plugin(m)):
        n += (await db.execute(delete(t).where(t.c.household_id == household_id))).rowcount or 0
    return n


async def hapus_semua_data_ruang(db, household_id) -> None:
    """Hapus ruang (hapus akun pemilik terakhir): semua tabel `p_*` ruang itu, eksplisit (tidak bergantung CASCADE)."""
    for t in reversed(_semua_tabel_plugin()):
        await db.execute(delete(t).where(t.c.household_id == household_id))


async def hapus_rujukan(db, tujuan: str, ids) -> None:
    """Baris inti `tujuan` (envelopes/incomes/transactions) akan dihapus permanen: baris plugin yang merujuknya ikut
    dihapus bila rujukannya wajib, atau rujukannya dilepas bila boleh NULL (seperti FK CASCADE / SET NULL)."""
    ids = list(ids)
    if not ids:
        return
    for t in reversed(_semua_tabel_plugin()):
        for c in t.c:
            if c.name == "household_id" or not any(fk.column.table.name == tujuan for fk in c.foreign_keys):
                continue
            if c.nullable:
                await db.execute(update(t).where(c.in_(ids)).values({c.name: None}))
            else:
                await db.execute(delete(t).where(c.in_(ids)))


async def bersihkan_terhapus(db, *, hari: int = HARI_SIMPAN_TERHAPUS, now: datetime | None = None) -> int:
    """Hapus permanen baris `deleted_at` lebih lama dari `hari` hari di semua tabel `p_*` (semua ruang). Anak dulu
    (urutan terbalik `sorted_tables`): rujukan yang boleh NULL sudah dilepas FK SET NULL / `hapus_rujukan`."""
    batas = (now or _sekarang()) - timedelta(days=hari)
    n = 0
    for t in reversed(_semua_tabel_plugin()):
        n += (await db.execute(delete(t).where(t.c.deleted_at.is_not(None), t.c.deleted_at < batas))).rowcount or 0
    return n


async def lepas_pembuat(db, user_id) -> None:
    """Hapus akun: pencatat data plugin menjadi kosong (tampil "Mantan anggota"); datanya tetap milik ruang."""
    for t in _semua_tabel_plugin():
        await db.execute(update(t).where(t.c.created_by == user_id).values(created_by=None))
