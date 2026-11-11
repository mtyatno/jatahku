# Worker email laporan — desain

**Status:** desain disetujui pemilik di percakapan (11 Nov 2026); menunggu review spec tertulis. Belum diimplementasikan.
**Terkait:** `docs/superpowers/specs/2026-11-01-laporan-berkala-design.md` (laporan berkala; tahap 2 email sudah tayang
lewat #198, #203, #206), `docs/laporan-berkala.md` (dokumen operasional).

## 1. Tujuan

Saat pengguna mencapai ribuan (sasaran hitung: 10.000 penerima), semua email laporan di hari gajian terkirim dalam
1–3 jam sesudah laporan terbit, tanpa memperlambat aplikasi, dan tanpa langkah manual yang harus diingat pemilik.

Keadaan sekarang: antrean email dijalankan `laporan_job` (tiap jam, menit :30, di proses API), paling banyak 50 email
per jalan. Untuk 10.000 penerima itu berarti ±8 hari. Pembuatan PDF (±0,11 detik per PDF, diukur) berjalan di proses
yang sama dengan API.

**Yang tidak berubah (jaminan tahap 2):** antrean tetap di tabel `reports` (`email_status` `menunggu` → `mengirim` →
`terkirim`/`gagal`/`dilewati`); klaim lewat UPDATE bersyarat; setiap klaim dihitung sebagai percobaan, paling banyak 3
(`MAKS_PERCOBAAN`), jeda 55 menit (`JEDA_COBA_ULANG`), klaim macet > 30 menit (`BATAS_MENGIRIM`); hasil hanya ditulis
pemilik klaim; badan email tanpa nominal; tautan berhenti berlangganan; log tanpa alamat, token, atau kata sandi; PDF
dibuat saat dikirim dan tidak pernah disimpan.

**Di luar cakupan:** Celery/BullMQ atau antrean Redis; penyimpanan PDF (object storage); jadwal kirim khusus malam;
pindah ke penyedia email transaksional (hanya alarm dan runbook-nya); tahap 3 laporan (kuartalan/tahunan).

## 2. Keputusan

1. **Worker = proses terpisah** (`jatahku-worker`, service systemd), bukan tugas di proses API: pembuatan PDF tidak
   bersaing dengan API. Biaya: ±150 MB RAM.
2. **Hanya antrean email yang pindah ke worker.** Penerbitan laporan dan notifikasinya tetap di `laporan_job` di proses
   API: worker mati → laporan tetap terbit di aplikasi dan Telegram, hanya email yang tertunda.
3. **Service yang jalan terus** (putaran berulang), bukan timer systemd atau scheduler di dalam worker.
4. **Laju kirim tetap**, bawaan 3 email per detik, bisa diubah lewat `.env` (`EMAIL_LAPORAN_PER_DETIK`).
5. **Alarm lewat Telegram admin** (`ADMIN_TELEGRAM_ID`) dan kartu di halaman Admin; pengecekan di proses API supaya
   worker yang mati tetap ketahuan.
6. **Ambang pindah penyedia: 300 penerima email laporan**; alarm berhenti sendiri saat `SMTP_HOST` bukan lagi
   `localhost`.

## 3. Worker

**Modul:** `app/services/laporan/worker_email.py`, dijalankan `python -m app.services.laporan.worker_email` dari
`/opt/jatahku/app`. Memuat pengaturan yang sama dengan API (`.env`), tidak memuat aplikasi FastAPI, scheduler, atau bot.

**Putaran:**
1. Kembalikan klaim macet (langkah 1 antrean sekarang: `mengirim` > 30 menit → `menunggu`, atau `gagal`/`smtp` bila
   percobaannya habis).
2. Ambil kelompok laporan `menunggu` yang siap dicoba (terbit terlama dulu, paling banyak `KELOMPOK` = 100), lalu untuk
   setiap laporan: klaim, baca ulang user dan pengaturan, buat PDF, kirim, tulis hasil — fungsi per laporan yang sudah
   ada di `antrean_email.py`. Antara dua kiriman dijaga jarak `1 / EMAIL_LAPORAN_PER_DETIK` detik (dihitung dari awal
   kiriman sebelumnya, jadi kiriman lambat tidak menambah jeda).
3. Kelompok penuh → langsung putaran berikutnya. Kelompok tidak penuh → tunggu `JEDA_KOSONG` = 60 detik (terputus
   seketika oleh permintaan berhenti).
4. Tulis tanda hidup ke Redis: kunci `laporan:worker_email:hidup`, nilai waktu UTC ISO, TTL 15 menit; ditulis di awal
   setiap putaran dan paling sedikit tiap 60 detik selama mengirim. Redis tidak terjangkau → dicatat sekali per putaran,
   pengiriman tetap jalan.

**Pengaturan** (`app/core/config.py`): `EMAIL_LAPORAN_PER_DETIK: float = 3.0`. Nilai di luar 0,1–20 → dipakai batas
terdekat, dengan peringatan di log saat worker menyala.

**Berhenti (SIGTERM/SIGINT):** tidak mengklaim laporan baru; kiriman yang sedang berjalan diselesaikan (paling lama
batas SMTP 30 detik + tulis hasil), lalu keluar dengan kode 0. Klaim yang tertinggal karena proses dimatikan paksa
dipulihkan aturan klaim macet.

**Galat:** galat satu laporan dicatat dan klaimnya terhitung percobaan (perilaku sekarang). Galat satu putaran (mis.
database putus) dicatat, tunggu 60 detik, lanjut. Worker tidak pernah keluar karena galat putaran.

**Log** (tanpa alamat): saat menyala (laju yang dipakai), dan ringkasan tiap putaran yang memproses sesuatu:
`email laporan: N terkirim, N gagal, N dilewati, N dicoba lagi` (teks yang sama dengan sekarang, supaya perintah cek di
checklist tetap berlaku).

**`proses_antrean_email`** tetap ada sebagai satu putaran tanpa jeda laju (dipakai tes dan perintah manual di
dokumentasi); batas `MAKS_EMAIL_PER_JALAN` diganti `KELOMPOK`.

## 4. `laporan_job` (proses API)

- Tidak lagi memanggil antrean email; hasilnya kembali `{"terbit", "gagal"}` ditambah `"ditunda"` (household yang belum
  sempat diproses).
- **Batas waktu:** household baru tidak dimulai sesudah 40 menit sejak job mulai (`BATAS_JALAN`); sisanya dihitung
  `ditunda` dan diproses jalan berikutnya (penerbitan idempoten). Sapu notifikasi tetap dijalankan sesudahnya.
- Durasi dan hasil setiap jalan yang menerbitkan atau menunda sesuatu dicatat di log.
- Sesudah itu job menjalankan pemeriksaan alarm (bagian 6); galat pemeriksaan dicatat, tidak membatalkan job.

## 5. Pemasangan

- **Unit di repo:** `deploy/jatahku-worker.service` — `User=jatahku`, `WorkingDirectory=/opt/jatahku/app`,
  `ExecStart=/opt/jatahku/venv/bin/python -m app.services.laporan.worker_email`, `Restart=always`, `RestartSec=5`,
  `Nice=5`, `TimeoutStopSec=60`, `After=network.target postgresql.service redis-server.service`,
  `WantedBy=multi-user.target`. Variabel lingkungan dibaca dengan cara yang sama seperti `jatahku.service` (dicek saat
  implementasi dari unit yang ada di server/dokumen; bila tidak ada di repo, pemilik diminta menampilkan
  `systemctl cat jatahku`).
- **`deploy.sh`:** sesudah cek API lulus: pasang unit bila berbeda dari `/etc/systemd/system/jatahku-worker.service`
  (`cp`, `systemctl daemon-reload`, `systemctl enable`), `systemctl restart jatahku-worker`, lalu pastikan
  `systemctl is-active` dalam 20 detik. Tidak aktif → tampilkan `journalctl -u jatahku-worker -n 40` dan deploy
  berakhir gagal (sesudah frontend terpasang, seperti peringatan migrasi), supaya notifikasi "Deploy GAGAL" terkirim.
- **Urutan saat deploy pertama:** API baru (tanpa antrean) menyala lebih dulu, worker sesudahnya; email tertunda
  paling lama beberapa menit. API lama dan worker baru berjalan bersamaan pun aman (klaim bersyarat).
- **Rollback:** revert PR → `laporan_job` kembali mengirim; worker lama harus dihentikan
  (`sudo systemctl disable --now jatahku-worker`) — ditulis di checklist. Keduanya berjalan bersamaan tetap tidak
  menggandakan email.
- Tanpa migrasi, tanpa paket baru.

## 6. Pemantauan dan alarm

**Ukuran** (`app/services/laporan/pantau_email.py`, satu fungsi `keadaan_email(db, redis, sekarang) -> dict`):
- `worker_hidup` (tanda hidup ada dan berumur ≤ 10 menit) dan `worker_terakhir` (waktu atau null);
- `menunggu` (jumlah `email_status = 'menunggu'`), `tertua_menit` (umur `terbit_at` laporan `menunggu` tertua, null
  bila kosong), `mengirim`;
- `terkirim_24_jam`, `gagal_7_hari`;
- `penerima` = user aktif (bukan `deleted_`/`banned_`) dengan email terverifikasi dan `email_on` tidak false (tanpa
  baris `report_settings` = menyala), `ambang_penerima` = 300, `smtp_lokal` (`SMTP_HOST` = `localhost`/`127.0.0.1`);
- `laju_per_detik`.

**Endpoint:** `GET /admin/email-laporan` (`require_admin`) → dict di atas. Tanpa alamat atau id user.

**Kartu "Email laporan" di halaman Admin** (`frontend/src/pages/Admin.jsx` + komponen kecil): status worker, antrean
(menunggu, umur tertua), terkirim 24 jam, gagal 7 hari, penerima `N / 300`, dan satu baris peringatan bila ada alarm
yang sedang berlaku. Gagal memuat → teks galat di kartu, halaman Admin lain tetap tampil.

**Alarm** (`pantau_email.periksa_alarm(...)`, dipanggil `laporan_job` tiap jam; kirim lewat Telegram bot ke
`ADMIN_TELEGRAM_ID`, pola `_notify_admin_new_user`):

| Kode | Syarat | Ulang paling cepat |
|---|---|---|
| `pindah_penyedia` | `penerima ≥ 300` dan `smtp_lokal` | 30 hari |
| `worker_mati` | tanda hidup tidak ada atau > 10 menit | 24 jam |
| `antrean_tersendat` | `tertua_menit > 360` | 24 jam |
| `email_gagal` | ada laporan `gagal` yang `email_terakhir_at`-nya sesudah alarm ini terakhir dikirim (pertama kali: 24 jam terakhir) | 24 jam |

- Waktu kirim terakhir per kode disimpan di `app_settings` (kunci `alarm_email_laporan:<kode>`, nilai waktu UTC ISO).
  Dicatat hanya bila pesan berhasil dikirim; Telegram admin tidak diatur atau gagal → `logger.warning` dengan kodenya,
  dicoba lagi jam berikutnya.
- Pesan berisi angka dan langkah singkat, tanpa alamat: mis. "📬 Penerima email laporan sudah 312. Saatnya pindah ke
  penyedia email transaksional — langkahnya di AGENTS.md bagian 'Pindah penyedia email'."; "⚠️ Worker email laporan
  tidak memberi tanda hidup sejak HH:MM WIB. Cek: sudo systemctl status jatahku-worker".
- `worker_mati` tidak dikirim dalam 15 menit pertama sesudah proses API menyala (deploy/restart), supaya deploy tidak
  memicu alarm palsu.

## 7. Dokumen

- `docs/laporan-berkala.md`: worker (putaran, laju, tanda hidup, berhenti), `laporan_job` tanpa email dan batas
  waktunya, pemantauan dan alarm, pemulihan (worker mati; kirim ulang tetap dengan UPDATE yang sama — worker
  mengambilnya dalam ±1 menit).
- `AGENTS.md`: checklist deploy PR ini; bagian baru **"Pindah penyedia email"** (verifikasi domain + SPF/DKIM di DNS;
  ganti `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` di `/opt/jatahku/.env`; restart `jatahku` dan
  `jatahku-worker`; tes email reset password dan cek "Tampilkan versi asli" → SPF/DKIM/DMARC PASS; sesuaikan
  `EMAIL_LAPORAN_PER_DETIK` dengan kuota penyedia; penyedia harus mengizinkan lampiran PDF dan header
  `List-Unsubscribe`).
- `CLAUDE.md`: satu baris di "Deploy" tentang `jatahku-worker`.
- Spec laporan berkala: status tahap 2 "tayang 10 Nov 2026" dan rujukan ke spec ini.

## 8. Pengujian

- **Worker:** jarak antar kiriman mengikuti laju (jam tiruan); kelompok penuh → tanpa jeda kosong; berhenti di tengah
  kelompok menyelesaikan kiriman berjalan dan tidak mengklaim yang baru; galat putaran tidak menghentikan worker; tanda
  hidup ditulis; Redis mati tidak menghentikan pengiriman; batas nilai `EMAIL_LAPORAN_PER_DETIK`.
- **Tanpa kiriman ganda:** dua putaran serentak atas antrean yang sama → setiap laporan terkirim sekali (pola tes
  barrier yang sudah ada).
- **`laporan_job`:** tidak memanggil antrean; batas 40 menit menunda sisanya dan jalan berikutnya menyelesaikannya;
  galat alarm tidak membatalkan job.
- **Alarm:** tiap syarat, batas ulang, pencatatan hanya saat terkirim, `pindah_penyedia` berhenti saat SMTP bukan
  lokal, masa tenang 15 menit, pesan tanpa `@`.
- **Endpoint Admin:** hanya admin; angka benar atas data uji; tanpa alamat.
- **Uji beban lokal** (skrip di scratchpad, tidak di-commit; hasil di PR): 2.000 laporan `menunggu` dengan pengirim
  tiruan dan PDF sungguhan, laju 20/detik → waktu selesai dan pemakaian CPU; dan laju 3/detik untuk 200 laporan →
  ±67 detik.
- **Deploy:** `deploy.sh` diuji dengan `bash -n` dan pembacaan ulang; pemasangan unit dibuktikan pemilik lewat
  checklist (`systemctl status jatahku-worker`, kartu Admin "worker hidup").
- Tangkapan layar kartu Admin, tema terang dan gelap.

## 9. Risiko dan batasan

- **Satu worker.** Dua worker tidak menggandakan email, tetapi laju totalnya dua kali; tidak didukung sebagai cara
  menaikkan laju — pakai `EMAIL_LAPORAN_PER_DETIK`.
- **Laju vs reputasi.** 3/detik dari IP VPS aman untuk volume sekarang; ribuan email per hari dari exim sendiri bisa
  dibatasi penyedia kotak surat. Itu sebabnya alarm `pindah_penyedia` ada di 300.
- **Aplikasi tidak tahu email yang ditolak sesudah diterima exim** (bounce); hanya penyedia transaksional yang
  melaporkannya. Tidak ditangani di sini.
- **RAM VPS 4 GB:** worker ±150 MB; dipantau lewat `systemctl status`.
