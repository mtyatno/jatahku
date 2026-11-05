"""API laporan berkala (spec 2026-11-01-laporan-berkala-design bagian 4, 7, dan 8; tahap 1, Task 7).

Dua router, keduanya dipasang di main.py: `router` di `/laporan` (daftar, detail, unduh PDF) dan `pengaturan_router` di
`/user` (`/laporan-pengaturan`: status dan kata sandi PDF). Semua endpoint baru, jadi API hanya bertambah.

Yang dijaga di sini (tes: app/tests/test_laporan_api.py):
- Laporan hanya milik pemanggil. Satu kueri `id` dan `user_id` pemanggil; keanggotaan household tidak dipakai sama
  sekali. "Tidak ada" dan "milik orang lain" memberi jawaban dan kueri yang sama (404), tanpa kueri tambahan yang
  waktunya membedakan.
- Kata sandi laporan masuk sebagai NFC, diperiksa `pdf.periksa_kata_sandi`, dan disimpan hanya sebagai token Fernet
  (`rahasia`). Respons tidak pernah memuat kata sandi atau token. Galat validasi dibersihkan dari `input` (bawaan
  FastAPI memantulkan nilai yang ditolak), dan log hanya berisi teks tetap dan id user. Setiap 422 yang bisa dipicu
  formulir kata sandi (panjang, karakter yang tak bisa dipakai di PDF) membawa `detail` berupa kalimat siap tampil.
- PDF dibuat saat diminta, hanya di memori, dengan `Cache-Control: no-store`. Koneksi database dilepas sebelum render.
- Batas frekuensi per user yang terautentikasi (`kunci_per_user`, ruling R11: klaim `sub` access token, bukan teks
  header; limiter slowapi bersama seperti `user_settings.py`): unduh PDF 10/menit untuk semua laporannya sekaligus
  (lihat `SCOPE_BATAS_PDF`), simpan kata sandi 5/jam.

`GET /user/laporan-pengaturan` menjawab `kata_sandi_diatur: false` bila kata sandi tersimpan tak terbaca atau kini
ditolak, sama dengan jalur unduh PDF yang menjawab 409; tanpa kunci server tetap seperti ada tidaknya token.

Galat yang membawa `kode` untuk mesin (badan persis, Global Constraints): 409 `kata_sandi_belum_diatur` (belum diatur,
atau yang tersimpan tidak terbaca atau tidak lagi bisa dipakai) dan 503 `kunci_belum_diatur` (REPORT_SECRET_KEY kosong
atau tidak valid di server).
"""
import logging
import unicodedata
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import limiter
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.rate_limit import kunci_per_user
from app.models.models import Report, ReportSettings, User
from app.services.laporan import antrean_email, hitung, pdf, rahasia, surel

logger = logging.getLogger("jatahku.laporan")

MIN_KATA_SANDI = 6
MAKS_KATA_SANDI = 64
MAKS_OFFSET = 100_000   # batas wajar; asyncpg mengikat OFFSET sebagai INTEGER (32-bit), lebih dari itu galat 500
# Limiter bersama bawaan slowapi (`key_style="url"`) menghitung `limit()` per URL persis, jadi di
# `/laporan/{report_id}/pdf` batas 10/menit berlaku per laporan, bukan per user: laporan yang berbeda tidak pernah
# saling membatasi. `shared_limit` dengan `scope` tetap menghitung semua laporan satu user dalam satu ember.
SCOPE_BATAS_PDF = "laporan_pdf"
MSG_TIDAK_DITEMUKAN = "Laporan tidak ditemukan"
MSG_PANJANG = f"Kata sandi laporan harus {MIN_KATA_SANDI}–{MAKS_KATA_SANDI} karakter."
_GALAT_PANJANG = {"string_too_short", "string_too_long"}   # jenis galat pydantic untuk `Field(min_length, max_length)`
# Peringatan untuk kata sandi tersimpan yang tak bisa dipakai (jalur unduh PDF dan GET status): teks tetap dan id user.
LOG_TOKEN_TAK_TERBACA = (
    "Kata sandi laporan user %s tersimpan tetapi tidak terbaca (kunci diganti atau data rusak); "
    "diperlakukan seperti belum diatur"
)
LOG_KATA_SANDI_TAK_VALID = (
    "Kata sandi laporan user %s tersimpan tetapi tidak bisa dipakai untuk PDF; diperlakukan seperti belum diatur"
)
# Isi GET tanpa baris `report_settings`. Harus sama dengan bawaan kolom ReportSettings (dijaga tes).
BAWAAN_PENGATURAN = {"email_on": True, "kuartalan_on": True, "tahunan_on": True}


class LaporanRingkas(BaseModel):
    id: UUID
    jenis: str
    judul: str
    periode_mulai: date
    periode_akhir: date
    terbit_at: datetime
    nama_file: str


class LaporanDetail(LaporanRingkas):
    data: dict


class PengaturanLaporan(BaseModel):
    kata_sandi_diatur: bool
    email: str | None
    email_terverifikasi: bool
    email_on: bool
    kuartalan_on: bool
    tahunan_on: bool
    pro: bool


class KataSandiLaporanIn(BaseModel):
    kata_sandi: str = Field(min_length=MIN_KATA_SANDI, max_length=MAKS_KATA_SANDI)


class UbahPengaturanLaporan(BaseModel):
    """Badan `PATCH /user/laporan-pengaturan`: hanya yang dikirim yang berubah. Tahap 2 hanya `email_on`; tahap 3
    menambah `kuartalan_on` dan `tahunan_on` di sini. Badan tanpa satu pun field, `null`, atau field asing = 422."""
    model_config = ConfigDict(extra="forbid")
    email_on: bool | None = None

    @model_validator(mode="after")
    def _minimal_satu(self):
        if not self.perubahan():
            raise ValueError("Kirim minimal satu pengaturan yang diubah.")
        return self

    def perubahan(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class GalatKode(BaseModel):
    detail: str
    kode: str


class GalatValidasiItem(BaseModel):
    type: str
    loc: list[str | int]
    msg: str


class GalatValidasi(BaseModel):
    """Isi 422 di `PUT /user/laporan-pengaturan`: `detail` berupa kalimat siap tampil untuk yang bisa dipicu formulir
    (panjang, karakter yang tak bisa dipakai di PDF), atau daftar `{type, loc, msg}` untuk badan yang salah bentuk."""
    detail: str | list[GalatValidasiItem]


class _RuteTanpaGemaMasukan(APIRoute):
    """Route yang galat validasinya tidak memantulkan nilai yang dikirim. Galat 422 bawaan FastAPI memuat `input`, yaitu
    nilai yang ditolak; untuk badan berisi kata sandi itu berarti kata sandinya ikut di respons. Yang dikembalikan
    hanya `type`, `loc`, dan `msg` (daftar yang sama dengan bawaan, tanpa `input`, `ctx`, dan `url`).

    Kecuali panjang `kata_sandi` yang salah: itu satu-satunya galat yang bisa dipicu formulir (HTML menghitung panjang
    dalam unit UTF-16, pydantic dalam titik kode: tiga emoji lolos `minLength=6` tetapi hanya tiga karakter), jadi
    jawabannya kalimat siap tampil yang sama dengan pemeriksaan panjang setelah NFC di route (`MSG_PANJANG`)."""

    def get_route_handler(self):
        asli = super().get_route_handler()

        async def tangani(request: Request) -> Response:
            try:
                return await asli(request)
            except RequestValidationError as exc:
                galat = [{k: e[k] for k in ("type", "loc", "msg") if k in e} for e in exc.errors()]
                if galat and all(
                    g.get("type") in _GALAT_PANJANG and tuple(g.get("loc", ())) == ("body", "kata_sandi")
                    for g in galat
                ):
                    return JSONResponse(status_code=422, content={"detail": MSG_PANJANG})
                return JSONResponse(status_code=422, content={"detail": galat})

        return tangani


router = APIRouter()
pengaturan_router = APIRouter(route_class=_RuteTanpaGemaMasukan)


def _galat(status: int, kode: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "kode": kode})


def _kata_sandi_belum_diatur() -> JSONResponse:
    return _galat(409, "kata_sandi_belum_diatur", "Atur kata sandi laporan dulu untuk mengunduh PDF.")


def _kunci_belum_diatur() -> JSONResponse:
    return _galat(503, "kunci_belum_diatur", "Kata sandi laporan belum bisa dipakai di server. Coba lagi nanti.")


def _ringkas(id_laporan: UUID, jenis: str, judul: str, periode_mulai: date, periode_akhir: date,
             terbit_at: datetime) -> dict:
    return {
        "id": id_laporan, "jenis": jenis, "judul": judul, "periode_mulai": periode_mulai,
        "periode_akhir": periode_akhir, "terbit_at": terbit_at,
        "nama_file": hitung.nama_file_pdf(jenis, periode_mulai, periode_akhir),
    }


async def _laporan_milik(db: AsyncSession, user_id: UUID, report_id: UUID) -> Report:
    """Laporan `report_id` milik `user_id`, atau 404. Satu kueri dengan dua syarat: laporan orang lain tidak pernah
    dibaca (apalagi dibandingkan di Python), dan "tidak ada" memberi jawaban serta kueri yang sama."""
    laporan = (await db.execute(
        select(Report).where(Report.id == report_id, Report.user_id == user_id)
    )).scalar_one_or_none()
    if laporan is None:
        raise HTTPException(status_code=404, detail=MSG_TIDAK_DITEMUKAN)
    return laporan


def _bentuk_pengaturan(user: User, pengaturan: ReportSettings | None) -> dict:
    """Isi GET dan PUT `/user/laporan-pengaturan`. Tanpa baris = bawaan. Tidak pernah memuat kata sandi atau token:
    hanya apakah ada."""
    nilai = BAWAAN_PENGATURAN if pengaturan is None else {k: getattr(pengaturan, k) for k in BAWAAN_PENGATURAN}
    return {
        "kata_sandi_diatur": pengaturan is not None and pengaturan.kata_sandi_enc is not None,
        "email": user.email,
        "email_terverifikasi": user.email_verified_at is not None,
        **nilai,
        "pro": user.plan == "pro",
    }


def _jawab_pengaturan(user: User, pengaturan: ReportSettings | None) -> dict:
    """Isi GET dan PATCH: `kata_sandi_diatur` true hanya bila kata sandi tersimpan benar-benar bisa dipakai."""
    bentuk = _bentuk_pengaturan(user, pengaturan)
    if bentuk["kata_sandi_diatur"] and not _token_masih_terpakai(user.id, pengaturan.kata_sandi_enc):
        bentuk["kata_sandi_diatur"] = False
    return bentuk


def _token_masih_terpakai(user_id: UUID, token: str) -> bool:
    """Apakah token tersimpan masih bisa membuka PDF: terbaca dengan kunci server sekarang dan kata sandinya masih
    lolos `periksa_kata_sandi`. Sama dengan syarat jalur unduh PDF (409 bila tidak). Tanpa kunci server pemeriksaan
    tidak mungkin, jadi dianggap masih terpakai (jalur unduh menjawab 503 untuk itu). Hanya teks tetap dan id user yang
    dicatat."""
    try:
        kata_sandi = rahasia.dekripsi(token)
    except rahasia.KunciLaporanTidakAda:
        return True
    except ValueError:
        logger.warning(LOG_TOKEN_TAK_TERBACA, user_id)
        return False
    try:
        pdf.periksa_kata_sandi(kata_sandi)
    except pdf.KataSandiPdfTidakValid:
        logger.warning(LOG_KATA_SANDI_TAK_VALID, user_id)
        return False
    return True


def _kunci_user(user_id: UUID):
    """Kueri pengunci baris `users` (Postgres: FOR NO KEY UPDATE, pola `fund_shift` dan `balance_check`)."""
    return select(User.id).where(User.id == user_id).with_for_update(key_share=True)


async def _simpan_pengaturan(db: AsyncSession, user_id: UUID, **ubah) -> ReportSettings:
    """Upsert `report_settings` user ini (PUT kata sandi, PATCH saklar, dan berhenti berlangganan): baris dibuat saat
    pertama kali disimpan dengan bawaan; setelah itu hanya kolom di `ubah` dan `updated_at` yang berubah (yang lain
    dibiarkan). Baris `users` dikunci dulu: dua simpan pertama yang bersamaan sama-sama tidak menemukan baris lalu
    INSERT, dan yang kalah gagal di kunci utama (500). Dengan kunci, yang kalah menunggu, lalu menemukan baris yang
    baru dibuat dan memperbaruinya. `email_on` dinyalakan → laporan yang dilewati karena `dimatikan` dan masih dalam
    jendela terbit kembali `menunggu` (keputusan rencana 2), dalam transaksi yang sama."""
    await db.execute(_kunci_user(user_id))
    pengaturan = await db.get(ReportSettings, user_id)
    if pengaturan is None:
        pengaturan = ReportSettings(user_id=user_id, **{**BAWAAN_PENGATURAN, **ubah})
        db.add(pengaturan)
    else:
        for kolom, nilai in ubah.items():
            setattr(pengaturan, kolom, nilai)
        pengaturan.updated_at = datetime.now(timezone.utc)
    if ubah.get("email_on") is True:
        await antrean_email.hidupkan_lagi(db, user_id, (antrean_email.ALASAN_DIMATIKAN,))
    await db.commit()
    return pengaturan


# --- /laporan ---------------------------------------------------------------------------------------------------


@router.get("", response_model=list[LaporanRingkas])
async def daftar_laporan(
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0, le=MAKS_OFFSET),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Laporan milik pemanggil, yang terbit paling akhir di atas (lalu periode paling baru), berhalaman. Tanpa `data`:
    `judul` dibaca langsung dari JSON-nya oleh database, jadi ratusan baris mutasi per laporan tidak ikut terbaca."""
    baris = (await db.execute(
        select(
            Report.id, Report.jenis, Report.periode_mulai, Report.periode_akhir, Report.terbit_at,
            Report.data["judul"].as_string().label("judul"),
        )
        .where(Report.user_id == user.id)
        .order_by(Report.terbit_at.desc(), Report.periode_mulai.desc(), Report.id)   # `id`: halaman tetap stabil
        .limit(limit)
        .offset(offset)
    )).all()
    return [_ringkas(b.id, b.jenis, b.judul, b.periode_mulai, b.periode_akhir, b.terbit_at) for b in baris]


# --- /laporan/berhenti-email (tanpa login; token bertanda tangan) ---------------------------------------------------
# Dideklarasikan SEBELUM `/{report_id}`: kalau tidak, "berhenti-email" ditelan sebagai report_id (422).
# GET hanya menampilkan konfirmasi dan tidak mengubah apa pun (pemindai tautan di layanan email membuka GET); hanya POST
# (tombol halaman dan one-click RFC 8058) mematikan `email_on`. Batas 30/menit per IP (kunci bawaan limiter).
_KEPALA_HALAMAN = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}   # alamatnya memuat token


def _halaman(html: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(html, status_code=status, headers=_KEPALA_HALAMAN)


@router.get(
    "/berhenti-email",
    response_class=HTMLResponse,
    responses={400: {"description": "Tautan tidak berlaku.", "content": {"text/html": {}}},
               429: {"description": "Lebih dari 30 permintaan per menit."}},
)
@limiter.shared_limit("30/minute", scope="berhenti_email_get")   # ember GET dan POST terpisah (satu URL)
async def halaman_berhenti_email(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    """Halaman konfirmasi (200), atau 400 bila token tidak sah atau akunnya sudah tidak ada. Tidak mengubah apa pun."""
    user_id = surel.baca_token_berhenti(token)
    if user_id is None or await db.get(User, user_id) is None:
        return _halaman(surel.halaman_tautan_tak_berlaku(), 400)
    return _halaman(surel.halaman_konfirmasi_berhenti(token))


@router.post(
    "/berhenti-email",
    response_class=HTMLResponse,
    responses={400: {"description": "Tautan tidak berlaku.", "content": {"text/html": {}}},
               429: {"description": "Lebih dari 30 permintaan per menit."}},
)
@limiter.shared_limit("30/minute", scope="berhenti_email_post")
async def berhenti_email(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    """Matikan `email_on` user pada token. Menerima tombol halaman (badan kosong) dan one-click RFC 8058
    (`List-Unsubscribe=One-Click`, form); badan tidak dibaca. Aman diulang."""
    user_id = surel.baca_token_berhenti(token)
    if user_id is None or await db.get(User, user_id) is None:
        return _halaman(surel.halaman_tautan_tak_berlaku(), 400)
    await _simpan_pengaturan(db, user_id, email_on=False)
    return _halaman(surel.halaman_berhenti_selesai())


@router.get("/{report_id}", response_model=LaporanDetail, responses={404: {"description": MSG_TIDAK_DITEMUKAN}})
async def detail_laporan(
    report_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Laporan lengkap (`data` v1 yang dibekukan saat terbit). Bukan milik pemanggil atau tidak ada: 404 yang sama."""
    laporan = await _laporan_milik(db, user.id, report_id)
    return {
        **_ringkas(laporan.id, laporan.jenis, laporan.data["judul"], laporan.periode_mulai, laporan.periode_akhir,
                   laporan.terbit_at),
        "data": laporan.data,
    }


@router.get(
    "/{report_id}/pdf",
    response_class=Response,
    responses={
        200: {
            "description": "PDF laporan, dienkripsi AES-256 dengan kata sandi laporan user.",
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        },
        404: {"description": MSG_TIDAK_DITEMUKAN},
        409: {"model": GalatKode, "description": "Kata sandi laporan belum diatur (kode `kata_sandi_belum_diatur`)."},
        503: {"model": GalatKode, "description": "Kunci server belum diatur (kode `kunci_belum_diatur`)."},
    },
)
@limiter.shared_limit("10/minute", scope=SCOPE_BATAS_PDF, key_func=kunci_per_user)
async def unduh_pdf_laporan(
    request: Request,
    report_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """PDF berkata sandi untuk laporan milik pemanggil, dibuat saat diminta dan tidak pernah disimpan. Urutan jawaban:
    404 (bukan milik atau tidak ada) lebih dulu, lalu 503 (kunci server tidak ada), lalu 409 (kata sandi belum diatur,
    tidak terbaca, atau tidak lagi bisa dipakai di PDF; dua yang terakhir dicatat sebagai peringatan tanpa rahasia)."""
    user_id = user.id
    laporan = await _laporan_milik(db, user_id, report_id)
    if not rahasia.kunci_tersedia():
        return _kunci_belum_diatur()
    pengaturan = await db.get(ReportSettings, user_id)
    token = None if pengaturan is None else pengaturan.kata_sandi_enc
    if token is None:
        return _kata_sandi_belum_diatur()
    data = laporan.data
    nama_file = hitung.nama_file_pdf(laporan.jenis, laporan.periode_mulai, laporan.periode_akhir)
    # Semua yang dibutuhkan sudah terbaca. Render menunggu giliran semaphore (paling banyak dua sekaligus) dan makan
    # ratusan milidetik; koneksi dari kolam (dipakai seluruh API) tidak boleh tertahan selama itu.
    await db.close()
    try:
        kata_sandi = rahasia.dekripsi(token)
    except rahasia.KunciLaporanTidakAda:
        return _kunci_belum_diatur()
    except ValueError:
        logger.warning(LOG_TOKEN_TAK_TERBACA, user_id)
        return _kata_sandi_belum_diatur()
    try:
        isi = await pdf.buat_pdf(data, kata_sandi)
    except pdf.KataSandiPdfTidakValid:   # subkelas ValueError: tidak lewat penanganan ValueError umum
        logger.warning(LOG_KATA_SANDI_TAK_VALID, user_id)
        return _kata_sandi_belum_diatur()
    return Response(
        content=isi,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nama_file}"', "Cache-Control": "no-store"},
    )


# --- /user/laporan-pengaturan -----------------------------------------------------------------------------------


@pengaturan_router.get("/laporan-pengaturan", response_model=PengaturanLaporan)
async def ambil_pengaturan_laporan(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Status pengaturan laporan. Tanpa baris `report_settings`: bawaan, dan tidak ada baris yang dibuat.
    `kata_sandi_diatur` true hanya bila kata sandi tersimpan benar-benar bisa dipakai (`_token_masih_terpakai`): token
    yang tak terbaca atau kata sandi yang kini ditolak berarti false, sama dengan jalur unduh yang menjawab 409."""
    return _jawab_pengaturan(user, await db.get(ReportSettings, user.id))


@pengaturan_router.put(
    "/laporan-pengaturan",
    response_model=PengaturanLaporan,
    responses={
        422: {
            "model": GalatValidasi,
            "description": "Kata sandi ditolak: `detail` kalimat siap tampil (panjang 6-64 karakter, karakter yang tak "
                           "bisa dipakai di PDF), atau daftar `{type, loc, msg}` bila badan permintaan salah bentuk.",
        },
        503: {"model": GalatKode, "description": "Kunci server belum diatur (kode `kunci_belum_diatur`)."},
    },
)
@limiter.limit("5/hour", key_func=kunci_per_user)
async def simpan_pengaturan_laporan(
    request: Request,
    body: KataSandiLaporanIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Atur atau ganti kata sandi PDF laporan. Disimpan NFC dan terenkripsi; jawabannya hanya bentuk GET (apakah
    kata sandi sudah diatur), tidak pernah kata sandinya. 422 bila bukan 6-64 karakter (setelah NFC) atau tidak bisa
    dipakai di PDF (`detail` berupa kalimat siap tampil)."""
    # NFC lebih dulu: yang diketik keyboard, yang diharapkan pembaca berbasis pdfium, dan yang dihitung panjangnya.
    kata_sandi = unicodedata.normalize("NFC", body.kata_sandi)
    if not MIN_KATA_SANDI <= len(kata_sandi) <= MAKS_KATA_SANDI:
        raise HTTPException(status_code=422, detail=MSG_PANJANG)
    try:
        pdf.periksa_kata_sandi(kata_sandi)
    except pdf.KataSandiPdfTidakValid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    try:
        token = rahasia.enkripsi(kata_sandi)
    except rahasia.KunciLaporanTidakAda:
        return _kunci_belum_diatur()
    return _bentuk_pengaturan(user, await _simpan_pengaturan(db, user.id, kata_sandi_enc=token))


@pengaturan_router.patch(
    "/laporan-pengaturan",
    response_model=PengaturanLaporan,
    responses={422: {"model": GalatValidasi, "description": "Badan kosong, field asing, atau nilai bukan boolean."}},
)
@limiter.limit("30/hour", key_func=kunci_per_user)   # ember sendiri, terpisah dari PUT kata sandi (5/jam)
async def ubah_pengaturan_laporan(
    request: Request,
    body: UbahPengaturanLaporan,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ubah saklar laporan (`email_on`); yang tidak dikirim tidak berubah, kata sandi tidak tersentuh. Menyalakan
    `email_on` menghidupkan lagi laporan terbaru yang dilewati karena email dimatikan. Jawabannya bentuk GET."""
    pengaturan = await _simpan_pengaturan(db, user.id, **body.perubahan())
    return _jawab_pengaturan(user, pengaturan)
