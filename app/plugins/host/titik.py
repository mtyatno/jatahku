"""Titik ekstensi server (Plugin H2; 03-workflow.md baris H2, 01-kajian.md "Katalog titik ekstensi").

Satu modul untuk semua tempat inti memanggil kode plugin. Aturan bersama:

- **Hanya plugin aktif.** Setiap titik memakai `siklus.aktif_dengan_instalasi` (status `active`, tanpa saklar
  darurat, flag rollout user aktif): plugin dijeda, dicopot, atau dimatikan server tidak meninggalkan kartu,
  peringatan, saran, perintah, notifikasi, job, atau kamus.
- **Tanpa plugin = tanpa kerja.** Bila tidak ada plugin dimuat yang mendaftarkan fungsi untuk titik itu
  (`registry().punya(...)`), fungsi di sini kembali seketika tanpa kueri DB. Ruang keluarga dan semua user hari
  ini (belum ada plugin terdaftar sampai U1) tidak berubah.
- **Gagal sendiri-sendiri.** Galat fungsi plugin dicatat di log dan hanya menghilangkan kontribusinya; pencatatan,
  Beranda, dan AI Advisor inti tetap jalan. Pengecualian: `periksa_field` (validasi form) memang menolak.
- **Keluaran diperiksa.** Bentuk kartu, saran, teks, dan tautan dari plugin diperiksa sebelum keluar; tautan hanya
  ke halaman plugin itu (`/p/<id>…`), tidak ada aksi tulis.
- **Ruang dari host.** Konteks dibuat untuk ruang yang memasang plugin dan sudah diperiksa keanggotaannya.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import get_settings
from app.models.models import (
    Household, HouseholdMember, HouseholdRole, HouseholdType, NotificationType, PluginInstallation, User,
)
from app.plugins.host import siklus
from app.plugins.host.manifest import Manifest
from app.plugins.host.registry import registry
from app.plugins.host import keadaan
from app.plugins.host.kode import IZIN_PER_JENIS
from app.plugins.host.keadaan import catat_audit, sesi
from app.plugins.sdk.context import (
    AksiRoute, NilaiTidakSah, PenggunaView, PeriodeView, PluginContext, RencanaPengeluaran, Saran,
)
from app.plugins.sdk.plugin import Pendaftaran

log = logging.getLogger("jatahku.plugins")

ANGGARAN_MS = 150                 # per fungsi plugin di jalur permintaan (kartu, cek, saran), seperti kartu B1
MAKS_PERINGATAN_PLUGIN = 2
MAKS_PERINGATAN = 3
MAKS_SARAN_PLUGIN = 5
MAKS_NOTIF_HARIAN = 2             # per plugin per user per hari lokal
TTL_BUKU = 2 * 24 * 3600
TONE = ("ok", "info", "warn", "danger")
ADMIN = ("owner", "admin")


# ── ruang dan konteks ────────────────────────────────────────────────────
def _peran_str(role) -> str:
    return str(getattr(role, "value", role))


def _karyawan(jenis_ruang: str | None, peran: str | None) -> bool:
    return jenis_ruang == HouseholdType.USAHA and peran == HouseholdRole.member.value


async def _ruang(db, household_id) -> Household | None:
    return (await db.execute(select(Household).where(Household.id == household_id))).scalar_one_or_none()


async def _peran(db, user_id, household_id) -> str | None:
    from app.services.ruang import keanggotaan
    anggota = await keanggotaan(db, user_id, household_id)
    return _peran_str(anggota.role) if anggota is not None else None


def izin_efektif(inst: PluginInstallation, m: Manifest, d: Pendaftaran) -> frozenset[str]:
    """Izin yang terbuka untuk satu panggilan: disetujui saat pasang ∩ manifest sekarang ∩ `izin=` fungsi ∩ izin
    yang boleh untuk jenis titik itu (`kode.IZIN_PER_JENIS`; mis. hanya job yang boleh mengirim, review #186 temuan 1)."""
    return (frozenset(inst.granted_permissions or []) & frozenset(m.permissions) & frozenset(d.izin)
            & IZIN_PER_JENIS.get(d.jenis, frozenset()))


def _pengguna(user) -> PenggunaView | None:
    """View beku user pemicu: plugin tidak pernah memegang objek ORM `User` (sesi DB, email, kredensial)."""
    if user is None:
        return None
    return PenggunaView(id=user.id, nama=user.name or "", zona_waktu=getattr(user, "timezone", None) or "Asia/Jakarta")


def konteks(db, m: Manifest, inst: PluginInstallation, ruang: Household, d: Pendaftaran, *,
            viewer=None, peran: str = "sistem", sumber: str, sekarang: datetime | None = None) -> PluginContext:
    """Konteks untuk satu panggilan fungsi plugin; `viewer` = objek `User` pemicu (atau None untuk job).
    `sekarang` = jam acuan panggilan itu (job: jam jadwalnya), dipakai penyaring notifikasi; None = jam sungguhan."""
    return keadaan.buat(
        db=db, plugin_id=m.id, nama_plugin=m.name, ruang_id=ruang.id, nama_ruang=ruang.name or "",
        jenis_ruang=ruang.type or HouseholdType.RUMAH_TANGGA, viewer=_pengguna(viewer), peran=peran,
        izin=izin_efektif(inst, m, d), jenis_notifikasi=frozenset(m.contributes.notifications),
        pengaturan=dict(inst.settings or {}), sumber=sumber, sekarang=sekarang,
    )


async def panggil(ctx: PluginContext, fn, *args):
    """Jalankan satu fungsi plugin, lalu tutup konteksnya: konteks yang disimpan plugin (variabel modul, cache) tidak
    berlaku lagi di panggilan berikutnya untuk user atau ruang lain (review ulang kedua #186 no. 1)."""
    try:
        return await fn(ctx, *args)
    finally:
        keadaan.tutup(ctx)


@dataclass
class _Aktif:
    m: Manifest
    inst: PluginInstallation
    d: Pendaftaran


async def _fungsi_aktif(db, household_id, user_id, jenis: str, kunci_manifest) -> list[_Aktif]:
    """(manifest, instalasi, fungsi) untuk setiap kontribusi `jenis` dari plugin yang aktif di ruang ini."""
    reg = registry()
    hasil = []
    for m, inst in await siklus.aktif_dengan_instalasi(db, household_id, user_id):
        p = reg.kode_plugin(m.id)
        if p is None:
            continue
        for kunci in kunci_manifest(m):
            d = p.ambil(jenis, kunci)
            if d is not None:
                hasil.append(_Aktif(m, inst, d))
    return hasil


def _waktu(mulai: float, m: Manifest, d: Pendaftaran) -> None:
    ms = (time.perf_counter() - mulai) * 1000
    if ms > ANGGARAN_MS:
        log.warning("plugin %s %s '%s' %.0f ms (anggaran %d ms)", m.id, d.jenis, d.kunci, ms, ANGGARAN_MS)


# ── pemeriksa keluaran ───────────────────────────────────────────────────
class KeluaranTidakSah(ValueError):
    pass


def _teks(v, maks: int, *, boleh_kosong: bool = True) -> str:
    if v is None and boleh_kosong:
        return ""
    if not isinstance(v, str) or len(v) > maks or (not v and not boleh_kosong):
        raise KeluaranTidakSah(f"teks harus string ≤ {maks} karakter")
    return v


def _angka(v, *, boleh_none: bool = True):
    """Nominal: int atau Decimal (Decimal dikirim sebagai string desimal). Float ditolak: tidak ada pembulatan diam."""
    if v is None and boleh_none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        raise KeluaranTidakSah("angka harus int atau Decimal (bukan float)")
    if isinstance(v, Decimal) and not v.is_finite():
        raise KeluaranTidakSah("angka harus terhingga (bukan NaN/Infinity)")
    return str(v) if isinstance(v, Decimal) else v


def _rasio(v):
    if v is None:
        return None
    try:
        r = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise KeluaranTidakSah("bar harus 0–1")
    if isinstance(v, bool) or not r.is_finite() or not Decimal(0) <= r <= Decimal(1):
        raise KeluaranTidakSah("bar harus 0–1")
    return float(round(r, 4))


def _tone(v, *, boleh_none: bool = True):
    if v is None and boleh_none:
        return None
    if v not in TONE:
        raise KeluaranTidakSah(f"tone harus salah satu dari {TONE}")
    return v


def rute_plugin(ke, plugin_id: str) -> str:
    if not isinstance(ke, str) or len(ke) > 200 or not re.fullmatch(rf"/p/{plugin_id}(/[a-z0-9_\-]+)*/?(\?[A-Za-z0-9_=&\-]*)?", ke):
        raise KeluaranTidakSah(f"tautan harus ke halaman plugin /p/{plugin_id}")
    return ke


def _aksi(v, plugin_id: str):
    """Hanya `route` ke halaman plugin itu (H2). Form dan rencana pemindahan dana menyusul bersama izinnya."""
    if v is None:
        return None
    if isinstance(v, AksiRoute):
        return {"kind": "route", "label": _teks(v.label, 30, boleh_kosong=False),
                "payload": {"to": rute_plugin(v.ke, plugin_id)}}
    if not isinstance(v, dict) or v.get("kind") != "route" or set(v) - {"kind", "label", "payload"}:
        raise KeluaranTidakSah("aksi kartu hanya {kind: route, label, payload: {to}}")
    payload = v.get("payload") or {}
    if not isinstance(payload, dict) or set(payload) != {"to"}:
        raise KeluaranTidakSah("aksi route hanya berisi payload.to")
    return {"kind": "route", "label": _teks(v.get("label"), 30),
            "payload": {"to": rute_plugin(payload["to"], plugin_id)}}


def _hanya(d: dict, kunci: set[str], nama: str) -> None:
    if not isinstance(d, dict):
        raise KeluaranTidakSah(f"{nama} harus objek")
    asing = set(d) - kunci
    if asing:
        raise KeluaranTidakSah(f"{nama}: field tidak dikenal {sorted(asing)}")


def rapikan_kartu(shape: str, data: Any, plugin_id: str) -> dict:
    """Payload kartu plugin → bentuk deklaratif sah (04-kontrak-api.md §4), atau `KeluaranTidakSah`."""
    if shape == "kpi":
        _hanya(data, {"value", "unit", "suffix", "bar", "footer", "tone", "chip"}, "kpi")
        if data.get("unit") not in (None, "rp", "persen", "hari", "angka"):
            raise KeluaranTidakSah("unit kpi tidak dikenal")
        out = {"value": _angka(data.get("value")), "unit": data.get("unit"), "suffix": _teks(data.get("suffix"), 40),
               "bar": _rasio(data.get("bar")), "footer": _teks(data.get("footer"), 120),
               "tone": _tone(data.get("tone")), "chip": _teks(data.get("chip"), 30)}
    elif shape == "progress":
        _hanya(data, {"items"}, "progress")
        items = data.get("items") or []
        if not isinstance(items, list) or len(items) > 10:
            raise KeluaranTidakSah("progress.items maksimal 10")
        out = {"items": []}
        for it in items:
            _hanya(it, {"label", "value", "target", "tone"}, "progress.items")
            out["items"].append({"label": _teks(it.get("label"), 60, boleh_kosong=False),
                                 "value": _angka(it.get("value"), boleh_none=False),
                                 "target": _angka(it.get("target")), "tone": _tone(it.get("tone"))})
    elif shape == "list":
        _hanya(data, {"items"}, "list")
        items = data.get("items") or []
        if not isinstance(items, list) or len(items) > 8:
            raise KeluaranTidakSah("list.items maksimal 8")
        out = {"items": []}
        for it in items:
            _hanya(it, {"judul", "subjudul", "nominal", "status", "aksi"}, "list.items")
            out["items"].append({"judul": _teks(it.get("judul"), 80, boleh_kosong=False),
                                 "subjudul": _teks(it.get("subjudul"), 120), "nominal": _angka(it.get("nominal")),
                                 "status": _teks(it.get("status"), 30), "aksi": _aksi(it.get("aksi"), plugin_id)})
    elif shape == "table":
        _hanya(data, {"columns", "rows"}, "table")
        cols, rows = data.get("columns") or [], data.get("rows") or []
        if not isinstance(cols, list) or not 1 <= len(cols) <= 6 or not isinstance(rows, list) or len(rows) > 10:
            raise KeluaranTidakSah("table: 1–6 kolom, maksimal 10 baris")
        out = {"columns": [_teks(c, 30, boleh_kosong=False) for c in cols], "rows": []}
        for r in rows:
            if not isinstance(r, list) or len(r) != len(cols):
                raise KeluaranTidakSah("table: setiap baris sepanjang kolom")
            out["rows"].append([_teks(c, 80) if isinstance(c, str) or c is None else _angka(c) for c in r])
    elif shape == "series":
        _hanya(data, {"x", "series", "acuan"}, "series")
        x, seri = data.get("x") or [], data.get("series") or []
        if not isinstance(x, list) or len(x) > 62 or not isinstance(seri, list) or not 1 <= len(seri) <= 3:
            raise KeluaranTidakSah("series: maksimal 62 titik, 1–3 seri")
        out = {"x": [_teks(v, 20, boleh_kosong=False) for v in x], "series": [],
               "acuan": _angka(data.get("acuan"))}
        for s in seri:
            _hanya(s, {"nama", "values"}, "series.series")
            vals = s.get("values") or []
            if not isinstance(vals, list) or len(vals) != len(x):
                raise KeluaranTidakSah("series: jumlah nilai harus sama dengan x")
            out["series"].append({"nama": _teks(s.get("nama"), 40, boleh_kosong=False),
                                  "values": [_angka(v) for v in vals]})
    elif shape == "alert":
        _hanya(data, {"tone", "judul", "isi", "aksi"}, "alert")
        out = {"tone": _tone(data.get("tone"), boleh_none=False), "judul": _teks(data.get("judul"), 80, boleh_kosong=False),
               "isi": _teks(data.get("isi"), 300), "aksi": _aksi(data.get("aksi"), plugin_id)}
    else:
        raise KeluaranTidakSah(f"bentuk '{shape}' tidak untuk plugin")
    return {"shape": shape, **out}


# ── cards (registry B1) ──────────────────────────────────────────────────
def _definisi(m: Manifest, k):
    from app.services.dashboard.registry import CardDef
    return CardDef(key=k.key, judul=k.title, deskripsi=k.title, size_bawaan=k.sizes[0], sizes=tuple(k.sizes),
                   shape=k.shape, supports_period=True, asal=m.id)


async def kartu_ruang(db, user, household_id) -> dict:
    """Definisi kartu plugin yang aktif di ruang ini untuk user ini (key → CardDef). Dipakai tata letak dan batch:
    kartu plugin yang tidak aktif diparkir dan tidak bisa ditambahkan atau dimuat datanya."""
    if household_id is None or not registry().punya("kartu"):
        return {}
    out = {}
    for a in await _fungsi_aktif(db, household_id, user.id, "kartu", lambda m: [k.key for k in m.contributes.cards]):
        k = next(k for k in a.m.contributes.cards if k.key == a.d.kunci)
        out[k.key] = _definisi(a.m, k)
    return out


async def data_kartu(db, user, household_id, definisi, pengaturan: dict, periode) -> dict:
    """Data satu kartu plugin. Melempar bila gagal (batch mengubahnya menjadi `gagal_memuat`)."""
    hasil = await _fungsi_aktif(db, household_id, user.id, "kartu", lambda m: [definisi.key] if m.id == definisi.asal else [])
    if not hasil:
        raise LookupError(f"kartu {definisi.key} tidak aktif")
    a = hasil[0]
    ruang = await _ruang(db, household_id)
    peran = await _peran(db, user.id, household_id)
    if ruang is None or peran is None:          # route sudah memeriksa lewat `ruang_aktif`; tetap fail-closed
        raise LookupError("bukan anggota ruang ini")
    ctx = konteks(db, a.m, a.inst, ruang, a.d, viewer=user, peran=peran, sumber=f"kartu:{definisi.key}")
    mulai = time.perf_counter()
    # Salinan beku: `Periode` batch dipakai bersama kartu inti sesudahnya (review ulang #186 no. 4).
    beku = PeriodeView(start=periode.start, end=periode.end, berjalan=bool(periode.berjalan))
    data = await panggil(ctx, a.d.fn, dict(pengaturan), beku)
    _waktu(mulai, a.m, a.d)
    return rapikan_kartu(definisi.shape, data, a.m.id)


# ── checks (expense_rules) ───────────────────────────────────────────────
async def peringatan_pengeluaran(db, user, envelope, jumlah, deskripsi: str) -> list[str]:
    """Peringatan plugin sebelum pengeluaran disimpan. Tidak pernah menolak dan tidak pernah melempar.
    Karyawan tidak mendapat peringatan plugin (isinya bisa memuat angka usaha, ADR-P3)."""
    if not registry().punya("cek"):
        return []
    try:
        hid = envelope.household_id
        ruang = await _ruang(db, hid)
        peran = await _peran(db, user.id, hid)
        if ruang is None or peran is None or _karyawan(ruang.type, peran):
            return []
        aktif = await _fungsi_aktif(db, hid, user.id, "cek", lambda m: m.contributes.checks)
    except Exception:
        log.exception("peringatan plugin: gagal menyiapkan")
        return []
    rencana = RencanaPengeluaran(amplop_id=envelope.id, jumlah=Decimal(jumlah), deskripsi=deskripsi or "")
    out: list[str] = []
    for a in aktif:
        ctx = konteks(db, a.m, a.inst, ruang, a.d, viewer=user, peran=peran, sumber=f"cek:{a.d.kunci}")
        mulai = time.perf_counter()
        try:
            hasil = await panggil(ctx, a.d.fn, rencana)
            teks = [_teks(t, 200, boleh_kosong=False) for t in (hasil or [])][:MAKS_PERINGATAN_PLUGIN]
        except Exception:
            log.exception("cek plugin %s '%s' gagal", a.m.id, a.d.kunci)
            continue
        finally:
            _waktu(mulai, a.m, a.d)
        out.extend(teks)
    return out[:MAKS_PERINGATAN]


# ── advisor_rules (select.py) ────────────────────────────────────────────
def ke_insight(m: Manifest, kode: str, s: Saran):
    """Saran plugin → Insight slot `daftar`, asal plugin. Teks sudah jadi (templat plugin), aksi hanya route."""
    from app.services.advisor.insight import Insight
    if not isinstance(s, Saran):
        raise KeluaranTidakSah("aturan advisor harus mengembalikan list[Saran]")
    if not isinstance(s.entitas, str) or not re.fullmatch(r"[A-Za-z0-9_.\-]{1,60}", s.entitas):
        raise KeluaranTidakSah("entitas saran tidak sah")
    if s.keyakinan not in ("tinggi", "sedang", "rendah"):
        raise KeluaranTidakSah("keyakinan tidak sah")
    if len(s.fakta) > 4 or len(s.aksi) > 2:
        raise KeluaranTidakSah("fakta maksimal 4, aksi maksimal 2")
    for nilai in (s.rupiah, s.urgensi):                 # float ditolak: tidak ada pembulatan diam (review #186 no. 7)
        if isinstance(nilai, bool) or not isinstance(nilai, (int, Decimal)) or not Decimal(nilai).is_finite():
            raise KeluaranTidakSah("rupiah dan urgensi harus int atau Decimal terhingga")
    rupiah = Decimal(s.rupiah)
    urgensi = Decimal(s.urgensi)
    if rupiah < 0 or not Decimal(0) <= urgensi <= Decimal(1):
        raise KeluaranTidakSah("rupiah ≥ 0, urgensi 0–1")
    teks = {"chip": _teks(s.chip, 30), "judul": _teks(s.judul, 80, boleh_kosong=False), "isi": _teks(s.isi, 300),
            "fakta": [{"label": _teks(lbl, 30, boleh_kosong=False), "nilai": _teks(nilai, 40)} for lbl, nilai in s.fakta]}
    return Insight(aturan=kode, entitas=s.entitas, tone=_tone(s.tone, boleh_none=False), slot=("daftar",),
                   data={"_teks": teks}, aksi=[{**_aksi(a, m.id), "kode": None} for a in s.aksi],
                   rupiah=rupiah, urgensi=urgensi, keyakinan=s.keyakinan, asal=m.id)


async def saran_advisor(db, user, household_id) -> list:
    """Insight dari aturan advisor plugin aktif di ruang ini, untuk `advisor.dashboard`. Tidak pernah melempar."""
    if household_id is None or not registry().punya("aturan_advisor"):
        return []
    try:
        ruang = await _ruang(db, household_id)
        peran = await _peran(db, user.id, household_id)
        if ruang is None or peran is None or _karyawan(ruang.type, peran):
            return []
        aktif = await _fungsi_aktif(db, household_id, user.id, "aturan_advisor", lambda m: m.contributes.advisor_rules)
    except Exception:
        log.exception("saran plugin: gagal menyiapkan")
        return []
    out = []
    for a in aktif:
        ctx = konteks(db, a.m, a.inst, ruang, a.d, viewer=user, peran=peran, sumber=f"advisor:{a.d.kunci}")
        mulai = time.perf_counter()
        try:
            hasil = await panggil(ctx, a.d.fn)
            out.extend(ke_insight(a.m, a.d.kunci, s) for s in list(hasil or [])[:MAKS_SARAN_PLUGIN])
        except Exception:
            log.exception("aturan advisor plugin %s '%s' gagal", a.m.id, a.d.kunci)
        finally:
            _waktu(mulai, a.m, a.d)
    return out


async def saring_payload_advisor(db, user, household_id, payload: dict) -> dict:
    """Payload AI Advisor dari cache tanpa saran plugin yang kini tidak aktif untuk user ini di ruang ini.
    Pasang/jeda/copot sudah menghapus cache (`advisor_cache`), tetapi saklar darurat dan flag (AppSetting) tidak;
    tanpa saran plugin di payload, kembali apa adanya tanpa kueri."""
    from app.plugins.host.manifest import DOMAIN_ADVISOR_INTI
    adv = payload.get("advisor") or {}

    def asal(kode: str | None) -> str | None:
        kode = kode or ""
        if not kode or kode.split("-")[0] in DOMAIN_ADVISOR_INTI:
            return None
        return pemilik.get(kode, "?")

    pemilik = {k: m.id for m in registry().plugins.values() for k in m.contributes.advisor_rules}
    semua = [i.get("aturan") for i in adv.get("items") or []] + \
            [(s.get("id") or "").split(":")[0] for s in adv.get("sisa") or []] + \
            [(s.get("kunci") or "").split(":")[0] for s in adv.get("disembunyikan") or []]
    if not any(asal(k) for k in semua):
        return payload
    aktif = {m.id for m in await siklus.aktif_di_ruang(db, household_id, user.id)} if household_id else set()

    def boleh(kode) -> bool:
        a = asal(kode)
        return a is None or a in aktif

    items = [i for i in adv.get("items") or [] if boleh(i.get("aturan"))]
    sisa = [s for s in adv.get("sisa") or [] if boleh((s.get("id") or "").split(":")[0])]
    sembunyi = [s for s in adv.get("disembunyikan") or [] if boleh((s.get("kunci") or "").split(":")[0])]
    return {**payload, "advisor": {**adv, "items": items, "sisa": sisa, "disembunyikan": sembunyi,
                                   "total": len(items) + len(sisa)}}


# ── bot_commands (Telegram dan chat web) ─────────────────────────────────
PESAN_BELUM_ADA = "Perintah ini belum tersedia di ruangmu."
PESAN_GAGAL = "Laporan belum bisa dibuat. Coba lagi sebentar."


def perintah_plugin() -> dict[str, tuple[str, str]]:
    """Perintah plugin yang punya fungsi: nama → (plugin_id, nama). Didaftarkan sekali saat start."""
    reg = registry()
    out = {}
    for m in reg.semua():
        p = reg.kode_plugin(m.id)
        for b in m.contributes.bot_commands:
            if p is not None and p.ambil("perintah_bot", b.command) is not None:
                out[b.command] = (m.id, b.command)
    return out


async def perintah(db, user, plugin_id: str, command: str) -> list[str]:
    """Jawaban perintah baca plugin untuk `user`, satu pesan per ruang yang memasang plugin itu, berawalan nama
    ruang (ADR-P2). `audience: admin` hanya owner/admin (ADR-P3), dicek saat dipanggil; karyawan di luar jam
    kerjanya tidak dilayani (R5). Tidak ada tulis: fungsi plugin hanya mengembalikan teks."""
    from app.services import peran as peran_mod
    from app.services.ruang import ruang_usaha_dibuka
    m = registry().get(plugin_id)
    spec = next((b for b in m.contributes.bot_commands if b.command == command), None) if m else None
    if spec is None:
        return [PESAN_BELUM_ADA]
    rows = (await db.execute(
        select(Household, HouseholdMember.role).join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .where(HouseholdMember.user_id == user.id).order_by(Household.name)
    )).all()
    hasil, ditolak = [], []
    usaha_dibuka = None
    for ruang, role in rows:
        peran = _peran_str(role)
        if ruang.type not in m.space_types:
            continue
        if ruang.type == HouseholdType.USAHA:
            if usaha_dibuka is None:
                usaha_dibuka = await ruang_usaha_dibuka(db, user.id)
            if not usaha_dibuka:
                continue
        aktif = await _fungsi_aktif(db, ruang.id, user.id, "perintah_bot",
                                    lambda mm: [command] if mm.id == plugin_id else [])
        if not aktif:
            continue
        if spec.audience == "admin" and peran not in ADMIN:
            ditolak.append(ruang.name)
            continue
        if _karyawan(ruang.type, peran):
            batasan = await peran_mod.batasan_karyawan(db, user.id, ruang.id)
            try:
                if batasan is not None:
                    peran_mod.cek_jam_kerja(batasan)
            except peran_mod.PeranDitolak:
                continue
        a = aktif[0]
        ctx = konteks(db, a.m, a.inst, ruang, a.d, viewer=user, peran=peran, sumber=f"bot:{command}")
        try:
            teks = _teks(await panggil(ctx, a.d.fn), 3500, boleh_kosong=False)
        except Exception:
            log.exception("perintah plugin %s /%s gagal", plugin_id, command)
            teks = PESAN_GAGAL
        hasil.append(f"[{ruang.name}] {teks}")
    if hasil:
        return hasil
    if ditolak:
        return [f"Laporan {', '.join(ditolak)} hanya untuk admin ruang."]
    return [PESAN_BELUM_ADA]



# ── notifications (lewat penyaring proaktif) ─────────────────────────────
def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(get_settings().REDIS_URL, socket_timeout=2)


def _tz(user) -> ZoneInfo:
    try:
        return ZoneInfo(getattr(user, "timezone", None) or "Asia/Jakarta")
    except Exception:
        return ZoneInfo("Asia/Jakarta")


async def _klaim_buku(plugin_id: str, user_id, tanggal: date, kunci: str) -> bool:
    """Batas harian per plugin per user, dan satu kiriman per `kunci` per hari. Redis mati → tidak mengirim."""
    key = f"plugin:notif:{plugin_id}:{user_id}:{tanggal.isoformat()}"
    try:
        r = _redis()
        try:
            if not await r.hsetnx(key, kunci, "1"):
                return False
            if await r.hlen(key) > MAKS_NOTIF_HARIAN:
                await r.hdel(key, kunci)
                return False
            await r.expire(key, TTL_BUKU)
            return True
        finally:
            await r.aclose()
    except Exception as exc:
        log.warning("buku notifikasi plugin gagal: %s", exc)
        return False


async def kirim_notifikasi(ctx: PluginContext, jenis: str, judul: str, isi: str, *, link: str | None,
                           kunci: str, now: datetime | None = None) -> int:
    """Notifikasi plugin ke owner/admin ruang yang plugin-nya aktif untuk mereka. Jam tenang 21.00–07.00 waktu
    penerima (`proaktif.jam_tenang`), maksimal `MAKS_NOTIF_HARIAN` per plugin per penerima per hari, satu per
    `kunci`. Telegram dan lonceng, judul berawalan nama ruang. Karyawan tidak menerima (ADR-P19 menyusul di U6).
    Ruang, plugin, dan user dibaca dari keadaan host, bukan dari properti konteks (review ulang #186 no. 1)."""
    from app.services import notification_service
    from app.services.advisor.proaktif import jam_tenang
    from app.services.ruang import ruang_usaha_dibuka
    k = keadaan.ambil(ctx)
    judul = _teks(judul, 80, boleh_kosong=False)
    isi = _teks(isi, 500, boleh_kosong=False)
    link = rute_plugin(link, k.plugin_id) if link is not None else None
    kunci = _teks(kunci, 60, boleh_kosong=False)
    db = k.db
    penerima = (await db.execute(
        select(User).join(HouseholdMember, HouseholdMember.user_id == User.id)
        .where(HouseholdMember.household_id == k.ruang_id,
               HouseholdMember.role.in_([HouseholdRole.owner, HouseholdRole.admin]))
    )).scalars().all()
    terkirim = 0
    for u in penerima:
        if k.jenis_ruang == HouseholdType.USAHA and not await ruang_usaha_dibuka(db, u.id):
            continue
        if k.plugin_id not in {m.id for m in await siklus.aktif_di_ruang(db, k.ruang_id, u.id)}:
            continue
        lokal = (now or datetime.now(timezone.utc)).astimezone(_tz(u))
        if jam_tenang(lokal) or not await _klaim_buku(k.plugin_id, u.id, lokal.date(), kunci):
            continue
        hasil = await notification_service.kirim(u, NotificationType.system, f"[{k.nama_ruang}] {judul}", isi,
                                                 link=link, permukaan=("telegram", "web"))
        terkirim += 1 if hasil else 0
    if terkirim:   # yang tersaring (jam tenang, batas, kunci sama) tidak dicatat, supaya audit tidak membanjir (no. 6)
        await catat_audit(k.ruang_id, k.plugin_id, k.viewer.id if k.viewer is not None else None,
                          "kirim:notifications", jenis=jenis, kunci=kunci, penerima=terkirim, sumber=k.sumber)
    return terkirim


# ── jobs (scheduler tiap jam) ────────────────────────────────────────────
def jatuh_tempo(schedule: str, lokal: datetime) -> str | None:
    """Kunci periode bila job harus jalan pada jam lokal ini, selain itu None. `hourly` → tiap jam;
    `daily HH:00` → sekali pada jam HH."""
    if schedule == "hourly":
        return lokal.strftime("%Y-%m-%dT%H")
    if schedule.startswith("daily ") and lokal.hour == int(schedule[6:8]):
        return lokal.strftime("%Y-%m-%d")
    return None


async def _klaim_job(plugin_id: str, key: str, household_id, periode: str) -> bool:
    try:
        r = _redis()
        try:
            return bool(await r.set(f"plugin:job:{plugin_id}:{key}:{household_id}:{periode}", "1",
                                    nx=True, ex=TTL_BUKU))
        finally:
            await r.aclose()
    except Exception as exc:
        log.warning("klaim job plugin gagal: %s", exc)
        return False


async def jalankan_job(now: datetime | None = None) -> int:
    """Dipanggil scheduler tiap jam. Untuk setiap instalasi aktif dan job yang jatuh tempo di zona waktu pemilik
    ruang: klaim sekali per periode (Redis), lalu jalankan dengan sesi DB sendiri dan konteks tanpa user (hanya
    amplop bersama, deskripsi tersamar). Mengembalikan jumlah job yang dijalankan."""
    from app.services.ruang import ruang_jenis, ruang_usaha_dibuka
    reg = registry()
    if not reg.punya("job"):
        return 0
    now = now or datetime.now(timezone.utc)
    jalan = 0
    async with sesi() as db:
        mati = await siklus.saklar_mati(db)
        pids = [m.id for m in reg.semua() if m.contributes.jobs and reg.kode_plugin(m.id) and m.id not in mati]
        if not pids:
            return 0
        insts = (await db.execute(select(PluginInstallation).where(
            PluginInstallation.plugin_id.in_(pids), PluginInstallation.status == siklus.ACTIVE,
            PluginInstallation.owner_id.is_(None),
        ))).scalars().all()
        rencana = []
        for inst in insts:
            pemilik = (await db.execute(
                select(User).join(HouseholdMember, HouseholdMember.user_id == User.id)
                .where(HouseholdMember.household_id == inst.household_id, HouseholdMember.role == HouseholdRole.owner)
                .limit(1))).scalar_one_or_none()
            m = reg.get(inst.plugin_id)
            if pemilik is None or not await siklus.boleh_dilihat(db, m, pemilik.id):
                continue
            # Ruang usaha di luar flag `ruang_usaha_users` pemiliknya: plugin tidak meninggalkan job (review #186 no. 5).
            if await ruang_jenis(db, inst.household_id) == HouseholdType.USAHA and \
                    not await ruang_usaha_dibuka(db, pemilik.id):
                continue
            lokal = now.astimezone(_tz(pemilik))
            for j in m.contributes.jobs:
                periode = jatuh_tempo(j.schedule, lokal)
                if periode is not None:
                    rencana.append((inst.household_id, m.id, j.key, periode))
    for hid, pid, key, periode in rencana:
        if not await _klaim_job(pid, key, hid, periode):
            continue
        try:
            async with sesi() as db:
                m = reg.get(pid)
                inst = await siklus.instalasi(db, hid, pid)
                if inst is None or inst.status != siklus.ACTIVE:
                    continue
                d = reg.kode_plugin(pid).ambil("job", key)
                ctx = konteks(db, m, inst, await _ruang(db, hid), d, sumber=f"job:{key}", sekarang=now)
                await panggil(ctx, d.fn)
                jalan += 1
        except Exception:
            log.exception("job plugin %s '%s' gagal di ruang %s", pid, key, hid)
    return jalan


# ── nlp_kamus (txn_nlp) ──────────────────────────────────────────────────
def ada_kamus() -> bool:
    reg = registry()
    return any(m.contributes.nlp_kamus for m in reg.plugins.values())


async def kamus_ruang(db, household_id, user_id) -> list[tuple[str, list[str]]]:
    """Kamus kategori plugin yang aktif di ruang ini untuk user ini, urut id plugin. Tanpa user → kosong."""
    if household_id is None or user_id is None or not ada_kamus():
        return []
    out = []
    for m in await siklus.aktif_di_ruang(db, household_id, user_id):
        out.extend(m.contributes.nlp_kamus.items())
    return out


def tebak_kamus(kamus: list[tuple[str, list[str]]], deskripsi: str) -> str | None:
    desc = (deskripsi or "").lower()
    for kategori, kata in kamus:
        if any(k in desc for k in kata):
            return kategori
    return None


# ── form_fields (validasi; disimpan di U2) ───────────────────────────────
def _field_tidak_sah(detail: str):
    return siklus._galat(422, "field_tidak_sah", detail)


def _nilai_bawaan(tipe: str, nilai):
    if tipe in ("text", "select"):
        if not isinstance(nilai, str) or len(nilai) > 200:
            raise _field_tidak_sah("Isian harus teks, maksimal 200 karakter.")
        return nilai
    if tipe == "number":
        if isinstance(nilai, bool) or not isinstance(nilai, (int, str)):
            raise _field_tidak_sah("Isian harus angka.")
        try:
            return Decimal(str(nilai))
        except InvalidOperation:
            raise _field_tidak_sah("Isian harus angka.")
    if tipe == "reference":
        try:
            return UUID(str(nilai))
        except ValueError:
            raise _field_tidak_sah("Pilihan tidak dikenali.")
    raise _field_tidak_sah("Jenis isian tidak dikenali.")


async def periksa_field(db, user, household_id, target: str, kiriman: dict) -> dict:
    """`{plugin_id: {key: nilai}}` dari form inti → nilai bersih, atau 422. Hanya field plugin yang aktif di ruang
    ini dan tercantum di manifest untuk `target`; nilai dicek tipe bawaan, lalu fungsi `field_form` plugin."""
    if not kiriman:
        return {}
    if not isinstance(kiriman, dict):
        raise _field_tidak_sah("Isian tambahan tidak sah.")
    peran = await _peran(db, user.id, household_id)
    ruang = await _ruang(db, household_id)
    if peran is None or ruang is None:
        raise _field_tidak_sah("Isian tambahan tidak tersedia di ruang ini.")
    per_plugin: dict[str, dict[str, _Aktif]] = {}
    for a in await _fungsi_aktif(db, household_id, user.id, "field_form",
                                 lambda m: [f"{f.target}.{f.key}" for f in m.contributes.form_fields if f.target == target]):
        per_plugin.setdefault(a.m.id, {})[a.d.kunci.split(".", 1)[1]] = a
    bersih: dict[str, dict] = {}
    for pid, isian in kiriman.items():
        if pid not in per_plugin or not isinstance(isian, dict):
            raise _field_tidak_sah("Isian tambahan tidak tersedia di ruang ini.")
        for key, nilai in isian.items():
            a = per_plugin[pid].get(key)
            if a is None:
                raise _field_tidak_sah("Isian tambahan tidak tersedia di ruang ini.")
            spec = next(f for f in a.m.contributes.form_fields if f.target == target and f.key == key)
            if nilai is None:
                bersih.setdefault(pid, {})[key] = None       # field plugin selalu opsional
                continue
            nilai = _nilai_bawaan(spec.type, nilai)
            ctx = konteks(db, a.m, a.inst, ruang, a.d, viewer=user, peran=peran, sumber=f"field:{target}.{key}")
            try:
                bersih.setdefault(pid, {})[key] = await panggil(ctx, a.d.fn, nilai)
            except NilaiTidakSah as exc:
                raise _field_tidak_sah(f"{spec.label}: {str(exc)[:120] or 'tidak sah'}")
    return bersih
