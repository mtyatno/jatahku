# Laporan berkala

Setiap periode anggaran yang tutup, setiap anggota ruang keluarga mendapat laporan bulanan: refleksi periode kemarin
yang dibekukan saat terbit, dibaca di halaman `/laporan`, dan bisa diunduh sebagai PDF ber-AES-256 dengan kata sandi
laporan yang diatur user sendiri. Lonceng dan Telegram memberi tahu saat laporan terbit. Desain dan keputusan produk:
`docs/superpowers/specs/2026-11-01-laporan-berkala-design.md` (Project doc `claude/laporan-berkala-desain.md`); rencana
tahap 1: `docs/superpowers/plans/2026-11-01-laporan-berkala-tahap-1.md`. "Ruling Rn" di bawah menunjuk keputusan saat
eksekusi rencana, yang dicatat di spec bagian "Penyesuaian saat eksekusi".

**Status (4 Nov 2026).** Tahap 1 (inti) selesai di kode di branch `feat/laporan-berkala`; PR berlabel `migrasi` belum
di-merge, jadi belum tayang. Revisi alembic `967a27d0c15d`. Langkah sebelum dan sesudah merge ada di `AGENTS.md`,
"Deploy Checklist — Laporan berkala tahap 1 (967a27d0c15d)". Tahap 2 (email, verifikasi email, berhenti berlangganan)
dan tahap 3 (kuartalan dan tahunan untuk Pro) mendapat rencana sendiri setelah tahap 1 tayang. Perbarui bagian ini saat
status berubah.

## Peta kode

| Berkas | Tugas |
|---|---|
| `app/services/laporan/schema.py` | `LAPORAN_DDL`: kolom `users.email_verified_at` (dijalankan lifespan dan revisi alembic) |
| `app/services/laporan/rahasia.py` | Fernet: enkripsi/dekripsi kata sandi laporan, cek kunci saat startup |
| `app/services/laporan/hitung.py` | fungsi murni: judul, nama file, status amplop, "pernah lewat batas", beruntun, persen, uang, sorotan |
| `app/services/laporan/susun.py` | dataclass bahan + `susun_bulanan` → `data` v1 (murni, tanpa DB) |
| `app/services/laporan/muat.py` | SATU-SATUNYA pembaca DB untuk isi laporan → `BahanLaporan`; lingkup dan penyamaran ditegakkan di sini |
| `app/services/pemasukan.py` | filter pemasukan bersama (analitik `_income_totals` dan laporan) |
| `app/services/laporan/job.py` | `laporan_job` (penerbitan per household) dan notifikasi |
| `app/services/laporan/pdf.py` + `app/assets/fonts/` | PDF dari `data`, AES-256, Noto Sans (OFL) |
| `app/api/routes/laporan.py` | `/laporan`, `/laporan/{id}`, `/laporan/{id}/pdf`, `/user/laporan-pengaturan` |
| `app/core/rate_limit.py` | `kunci_per_user`: kunci batas frekuensi per user yang terautentikasi |
| `frontend/src/lib/laporanView.js`, `lib/laporanFormat.js` | helper murni halaman dan alur unduh (diuji `node --test`) |
| `frontend/src/pages/Laporan.jsx`, `LaporanDetail.jsx`, `components/laporan/*`, `components/LaporanSettings.jsx` | UI |

## Model data

| Tabel / kolom | Isi |
|---|---|
| `reports` | Satu laporan yang sudah terbit. `user_id` (FK `users`, ON DELETE CASCADE), `household_id` (FK `households`, ON DELETE SET NULL: laporan mantan anggota tetap ada saat household dihapus), `jenis` (`bulanan`; `kuartalan`/`tahunan` di tahap 3), `periode_mulai`/`periode_akhir`, `payday_day` (tanggal gajian rumah saat terbit), `data` (JSONB beku), `terbit_at` (bawaan `now()`), `notified_at`, dan kolom antrean email tahap 2 (`email_status`, `email_alasan`, `email_percobaan` bawaan 0, `email_terakhir_at`, `email_terkirim_at`). Unik `uq_reports_user_jenis_periode (user_id, jenis, periode_mulai)`; indeks `ix_reports_email_antrean (email_status, email_terakhir_at)`. Tahap 1 membiarkan `email_status` NULL. |
| `report_settings` | Satu baris per user (kunci utama `user_id`, FK CASCADE), dibuat saat kata sandi pertama kali disimpan; tanpa baris = bawaan. `kata_sandi_enc` (token Fernet; NULL = belum diatur), `email_on`, `kuartalan_on`, `tahunan_on` (bawaan true; belum bisa diubah di tahap 1), `updated_at`. |
| `users.email_verified_at` | TIMESTAMPTZ NULL tanpa bawaan: NULL = belum (atau tidak lagi) terverifikasi. Belum ditulis jalur mana pun di tahap 1 (verifikasi email = tahap 2). |

**Pemasangan** (dua jalur, idempoten, pola Kotak Struk): restart API menjalankan `create_all` (dua tabel baru) dan
`LAPORAN_DDL` (`ADD COLUMN IF NOT EXISTS`) di `lifespan`; revisi `967a27d0c15d` membuat hal yang sama dengan
`if_not_exists`. Urutan restart dan `alembic upgrade` bebas, dan tidak ada jendela 500 (kolom `users` nullable). Syaratnya
user DB aplikasi pemilik `users` dan boleh REFERENCES `users`/`households` (checklist deploy). `downgrade` membuang kedua
tabel (termasuk laporan yang sudah terbit dan kata sandi laporan) dan kolomnya, dan hanya bermakna bersama kode lama.
Diuji di PostgreSQL 16 (4 Nov 2026): `cek-migrasi.sh` (naik, `alembic check`, turun, naik), dan skema hasil migrasi
identik dengan skema hasil lifespan-dulu (`pg_dump -s`, termasuk nama constraint dan bawaan server).

## Penerbitan

`laporan_job` (`app/services/laporan/job.py`) dijadwalkan di proses API (`scheduler.start_scheduler`, `id="laporan"`,
tiap jam pada menit 30, `max_instances=1`) dengan tanggal server (UTC), dan idempoten. Job memilih household bertipe
`rumah_tangga` yang punya anggota; ruang usaha tidak pernah diproses. Per household, seluruhnya di dalam
`household_lock` (kunci yang sama dengan job snapshot harian, `recompute_history`, dan `POST /snapshots/run`):

1. Tanggal gajian dibaca di dalam kunci (`current_payday`; household yang sudah dihapus dilewati). Periode yang paling
   baru tutup = `get_closed_periods(payday, today, 1)`, sama dengan job snapshot. Lewati bila periode itu berakhir lebih
   dari `JENDELA_TERBIT_HARI` = 7 hari lalu.
2. Prasyarat: ada ≥ 1 snapshot kunci periode itu di antara amplop household, artinya job snapshot 00:05 sudah
   memprosesnya. Belum ada → ditunda ke jam berikutnya (log DEBUG).
3. Calon penerima: anggota yang belum punya laporan bulanan periode itu dan `penerima_layak`: email tidak berawalan
   `deleted_`/`banned_` (akun tanpa email, hanya Telegram, tetap layak) dan akun dibuat paling lambat akhir periode
   (tanggal UTC). Tanpa calon, atau tanpa transaksi maupun alokasi di jendela pada amplop household mana pun, berhenti
   di sini (Ruling R9: buku besar hanya ditulis ulang bila ada laporan yang akan dibangun).
4. Refresh snapshot periode itu (Ruling R4): `create_monthly_snapshots(ps, pe, force=True, household_ids=[hid])`, lalu
   `advisor_cache.invalidate`. Snapshot dibekukan 00:05, sedangkan mutasi dan pola harian membaca transaksi hidup;
   transaksi bertanggal mundur yang dicatat sesudahnya akan membuat Σ mutasi ≠ terpakai. Periode yang paling baru tutup
   belum punya snapshot penerus, jadi menulis ulangnya aman. Refresh yang melaporkan error per amplop menggagalkan
   household itu untuk jam ini (`RefreshSnapshotGagal`, log ERROR): laporan tidak boleh beku tanpa belanja satu amplop.
5. Per calon: `muat_bahan` → dilewati bila tanpa aktivitas di lingkupnya (tanpa alokasi > 0 dan tanpa transaksi; tidak
   ada laporan kosong) → `Report` dengan `data = susun_bulanan(bahan)`. Satu commit untuk semua anggota household; log
   INFO `household=… payday=… periode … → …: N laporan terbit`.

Setelah kunci dilepas, tiap laporan baru diberi tahu lewat `notification_service.kirim` (lonceng selalu, Telegram bila
tertaut), lalu `notified_at` diisi. Judul `"{judul} siap"`, pesan `"Lihat bagaimana periode kemarin berjalan."`, tautan
`/laporan/{id}`; teks Telegram memuat tautan penuh `{APP_URL}/laporan/{id}` ("Buka laporan"). Tanpa nominal. Kegagalan satu
household dicatat dan tidak menghentikan yang lain; household itu dicoba lagi jam berikutnya selama jendela 7 hari.

**Jam terbit.** Di hari gajian, job snapshot jalan 00:05 UTC (07:05 WIB), jadi laporan normalnya terbit ±00:30 UTC
(07:30 WIB, 08:30 WITA, 09:30 WIT). Server mati beberapa hari: laporan tertinggal tetap terbit selama periodenya tutup
≤ 7 hari. Saat fitur tayang, periode yang tutup ≤ 7 hari sebelumnya ikut terbit; yang lebih lama tidak.

**Judul dan nama file.** Periode = bulan kalender (gajian tanggal 1): "Laporan Oktober 2026",
`jatahku-laporan-2026-10.pdf`. Selain itu "Laporan 25 Sep – 24 Okt 2026" (beda tahun: "Laporan 25 Des 2026 – 24 Jan
2027"), `jatahku-laporan-2026-09-25.pdf` (tanggal awal).

## Isi laporan (`data` v1, beku)

**Lingkup per penerima:** amplop bersama household (`owner_id` NULL) dan amplop pribadi milik penerima, aktif atau
tidak; amplop pribadi anggota lain tidak pernah dibaca, juga tidak untuk total pembanding. Ruang usaha tidak ikut.

**Baris amplop:** amplop lingkup yang punya snapshot periode itu (angka dari `monthly_snapshots`; kolom
`allocated_amount`/`spent_amount` NULL dihitung `calculate_envelope_balance`), ditambah amplop nonaktif tanpa snapshot
yang punya transaksi atau alokasi di jendela (`ditutup`, dihitung dengan fungsi penulis snapshot). Amplop aktif tanpa
snapshot, dan amplop yang tanggal UTC `created_at`-nya sesudah akhir periode walau punya snapshot (Ruling R8: refresh
paksa memberinya snapshot nol), tidak jadi baris.

Kunci `data` (uang = teks dua desimal, tanggal ISO, persen bilangan bulat, tanpa float):

| Kunci | Isi |
|---|---|
| `versi`, `jenis`, `judul`, `periode {mulai, akhir, gajian}`, `angka_per`, `penerima {nama, rumah}` | Identitas; `angka_per` = tanggal terbit ("Angka per …" di halaman dan PDF). |
| `ringkasan` | `pemasukan` (yang dicatat penerima sendiri, nominal > 0, tanpa penyesuaian cocokkan saldo: definisi analitik), `dialokasikan`, `terpakai`, `sisa` (Σ akhir), `dibawa` (Σ rollover), `persen_terpakai`. Jumlah uang meliputi semua baris; `persen_terpakai` hanya amplop selain tabungan, di pembilang dan penyebut (Ruling R5, sama dengan Beranda), jadi bukan Σ terpakai / Σ awal tabel. |
| `amplop[]` | `id, nama, emoji, jenis (bersama/pribadi), tujuan, awal, alokasi, terpakai, akhir, rollover, status, pernah_lewat_batas, ditutup`. Status berurutan: `tabungan` (purpose `saving`/`sinking_fund`), `lewat_batas` (akhir < 0), `kosong` (awal ≤ 0), `hampir_habis` (terpakai ≥ 70% awal), selain itu `aman`. `pernah_lewat_batas`: saldo harian (rollover masuk + alokasi menurut `income_date` − belanja menurut `transaction_date`) pernah < 0. |
| `banding` | Total periode lalu, rata-rata 3 periode sebelumnya, `persen_perubahan`, dan per amplop. Total dari terpakai SEMUA amplop lingkup yang punya snapshot periode itu, juga yang kini ditutup (Ruling R3), supaya tren tidak melompat saat amplop dibuat atau ditutup. |
| `harian[]`, `hari_terboros` | Terpakai per hari untuk setiap hari di jendela (nol ikut), hari terbesar. |
| `terbesar[]` | 5 pengeluaran terbesar (bukan penyesuaian): tanggal, amplop, keterangan tersamar, jumlah, pencatat. |
| `langganan` | `terbayar[]`: transaksi berpenanda tombol Bayar (`"🔄 "`) di jendela (keputusan rencana 2); `jatuh_tempo[]`: langganan aktif di amplop baris dengan `next_run` di periode berikutnya (Ruling R2). |
| `sorotan` | `hari_mencatat`, `beruntun_terpanjang` (catatan penerima sendiri, bukan penyesuaian), `streak_saat_ini` (`streak.get_streak`, 0 bila sudah putus: Ruling R7), `amplop_aman[]` (nama amplop selain tabungan, kosong, dan lewat batas yang tidak pernah lewat batas: Ruling R6), `target[]` (target tabungan; terkumpul = saldo akhir amplopnya). |
| `mutasi[]` | Pemasukan penerima + semua transaksi di amplop baris, urut tanggal (masuk sebelum keluar di hari yang sama): `tanggal, arah, amplop, keterangan, jumlah, pencatat, penyesuaian`. Σ keluar per amplop = terpakai amplop itu. |
| `email` | Ringkasan tanpa nominal untuk body email tahap 2 (persen terpakai, jumlah amplop aman dan lewat batas, tren, satu kalimat sorotan); dihitung dan dibekukan sejak tahap 1 (keputusan rencana 5), belum dipakai. |

Nilai `null` yang sah (persen tanpa penyebut, pembanding tanpa snapshot, `hari_terboros`, amplop tagihan berikut, dll.)
didaftar di docstring `susun.py`; halaman dan PDF menampilkannya "—" dan tidak pernah menghitung ulang.

**Beku.** Setelah terbit, `data` tidak pernah diubah: transaksi bertanggal mundur, edit, atau recompute riwayat
sesudahnya tidak mengubah laporan yang sudah terbit.

## Privasi

- Keterangan transaksi hanya lewat `visibility.masked_description`: transaksi privat anggota lain → "Transaksi privat".
  Penanda tagihan (`"🔄 "`) hanya dibaca dari keterangan yang boleh dilihat penerima, jadi awalan keterangan privat
  anggota lain tidak bocor lewat `langganan.terbayar`. Agregat (terpakai, alokasi) menghitung semua transaksi.
- Endpoint hanya melayani laporan milik pemanggil: satu kueri `id` + `user_id`; "tidak ada" dan "milik orang lain"
  sama-sama 404 dengan kueri yang sama. Anggota satu rumah pun tidak bisa membuka laporan anggota lain.
- Nominal hanya di aplikasi dan di PDF ber-AES-256; notifikasi dan Telegram tanpa nominal.

## Kata sandi laporan dan PDF

**Kata sandi.** Diatur di Pengaturan → Laporan (`PUT /user/laporan-pengaturan`). Dinormalkan NFC, harus 6–64 karakter,
dan lolos `pdf.periksa_kata_sandi` (Ruling R10): tidak kosong setelah SASLprep, tanpa karakter kontrol atau dua arah
bercampur, paling banyak 127 byte UTF-8, dan tidak diubah SASLprep (spasi lebar, karakter tak kasatmata, huruf lebar
penuh), karena pembaca berbasis pdfium memakai teks apa adanya. Ditolak → 422 dengan kalimat siap tampil. Disimpan
sebagai token Fernet dengan kunci `REPORT_SECRET_KEY` (hanya di `/opt/jatahku/.env`). API tidak pernah mengembalikan kata
sandi atau tokennya (hanya `kata_sandi_diatur`), galat 422 tidak memantulkan masukan, dan log hanya berisi teks tetap
dan id user. Mengganti kata sandi berlaku untuk unduhan berikutnya.

- **Kunci kosong atau tidak valid:** API tetap jalan; startup mencatat `REPORT_SECRET_KEY kosong atau tidak valid: kata
  sandi dan PDF laporan nonaktif`; simpan kata sandi dan unduh PDF → 503 `kunci_belum_diatur`.
- **Token tak terbaca (kunci diganti) atau kata sandi tersimpan yang kini ditolak:** diperlakukan seperti belum diatur
  (keputusan rencana 7): unduh → 409 `kata_sandi_belum_diatur`, `GET` → `kata_sandi_diatur: false`, warning di log; user
  mengatur ulang. Rotasi kunci di luar cakupan.

**PDF.** fpdf2 2.8.9, A4 tegak, dienkripsi `EncryptionMethod.AES_256` (PDF 2.0, revisi 6): kata sandi pengguna = kata
sandi laporan, kata sandi pemilik acak per berkas dan tidak disimpan; mencetak dan menyalin diizinkan. Font Noto Sans
Regular/Bold (OFL, `app/assets/fonts/`, tertanam subset); karakter di luar font (emoji, panah) dibuang. Header: Jatahku,
judul, periode, penerima dan rumah, "Angka per …"; bagian `Ringkasan`, `Amplop`, `Dibanding periode lalu`, `Pola harian`
(grafik batang dari primitif fpdf2), `5 pengeluaran terbesar`, `Langganan`, `Sorotan`, lalu `Lampiran: mutasi` (tabel
lintas halaman, judul kolom berulang); footer "Halaman x dari y" dan "Dibuat otomatis oleh Jatahku". Teks digambar
sebagai teks PDF, bukan HTML.

Dibuat saat diminta: koneksi DB dilepas sebelum render, render di thread (`asyncio.to_thread`) dengan paling banyak
`MAKS_PDF_SERENTAK` = 2 sekaligus (semaphore; yang lain menunggu giliran), hanya di memori (tidak ada berkas laporan di
disk), dijawab dengan `Cache-Control: no-store`. `pdf.py` memakai bagian dalam fpdf2 untuk dua hal: membersihkan cache
glyph global (`SubsetMap.pick/get_glyph`) dan menutup berkas font di `finally` setiap render, karena fpdf2 baru
melakukannya di akhir `output()` yang sukses; dan `StandardSecurityHandler.prepare_string` untuk SASLprep. Periksa lagi
keduanya setiap menaikkan versi fpdf2.

## Halaman web

- **Desktop (≥ 1024 px):** menu "Laporan" di sidebar setelah Analitik; `/laporan` arsip (terbaru di atas); `/laporan/:id`
  laporan lengkap bagian 1–8 (grafik recharts, mutasi 50 baris per langkah dengan "Tampilkan lebih banyak").
- **HP dan tablet (< 1024 px):** `/laporan/:id` tampil sebagai layar ringkas (judul, periode, angka utama, sorotan, tren,
  tombol besar "Unduh PDF"). Di tahap 1 tidak ada menu laporan di HP; layar ini dibuka dari lonceng atau tautan Telegram.
- **Banner** "Atur kata sandi laporan untuk mengunduh PDF." (tautan `/settings#laporan`) bila kata sandi belum diatur
  (banner email belum terverifikasi menyusul di tahap 2).
- **Unduh:** 200 → `native.files.save` dengan nama dari `nama_file` di JSON (CORS tidak membuka `Content-Disposition`);
  409 → dialog kata sandi, lalu diulang sekali; 429 → "Terlalu sering mengunduh. Coba lagi sebentar lagi."
- **Pengaturan → 📄 Laporan** (`#laporan`): status kata sandi dan formulir "Atur kata sandi"/"Ganti kata sandi". Toggle
  email, kuartalan, dan tahunan belum tampil di tahap 1.
- Tombol top bar ekspor manual (PDF/CSV) kini bernama "Ekspor" / "Ekspor {periode}".

## API

| Endpoint | Perilaku dan status |
|---|---|
| `GET /laporan?limit=24&offset=0` | Laporan milik pemanggil `[{id, jenis, judul, periode_mulai, periode_akhir, terbit_at, nama_file}]`, terbit terbaru dulu lalu periode terbaru. `limit` 1–100, `offset` 0–100000 (di luar → 422). `judul` dibaca dari JSONB oleh database (`data ->> 'judul'`), `data` utuh tidak ikut terbaca. |
| `GET /laporan/{id}` | Bentuk di atas + `data`. Bukan milik pemanggil atau tidak ada → 404 `"Laporan tidak ditemukan"`. |
| `GET /laporan/{id}/pdf` | 200 `application/pdf` (`Content-Disposition: attachment; filename="…"`, `no-store`). Galat menurut urutan pemeriksaan di route: 404; 503 `{"detail": …, "kode": "kunci_belum_diatur"}`; 409 `{"detail": "Atur kata sandi laporan dulu untuk mengunduh PDF.", "kode": "kata_sandi_belum_diatur"}`. Lebih dari 10/menit → 429 (diperiksa sebelum route). |
| `GET /user/laporan-pengaturan` | `{kata_sandi_diatur, email, email_terverifikasi, email_on, kuartalan_on, tahunan_on, pro}`; tanpa baris = bawaan dan tidak ada baris yang dibuat. |
| `PUT /user/laporan-pengaturan` | Badan `{"kata_sandi": "…"}` (hanya kata sandi di tahap 1) → bentuk GET. 422: `detail` kalimat siap tampil untuk panjang dan karakter, atau daftar `{type, loc, msg}` untuk badan salah bentuk; 503 `kunci_belum_diatur`; 429. |

Semua endpoint baru, jadi API hanya bertambah (`openapi_cek` bersih). Nama tidak bentrok dengan rencana Buku Usaha
(`/p/buku_usaha/laporan`).

## Keamanan

- **Batas frekuensi per user** (slowapi, limiter bersama `auth.limiter`): unduh PDF 10/menit untuk semua laporan user
  sekaligus (`shared_limit`, scope `laporan_pdf`), simpan kata sandi 5/jam. Kuncinya `kunci_per_user`
  (`app/core/rate_limit.py`, Ruling R11/R12): `user:<sub>` dari access token yang sah, jadi menulis ulang header,
  menambah karakter di ujung token, atau login ulang tidak memberi ember baru; token tidak sah jatuh ke alamat IP.
  Hitungan di memori proses API (satu proses uvicorn) dan kembali nol saat restart. Jawaban 429 berbadan `{"error": …}`
  (bawaan slowapi), bukan `{"detail": …}`.
- **Apa yang memakai jatah:** setiap permintaan yang sampai ke route, berhasil maupun ditolak. 422 dari validasi badan
  oleh pydantic (bukan JSON, tanpa `kata_sandi`, panjang di luar 6–64 titik kode) ditolak sebelum route berjalan dan
  tidak memakai jatah PUT; 422 dari route (panjang setelah NFC, karakter yang tak bisa dipakai di PDF) dan 503
  memakainya, begitu juga 404/409/503 untuk jatah unduh PDF. Jadi lima kata sandi yang ditolak route mengunci formulir
  selama satu jam.
- `REPORT_SECRET_KEY` dan kata sandi laporan tidak pernah di log, respons, atau repo; tidak ada berkas laporan di disk.

## Batasan yang diketahui

- **Cakupan tahap 1:** tanpa email laporan, verifikasi email, dan berhenti berlangganan (tahap 2); tanpa laporan
  kuartalan dan tahunan (tahap 3). `email_status` tetap NULL; toggle di `report_settings` hanya bisa dibaca. PDF tidak
  dikirim lewat bot Telegram atau chat web.
- **Alokasi bertanggal mundur ke amplop baru** (Ruling R8): alokasi ke amplop yang dibuat sesudah periode tutup (mis.
  amplop "Tabungan" yang dibuat otomatis oleh pemasukan bertanggal mundur) tidak tampil sebagai baris, padahal
  pemasukannya tetap dihitung di `ringkasan.pemasukan`.
- **Amplop yang dibuat di hari gajian sebelum 07:00 WIB** (tanggal UTC = akhir periode) tetap bisa muncul sebagai baris
  `kosong` (biaya R8).
- **Tagihan berikut di amplop baru** (Ruling R2): langganan pada amplop yang dibuat sesudah periode tutup tidak masuk
  `jatuh_tempo` laporan itu.
- **Anggota yang bergabung sesudah periode** tetap menerima laporan periode itu bila akunnya dibuat sebelum periode
  berakhir (kelayakan memakai tanggal akun, bukan tanggal bergabung); isinya amplop bersama (dan amplop pribadinya bila
  ada).
- **Notifikasi yang gagal tidak dicoba ulang:** `notified_at` tetap NULL, laporannya tetap ada di `/laporan`. Restart
  tepat di antara commit laporan dan pengiriman juga menghilangkan notifikasinya. Kirim ulang manual: bagian
  "Pemulihan".
- **Cache advisor** household dikosongkan setelah refresh walau refresh itu melaporkan error (tidak berbahaya: hanya
  dihitung ulang).
- **Gerbang refresh R9** menghitung aktivitas di semua amplop household, termasuk amplop pribadi anggota lain: bila hanya
  amplop itu yang beraktivitas dan ada calon tanpa aktivitas, refresh paksa berjalan tiap jam sampai jendela 7 hari
  habis (hanya biaya; laporan kosong tetap tidak terbit).
- **Snapshot yang belum ada** hanya dicatat di level DEBUG, juga di hari terakhir jendela.
- **Deskripsi beku:** transaksi yang ditandai privat sesudah laporan terbit tetap terbaca di laporan lama penerima lain.
  **Tanggal gajian diubah** dalam 7 hari sesudah periode tutup: laporan yang sudah terbit tetap; laporan berikutnya
  mengikuti siklus baru. **Jam server UTC:** transaksi bertanggal hari gajian yang dicatat sebelum 07:00 WIB tetap masuk
  periode baru (berbasis tanggal).
- **Teks `{nb}`** di nama amplop atau keterangan tercetak sebagai jumlah halaman di PDF (alias halaman fpdf2; kosmetik).
- **Gabung akun:** notifikasi sumber yang tautannya menunjuk laporan sumber yang bentrok dan dihapus berakhir di
  "Laporan tidak ditemukan"; `report_settings` target yang tanpa kata sandi tetap dipakai dan kata sandi sumber dibuang
  (aturan per baris).
- Periode yang tutup lebih dari 7 hari sebelum job berjalan tidak pernah mendapat laporan.
- Kata sandi PDF hanya penghalang akses santai; perlindungan utamanya kontrol akses aplikasi dan (tahap 2) email
  terverifikasi tanpa nominal.

## Pemulihan

- **Household gagal** (`laporan household=… ditunda ke jam berikutnya` atau `penerbitan laporan household=… gagal`): job
  mencoba lagi tiap jam selama jendela 7 hari, tanpa tindakan. Pantau: `journalctl -u jatahku | grep -i laporan`.
- **Menjalankan job manual** (mis. scheduler tidak berjalan): dari shell di VPS, **jauh dari menit :30** (job terjadwal),
  jauh dari 00:05 (job snapshot), dan tidak selagi tanggal gajian diubah. `household_lock` hanya berlaku di dalam satu
  proses, jadi proses shell tidak diserialkan dengan penulis snapshot di proses API. Laporan dobel tetap tidak mungkin
  (kunci unik), tetapi refresh snapshot yang bertabrakan menggagalkan household itu.
  ```bash
  cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -c "import asyncio, logging; \
  logging.basicConfig(level=logging.INFO); from app.services.laporan.job import laporan_job; print(asyncio.run(laporan_job()))"
  ```
  Keluaran terakhir `{'terbit': N, 'gagal': M}`. Jalankan **tanpa** argumen tanggal: `laporan_job(today=<tanggal lampau>)`
  melewati jendela 7 hari dan me-refresh paksa periode yang sudah punya snapshot penerus, sehingga rantai rollover
  sesudahnya tidak lagi cocok.
- **Kirim ulang notifikasi** laporan yang `notified_at`-nya NULL (laporan yang sudah diberi tahu dilewati):
  ```bash
  sudo -u postgres psql jatahku_db -c "SELECT id, terbit_at FROM reports WHERE notified_at IS NULL ORDER BY terbit_at"
  cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -c "import asyncio, uuid; \
  from app.services.laporan.job import kirim_notifikasi_laporan as k; asyncio.run(k(uuid.UUID('<id>')))"
  ```
- **`REPORT_SECRET_KEY` hilang atau tidak valid** (startup mencatat peringatannya; PUT dan unduh 503): isi kunci di
  `.env`, lalu `sudo systemctl restart jatahku`. Kunci **lain** dari sebelumnya membuat kata sandi tersimpan tak terbaca:
  user diminta mengatur ulang (409 dan banner), laporannya sendiri tidak terpengaruh.

## Pengujian

- Backend (tanpa Postgres): `test_laporan_model` (tabel, DDL, lifespan, revisi alembic termasuk bawaan server),
  `test_laporan_rahasia`, `test_laporan_hitung`, `test_laporan_susun`, `test_laporan_muat` (SQLite: lingkup, penyamaran,
  R2/R3/R8), `test_laporan_job` (unit + ujung ke ujung SQLite: refresh R4, idempoten, jendela, notifikasi),
  `test_laporan_pdf` (pypdfium2: terbuka hanya dengan kata sandi, multi-halaman, emoji), `test_laporan_api` (IDOR, 409/503,
  kata sandi tidak pernah dikembalikan, batas frekuensi per user), `test_laporan_akun` (hapus dan gabung akun),
  `test_rate_limit`.
- Frontend: `node --test src/lib/*.test.js` (`laporanView`, `laporanFormat`, `exportPeriod`), lalu `npm run build`.
- PostgreSQL 16 nyata (4 Nov 2026, klaster sementara): `cek-migrasi.sh`; perbandingan skema migrasi vs lifespan; dan
  tes ber-SQLite (`test_laporan_model` integrasi, `test_laporan_muat`, ujung ke ujung `test_laporan_job`,
  `test_laporan_api`, `test_laporan_akun`; 110 tes) dijalankan ulang di Postgres. Semua lulus kecuali lima tes yang
  memeriksa SQL khas SQLite (`PRAGMA foreign_keys`, `JSON_EXTRACT`); di Postgres daftar laporan memakai
  `data ->> 'judul'` dan simpan kata sandi memakai `FOR NO KEY UPDATE`, keduanya jalan.
