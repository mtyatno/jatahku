# Worker Email Laporan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** dieksekusi 12 Nov 2026 (subagent-driven, Task 1–7 di branch `feat/worker-email-laporan`); menunggu review akhir dan merge.

**Goal:** Antrean email laporan dijalankan service terpisah `jatahku-worker` dengan laju tetap, `laporan_job` hanya menerbitkan (dengan batas waktu), dan pemilik mendapat kartu Admin serta alarm Telegram.

**Architecture:** Antrean tetap di tabel `reports`; `antrean_email.py` mendapat satu fungsi putaran yang bisa dipacu dan dihentikan, dipakai worker (`worker_email.py`, proses sendiri, tanda hidup di Redis). `pantau_email.py` menghitung keadaan antrean untuk endpoint Admin dan alarm yang diperiksa `laporan_job` di proses API. `deploy.sh` memasang dan me-restart unit systemd dari repo.

**Tech Stack:** Python 3 asyncio, SQLAlchemy async, redis.asyncio, python-telegram-bot (`Bot.send_message`), systemd, React/Vite. Tanpa migrasi, tanpa paket baru.

**Spec:** `docs/superpowers/specs/2026-11-11-worker-email-laporan-design.md`

## Global Constraints

- Jaminan tahap 2 tidak berubah: klaim UPDATE bersyarat; setiap klaim = percobaan; `MAKS_PERCOBAAN = 3`, `JEDA_COBA_ULANG = 55 menit`, `BATAS_MENGIRIM = 30 menit`; hasil hanya ditulis pemilik klaim; badan email tanpa nominal; PDF tidak disimpan.
- Log, pesan alarm, dan respons Admin tidak pernah memuat alamat email, token, kata sandi, atau id user (id laporan boleh di log).
- Konstanta: `KELOMPOK = 100`, `JEDA_KOSONG = 60` detik, `EMAIL_LAPORAN_PER_DETIK` bawaan `3.0` dibatasi `0.1`–`20`, kunci Redis `laporan:worker_email:hidup` TTL 900 detik, worker dianggap hidup bila tanda ≤ 10 menit, `BATAS_JALAN = 40 menit`, `AMBANG_PENERIMA = 300`, antrean tersendat `> 360` menit, masa tenang `worker_mati` 15 menit sesudah API menyala.
- Alarm: kode `pindah_penyedia` (ulang 30 hari), `worker_mati`, `antrean_tersendat`, `email_gagal` (ulang 24 jam); kunci `app_settings` `alarm_email_laporan:<kode>`, nilai waktu UTC ISO, ditulis hanya bila pesan terkirim.
- Teks log ringkasan tetap `email laporan: %s terkirim, %s gagal, %s dilewati, %s dicoba lagi`.
- Repo publik: tanpa kredensial, alamat, atau id sungguhan. Stage file satu per satu; `docs/superpowers/` dengan `git add -f`; jangan commit `frontend/dist/` (sesudah build: `git checkout -- frontend/dist`).
- Tes backend: `DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python3 -m unittest <modul>` dari root repo. Frontend dari `frontend/`: `node --test src/lib/*.test.js src/native/*.test.js`.
- Commit diakhiri:
  `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>` dan
  `Claude-Session: https://claude.ai/code/session_017DL2c6KwEzKSaXsjUN4PBR`.

## Review Focus

1. Worker dihentikan (SIGTERM) di tengah kiriman → kiriman itu selesai dan tercatat, tidak ada klaim baru (Task 2).
2. Redis mati → worker tetap mengirim; Admin dan alarm menganggap worker tidak hidup tanpa galat 500 (Task 2, 3, 5).
3. API lama/putaran manual dan worker berjalan bersamaan → setiap laporan terkirim sekali (Task 1).
4. Telegram admin tidak diatur atau gagal → alarm tidak dicatat terkirim dan `laporan_job` tetap selesai (Task 3, 4).
5. `EMAIL_LAPORAN_PER_DETIK` kosong, nol, negatif, atau sangat besar di `.env` → worker tetap menyala dengan batas terdekat (Task 2).

---

### Task 1: Putaran antrean yang bisa dipacu dan dihentikan

**Files:**
- Modify: `app/services/laporan/antrean_email.py`
- Test: `app/tests/test_laporan_antrean_email.py`

**Interfaces:**
- Produces: `KELOMPOK = 100` (menggantikan `MAKS_EMAIL_PER_JALAN`); `async def putaran_antrean(jam: Callable[[], datetime], *, sebelum_laporan: Callable[[], Awaitable[None]] | None = None, berhenti: Callable[[], bool] | None = None) -> tuple[dict, bool]` — satu putaran (rapikan klaim basi, ambil ≤ `KELOMPOK` laporan siap, proses satu per satu). `sebelum_laporan` di-await sebelum setiap laporan; `berhenti()` dicek sebelum setiap laporan dan bila true putaran berakhir tanpa mengklaim lagi. Mengembalikan `(hasil, penuh)`; `penuh` = jumlah yang diambil sama dengan `KELOMPOK` dan putaran tidak dihentikan.
- `proses_antrean_email(sekarang=None) -> dict` tetap, kini memanggil `putaran_antrean` dan mengembalikan `hasil`.

- [ ] **Step 1: Tes gagal.** Ganti `test_paling_banyak_50_per_jalan_terlama_dulu` menjadi `test_paling_banyak_kelompok_per_putaran_terlama_dulu` (`KELOMPOK + 5` laporan → terkirim `KELOMPOK`, yang tersisa lima terbaru; `putaran_antrean` → `penuh is True`; putaran kedua → `penuh is False`). Tambah `test_sebelum_laporan_dipanggil_per_laporan` (3 laporan → pencatat dipanggil 3 kali, masing-masing sebelum kiriman ke-n) dan `test_berhenti_tidak_mengklaim_lagi` (`berhenti` true sesudah kiriman pertama → 1 terkirim, sisanya masih `menunggu` dengan `email_percobaan == 0`, `penuh is False`).
- [ ] **Step 2:** Jalankan modul tes; gagal karena `putaran_antrean`/`KELOMPOK` belum ada.
- [ ] **Step 3:** Implementasi sesuai Interfaces; perbarui docstring modul (langkah 2: `KELOMPOK`, dipacu pemanggil).
- [ ] **Step 4:** `app.tests.test_laporan_antrean_email` lulus seluruhnya (termasuk tes dua proses bersamaan yang sudah ada).
- [ ] **Step 5: Commit** `refactor(laporan): putaran antrean email bisa dipacu dan dihentikan`.

### Task 2: Worker email

**Files:**
- Create: `app/services/laporan/worker_email.py`
- Modify: `app/core/config.py` (`EMAIL_LAPORAN_PER_DETIK: float = 3.0`)
- Test: `app/tests/test_laporan_worker_email.py`

**Interfaces:**
- Consumes: `antrean_email.putaran_antrean`, `KELOMPOK`.
- Produces:
  - `KUNCI_HIDUP = "laporan:worker_email:hidup"`, `TTL_HIDUP = 900`, `JEDA_KOSONG = 60.0`, `JEDA_TANDA = 60.0`, `LAJU_MIN = 0.1`, `LAJU_MAKS = 20.0`.
  - `def laju_dari_pengaturan(nilai) -> float` — angka di luar batas, bukan angka, atau `None` → batas terdekat/bawaan 3.0.
  - `class Pemacu: def __init__(self, per_detik: float, *, jam=time.monotonic, tidur=asyncio.sleep); async def tunggu(self) -> None` — menjaga jarak `1/per_detik` dari awal kiriman sebelumnya; panggilan pertama tidak menunggu.
  - `async def tulis_tanda_hidup(redis, sekarang: datetime) -> bool` — `SET KUNCI_HIDUP <iso> EX TTL_HIDUP`; galat Redis → `False`, tidak melempar.
  - `async def jalankan(berhenti: asyncio.Event, *, redis=None, per_detik: float | None = None, putaran=antrean_email.putaran_antrean) -> None` — loop spec bagian 3; `redis=None` → `redis.asyncio.from_url(settings.REDIS_URL)`; log ringkasan bila ada hasil.
  - `def main() -> None` — pasang penangan SIGTERM/SIGINT yang menyalakan `berhenti`, `asyncio.run(jalankan(...))`, keluar 0. Blok `if __name__ == "__main__": main()`.

- [ ] **Step 1: Tes gagal** (`unittest.IsolatedAsyncioTestCase`, jam dan tidur tiruan, `putaran` tiruan, Redis tiruan sederhana dengan `set`):
  - `test_laju_dari_pengaturan`: `(None→3.0, "abc"→3.0, 0→0.1, -1→0.1, 500→20.0, 2.5→2.5)`.
  - `test_pemacu_menjaga_jarak`: laju 4 → tidur `0.25` dikurangi waktu yang sudah lewat; kiriman yang makan 1 detik → tanpa tidur; panggilan pertama tanpa tidur.
  - `test_kelompok_penuh_langsung_lanjut_kosong_menunggu`: putaran mengembalikan `penuh=True` lalu `False` → tidak ada tunggu 60 detik di antara keduanya, ada sesudah yang kedua.
  - `test_berhenti_di_tengah_putaran`: `berhenti` dinyalakan di dalam putaran → `jalankan` selesai tanpa memulai putaran baru; fungsi `berhenti` yang diteruskan ke putaran mengembalikan true.
  - `test_galat_putaran_tidak_menghentikan_worker`: putaran pertama melempar → dicatat (`assertLogs`), tunggu 60 detik, putaran kedua berjalan.
  - `test_tanda_hidup_ditulis_dan_redis_mati_tidak_menghentikan`: tanda ditulis di awal putaran dengan TTL 900; Redis yang melempar → `tulis_tanda_hidup` `False`, putaran tetap dipanggil.
  - `test_log_tanpa_alamat`: log worker tidak memuat `@`.
- [ ] **Step 2:** Jalankan; gagal karena modul belum ada.
- [ ] **Step 3:** Implementasi. `jalankan` meneruskan `sebelum_laporan` = pemacu + tulis tanda hidup bila sudah ≥ `JEDA_TANDA` sejak terakhir, dan `berhenti=berhenti.is_set`. Tunggu kosong: `asyncio.wait_for(berhenti.wait(), JEDA_KOSONG)`.
- [ ] **Step 4:** Tes lulus; `python -m app.services.laporan.worker_email` dijalankan lokal 5 detik dengan `timeout -s TERM 5` → keluar 0 dan log "menyala" (lampirkan output di laporan).
- [ ] **Step 5: Commit** `feat(laporan): worker email laporan dengan laju tetap`.

### Task 3: Keadaan antrean dan alarm

**Files:**
- Create: `app/services/laporan/pantau_email.py`
- Test: `app/tests/test_laporan_pantau_email.py`

**Interfaces:**
- Consumes: `worker_email.KUNCI_HIDUP`, `laju_dari_pengaturan`; `job._AWALAN_AKUN_NONAKTIF` (impor lokal atau pindahkan konstanta ke `antrean_email` bila ada impor melingkar); `AppSetting`.
- Produces:
  - `AMBANG_PENERIMA = 300`, `BATAS_HIDUP = timedelta(minutes=10)`, `BATAS_TERSENDAT_MENIT = 360`, `MASA_TENANG = timedelta(minutes=15)`, `ULANG = {"pindah_penyedia": timedelta(days=30), "worker_mati": timedelta(hours=24), "antrean_tersendat": timedelta(hours=24), "email_gagal": timedelta(hours=24)}`.
  - `async def keadaan_email(db, redis, sekarang: datetime) -> dict` dengan kunci persis: `worker_hidup: bool`, `worker_terakhir: str | None` (ISO), `menunggu: int`, `tertua_menit: int | None`, `mengirim: int`, `terkirim_24_jam: int`, `gagal_7_hari: int`, `penerima: int`, `ambang_penerima: int`, `smtp_lokal: bool`, `laju_per_detik: float`. Redis galat atau `None` → `worker_hidup False`, `worker_terakhir None`.
  - `async def alarm_berlaku(db, keadaan: dict, sekarang: datetime) -> list[str]` — kode yang syaratnya terpenuhi (tanpa melihat batas ulang); dipakai kartu Admin.
  - `def pesan_alarm(kode: str, keadaan: dict) -> str` — teks spec bagian 6 (WIB untuk jam).
  - `async def periksa_alarm(db, redis, sekarang: datetime, *, kirim, api_menyala: datetime) -> list[str]` — `kirim(teks) -> Awaitable[bool]`; mengirim alarm yang berlaku dan sudah lewat batas ulangnya, mencatat waktu di `app_settings` hanya bila `kirim` mengembalikan true, commit; mengembalikan kode yang terkirim. `worker_mati` dilewati bila `sekarang - api_menyala < MASA_TENANG`.
  - `async def kirim_telegram_admin(teks: str) -> bool` — pola `_notify_admin_new_user` (`auth.py`), tanpa `parse_mode`; token atau `ADMIN_TELEGRAM_ID` kosong, atau galat → `False` + `logger.warning` tanpa isi pesan.

- [ ] **Step 1: Tes gagal** (pola fixture `test_laporan_antrean_email.py`):
  - `test_keadaan_menghitung`: data campuran (menunggu 2 dengan umur 90 dan 400 menit, mengirim 1, terkirim 3 dalam 24 jam + 1 lebih lama, gagal 1 dalam 7 hari + 1 lebih lama; user: terverifikasi+menyala, terverifikasi tanpa baris pengaturan, terverifikasi+mati, belum terverifikasi, `deleted_…` terverifikasi) → `menunggu 2, tertua_menit 400, mengirim 1, terkirim_24_jam 3, gagal_7_hari 1, penerima 2`.
  - `test_worker_hidup_dari_tanda`: tanda 5 menit lalu → hidup; 11 menit → tidak; tanpa tanda, Redis melempar, `redis=None` → tidak, tanpa galat.
  - `test_alarm_per_syarat`: masing-masing kode muncul tepat saat syaratnya terpenuhi (penerima 300 + SMTP lokal; penerima 300 + `SMTP_HOST` lain → tidak; tertua 361 vs 360; gagal baru).
  - `test_batas_ulang_dan_pencatatan`: terkirim → jam berikutnya tidak dikirim; sesudah 24 jam (30 hari untuk `pindah_penyedia`) dikirim lagi; `kirim` mengembalikan false → tidak dicatat dan dicoba lagi jam berikutnya.
  - `test_email_gagal_hanya_yang_baru`: laporan gagal sebelum alarm terakhir tidak memicu lagi.
  - `test_masa_tenang_worker_mati`: API menyala 5 menit lalu → tidak dikirim; 16 menit → dikirim.
  - `test_pesan_tanpa_alamat`: semua `pesan_alarm` tanpa `@`; `pindah_penyedia` memuat jumlah penerima dan "AGENTS.md".
- [ ] **Step 2:** Jalankan; gagal.
- [ ] **Step 3:** Implementasi.
- [ ] **Step 4:** Tes lulus.
- [ ] **Step 5: Commit** `feat(laporan): keadaan antrean email dan alarm admin`.

### Task 4: `laporan_job` tanpa email, dengan batas waktu dan alarm

**Files:**
- Modify: `app/services/laporan/job.py`, `app/main.py` (catat waktu API menyala: `app.state`/variabel modul `pantau_email.API_MENYALA` diisi di `lifespan`)
- Test: `app/tests/test_laporan_job.py`

**Interfaces:**
- Consumes: `pantau_email.periksa_alarm`, `kirim_telegram_admin`.
- Produces: `BATAS_JALAN = timedelta(minutes=40)`; `laporan_job(today=None, *, jam=time.monotonic) -> {"terbit": int, "gagal": int, "ditunda": int}`.

- [ ] **Step 1: Tes gagal:** perbarui harapan hasil (`"email"` hilang, `"ditunda"` ada) dan hapus tiruan antrean; `test_job_tidak_menjalankan_antrean_email` (`antrean_email.putaran_antrean` dan `proses_antrean_email` di-patch → tidak dipanggil); `test_batas_waktu_menunda_sisanya` (jam tiruan melewati 40 menit sesudah household kedua dari lima → `terbit` dari dua, `ditunda 3`, sapu notifikasi tetap jalan; jalan berikutnya menyelesaikan tiga sisanya); `test_durasi_dicatat` (`assertLogs`: durasi dan hasil); `test_alarm_diperiksa_dan_galatnya_tidak_membatalkan` (`periksa_alarm` dipanggil sekali sesudah sapu; melempar → hasil job tetap dikembalikan, galat dicatat).
- [ ] **Step 2:** Jalankan; gagal.
- [ ] **Step 3:** Implementasi; docstring `laporan_job` dan modul diperbarui.
- [ ] **Step 4:** `app.tests.test_laporan_job` dan `app.tests.test_laporan_antrean_email` lulus.
- [ ] **Step 5: Commit** `feat(laporan): job penerbitan berbatas waktu, email pindah ke worker`.

### Task 5: Endpoint dan kartu Admin

**Files:**
- Modify: `app/api/routes/admin.py`, `frontend/src/lib/api.js`, `frontend/src/pages/Admin.jsx`
- Create: `frontend/src/components/admin/EmailLaporanCard.jsx`, `frontend/src/lib/emailLaporanView.js`, `frontend/src/lib/emailLaporanView.test.js`
- Test: `app/tests/test_admin_email_laporan.py`

**Interfaces:**
- Consumes: `pantau_email.keadaan_email`, `alarm_berlaku`.
- Produces: `GET /admin/email-laporan` (`require_admin`) → dict `keadaan_email` + `"alarm": list[str]`; `api.adminEmailLaporan()` → `{ok, status, data}` (pola `adminProofRules`); `emailLaporanView.js`: `barisKartu(keadaan) -> [{label, nilai, nada}]` dan `teksAlarm(kode) -> string`.
- Teks kartu: judul "Email laporan"; baris "Worker" (`Hidup · terakhir HH.MM` / `Tidak memberi tanda hidup`), "Menunggu" (`N` / `N · tertua X jam Y menit`), "Terkirim 24 jam", "Gagal 7 hari", "Penerima" (`N / 300`), "Laju" (`N email/detik`). Alarm: `pindah_penyedia` "Saatnya pindah ke penyedia email transaksional (langkah di AGENTS.md).", `worker_mati` "Worker email tidak berjalan.", `antrean_tersendat` "Antrean tersendat lebih dari 6 jam.", `email_gagal` "Ada email laporan yang gagal dikirim.". Gagal memuat: "Status email laporan tidak bisa dimuat."

- [ ] **Step 1: Tes gagal:** backend — non-admin 403, admin 200 dengan semua kunci, respons tanpa `@` atas data uji beralamat, Redis mati → 200 dengan `worker_hidup false`; frontend — `barisKartu` untuk worker hidup/mati, antrean kosong/berumur, `teksAlarm` setiap kode dan kode tak dikenal → `''`.
- [ ] **Step 2:** Jalankan keduanya; gagal.
- [ ] **Step 3:** Implementasi; kartu dipasang di tab ringkasan Admin (dimuat sendiri, galatnya tidak mengganggu kartu lain).
- [ ] **Step 4:** Tes lulus; `npm run build` OK lalu `git checkout -- frontend/dist`; `python -m app.scripts.openapi_cek` tanpa perubahan memutus; tangkapan layar kartu (terang + gelap, 390 px; keadaan normal dan keadaan beralarm) dengan Playwright dan API tiruan, dilihat satu per satu.
- [ ] **Step 5: Commit** `feat(admin): kartu status email laporan`.

### Task 6: Unit systemd dan deploy

**Files:**
- Create: `deploy/jatahku-worker.service`
- Modify: `deploy.sh`
- Test: `app/tests/test_deploy_worker.py`

**Interfaces:**
- Unit persis spec bagian 5 (`User=jatahku`, `WorkingDirectory=/opt/jatahku/app`, `ExecStart=/opt/jatahku/venv/bin/python -m app.services.laporan.worker_email`, `Restart=always`, `RestartSec=5`, `Nice=5`, `TimeoutStopSec=60`, `After=network.target postgresql.service redis-server.service`, `WantedBy=multi-user.target`). Pengaturan dibaca `config.py` dari `/opt/jatahku/.env` (`env_file`), jadi unit tidak butuh `EnvironmentFile`; bila unit API di server ternyata memakai variabel lain yang dibutuhkan worker, laporkan (pemilik diminta `systemctl cat jatahku`).
- `deploy.sh`, sesudah blok cek API: pasang unit bila `cmp -s` berbeda (`cp`, `systemctl daemon-reload`, `systemctl enable jatahku-worker`), `systemctl restart jatahku-worker`, tunggu `is-active` ≤ 20 detik; tidak aktif → cetak `journalctl -u jatahku-worker -n 40 --no-pager`, set `WORKER_GAGAL=1`, dan di akhir skrip keluar 1 bersama pola `MIG_PENDING` yang ada.

- [ ] **Step 1: Tes gagal:** unit memuat setiap baris di atas; `deploy.sh` lolos `bash -n`; blok worker berada sesudah cek API dan sebelum akhir; `WORKER_GAGAL` membuat skrip keluar bukan nol di akhir (uji teks/urutan, tanpa menjalankan systemctl).
- [ ] **Step 2:** Jalankan; gagal.
- [ ] **Step 3:** Implementasi; baca seluruh `deploy.sh` dulu dan ikuti gaya penutup `MIG_PENDING`.
- [ ] **Step 4:** Tes lulus; `bash -n deploy.sh`.
- [ ] **Step 5: Commit** `feat(deploy): pasang dan restart jatahku-worker`.

### Task 7: Dokumen, uji beban, verifikasi akhir

**Files:**
- Modify: `docs/laporan-berkala.md`, `AGENTS.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-11-01-laporan-berkala-design.md`, spec dan plan ini (status)

- [ ] **Step 1: Dokumen** sesuai spec bagian 7: worker, `laporan_job`, pemantauan/alarm, pemulihan; `AGENTS.md` — "Deploy Checklist — Worker email laporan (tanpa migrasi)" (sebelum merge: tidak ada; sesudah: deploy hijau, `sudo systemctl status jatahku-worker`, kartu Admin "Hidup", kirim ulang satu email uji dan lihat terkirim ≤ 2 menit, log tanpa alamat; rollback: revert + `sudo systemctl disable --now jatahku-worker`) dan bagian "Pindah penyedia email"; `CLAUDE.md` satu baris di Deploy; spec laporan berkala: tahap 2 tayang 10 Nov 2026 + rujukan.
- [ ] **Step 2: Uji beban lokal** (skrip di scratchpad, tidak di-commit): 2.000 laporan `menunggu`, pengirim tiruan, PDF sungguhan, laju 20/detik → catat waktu selesai dan CPU; 200 laporan pada 3/detik → ±67 detik. Hasil ditulis di laporan dan PR.
- [ ] **Step 3: Verifikasi penuh:** suite backend, `openapi_cek`, tes frontend, build (lalu pulihkan `dist`), `git status` bersih.
- [ ] **Step 4: Commit** `docs(laporan): worker email, alarm, dan pindah penyedia email`.
