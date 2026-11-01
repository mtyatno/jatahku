"""Siklus status plugin per ruang (Plugin H1; 01-kajian.md "Siklus hidup", 04-kontrak-api.md §5).

Satu-satunya penulis `plugin_installations` dan `plugin_audit_log`. Route (`app/api/routes/plugins.py`)
menentukan ruang dari path dan memeriksa peran sebelum memanggil fungsi di sini; fungsi di sini memeriksa
aturan plugin (jenis ruang, flag, saklar darurat, requires, conflicts, perpindahan status).

    (tidak ada) ──pasang──▶ installed ──lanjut──▶ active ◀──lanjut── paused
                             │  (tanpa wizard: pasang langsung active)   ▲
                             └──────────jeda────────────▶ paused ◀─jeda─┘ (dari active)
    installed | active | paused ──copot──▶ uninstalled (arsip, purge_after = +90 hari)
    uninstalled ──pasang──▶ dipulihkan (data arsip kembali)   ·   purge_after lewat ──job──▶ baris dihapus

Aksi yang diulang pada status tujuannya tidak mengubah apa pun dan tidak menambah audit (idempoten,
aman untuk klik ganda dan kirim ulang aplikasi). Lanjut/jeda pada plugin yang belum terpasang atau
sudah diarsipkan → 404 `plugin_tidak_aktif`.

Saklar darurat (`AppSetting plugin_saklar_darurat`, daftar id dipisah koma) tidak mengubah status per
ruang: kontribusi plugin disembunyikan (`aktif_di_ruang`), pasang dan lanjut ditolak, jeda dan copot tetap
boleh (arah yang aman).

Hak (`entitlements`) hanya dibaca untuk katalog; selama beta tidak ada yang ditolak (ADR-P13, keputusan
R3 B). Penegakan `butuh_paket_usaha` (402) menyusul di V1.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AppSetting, Entitlement, PluginAuditLog, PluginInstallation
from app.plugins.host.manifest import Manifest
from app.plugins.host.registry import registry
from app.services.advisor.dashboard import flag_aktif
from app.services.ruang import RuangDitolak

SAKLAR_KEY = "plugin_saklar_darurat"
ARSIP_HARI = 90

INSTALLED, ACTIVE, PAUSED, UNINSTALLED = "installed", "active", "paused", "uninstalled"
# Nama status di API (04-kontrak-api.md §5).
STATUS_API = {None: "tersedia", INSTALLED: "terpasang", ACTIVE: "aktif", PAUSED: "dijeda", UNINSTALLED: "arsip"}


class GalatPlugin(RuangDitolak):
    """Galat dengan `detail` siap tampil dan `kode` untuk mesin (handler `ruang.install`)."""


def _galat(status: int, kode: str, detail: str) -> GalatPlugin:
    return GalatPlugin(kode=kode, detail=detail, status_code=status)


def _sekarang() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite mengembalikan datetime naif; PostgreSQL timestamptz sudah ber-zona.
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


# ── pengaturan global ────────────────────────────────────────────────────
async def _setting(db: AsyncSession, key: str) -> str | None:
    return (await db.execute(select(AppSetting.value).where(AppSetting.key == key))).scalar_one_or_none()


async def saklar_mati(db: AsyncSession) -> set[str]:
    """Id plugin yang sedang dimatikan server lewat saklar darurat."""
    raw = await _setting(db, SAKLAR_KEY) or ""
    return {x.strip() for x in raw.split(",") if x.strip()}


async def boleh_dilihat(db: AsyncSession, m: Manifest, user_id) -> bool:
    """Flag rollout per plugin (`plugin_<id>_users`: daftar user_id atau `*`)."""
    return flag_aktif(await _setting(db, m.flag_key), user_id)


# ── baca ────────────────────────────────────────────────────────────────
async def instalasi(db: AsyncSession, household_id: UUID, plugin_id: str, *, kunci: bool = False):
    q = select(PluginInstallation).where(
        PluginInstallation.household_id == household_id,
        PluginInstallation.plugin_id == plugin_id,
        PluginInstallation.owner_id.is_(None),
    )
    if kunci:
        q = q.with_for_update()
    return (await db.execute(q)).scalar_one_or_none()


async def _instalasi_ruang(db: AsyncSession, household_id: UUID) -> dict[str, PluginInstallation]:
    rows = (await db.execute(select(PluginInstallation).where(
        PluginInstallation.household_id == household_id, PluginInstallation.owner_id.is_(None),
    ))).scalars()
    return {r.plugin_id: r for r in rows}


async def hak(db: AsyncSession, household_id: UUID, m: Manifest) -> dict:
    """Hak ruang atas SKU plugin, untuk ditampilkan. Tidak menolak apa pun selama beta."""
    if m.entitlement is None:
        return {"status": "gratis", "sampai": None}
    now = _sekarang()
    rows = (await db.execute(select(Entitlement).where(
        Entitlement.household_id == household_id,
        Entitlement.sku == m.entitlement.sku,
        Entitlement.status == "aktif",
    ))).scalars().all()
    berlaku = [r for r in rows if _aware(r.starts_at) <= now and (r.ends_at is None or _aware(r.ends_at) > now)]
    if berlaku:
        sampai = [_aware(r.ends_at) for r in berlaku]
        akhir = None if any(s is None for s in sampai) else max(sampai).date().isoformat()
        return {"status": "aktif", "sampai": akhir}
    return {"status": "uji_coba", "sampai": None}   # beta: uji coba gratis untuk semua ruang usaha (ADR-P13)


def ke_api(m: Manifest, inst: PluginInstallation | None) -> dict:
    status = inst.status if inst is not None else None
    arsip = _aware(inst.purge_after) if inst is not None and status == UNINSTALLED else None
    return {
        "plugin": m.id,
        "status": STATUS_API[status],
        "arsip_sampai": arsip.date().isoformat() if arsip else None,
        "izin_diberikan": list(inst.granted_permissions or []) if inst is not None and status != UNINSTALLED else [],
    }


async def katalog(db: AsyncSession, user, household_id: UUID, jenis_ruang: str, *, boleh_kelola: bool) -> list[dict]:
    """`GET /plugins`: plugin yang cocok dengan jenis ruang dan flag user, ditambah plugin yang sudah
    punya baris instalasi di ruang ini (supaya tetap bisa dijeda atau dicopot walau flag dicabut)."""
    terpasang = await _instalasi_ruang(db, household_id)
    mati = await saklar_mati(db)
    hasil = []
    for m in registry().semua():
        inst = terpasang.get(m.id)
        if inst is None and (jenis_ruang not in m.space_types or not await boleh_dilihat(db, m, user.id)):
            continue
        hasil.append({
            "id": m.id, "nama": m.name, "versi": m.version, "deskripsi": m.description,
            "ikon": m.icon, "kategori": m.category, "jenis_ruang": list(m.space_types),
            **{k: v for k, v in ke_api(m, inst).items() if k != "plugin"},
            "izin": m.izin_tampil(),
            "kartu": [{"key": k.key, "judul": k.title, "bawaan": k.default} for k in m.contributes.cards],
            "hak": await hak(db, household_id, m),
            "butuh": list(m.requires),
            "diperbaiki": m.id in mati,
            "boleh_kelola": boleh_kelola,
        })
    return hasil


async def aktif_di_ruang(db: AsyncSession, household_id: UUID, user_id) -> list[Manifest]:
    """Plugin yang kontribusinya boleh tampil di ruang ini untuk user ini: berstatus `active`, tidak
    terkena saklar darurat, flag user aktif, dan masih dimuat registry. Dipakai H2/H3 (kartu, menu,
    perintah, job) — plugin dijeda, dicopot, atau dimatikan server tidak meninggalkan apa pun."""
    mati = await saklar_mati(db)
    hasil = []
    for pid, inst in sorted((await _instalasi_ruang(db, household_id)).items()):
        m = registry().get(pid)
        if inst.status != ACTIVE or m is None or pid in mati or not await boleh_dilihat(db, m, user_id):
            continue
        hasil.append(m)
    return hasil


# ── tulis ───────────────────────────────────────────────────────────────
def _audit(db: AsyncSession, household_id, plugin_id, actor_id, aksi: str, **detail):
    db.add(PluginAuditLog(household_id=household_id, plugin_id=plugin_id, actor_id=actor_id,
                          action=aksi, detail=detail))


def manifest_atau_404(plugin_id: str) -> Manifest:
    m = registry().get(plugin_id)
    if m is None:
        raise _galat(404, "plugin_tidak_ada", "Fitur Tambahan ini tidak ditemukan.")
    return m


async def _cek_boleh_menyala(db: AsyncSession, household_id: UUID, jenis_ruang: str, m: Manifest):
    """Syarat bersama pasang/pulihkan/lanjut: arah yang menyalakan plugin."""
    if m.id in await saklar_mati(db):
        raise _galat(503, "plugin_diperbaiki", f"{m.name} sedang diperbaiki. Coba lagi nanti.")
    if jenis_ruang not in m.space_types:
        raise _galat(422, "jenis_ruang_tidak_cocok", f"{m.name} tidak tersedia untuk ruang jenis ini.")
    terpasang = await _instalasi_ruang(db, household_id)
    kurang = [r for r in m.requires if getattr(terpasang.get(r), "status", None) != ACTIVE]
    if kurang:
        nama = ", ".join((registry().get(r).name if registry().get(r) else r) for r in kurang)
        raise _galat(409, "butuh_plugin", f"Aktifkan dulu {nama} di ruang ini.")
    bentrok = [pid for pid, inst in terpasang.items() if inst.status != UNINSTALLED and pid != m.id and (
        pid in m.conflicts or (registry().get(pid) is not None and m.id in registry().get(pid).conflicts))]
    if bentrok:
        nama = ", ".join((registry().get(p).name if registry().get(p) else p) for p in bentrok)
        raise _galat(409, "bentrok_plugin", f"{m.name} tidak bisa dipakai bersama {nama}.")


async def pasang(db: AsyncSession, user, household_id: UUID, jenis_ruang: str, m: Manifest,
                 *, pengaturan: dict | None = None) -> PluginInstallation:
    """Pasang baru, atau pulihkan dari arsip. Sudah terpasang/aktif/dijeda → dikembalikan apa adanya."""
    if pengaturan:
        # Form pengaturan dari JSON Schema + validasi server adalah titik `settings` (H2/U1).
        raise _galat(422, "pengaturan_tidak_sah", "Pengaturan Fitur Tambahan belum bisa diisi saat memasang.")
    inst = await instalasi(db, household_id, m.id, kunci=True)
    if inst is not None and inst.status != UNINSTALLED:
        return inst
    if not await boleh_dilihat(db, m, user.id):
        raise _galat(404, "plugin_tidak_ada", "Fitur Tambahan ini tidak ditemukan.")
    await _cek_boleh_menyala(db, household_id, jenis_ruang, m)

    tujuan = INSTALLED if m.contributes.setup else ACTIVE
    if inst is None:
        inst = PluginInstallation(household_id=household_id, plugin_id=m.id, status=tujuan,
                                  installed_by=user.id, granted_permissions=list(m.permissions), settings={})
        db.add(inst)
        _audit(db, household_id, m.id, user.id, "pasang", ke=tujuan, izin=list(m.permissions), versi=m.version)
        try:
            await db.flush()
        except IntegrityError:
            # Dua permintaan pasang bersamaan: indeks unik menolak yang kedua; kembalikan yang menang.
            await db.rollback()
            ada = await instalasi(db, household_id, m.id)
            if ada is None:
                raise
            return ada
    else:
        # Pulihkan: data arsip kembali; izin disetujui ulang sesuai manifest versi sekarang.
        inst.status = tujuan
        inst.uninstalled_at = None
        inst.purge_after = None
        inst.disabled_reason = None
        inst.installed_by = user.id
        inst.granted_permissions = list(m.permissions)
        _audit(db, household_id, m.id, user.id, "pulihkan", dari=UNINSTALLED, ke=tujuan,
               izin=list(m.permissions), versi=m.version)
        await db.flush()
    return inst


def _404_tidak_aktif(m: Manifest) -> GalatPlugin:
    return _galat(404, "plugin_tidak_aktif", f"{m.name} belum terpasang di ruang ini.")


async def lanjut(db: AsyncSession, user, household_id: UUID, jenis_ruang: str, m: Manifest) -> PluginInstallation:
    """installed (wizard selesai/dilewati) atau paused → active."""
    inst = await instalasi(db, household_id, m.id, kunci=True)
    if inst is None or inst.status == UNINSTALLED:
        raise _404_tidak_aktif(m)
    if inst.status == ACTIVE:
        return inst
    await _cek_boleh_menyala(db, household_id, jenis_ruang, m)
    dari, inst.status, inst.disabled_reason = inst.status, ACTIVE, None
    _audit(db, household_id, m.id, user.id, "lanjut", dari=dari, ke=ACTIVE)
    await db.flush()
    return inst


async def _pemakai(db: AsyncSession, household_id: UUID, m: Manifest, status: tuple[str, ...]) -> list[str]:
    """Plugin di ruang ini yang membutuhkan `m` dan berstatus salah satu dari `status`."""
    terpasang = await _instalasi_ruang(db, household_id)
    return [p for p in registry().dibutuhkan_oleh(m.id) if getattr(terpasang.get(p), "status", None) in status]


async def jeda(db: AsyncSession, user, household_id: UUID, m: Manifest) -> PluginInstallation:
    """installed atau active → paused. Data tetap, kontribusi hilang."""
    inst = await instalasi(db, household_id, m.id, kunci=True)
    if inst is None or inst.status == UNINSTALLED:
        raise _404_tidak_aktif(m)
    if inst.status == PAUSED:
        return inst
    pemakai = await _pemakai(db, household_id, m, (ACTIVE, INSTALLED))
    if pemakai:
        nama = ", ".join(registry().get(p).name for p in pemakai)
        raise _galat(409, "dibutuhkan_plugin_lain", f"Jeda dulu {nama}, yang memakai {m.name}.")
    dari, inst.status, inst.disabled_reason = inst.status, PAUSED, "user"
    _audit(db, household_id, m.id, user.id, "jeda", dari=dari, ke=PAUSED)
    await db.flush()
    return inst


async def copot(db: AsyncSession, user, household_id: UUID, m: Manifest) -> PluginInstallation:
    """installed, active, atau paused → uninstalled (arsip 90 hari). Data inti (transaksi, pemasukan) tidak
    pernah ikut terhapus; data `p_<id>_*` dihapus job pembersih setelah `purge_after` (ADR-P15)."""
    inst = await instalasi(db, household_id, m.id, kunci=True)
    if inst is None:
        raise _404_tidak_aktif(m)
    if inst.status == UNINSTALLED:
        return inst
    pemakai = await _pemakai(db, household_id, m, (ACTIVE, INSTALLED, PAUSED))
    if pemakai:
        nama = ", ".join(registry().get(p).name for p in pemakai)
        raise _galat(409, "dibutuhkan_plugin_lain", f"Copot dulu {nama}, yang memakai {m.name}.")
    now = _sekarang()
    dari = inst.status
    inst.status, inst.disabled_reason = UNINSTALLED, "user"
    inst.uninstalled_at, inst.purge_after = now, now + timedelta(days=ARSIP_HARI)
    _audit(db, household_id, m.id, user.id, "copot", dari=dari, ke=UNINSTALLED,
           arsip_sampai=inst.purge_after.date().isoformat())
    await db.flush()
    return inst


async def bersihkan_kedaluwarsa(db: AsyncSession, now: datetime | None = None) -> list[tuple[UUID, str]]:
    """Hapus baris instalasi yang arsipnya lewat `purge_after`. Mengembalikan (ruang, plugin) yang dihapus.

    BELUM dijadwalkan di H1: ADR-P15 mewajibkan pemberitahuan 7 hari sebelum penghapusan, dan penghapusan
    data `p_<id>_*` lewat hook plugin. Keduanya datang bersama plugin pertama (H2 `notifications`/`jobs`,
    U1 tabel Buku Usaha); job harian memanggil fungsi ini sesudahnya."""
    now = now or _sekarang()
    rows = (await db.execute(select(PluginInstallation).where(
        PluginInstallation.status == UNINSTALLED,
        PluginInstallation.purge_after.is_not(None),
    ))).scalars().all()
    hapus = [r for r in rows if _aware(r.purge_after) <= now]
    for r in hapus:
        _audit(db, r.household_id, r.plugin_id, None, "bersihkan", dari=UNINSTALLED)
    if hapus:
        await db.execute(delete(PluginInstallation).where(PluginInstallation.id.in_([r.id for r in hapus])))
        await db.flush()
    return [(r.household_id, r.plugin_id) for r in hapus]
