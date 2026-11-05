"""Fitur Tambahan / plugin (Plugin H1; docs/plugin/04-kontrak-api.md §5).

- `GET /plugins` — katalog untuk ruang aktif (header `X-Jatahku-Ruang`, membaca). Di ruang usaha, karyawan ditolak
  gerbang R5 (403 `khusus_admin`, route ini tidak di `KARYAWAN_BOLEH`); di ruang keluarga semua anggota boleh melihat.
- `GET /plugins/contributions` (H3) — kontribusi plugin aktif untuk ruang aktif dan user ini; karyawan ditolak sama.
- `POST /ruang/{ruang_id}/plugins/{plugin_id}/pasang | lanjut | jeda | copot` — ruang dari **path**, lalu
  keanggotaan (bukan anggota → 404 seperti ruang tidak ada, supaya keberadaan ruang orang lain tidak bocor),
  lalu peran owner/admin (selain itu 403 `khusus_admin`, ADR-P11). Aturan plugin di `app/plugins/host/siklus.py`.
- `GET /ruang/{ruang_id}/plugins/{plugin_id}/ekspor?format=json|csv` (U1) — semua data tabel plugin di ruang itu,
  juga saat dijeda atau arsip (layar copot, ADR-P15); ruang dari path, owner/admin. CSV = ZIP satu berkas per tabel,
  sel teks dengan anti formula-injection (`export._csv_text`, PR #136).
- `/p/{plugin_id}/{path}` (U1, semua metode) — endpoint plugin dari manifest `routes` (`@plugin.rute`): ruang dari
  header (`ruang_aktif`; karyawan 403 lewat gerbang R5 karena route ini di luar `KARYAWAN_BOLEH`), plugin harus aktif
  di ruang itu untuk user ini, lalu fungsi plugin (`app/plugins/host/titik.jalankan_rute`). Data yang disentuh hanya
  tabel plugin sendiri di ruang itu (`ctx.data()`, `app/plugins/host/data.py`); objek baru tanpa induk memakai ruang
  header (R3 keputusan A), objek lama milik ruang lain = 404.

Router `/ruang` di sini hanya berisi rute plugin; `/ruang` milik R4 boleh menambah router lain di awalan yang sama.
"""
import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import HouseholdRole, User
from app.plugins.host import siklus
from app.services.ruang import RuangAktif, RuangDitolak, keanggotaan, ruang_jenis, ruang_objek

router = APIRouter()
ruang_router = APIRouter()
p_router = APIRouter()

PERAN_KELOLA = (HouseholdRole.owner, HouseholdRole.admin)
_PLUGIN_ID = Path(..., pattern=r"^[a-z][a-z0-9_]{1,29}$")


def _boleh_kelola(peran) -> bool:
    return peran in PERAN_KELOLA


@router.get("")
async def daftar_plugin(
    *,
    hid: RuangAktif,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if hid is None:
        return []
    anggota = await keanggotaan(db, user.id, hid)
    return await siklus.katalog(db, user, hid, await ruang_jenis(db, hid),
                                boleh_kelola=anggota is not None and _boleh_kelola(anggota.role))


@router.get("/contributions")
async def kontribusi_plugin(
    *,
    hid: RuangAktif,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Menu, aksi cepat, halaman, kartu, dan field form plugin yang aktif di ruang aktif untuk user ini (H3).

    Membaca (`ruang_aktif`, header). Karyawan ruang usaha ditolak gerbang R5 (403 `khusus_admin`, route ini tidak di
    `KARYAWAN_BOLEH`): selama H3 karyawan tidak mendapat kontribusi plugin apa pun (keputusan pembukaan sesi H3, B)."""
    from app.plugins.host import titik
    if hid is None:
        return siklus.kontribusi([], {})
    return siklus.kontribusi(await siklus.aktif_di_ruang(db, hid, user.id), await titik.kartu_ruang(db, user, hid))


async def _ruang_kelola(db: AsyncSession, user: User, ruang_id: str) -> tuple[UUID, str]:
    """Ruang dari path → keanggotaan → peran pengelola. Mengembalikan (household_id, jenis ruang)."""
    try:
        rid = UUID(ruang_id)
    except ValueError:
        rid = None
    hid = await ruang_objek(db, user, rid)
    if hid is None:
        raise RuangDitolak(kode="ruang_tidak_ada", detail="Ruang tidak ditemukan.", status_code=404)
    anggota = await keanggotaan(db, user.id, hid)
    if anggota is None or not _boleh_kelola(anggota.role):
        raise RuangDitolak(kode="khusus_admin", detail="Hanya pemilik dan admin ruang yang bisa mengatur Fitur Tambahan.")
    return hid, await ruang_jenis(db, hid)


class PasangIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pengaturan: dict | None = None
    # H3: kode izin yang ditampilkan di layar izin. Beda dengan manifest sekarang → 409 `izin_berubah`.
    izin: list[Annotated[str, StringConstraints(max_length=60)]] | None = Field(default=None, max_length=40)


@ruang_router.post("/{ruang_id}/plugins/{plugin_id}/pasang")
async def pasang_plugin(
    ruang_id: str,
    plugin_id: str = _PLUGIN_ID,
    body: PasangIn | None = Body(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid, jenis = await _ruang_kelola(db, user, ruang_id)
    m = siklus.manifest_atau_404(plugin_id)
    inst = await siklus.pasang(db, user, hid, jenis, m, pengaturan=(body.pengaturan if body else None),
                               izin=(body.izin if body else None))
    await db.commit()
    return siklus.ke_api(m, inst)


@ruang_router.post("/{ruang_id}/plugins/{plugin_id}/lanjut")
async def lanjut_plugin(
    ruang_id: str,
    plugin_id: str = _PLUGIN_ID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid, jenis = await _ruang_kelola(db, user, ruang_id)
    m = siklus.manifest_atau_404(plugin_id)
    inst = await siklus.lanjut(db, user, hid, jenis, m)
    await db.commit()
    return siklus.ke_api(m, inst)


@ruang_router.post("/{ruang_id}/plugins/{plugin_id}/jeda")
async def jeda_plugin(
    ruang_id: str,
    plugin_id: str = _PLUGIN_ID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid, _ = await _ruang_kelola(db, user, ruang_id)
    m = siklus.manifest_atau_404(plugin_id)
    inst = await siklus.jeda(db, user, hid, m)
    await db.commit()
    return siklus.ke_api(m, inst)


@ruang_router.post("/{ruang_id}/plugins/{plugin_id}/copot")
async def copot_plugin(
    ruang_id: str,
    plugin_id: str = _PLUGIN_ID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid, _ = await _ruang_kelola(db, user, ruang_id)
    m = siklus.manifest_atau_404(plugin_id)
    inst = await siklus.copot(db, user, hid, m)
    await db.commit()
    return {**siklus.ke_api(m, inst), "ekspor": _tautan_ekspor(m, hid)}


# ── ekspor data plugin (U1) ───────────────────────────────────────────────
def _tautan_ekspor(m, hid) -> dict | None:
    """Tautan unduh per format yang dinyatakan manifest (`data_lifecycle.export`); None bila plugin tanpa data."""
    if not m.entities or not m.data_lifecycle.export:
        return None
    return {f: f"/ruang/{hid}/plugins/{m.id}/ekspor?format={f}" for f in m.data_lifecycle.export}


def _nama_berkas(m, waktu: datetime, ext: str) -> str:
    return f"jatahku-{m.id}-{waktu.strftime('%Y%m%d-%H%M')}.{ext}"


@ruang_router.get("/{ruang_id}/plugins/{plugin_id}/ekspor")
async def ekspor_plugin(
    ruang_id: str,
    plugin_id: str = _PLUGIN_ID,
    format: str = Query("json", pattern=r"^(json|csv)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Semua baris hidup tabel plugin di ruang ini (ADR-P15: layar copot selalu menawarkan ekspor). Boleh saat aktif,
    dijeda, atau arsip; plugin yang belum pernah terpasang di ruang ini → 404 `plugin_tidak_aktif`."""
    from app.api.routes.export import _csv_text
    from app.plugins.host import data as data_plugin
    hid, _ = await _ruang_kelola(db, user, ruang_id)
    m = siklus.manifest_atau_404(plugin_id)
    inst = await siklus.instalasi(db, hid, m.id)
    if inst is None:
        raise RuangDitolak(kode="plugin_tidak_aktif", detail=f"{m.name} belum terpasang di ruang ini.", status_code=404)
    if not m.entities or format not in m.data_lifecycle.export:
        raise RuangDitolak(kode="format_tidak_tersedia", detail="Format unduhan ini tidak tersedia.", status_code=404)
    isi = await data_plugin.ekspor(db, m, hid)
    siklus._audit(db, hid, m.id, user.id, "ekspor", format=format, tabel={k: len(v) for k, v in isi.items()})
    await db.commit()
    waktu = datetime.now(timezone.utc)
    from app.plugins.host.titik import json_aman
    if format == "json":
        body = json.dumps({"plugin": m.id, "versi": m.version, "ruang_id": str(hid), "dibuat": waktu.isoformat(),
                           "data": json_aman(isi)}, ensure_ascii=False, indent=1)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{_nama_berkas(m, waktu, "json")}"'})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nama, baris in isi.items():
            teks = io.StringIO()
            kolom = list(baris[0].keys()) if baris else []
            w = csv.writer(teks, lineterminator="\n")
            w.writerow(kolom)
            for b in baris:
                w.writerow([_csv_text(_sel(v)) for v in b.values()])
            z.writestr(f"{nama}.csv", "\ufeff" + teks.getvalue())
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{_nama_berkas(m, waktu, "zip")}"'})


def _sel(v):
    """Nilai sel CSV: angka tetap angka; UUID, tanggal, Decimal sebagai teks."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "ya" if v else "tidak"
    if isinstance(v, int):
        return v
    from app.plugins.host.titik import json_aman
    return str(json_aman(v))


# ── endpoint plugin (U1) ──────────────────────────────────────────────────
from app.plugins.host.titik import MAKS_BODY_RUTE, MAKS_QUERY_RUTE  # noqa: E402


@p_router.api_route("/{plugin_id}/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
async def rute_plugin(
    request: Request,
    plugin_id: str = _PLUGIN_ID,
    path: str = Path(..., max_length=200),
    *,
    hid: RuangAktif,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Endpoint plugin (`@plugin.rute`): ruang dari header, user harus anggota (karyawan ditolak gerbang R5), plugin
    aktif di ruang itu. Body JSON ≤ 64 KB; query ≤ 20 parameter (nilai pertama)."""
    from app.plugins.host import titik
    if hid is None:
        raise RuangDitolak(kode="ruang_tidak_ada", detail="Ruang tidak ditemukan.", status_code=404)
    body = None
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        panjang = request.headers.get("content-length")
        if panjang and panjang.isdigit() and int(panjang) > MAKS_BODY_RUTE:
            raise RuangDitolak(kode="body_terlalu_besar", detail="Isian terlalu besar.", status_code=413)
        mentah = await request.body()
        if len(mentah) > MAKS_BODY_RUTE:
            raise RuangDitolak(kode="body_terlalu_besar", detail="Isian terlalu besar.", status_code=413)
        if mentah.strip():
            try:
                body = json.loads(mentah)
            except (ValueError, RecursionError):      # review #196 saran 4: JSON sangat bersarang → 422, bukan 500
                raise RuangDitolak(kode="body_bukan_json", detail="Isian tidak terbaca.", status_code=422)
            if not isinstance(body, (dict, list)):
                raise RuangDitolak(kode="body_bukan_json", detail="Isian tidak terbaca.", status_code=422)
    query = {}
    for k, v in request.query_params.items():
        if k in query:
            continue
        if len(query) >= MAKS_QUERY_RUTE or len(k) > 40:
            raise RuangDitolak(kode="query_terlalu_banyak", detail="Permintaan tidak sah.", status_code=422)
        query[k] = v[:200]
    hasil = await titik.jalankan_rute(db, user, hid, plugin_id, request.method, "/" + path, query, body)
    await db.commit()
    if hasil.status == 204:
        return Response(status_code=204)
    return JSONResponse(status_code=hasil.status, content=hasil.data)
