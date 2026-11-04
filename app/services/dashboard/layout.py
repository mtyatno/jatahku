"""Tata letak Beranda (Plugin B1, 01-kajian.md "Penyimpanan tata letak" dan "Tata letak efektif
dihitung server", ADR-P8).

Dokumen: satu baris `dashboard_layouts` per (user, ruang, permukaan). Belum tersimpan → template
bawaan dengan `version` 0. Menyimpan selalu dokumen utuh dengan `if_version`; instans yang hilang
tanpa disebut di `removed` ditolak, supaya menyimpan dari satu perangkat tidak menghapus kartu
perangkat lain. Ruang = household user, ditentukan server (R2: `ruang_aktif`).
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models.models import DashboardLayout
from app.services import peran
from app.services.dashboard import registry


class GalatTataLetak(Exception):
    def __init__(self, status: int, kode: str, detail: str):
        super().__init__(detail)
        self.status, self.kode, self.detail = status, kode, detail


def _422(kode: str, detail: str) -> GalatTataLetak:
    return GalatTataLetak(422, kode, detail)


def efektif(surface: str, items: list[dict], parked: list[dict], version: int, *, karyawan: bool) -> dict:
    """Tata letak yang benar-benar tampil. Instans yang definisinya tidak ada lagi dipindah ke
    `parked` (posisinya kembali bila kartunya ada lagi). Semua instans yang tersisa dikirim,
    termasuk yang `visible: false`, dan wajib dikirim balik saat menyimpan.

    R6: kartu yang bukan untuk peran ini (kartu umum untuk karyawan, kartu karyawan untuk selain karyawan)
    tetap dikirim dengan `visible: false` dan `alasan`, tanpa data; `POST /dashboard/data` juga menolaknya."""
    aktif, parkir = [], [dict(p) for p in parked]
    for item in items:
        definisi = registry.get(item.get("card"))
        if definisi is None:
            parkir.append(dict(item))
            continue
        baris = {
            "id": item["id"], "card": item["card"], "size": item.get("size") or definisi.size_bawaan,
            "hidden": bool(item.get("hidden", False)), "devices": item.get("devices") or "all",
            "settings": item.get("settings") or {}, "visible": True,
        }
        if not registry.boleh(definisi, karyawan):
            baris.update(visible=False, alasan="khusus_admin" if karyawan else "khusus_karyawan")
        aktif.append(baris)
    return {"surface": surface, "schema_version": registry.SCHEMA_VERSION, "version": version,
            "items": aktif, "parked": parkir, "untuk": "karyawan" if karyawan else "umum"}


async def _muat(db, user_id, household_id, surface) -> DashboardLayout | None:
    return (await db.execute(select(DashboardLayout).where(
        DashboardLayout.user_id == user_id, DashboardLayout.household_id == household_id,
        DashboardLayout.surface == surface,
    ))).scalar_one_or_none()


async def peran_karyawan(db, user_id, household_id) -> bool:
    """Karyawan (peran `member` di ruang usaha) di ruang ini? Dihitung di sini, bukan diterima dari pemanggil
    (review keamanan PR #185 temuan 2)."""
    return household_id is not None and await peran.batasan_karyawan(db, user_id, household_id) is not None


async def ambil(db, user_id, household_id, surface: str) -> dict:
    karyawan = await peran_karyawan(db, user_id, household_id)
    row = await _muat(db, user_id, household_id, surface)
    if row is None:
        return efektif(surface, registry.template(surface, karyawan), [], 0, karyawan=karyawan)
    return efektif(surface, row.items or [], row.parked or [], row.version, karyawan=karyawan)


async def hapus_milik(db, user_id, household_id) -> None:
    """Tata letak user di satu ruang dibuang (peran berubah atau keluar dari ruang): Beranda berikutnya memakai
    template peran yang baru. Ikut commit pemanggil."""
    from sqlalchemy import delete
    await db.execute(delete(DashboardLayout).where(
        DashboardLayout.user_id == user_id, DashboardLayout.household_id == household_id))


def _rapikan(item, *, karyawan: bool) -> dict:
    """Satu instans dari klien → bentuk tersimpan, atau 422."""
    if not isinstance(item, dict):
        raise _422("instans_tidak_sah", "Bentuk kartu tidak dikenali.")
    iid, key = item.get("id"), item.get("card")
    if not isinstance(iid, str) or not registry.ID_RE.match(iid):
        raise _422("instans_tidak_sah", "ID kartu tidak sah.")
    definisi = registry.get(key) if isinstance(key, str) else None
    if definisi is None or not registry.boleh(definisi, karyawan):
        raise _422("kartu_tidak_dikenal", "Ada kartu yang tidak tersedia.")
    size = item.get("size", definisi.size_bawaan)
    if size not in definisi.sizes:
        raise _422("ukuran_tidak_sah", f"Ukuran {size} tidak tersedia untuk kartu {definisi.judul}.")
    devices = item.get("devices", "all")
    if devices not in registry.DEVICES:
        raise _422("instans_tidak_sah", "Pilihan perangkat tidak dikenali.")
    hidden = item.get("hidden", False)
    if not isinstance(hidden, bool):
        raise _422("instans_tidak_sah", "Nilai sembunyikan tidak sah.")
    settings = item.get("settings") or {}
    if not isinstance(settings, dict):
        raise _422("pengaturan_tidak_sah", "Pengaturan kartu tidak sah.")
    try:
        settings = definisi.validasi(settings)
    except registry.PengaturanTidakSah as exc:
        raise _422("pengaturan_tidak_sah", f"{definisi.judul}: {exc}") from None
    rapi = {"id": iid, "card": key, "size": size, "hidden": hidden, "devices": devices}
    if settings:
        rapi["settings"] = settings
    return rapi


def validasi(items: list, removed: list, sekarang: dict, *, karyawan: bool) -> tuple[list[dict], list[dict]]:
    """(items tersimpan, parked tersimpan) dari kiriman klien terhadap tata letak efektif `sekarang`.
    Kartu yang bukan untuk peran ini ditolak (`kartu_tidak_dikenal`), kecuali instans lama yang dikirim balik
    (`visible: false` di `sekarang`), supaya dokumen tidak kehilangan instans saat peran berganti. Instans lama itu
    disimpan dari salinan server, bukan dari isi klien (ukuran dan pengaturannya tidak bisa diubah; review PR #185 no. 3)."""
    if len(items) > registry.MAX_ITEMS:
        raise _422("terlalu_banyak", f"Beranda paling banyak {registry.MAX_ITEMS} kartu.")
    lama = {i["id"]: i for i in sekarang["items"] if not i.get("visible", True)}

    def _satu(item):
        if isinstance(item, dict) and item.get("id") in lama and lama[item["id"]]["card"] == item.get("card"):
            asli = lama[item["id"]]
            tersimpan = {k: asli[k] for k in ("id", "card", "size", "hidden", "devices")}
            if asli.get("settings"):
                tersimpan["settings"] = asli["settings"]
            return tersimpan
        return _rapikan(item, karyawan=karyawan)

    baru = [_satu(i) for i in items]
    ids = [i["id"] for i in baru]
    if len(set(ids)) != len(ids):
        raise _422("instans_tidak_sah", "Ada ID kartu ganda.")
    kunci = [i["card"] for i in baru if not registry.REGISTRY[i["card"]].multi_instance]
    if len(set(kunci)) != len(kunci):
        raise _422("kartu_ganda", "Kartu ini hanya boleh ada satu di Beranda.")
    if not all(isinstance(r, str) for r in removed):
        raise _422("instans_tidak_sah", "Daftar kartu yang dihapus tidak sah.")
    hilang = {i["id"] for i in sekarang["items"]} - set(ids) - set(removed)
    if hilang:
        raise _422("instans_hilang", "Tata letak berubah di perangkat lain. Muat ulang Beranda, lalu ulangi.")
    # Kartu parkir yang dikirim balik keluar dari parked; yang dihapus juga dibuang dari parked.
    parked = [p for p in sekarang["parked"] if p.get("id") not in set(ids) | set(removed)]
    return baru, parked


async def simpan(db, user_id, household_id, surface: str, if_version: int, items: list, removed: list) -> dict:
    sekarang = await ambil(db, user_id, household_id, surface)
    karyawan = sekarang["untuk"] == "karyawan"
    if if_version != sekarang["version"]:
        raise GalatTataLetak(409, "versi_beda", "Beranda sudah diubah di tempat lain. Muat ulang, lalu ulangi.")
    baru, parked = validasi(items, removed, sekarang, karyawan=karyawan)
    versi = if_version + 1
    if if_version == 0:
        db.add(DashboardLayout(user_id=user_id, household_id=household_id, surface=surface,
                               schema_version=registry.SCHEMA_VERSION, items=baru, parked=parked,
                               version=versi))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise GalatTataLetak(409, "versi_beda", "Beranda sudah diubah di tempat lain. Muat ulang, lalu ulangi.")
    else:
        hasil = await db.execute(
            update(DashboardLayout)
            .where(DashboardLayout.user_id == user_id, DashboardLayout.household_id == household_id,
                   DashboardLayout.surface == surface, DashboardLayout.version == if_version)
            .values(items=baru, parked=parked, version=versi, schema_version=registry.SCHEMA_VERSION)
            .execution_options(synchronize_session=False)
        )
        if hasil.rowcount != 1:
            await db.rollback()
            raise GalatTataLetak(409, "versi_beda", "Beranda sudah diubah di tempat lain. Muat ulang, lalu ulangi.")
        await db.commit()
    return efektif(surface, baru, parked, versi, karyawan=karyawan)
