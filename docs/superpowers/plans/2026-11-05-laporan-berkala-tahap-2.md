# Laporan berkala tahap 2 (email) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** dieksekusi 5 Nov 2026 (subagent-driven, Task 1–8 di branch `feat/laporan-berkala-email`); menunggu review akhir dan merge. Keputusan eksekusi: spec bagian "Penyesuaian saat eksekusi tahap 2".

**Goal:** Laporan yang terbit dikirim ke email user yang terverifikasi: ringkasan tanpa nominal di body, PDF berkata sandi
sebagai lampiran, antrean dengan coba ulang, verifikasi email, dan berhenti berlangganan satu klik.

**Architecture:** Satu penjaga `email_verified_at` di model (`User.email` berubah → kosong). Token bertujuan
(`verifikasi_email`, `berhenti_email_laporan`) di `app/core/security.py`. Isi email dan halaman berhenti di
`app/services/laporan/surel.py` (fungsi murni); pengiriman MIME di `email_service.py` (satu-satunya tempat SMTP). Antrean
di `app/services/laporan/antrean_email.py`, dijalankan `laporan_job` sesudah penerbitan dan sapu notifikasi. API baru di
`app/api/routes/verifikasi_email.py` dan `laporan.py`; kartu Pengaturan → Laporan diperluas.

**Tech Stack:** FastAPI, SQLAlchemy async (event atribut), PyJWT, smtplib (thread), fpdf2 (tahap 1), slowapi
(`kunci_per_user`), React/Vite, `node:test`.

**Spec:** `docs/superpowers/specs/2026-11-01-laporan-berkala-design.md` — bagian 5 (Pengaturan, banner), 6a–6c, 7, 8, 10,
11 butir 2. Perilaku tahap 1 yang dipakai: `docs/laporan-berkala.md`.

## Keputusan rencana

1. **Toggle lewat `PATCH /user/laporan-pengaturan`** (body semua opsional, 30/jam per user). `PUT` tetap hanya kata sandi
   (5/jam); spec bagian 7 menulis keduanya di PUT, tetapi batas 5/jam untuk kata sandi tidak boleh ikut memakan saklar.
   API tetap hanya bertambah. Tahap 3 menambah `kuartalan_on`/`tahunan_on` ke PATCH ini.
2. **Laporan yang dilewati dihidupkan lagi** (spec 6b: "dikirim bila email terverifikasi, `email_on`, dan laporan belum
   pernah dikirim"): verifikasi berhasil → laporan user ini berstatus `dilewati` dengan alasan `belum_verifikasi` atau
   `tanpa_email` yang terbit ≤ `JENDELA_TERBIT_HARI` (7) hari lalu kembali `menunggu`; `email_on` dinyalakan → alasan
   `dimatikan` begitu juga. Yang lebih tua tidak dikirim.
3. **Jeda coba ulang 55 menit** untuk "paling cepat 1 jam" (6c): job jalan tiap jam di menit 30, jadi 60 menit tepat bisa
   meleset beberapa detik dan menunda satu jam lagi.
4. **`GET /laporan/berhenti-email` tidak pernah mengubah apa pun**: pemindai tautan di layanan email membuka GET. Hanya
   POST (tombol halaman dan one-click RFC 8058) mematikan `email_on`.
5. **Klaim kirim** `menunggu → mengirim` dengan `UPDATE … WHERE email_status = 'menunggu'` (cek rowcount), pola klaim
   notifikasi R16: job terjadwal dan jalan manual dari shell tidak mengirim dua kali.
6. **Lampiran jatuh dengan anggun:** token kata sandi tak terbaca atau kata sandi yang kini ditolak → tanpa lampiran, baris
   "atur kata sandi" (sama dengan 409 di unduh); kunci server tidak ada atau galat PDF tak terduga → tanpa lampiran, baris
   "unduh di aplikasi". Email tetap terkirim.
7. **Laporan tahap 1 (`email_status` NULL) tidak pernah dikirim** (keputusan rencana tahap 1 butir 3).

## Global Constraints

- Body dan subjek email laporan tanpa nominal rupiah: tidak memuat "Rp" dan tidak memuat angka uang apa pun dari `data`
  (hanya `data.judul` dan `data.email`). Email verifikasi tanpa data keuangan.
- Email laporan hanya ke `users.email` yang terverifikasi (`email_verified_at` tidak NULL), `email_on` true, dan status
  `menunggu`; dibaca ulang saat mengirim.
- Kata sandi PDF = kata sandi laporan user (tahap 1, Fernet `REPORT_SECRET_KEY`). Tidak pernah di log, respons, atau repo.
- Log antrean dan verifikasi hanya memuat id laporan/user dan teks tetap: tidak pernah alamat email, kata sandi, token,
  atau isi laporan.
- Token: JWT `JWT_SECRET`, klaim `type` = tujuan. `verifikasi_email`: klaim `sub` (id user) dan `email` (huruf kecil),
  berlaku 24 jam. `berhenti_email_laporan`: klaim `sub`, tanpa `exp`. Token login tetap menolak `type` selain `access`.
- Batas frekuensi (slowapi, `app.core.rate_limit.kunci_per_user`): kirim verifikasi 3/jam per user; PATCH pengaturan
  30/jam per user; GET verifikasi dan GET/POST berhenti memakai kunci IP bawaan, 30/menit.
- Antrean: `MAKS_PERCOBAAN = 3` → `gagal` alasan `smtp` + `logger.error`; `JEDA_COBA_ULANG = 55 menit`;
  `BATAS_MENGIRIM = 30 menit` (`mengirim` lebih lama → `menunggu`, percobaan tidak bertambah); `MAKS_EMAIL_PER_JALAN = 50`.
- Status (`String(16)`): `menunggu`, `mengirim`, `terkirim`, `gagal`, `dilewati`. Alasan (`String(32)`):
  `belum_verifikasi`, `dimatikan`, `tanpa_email`, `smtp`.
- Tanpa migrasi (semua kolom dari tahap 1, termasuk `reports.email_terkirim_at`). Tanpa paket dan `.env` baru.
- Teks (persis):
  - Subjek email laporan: `f"{data['judul']} · Jatahku"`. Judul isi: `data['judul']`. Pembuka: `"Hai {nama},"`,
    `"{judul} sudah terbit."`
  - Baris ringkasan: `"Anggaran terpakai: {persen}%"` (null → `"Anggaran terpakai: —"`); `"Amplop aman: {aman} · Lewat
    batas: {lewat}"`; tren seperti `trenTeks` frontend (`"Pengeluaran turun 12% dibanding periode lalu"`, `"… naik 5% …"`,
    `"Pengeluaran sama dengan periode lalu"`, null → tidak ada baris); `data.email.sorotan` apa adanya.
  - Lampiran: `terlampir` → `"PDF laporan terlampir. Buka dengan kata sandi laporanmu."`; `belum_diatur` → `"Atur kata
    sandi laporan di Pengaturan → Laporan untuk menerima PDF di email berikutnya."`; `tidak_tersedia` → `"PDF laporan
    bisa diunduh di aplikasi."`
  - Tombol: `"Lihat laporan"` → `{APP_URL}/laporan/{id}`. Kaki: `"Tidak ingin menerima laporan lewat email? "` + tautan
    `"Berhenti berlangganan"`.
  - Email verifikasi: subjek `"Verifikasi email Jatahku kamu"`, judul `"Verifikasi email kamu"`, isi `"Hai {nama},"`,
    `"Klik tombol di bawah untuk memverifikasi {email} sebagai alamat penerima laporan Jatahku. Tautan berlaku 24
    jam."`, `"Kalau kamu tidak meminta ini, abaikan email ini."`, tombol `"Verifikasi email"`.
  - Halaman berhenti: konfirmasi `"Berhenti menerima email laporan?"`, `"Email laporan Jatahku untuk akun ini akan
    dimatikan. Laporan tetap terbit di aplikasi."`, tombol `"Berhenti berlangganan"`; selesai `"Email laporan dimatikan"`,
    `"Laporan tetap terbit di aplikasi. Kamu bisa menyalakannya lagi di Pengaturan → Laporan."`; tidak berlaku
    `"Tautan tidak berlaku"`, `"Buka Pengaturan → Laporan di aplikasi Jatahku untuk mengatur email laporan."`
  - Pengaturan: `"Email {email} terverifikasi."`, `"Email {email} belum terverifikasi."`, `"Belum ada email di akun ini.
    Laporan tetap terbit di aplikasi dan Telegram."`; tombol `"Kirim tautan verifikasi"`; sukses `"Tautan verifikasi
    dikirim ke {email}. Berlaku 24 jam."`; saklar `"Kirim laporan ke email"`.
  - Pesan sesudah tautan verifikasi (`?email_verifikasi=`): `berhasil` → `"Email terverifikasi. Laporan berikutnya juga
    dikirim ke email."`; `tidak_berlaku` → `"Tautan verifikasi tidak berlaku atau sudah kedaluwarsa. Kirim tautan
    baru."`; `berubah` → `"Alamat email akunmu sudah berubah sejak tautan dikirim. Kirim tautan baru."`
  - Banner email: `"Verifikasi email untuk menerima laporan lewat email."`, tautan `/settings#laporan`.
- Repo publik: tanpa rahasia; jangan `git add -A`; jangan commit `frontend/dist/`; `docs/superpowers/` → `git add -f`.
- Tes: `DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python3 -m unittest …`
  dari root repo; frontend `node --test src/lib/*.test.js src/native/*.test.js` dari `frontend/`.

## Review Focus

1. **Pemindai tautan email membuka tautan berhenti** → `email_on` tidak berubah oleh GET (Task 5).
2. **Alamat beda huruf besar-kecil** (`PUT /user/email` tidak menormalkan) → token tetap cocok; alamat yang benar-benar
   berganti → `berubah` (Task 1, Task 4).
3. **SMTP mati berjam-jam** → tiap laporan paling banyak 3 percobaan berjarak ≥ 55 menit lalu `gagal`; tidak ada putaran
   rapat dan satu laporan gagal tidak menghentikan antrean (Task 3).
4. **Dua jalan job bersamaan** (terjadwal + manual) → satu email per laporan (Task 3).
5. **Kata sandi tersimpan tak terbaca / kunci server hilang saat mengirim** → email tetap terkirim tanpa lampiran dengan
   baris yang tepat; tidak ada token atau kata sandi di log (Task 3).

---

### Task 1: Penjaga verifikasi email dan token bertujuan

**Files:**
- Modify: `app/models/models.py` (event setelah kelas `User`), `app/core/security.py`, `app/api/routes/auth.py`
  (`google_login`, `google_link`)
- Create: `app/services/verifikasi_email.py`, `app/tests/test_verifikasi_email.py`

**Interfaces:**
- Produces: `security.create_purpose_token(user_id: str, tujuan: str, berlaku: timedelta | None = None, **klaim) -> str`;
  `security.decode_purpose_token(token: str, tujuan: str) -> dict | None` (None bila tanda tangan/kedaluwarsa/`type` salah
  atau tanpa `sub`). `verifikasi_email`: `TUJUAN_VERIFIKASI = "verifikasi_email"`, `BERLAKU_VERIFIKASI = timedelta(hours=24)`,
  `sama_email(a: str | None, b: str | None) -> bool` (strip + lower; None → False), `tandai_terverifikasi(user, sekarang:
  datetime | None = None) -> None` (isi bila masih NULL), `tautan_verifikasi(user) -> str`
  (`{API_URL}/auth/verifikasi-email?token=…`), `baca_token_verifikasi(token: str) -> tuple[UUID, str] | None`.
- Event: `@event.listens_for(User.email, "set", active_history=True)` mengosongkan `email_verified_at` bila nilai baru
  tidak `sama_email` dengan nilai lama (nilai lama bukan str → kosongkan). Jangan pernah mengisi `email_verified_at` di
  konstruktor `User(...)`; isi sesudahnya.

- [ ] **Step 1: Tulis tes yang gagal** — `test_ganti_email_mengosongkan_verifikasi` (user terverifikasi, `user.email =
  "baru@x.id"`, flush → `email_verified_at is None`); `test_email_sama_beda_huruf_tidak_mengosongkan`
  (`"Ani@X.id"` → `"ani@x.id "`); setiap jalur penulis lewat route nyata (SQLite + override `get_db`): `PUT /user/email`,
  reset data yang mengisi email (`user_settings.py` ±462), `link.py` (Telegram mengisi email), larangan admin
  (`banned_…`) → semuanya NULL; `POST /auth/register` → NULL; Google (`verify_google_credential` dipalsukan):
  `test_google_daftar_baru_terverifikasi`, `test_google_email_terdaftar_terverifikasi`,
  `test_google_id_dengan_email_sama_terverifikasi`, `test_google_link_mengisi_email_terverifikasi`,
  `test_google_link_email_beda_tidak_mengubah`; `test_pagar_tanpa_update_core_email` (pindai `app/**/*.py` selain
  tes: tidak ada `.values(` yang memuat `email=`); token: `test_token_verifikasi_bolak_balik`,
  `test_token_kedaluwarsa_ditolak`, `test_token_type_lain_ditolak` (access/refresh/berhenti),
  `test_token_bertujuan_tidak_bisa_login` (`get_current_user` 401 untuk token `verifikasi_email`).
- [ ] **Step 2:** jalankan → gagal (modul/fungsi belum ada, email tetap terverifikasi).
- [ ] **Step 3: Implementasikan** sesuai Interfaces; `google_login`/`google_link` memanggil `tandai_terverifikasi(user)`
  bila `sama_email(user.email, claims["email"])` sesudah email diisi.
- [ ] **Step 4:** jalankan tes ini + `app.tests.test_auth*`, `test_user_settings*`, `test_link*` (grep), `test_ruang_pagar`
  → PASS.
- [ ] **Step 5: Commit** — `feat(laporan): penjaga verifikasi email dan token bertujuan`.

### Task 2: Isi email, halaman berhenti, dan kiriman MIME

**Files:**
- Create: `app/services/laporan/surel.py`, `app/tests/test_laporan_surel.py`
- Modify: `app/services/email_service.py` (`email_template` + `footer_html`, `send_laporan_email`)

**Interfaces:**
- Consumes: `security.create_purpose_token`/`decode_purpose_token` (Task 1).
- Produces (`surel.py`): `LAMPIRAN_TERLAMPIR = "terlampir"`, `LAMPIRAN_BELUM_DIATUR = "belum_diatur"`,
  `LAMPIRAN_TIDAK_TERSEDIA = "tidak_tersedia"`; `TUJUAN_BERHENTI = "berhenti_email_laporan"`;
  `isi_email_laporan(data: dict, nama: str, tautan_laporan: str, tautan_berhenti: str, lampiran: str) -> tuple[str, str,
  str]` (subjek, html, teks); `isi_email_verifikasi(nama: str, email: str, tautan: str) -> tuple[str, str, str]`;
  `tautan_berhenti(user_id) -> str` (`{API_URL}/laporan/berhenti-email?token=…`); `baca_token_berhenti(token: str) -> UUID
  | None`; `halaman_konfirmasi_berhenti(token: str) -> str`, `halaman_berhenti_selesai() -> str`,
  `halaman_tautan_tak_berlaku() -> str` (HTML utuh, tanpa skrip, semua isi lewat `email_service.h`).
- Produces (`email_service.py`): `email_template(title, body_html, cta_text=None, cta_url=None, footer_html=None)`
  (`footer_html` HTML siap pakai, disisipkan di kaki di atas "Setiap rupiah ada jatahnya."); `send_laporan_email(to_email:
  str, subject: str, html_body: str, text_body: str, unsubscribe_url: str, pdf_bytes: bytes | None = None, filename: str |
  None = None) -> bool` — `MIMEMultipart("mixed")` berisi bagian `alternative` (teks + HTML) dan lampiran
  `application/pdf` bila ada; header `List-Unsubscribe: <{unsubscribe_url}>, <mailto:{SMTP_FROM}?subject=unsubscribe>` dan
  `List-Unsubscribe-Post: List-Unsubscribe=One-Click`; kirim lewat `_deliver`; log tanpa alamat.

- [ ] **Step 1: Tulis tes yang gagal** — dengan `data` dari `susun_bulanan` (bahan tes tahap 1, mis.
  `app/tests/test_laporan_susun.py`): `test_subjek_dan_body_tanpa_nominal` (subjek = `"Laporan Oktober 2026 · Jatahku"`;
  html dan teks tidak memuat `"Rp"`, dan tidak memuat satu pun nilai uang dari `data` dalam bentuk mentah maupun
  `hitung`/`pdf.rupiah`); `test_baris_ringkasan` (persen null → `"Anggaran terpakai: —"`, tren null → tanpa baris tren,
  `-12` → `"Pengeluaran turun 12% dibanding periode lalu"`); `test_baris_lampiran_per_kode` (tiga kode, teks persis);
  `test_nama_di_escape` (`nama='<b>x</b>'` → `&lt;b&gt;`); `test_tautan_berhenti_bolak_balik` dan token `verifikasi_email`
  ditolak `baca_token_berhenti`; `test_halaman_tanpa_skrip_dan_token_di_escape`; `send_laporan_email` dengan `_deliver`
  dipalsukan: `test_mime_dengan_lampiran` (satu bagian `application/pdf` bernama `filename`, header `List-Unsubscribe`
  memuat URL https dan mailto, `List-Unsubscribe-Post` persis), `test_mime_tanpa_lampiran`,
  `test_galat_smtp_mengembalikan_false_tanpa_alamat_di_log` (`assertLogs`: alamat tidak muncul).
- [ ] **Step 2:** jalankan → gagal.
- [ ] **Step 3: Implementasikan** sesuai Interfaces dan teks Global Constraints.
- [ ] **Step 4:** jalankan tes ini + tes email yang ada (grep `email_template`, `send_email` di `app/tests`) → PASS.
- [ ] **Step 5: Commit** — `feat(laporan): isi email laporan, halaman berhenti, kiriman MIME berlampiran`.

### Task 3: Antrean email dan status saat terbit

**Files:**
- Create: `app/services/laporan/antrean_email.py`, `app/tests/test_laporan_antrean_email.py`
- Modify: `app/services/laporan/job.py` (`terbitkan_household`, `laporan_job`), `app/tests/test_laporan_job.py`

**Interfaces:**
- Consumes: Task 1 (`verifikasi_email`), Task 2 (`surel.isi_email_laporan`, `surel.tautan_berhenti`,
  `email_service.send_laporan_email`), tahap 1 (`pdf.buat_pdf`, `pdf.periksa_kata_sandi`, `rahasia.dekripsi`,
  `hitung.nama_file_pdf`, `JENDELA_TERBIT_HARI`).
- Produces: konstanta status/alasan dan antrean di Global Constraints; `status_awal(user: User, pengaturan:
  ReportSettings | None) -> tuple[str, str | None]` (urutan: tanpa email → `dilewati`/`tanpa_email`; belum terverifikasi →
  `belum_verifikasi`; `email_on` false → `dimatikan`; selainnya `menunggu`, None); `lampiran_untuk(pengaturan:
  ReportSettings | None) -> tuple[str | None, str]` (kata sandi atau None, kode lampiran; keputusan rencana 6);
  `async proses_antrean_email(sekarang: datetime | None = None) -> dict` → `{"terkirim", "gagal", "dilewati",
  "dicoba_lagi"}`; `async hidupkan_lagi(db, user_id: UUID, alasan: tuple[str, ...], sekarang: datetime | None = None) ->
  int` (tidak commit). `laporan_job` mengembalikan `{"terbit", "gagal", "email": <hasil proses_antrean_email>}`.

Alur `proses_antrean_email`: (1) `mengirim` dengan `email_terakhir_at` < sekarang − 30 menit → `menunggu`; (2) ambil
paling banyak 50 laporan `menunggu` dengan `email_terakhir_at` NULL atau ≤ sekarang − 55 menit, `terbit_at` terlama dulu;
(3) per laporan: baca ulang user + pengaturan, `status_awal` ≠ `menunggu` → `dilewati` dengan alasan itu; selainnya klaim
(keputusan rencana 5, `email_terakhir_at` = sekarang, commit), PDF lewat `buat_pdf` bila ada kata sandi, kirim di
`asyncio.to_thread`; berhasil → `terkirim` + `email_terkirim_at`; gagal → `email_percobaan` + 1, `gagal`/`smtp` +
`logger.error` bila sudah 3, selainnya `menunggu`. Satu laporan yang melempar galat dicatat (`logger.exception` dengan id)
dan dilewati, antrean lanjut.

- [ ] **Step 1: Tulis tes yang gagal** (SQLite, pengirim dipalsukan merekam panggilan): `test_status_awal_urutan_alasan`;
  `test_terbit_mengisi_status_email` (job tahap 1: penerima terverifikasi → `menunggu`, belum → `dilewati`/
  `belum_verifikasi`, tanpa email → `tanpa_email`, `email_on` false → `dimatikan`); `test_laporan_tahap1_null_tidak_dikirim`;
  `test_kirim_dengan_lampiran_bila_kata_sandi_diatur` (PDF terbuka dengan `pypdfium2` memakai kata sandi itu, gagal tanpa);
  `test_tanpa_kata_sandi_tanpa_lampiran`; `test_token_tak_terbaca_dan_kunci_hilang` (kode `belum_diatur` /
  `tidak_tersedia`, email tetap terkirim, log tanpa token/kata sandi); `test_dibaca_ulang_saat_kirim` (email diganti atau
  `email_on` dimatikan sesudah terbit → `dilewati`); `test_gagal_dicoba_lagi_paling_cepat_55_menit` (jalan kedua 30 menit
  kemudian tidak mencoba; 56 menit kemudian mencoba); `test_tiga_percobaan_lalu_gagal_smtp` (`assertLogs` ERROR, tanpa
  alamat); `test_mengirim_basi_kembali_menunggu` (31 menit → `menunggu`, percobaan tetap); `test_dua_proses_bersamaan_satu_email`
  (dua `proses_antrean_email` lewat `asyncio.gather` → pengirim dipanggil sekali per laporan); `test_satu_galat_tidak_menghentikan_antrean`;
  `test_hidupkan_lagi_dalam_jendela` (8 hari lalu tidak, 6 hari lalu ya; alasan lain tidak); `test_laporan_job_menjalankan_antrean`
  (perbarui tes yang membandingkan hasil `laporan_job` persis).
- [ ] **Step 2:** jalankan → gagal.
- [ ] **Step 3: Implementasikan** `antrean_email.py`; di `terbitkan_household` muat `ReportSettings` calon dalam satu
  kueri dan isi `email_status`/`email_alasan` dari `status_awal`; di `laporan_job` panggil `proses_antrean_email()`
  sesudah sapu notifikasi, di luar kunci household, dan catat satu baris INFO ringkasan (angka saja).
- [ ] **Step 4:** jalankan tes ini + `app.tests.test_laporan_job` + `test_laporan_pdf` → PASS.
- [ ] **Step 5: Commit** — `feat(laporan): antrean email laporan dengan coba ulang`.

### Task 4: API verifikasi email

**Files:**
- Create: `app/api/routes/verifikasi_email.py`, `app/tests/test_verifikasi_email_api.py`
- Modify: `app/main.py` (pasang `user_router` prefix `/user`, `auth_router` prefix `/auth`)

**Interfaces:**
- Consumes: Task 1, Task 2 (`surel.isi_email_verifikasi`), Task 3 (`hidupkan_lagi`, alasan), `email_service.send_email`.
- Produces: `POST /user/email/verifikasi` (3/jam per user) → 200 `{"status": "terkirim"}`; 409 `{detail, kode:
  "sudah_terverifikasi"}`; 422 `{detail, kode: "tanpa_email"}`; 502 `{detail, kode: "gagal_kirim"}` (kirim di thread);
  semuanya `responses=` di OpenAPI. `GET /auth/verifikasi-email?token=` (30/menit IP) → 303 ke
  `{APP_URL}/settings?email_verifikasi={hasil}#laporan`, `hasil` ∈ `berhasil` (juga bila sudah terverifikasi),
  `tidak_berlaku` (token salah/kedaluwarsa/`type` lain/user tidak ada), `berubah` (email akun tidak `sama_email` dengan
  token). Berhasil: `tandai_terverifikasi` + `hidupkan_lagi(…, ("belum_verifikasi", "tanpa_email"))` + commit.

- [ ] **Step 1: Tulis tes yang gagal** (token asli `create_access_token`, `get_current_user` asli, hanya `get_db` dan
  pengirim dipalsukan): `test_kirim_tautan` (pengirim dipanggil sekali dengan tautan berisi token yang dibaca balik ke
  user dan email itu); `test_sudah_terverifikasi_409`, `test_tanpa_email_422`, `test_smtp_gagal_502`;
  `test_batas_tiga_per_jam` (panggilan ke-4 → 429, variasi header satu ember); `test_buka_tautan_berhasil` (303, lokasi
  persis, `email_verified_at` terisi, laporan `dilewati`/`belum_verifikasi` 2 hari lalu → `menunggu`);
  `test_tautan_kedaluwarsa_dan_type_lain` (→ `tidak_berlaku`, tidak ada perubahan);
  `test_email_berganti_sesudah_kirim` (→ `berubah`); `test_email_beda_huruf_tetap_berhasil`; `test_openapi_cek`
  (`python3 -m app.scripts.openapi_cek` lulus).
- [ ] **Step 2:** jalankan → gagal.
- [ ] **Step 3: Implementasikan** route sesuai Interfaces (limiter bersama `from app.api.routes.auth import limiter`,
  pola `laporan.py`).
- [ ] **Step 4:** jalankan tes ini + `test_ruang_pagar` + `openapi_cek` → PASS.
- [ ] **Step 5: Commit** — `feat(laporan): kirim dan buka tautan verifikasi email`.

### Task 5: API saklar email dan berhenti berlangganan

**Files:**
- Modify: `app/api/routes/laporan.py`, `app/tests/test_laporan_api.py`, `app/tests/test_ruang_pagar.py` (`tanpa` +
  `("POST", "/laporan/berhenti-email")` dengan alasan)

**Interfaces:**
- Consumes: Task 2 (`baca_token_berhenti`, tiga halaman HTML), Task 3 (`hidupkan_lagi`).
- Produces: `PATCH /user/laporan-pengaturan` body `UbahPengaturanLaporan` (`extra="forbid"`, `email_on: bool | None =
  None`; tanpa satu pun field → 422) → `PengaturanLaporan` (30/jam per user). Upsert dengan kunci baris `users` seperti
  `_simpan_token` (jadikan satu `_simpan_pengaturan(db, user_id, **ubah)` untuk keduanya). `email_on` true →
  `hidupkan_lagi(…, ("dimatikan",))`. `GET /laporan/berhenti-email?token=` → `HTMLResponse` konfirmasi 200 / tak berlaku
  400, **tanpa** mengubah apa pun. `POST /laporan/berhenti-email?token=` → `email_on` false (upsert) → halaman selesai
  200 / tak berlaku 400; menerima body form `List-Unsubscribe=One-Click` maupun kosong. Kedua route berhenti dideklarasikan
  **sebelum** `GET /laporan/{report_id}`.

- [ ] **Step 1: Tulis tes yang gagal** — `test_patch_email_on` (false lalu true; baris `report_settings` dibuat sekali;
  kata sandi tidak tersentuh); `test_patch_kosong_dan_field_asing_422`; `test_patch_tidak_memakai_batas_kata_sandi`
  (6 PATCH berturut-turut tidak 429, PUT kata sandi tetap punya 5/jam sendiri); `test_patch_menyalakan_menghidupkan_lagi`;
  `test_get_berhenti_tidak_mengubah` (GET dengan token sah → 200 HTML, `email_on` tetap true);
  `test_post_berhenti_mematikan` (form tombol dan body one-click; laporan di aplikasi tetap bisa dibuka);
  `test_berhenti_token_salah_400` (token access, acak, user terhapus); `test_rute_berhenti_tidak_tertelan_report_id`
  (`GET /laporan/berhenti-email` bukan 422); `test_ruang_pagar` hijau.
- [ ] **Step 2:** jalankan → gagal.
- [ ] **Step 3: Implementasikan** sesuai Interfaces.
- [ ] **Step 4:** jalankan `app.tests.test_laporan_api`, `test_ruang_pagar`, `test_ruang_gerbang`, `openapi_cek` → PASS.
- [ ] **Step 5: Commit** — `feat(laporan): saklar email laporan dan berhenti berlangganan satu klik`.

### Task 6: Frontend — helper dan API

**Files:**
- Modify: `frontend/src/lib/laporanView.js`, `frontend/src/lib/laporanView.test.js`, `frontend/src/lib/api.js`

**Interfaces:**
- Produces: `bannerLaporan(pengaturan)` — kata sandi belum diatur → banner tahap 1 (tetap); selainnya `pengaturan.email`
  ada, belum terverifikasi, dan `email_on` → `{ teks: "Verifikasi email untuk menerima laporan lewat email.", tautan:
  "/settings#laporan" }`; selainnya null. `statusEmail(pengaturan) -> { teks: string, bisaVerifikasi: boolean }` (tiga teks
  Pengaturan di Global Constraints). `pesanVerifikasi(kode) -> { teks, jenis: 'sukses' | 'galat' } | null` (tiga kode;
  lainnya null). `api.kirimVerifikasiEmail()` (POST; 429 → `"Terlalu sering. Coba lagi nanti."`; galat lain → `detail`
  string) dan `api.ubahPengaturanLaporan(body)` (PATCH; mengembalikan pengaturan; galat seperti di atas).

- [ ] **Step 1: Tulis tes yang gagal** (`node:test`): semua cabang `bannerLaporan`, `statusEmail` (tanpa email, belum,
  terverifikasi), `pesanVerifikasi` (tiga kode + kode asing + null).
- [ ] **Step 2–4:** gagal → implementasi → `node --test src/lib/*.test.js src/native/*.test.js` PASS.
- [ ] **Step 5: Commit** — `feat(laporan): helper status email dan API verifikasi di frontend`.

### Task 7: Frontend — kartu Pengaturan → Laporan

**Files:**
- Modify: `frontend/src/components/LaporanSettings.jsx`

**Interfaces:**
- Consumes: Task 6.
- Behaviour: di atas bagian kata sandi: teks `statusEmail`; bila `bisaVerifikasi`, tombol `"Kirim tautan verifikasi"`
  (sibuk saat mengirim; sukses → teks sukses dengan alamat; galat di bawah tombol); saklar `"Kirim laporan ke email"`
  (checkbox, `ubahPengaturanLaporan({ email_on })`, galat dikembalikan ke nilai sebelumnya). Saat halaman dibuka dengan
  `?email_verifikasi=<kode>`: tampilkan `pesanVerifikasi` di kartu, muat ulang pengaturan, lalu hapus hanya parameter itu
  dari URL (`history.replaceState`, `#laporan` tetap).

- [ ] **Step 1: Implementasikan** komponen (logika di Task 6, komponen hanya merender; kelas tombol yang sudah ada,
  mis. `btn-outline`).
- [ ] **Step 2: Verifikasi** — `npm run build` lulus; tangkapan layar Playwright (API dimock, skrip di scratchpad) mode
  gelap dan terang: kartu tanpa email, belum terverifikasi, terverifikasi, sesudah `?email_verifikasi=berhasil`, dan
  banner email di `/laporan/<id>`; lihat setiap tangkapan; `git checkout -- frontend/dist`.
- [ ] **Step 3: Commit** — `feat(laporan): status email, verifikasi, dan saklar email di Pengaturan`.

### Task 8: Dokumen, checklist, verifikasi akhir

**Files:**
- Modify: `docs/laporan-berkala.md` (bagian email, verifikasi, berhenti, antrean, batasan baru, pemulihan: kirim ulang
  email = set `email_status` ke `menunggu`), `AGENTS.md` (checklist baru), spec (status + "Penyesuaian saat menyusun
  rencana tahap 2" = tujuh keputusan rencana di atas; `git add -f`), rencana ini (status).

- [ ] **Step 1:** dokumen dan `## Deploy Checklist — Laporan berkala tahap 2: email (tanpa migrasi)`: sebelum merge — email
  reset password terkirim (SMTP hidup), `API_URL`/`APP_URL` di `.env` kosong atau URL produksi; sesudah merge — tunggu
  deploy hijau, kirim tautan verifikasi dari Pengaturan, buka → "Email terverifikasi", `journalctl -u jatahku | grep -i
  "email laporan"` tanpa alamat; hari gajian berikutnya: email tiba, PDF terbuka dengan kata sandi, tautan "Berhenti
  berlangganan" mematikan saklar dan saklar bisa dinyalakan lagi.
- [ ] **Step 2: Verifikasi penuh** — suite backend (hanya kegagalan bergantung tanggal yang sudah ada di main, sebutkan
  namanya), `openapi_cek`, `node --test`, `npm run build` lalu `git checkout -- frontend/dist`, `git status` bersih.
- [ ] **Step 3: Commit** — `docs(laporan): email laporan tahap 2, checklist deploy`.
