# Laporan berkala

Setiap periode anggaran yang tutup, setiap anggota ruang keluarga mendapat laporan bulanan: refleksi periode kemarin
yang dibekukan saat terbit, dibaca di halaman `/laporan`, dan bisa diunduh sebagai PDF ber-AES-256 dengan kata sandi
laporan yang diatur user sendiri. Lonceng dan Telegram memberi tahu saat laporan terbit, dan (tahap 2) laporan juga
dikirim ke email yang sudah diverifikasi, dengan PDF terlampir. Desain dan keputusan produk:
`docs/superpowers/specs/2026-11-01-laporan-berkala-design.md` (Project doc `claude/laporan-berkala-desain.md`); rencana
tahap 1: `docs/superpowers/plans/2026-11-01-laporan-berkala-tahap-1.md`; rencana tahap 2:
`docs/superpowers/plans/2026-11-05-laporan-berkala-tahap-2.md`. "Ruling Rn" di bawah menunjuk keputusan saat eksekusi
rencana tahap 1, "R-T3-n" dan "F-n" keputusan tahap 2 (review per tugas dan review akhir); keduanya dicatat di spec
("Penyesuaian saat eksekusi" dan "Penyesuaian saat eksekusi tahap 2"). Pengiriman email dijalankan worker tersendiri
(`jatahku-worker`), bukan lagi `laporan_job`: desain `docs/superpowers/specs/2026-11-11-worker-email-laporan-design.md`
(keputusan saat eksekusi: "Penyesuaian saat eksekusi (12 Nov 2026)"), rencana
`docs/superpowers/plans/2026-11-11-worker-email-laporan.md`.

**Status (5 Nov 2026).** Tahap 1 (inti) tayang 5 Nov 2026: PR #190 (squash `56ddf74`), revisi alembic `967a27d0c15d`
dan checklist deploy di `AGENTS.md` ("Deploy Checklist — Laporan berkala tahap 1 (967a27d0c15d)") dijalankan pemilik.
Job pertama (5 Nov 04.30 WIB) menerbitkan 21 laporan untuk rumah yang periodenya tutup ≤ 7 hari sebelumnya (gajian
tanggal 1 dan 30), semuanya diberi tahu. Tahap 2 (email laporan, verifikasi email, berhenti berlangganan) tayang
10 Nov 2026 (PR #198, #203, #206; tanpa migrasi). **Worker email laporan** (12 Nov 2026): antrean email pindah dari
`laporan_job` ke service `jatahku-worker` dengan laju tetap, ditambah kartu Admin dan alarm Telegram; selesai dikerjakan
di branch `feat/worker-email-laporan` (tanpa migrasi), **belum digabung dan belum tayang** (menunggu review akhir, merge,
dan checklist "Worker email laporan" di `AGENTS.md`). Bagian di bawah menggambarkan keadaan sesudah merge; sebelum itu
antrean masih dijalankan `laporan_job` (50 laporan per jam). Tahap 3 (kuartalan dan tahunan untuk Pro) mendapat rencana
sendiri. Perbarui bagian ini saat status berubah.

## Peta kode

| Berkas | Tugas |
|---|---|
| `app/services/laporan/schema.py` | `LAPORAN_DDL`: kolom `users.email_verified_at` (dijalankan lifespan dan revisi alembic) |
| `app/services/laporan/rahasia.py` | Fernet: enkripsi/dekripsi kata sandi laporan, cek kunci saat startup |
| `app/services/laporan/hitung.py` | fungsi murni: judul, nama file, status amplop, "pernah lewat batas", beruntun, persen, uang, sorotan |
| `app/services/laporan/susun.py` | dataclass bahan + `susun_bulanan` → `data` v1 (murni, tanpa DB) |
| `app/services/laporan/muat.py` | SATU-SATUNYA pembaca DB untuk isi laporan → `BahanLaporan`; lingkup dan penyamaran ditegakkan di sini |
| `app/services/laporan/pencatat.py` | SATU-SATUNYA penulis ulang `data` setelah terbit: anonimisasi saat hapus akun, `pencatat_id` saat gabung akun (Ruling R15) |
| `app/services/pemasukan.py` | filter pemasukan bersama (analitik `_income_totals` dan laporan) |
| `app/services/laporan/job.py` | `laporan_job` (penerbitan per household, batas waktu `BATAS_JALAN`), notifikasi, lalu pemeriksaan alarm; **tidak** mengirim email |
| `app/services/laporan/antrean_email.py` | antrean email: `status_awal`, `putaran_antrean` (satu putaran yang bisa dipacu dan dihentikan; `KELOMPOK`), `proses_antrean_email` (satu putaran tanpa pacu, untuk jalan manual), `lampiran_untuk`, `hidupkan_lagi`, `AWALAN_AKUN_NONAKTIF` |
| `app/services/laporan/worker_email.py` | worker: loop `putaran_antrean` dengan laju tetap, tanda hidup di Redis, berhenti rapi; `python -m app.services.laporan.worker_email` |
| `app/services/laporan/pantau_email.py` | `keadaan_email` (angka antrean dan tanda hidup, dipakai kartu Admin), `periksa_alarm` (alarm Telegram admin, dipanggil `laporan_job`), `API_MENYALA` |
| `deploy/jatahku-worker.service` | unit systemd worker; dipasang dan di-restart oleh `deploy.sh` |
| `app/services/laporan/surel.py` | fungsi murni: isi email laporan dan verifikasi, tautan dan halaman berhenti berlangganan, halaman konfirmasi verifikasi |
| `app/services/verifikasi_email.py` | token verifikasi (24 jam; membawa sidik alamat, bukan alamat: `sidik_email`, `cocok_email`), `sama_email`, `tandai_terverifikasi` |
| `app/services/email_service.py` | satu-satunya tempat SMTP (email laporan dikirim dari proses worker): `send_laporan_email` (MIME + PDF + List-Unsubscribe), `send_verifikasi_email`, `SMTP_TIMEOUT` |
| `app/core/security.py` | `create_purpose_token` / `decode_purpose_token`: token bertujuan (klaim `type`; `berlaku` wajib disebut) |
| `app/services/laporan/pdf.py` + `app/assets/fonts/` | PDF dari `data`, AES-256, Noto Sans (OFL) |
| `app/api/routes/laporan.py` | `/laporan`, `/laporan/{id}`, `/laporan/{id}/pdf`, `/laporan/berhenti-email`, `/user/laporan-pengaturan` (GET, PUT, PATCH) |
| `app/api/routes/verifikasi_email.py` | `POST /user/email/verifikasi` (kirim tautan), `GET /auth/verifikasi-email` (tautan di email: halaman konfirmasi, tidak menulis) dan `POST /auth/verifikasi-email` (tombol "Verifikasi email") |
| `app/core/rate_limit.py` | `kunci_per_user`: kunci batas frekuensi per user yang terautentikasi |
| `app/api/routes/admin.py` | `GET /admin/email-laporan` (keadaan antrean + alarm yang berlaku, `require_admin`) |
| `frontend/src/components/admin/EmailLaporanCard.jsx`, `lib/emailLaporanView.js` | kartu "Email laporan" di halaman Admin (logika murni diuji `node --test`) |
| `app/core/log_akses.py` | filter logger `uvicorn.access`: nilai `?token=`/`?code=` dan nilai berisi alamat email ditulis `***`; dipasang di `app/main.py` |
| `frontend/src/lib/laporanView.js`, `lib/laporanFormat.js` | helper murni halaman dan alur unduh (diuji `node --test`) |
| `frontend/src/pages/Laporan.jsx`, `LaporanDetail.jsx`, `components/laporan/*`, `components/LaporanSettings.jsx` | UI (kartu Pengaturan memuat status email, tautan verifikasi, dan saklar email) |

## Model data

| Tabel / kolom | Isi |
|---|---|
| `reports` | Satu laporan yang sudah terbit. `user_id` (FK `users`, ON DELETE CASCADE), `household_id` (FK `households`, ON DELETE SET NULL: laporan mantan anggota tetap ada saat household dihapus), `jenis` (`bulanan`; `kuartalan`/`tahunan` di tahap 3), `periode_mulai`/`periode_akhir`, `payday_day` (tanggal gajian rumah saat terbit), `data` (JSONB beku), `terbit_at` (bawaan `now()`), `notified_at`, dan kolom antrean email tahap 2 (`email_status`, `email_alasan`, `email_percobaan` bawaan 0, `email_terakhir_at`, `email_terkirim_at`). Unik `uq_reports_user_jenis_periode (user_id, jenis, periode_mulai)`; indeks `ix_reports_email_antrean (email_status, email_terakhir_at)`. Tahap 1 membiarkan `email_status` NULL. |
| `report_settings` | Satu baris per user (kunci utama `user_id`, FK CASCADE), dibuat saat kata sandi pertama kali disimpan atau saklar email pertama kali diubah (PATCH, atau berhenti berlangganan); tanpa baris = bawaan. `kata_sandi_enc` (token Fernet; NULL = belum diatur), `email_on` (bisa diubah sejak tahap 2), `kuartalan_on`, `tahunan_on` (bawaan true; belum bisa diubah, tahap 3), `updated_at`. |
| `users.email_verified_at` | TIMESTAMPTZ NULL tanpa bawaan: NULL = belum (atau tidak lagi) terverifikasi. Diisi (tahap 2) oleh tombol "Verifikasi email" di halaman tautan verifikasi (POST) dan oleh login/tautan Google yang emailnya sama dengan email akun (Google menjamin `email_verified`); dikosongkan oleh event model `User.email` (`app/models/models.py`): jalur apa pun yang mengganti `users.email` lewat atribut ORM (route, bot, admin) mengosongkannya bila alamatnya benar-benar berganti (beda huruf besar-kecil atau spasi saja tidak). UPDATE Core atas kolom email tidak lewat event itu; tes pagar melarangnya. |

Tahap 2 tanpa migrasi: semua kolom email di `reports` dan `email_verified_at` sudah ada sejak revisi `967a27d0c15d`.
`reports.email_status` (`String(16)`): `menunggu`, `mengirim`, `terkirim`, `gagal`, `dilewati`; `email_alasan`
(`String(32)`): `belum_verifikasi`, `tanpa_email`, `dimatikan` (untuk `dilewati`) dan `smtp` (untuk `gagal`);
`email_percobaan` = jumlah klaim kirim (bagian "Email laporan").

**Pemasangan** (dua jalur, idempoten, pola Kotak Struk): restart API menjalankan `create_all` (dua tabel baru) dan
`LAPORAN_DDL` (`ADD COLUMN IF NOT EXISTS`) di `lifespan`; revisi `967a27d0c15d` membuat hal yang sama dengan
`if_not_exists`. Urutan restart dan `alembic upgrade` bebas, dan tidak ada jendela 500 (kolom `users` nullable). Syaratnya
user DB aplikasi pemilik `users` dan boleh REFERENCES `users`/`households` (checklist deploy). `downgrade` membuang kedua
tabel (termasuk laporan yang sudah terbit dan kata sandi laporan) dan kolomnya, dan hanya bermakna bersama kode lama.
Diuji di PostgreSQL 16 (4 Nov 2026): `cek-migrasi.sh` (naik, `alembic check`, turun, naik), dan skema hasil migrasi
identik dengan skema hasil lifespan-dulu (`pg_dump -s`, termasuk nama constraint dan bawaan server).

## Penerbitan

`laporan_job` (`app/services/laporan/job.py`) dijadwalkan di proses API (`scheduler.start_scheduler`, `id="laporan"`,
tiap jam pada menit 30, `max_instances=1`) dengan tanggal server (UTC), dan idempoten. Job hanya menerbitkan laporan,
memberi tahu, dan memeriksa alarm; **email tidak dikirim di sini** (bagian "Email laporan": worker). Job memilih household bertipe
`rumah_tangga` yang punya anggota; ruang usaha tidak pernah diproses. Per household, seluruhnya di dalam
`household_lock` (kunci yang sama dengan job snapshot harian, `recompute_history`, dan `POST /snapshots/run`):

1. Tanggal gajian dibaca di dalam kunci (`current_payday`; household yang sudah dihapus dilewati). Periode yang paling
   baru tutup = `get_closed_periods(payday, today, 1)`, sama dengan job snapshot. Lewati bila periode itu berakhir lebih
   dari `JENDELA_TERBIT_HARI` = 7 hari lalu.
2. Prasyarat: ada ≥ 1 snapshot kunci periode itu di antara amplop household, artinya job snapshot 00:05 sudah
   memprosesnya. Belum ada → ditunda ke jam berikutnya (log DEBUG). Di hari terakhir jendela (7 hari setelah periode
   tutup), household yang punya transaksi atau alokasi di periode itu dicatat WARNING (Ruling R16: `… masih belum punya
   snapshot di hari terakhir jendela terbit; laporan periode ini tidak akan terbit …`), karena laporannya hilang bila
   snapshot tidak dibuat hari itu.
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

Saat dibuat, setiap laporan mendapat status email awal dari `antrean_email.status_awal(user, pengaturan)` (pengaturan semua
calon dibaca dalam satu kueri): `menunggu`, atau `dilewati` dengan alasan `tanpa_email` (akun hanya Telegram),
`belum_verifikasi`, atau `dimatikan`, dalam urutan itu. Laporan yang `dilewati` tidak hilang: lihat "Email laporan".

Setelah kunci dilepas, tiap laporan baru diberi tahu (`kirim_notifikasi_laporan`, Ruling R16): lonceng dan `notified_at`
disimpan dalam **satu transaksi**, didahului UPDATE bersyarat `notified_at IS NULL` yang harus mengenai tepat satu baris
(proses lain yang bersamaan tidak bisa ikut membuat lonceng); sesudah commit, Telegram (bila tertaut) dikirim **sekali**
lewat `notification_service.kirim(permukaan=("telegram",))`, best-effort. Judul `"{judul} siap"`, pesan `"Lihat
bagaimana periode kemarin berjalan."`, tautan `/laporan/{id}`; teks Telegram memuat tautan penuh `{APP_URL}/laporan/{id}`
("Buka laporan"). Tanpa nominal. Kegagalan satu household dicatat dan tidak menghentikan yang lain; household itu dicoba
lagi jam berikutnya selama jendela 7 hari.

**Sapu notifikasi** (`kirim_notifikasi_tertunda`, akhir setiap jalan): laporan yang `notified_at`-nya masih NULL dan
`terbit_at`-nya paling awal 00:00 UTC tujuh hari sebelum hari job diberi tahu lewat jalur yang sama, terlama dulu;
laporan yang sudah dicoba di jalan itu dilewati (tidak dicoba dua kali dalam satu jam). Jadi galat DB atau restart di
antara commit laporan dan notifikasinya tersusulkan jam berikutnya, tanpa lonceng kedua; Telegram yang gagal permanen
(bot diblokir) tidak dikirim ulang karena `notified_at` sudah terisi bersama lonceng. Log INFO `N notifikasi laporan
yang tertinggal dikirim`; galat per laporan `logger.exception`, dicoba lagi jam berikutnya sampai keluar jendela.

**Batas waktu** (`BATAS_JALAN` = 40 menit): household baru tidak dimulai sesudah 40 menit sejak job mulai (jam monotonik),
supaya satu jalan tidak bertabrakan dengan jalan jam berikutnya (`max_instances=1`). Household yang belum dimulai
dihitung `ditunda`: tidak diterbitkan dan tidak diberi tahu di jalan itu (WARNING `laporan_job melewati batas 40 menit: N
household ditunda ke jam berikutnya`), dan diselesaikan jalan berikutnya karena penerbitan idempoten. Sapu notifikasi dan
pemeriksaan alarm tetap berjalan. Jalan yang menerbitkan, menggagalkan, atau menunda sesuatu mencatat satu baris INFO
`laporan_job selesai dalam X.X detik: N terbit, M gagal, K ditunda`; jalan sepi tiap jam tidak menambah log. Proses API
tidak mengatur logging (hanya WARNING ke atas yang sampai ke journal `jatahku`), jadi baris INFO ini tidak muncul di
journal; WARNING penundaan (`laporan_job melewati batas 40 menit …`) muncul.

**Pemeriksaan alarm** (paling akhir, `pantau_email.periksa_alarm`, bagian "Pemantauan dan alarm"), dengan sesi database
dan klien Redis milik sendiri. Galat apa pun dicatat (`pemeriksaan alarm email laporan gagal; dicoba lagi jam berikutnya`)
dan tidak mengubah hasil job. `laporan_job` mengembalikan `{"terbit": N, "gagal": M, "ditunda": K}` (tanpa kunci
`email`: sebelum worker hasilnya memuat `"email": {...}`).

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
| `terbesar[]` | 5 pengeluaran terbesar (bukan penyesuaian): tanggal, amplop, keterangan tersamar, jumlah, pencatat, `pencatat_id`. |
| `langganan` | `terbayar[]`: transaksi berpenanda tombol Bayar (`"🔄 "`) di jendela (keputusan rencana 2), namanya dari keterangan pembayaran, dengan `pencatat_id` pembayarnya; `jatuh_tempo[]`: langganan aktif di amplop baris dengan `next_run` di periode berikutnya (Ruling R2), tanpa `pencatat_id` (langganan tidak menyimpan pembuatnya). |
| `sorotan` | `hari_mencatat`, `beruntun_terpanjang` (catatan penerima sendiri, bukan penyesuaian), `streak_saat_ini` (`streak.get_streak`, 0 bila sudah putus: Ruling R7), `amplop_aman[]` (nama amplop selain tabungan, kosong, dan lewat batas yang tidak pernah lewat batas: Ruling R6), `target[]` (target tabungan; terkumpul = saldo akhir amplopnya). |
| `mutasi[]` | Pemasukan penerima + semua transaksi di amplop baris, urut tanggal (masuk sebelum keluar di hari yang sama): `tanggal, arah, amplop, keterangan, jumlah, pencatat, pencatat_id, penyesuaian`. Σ keluar per amplop = terpakai amplop itu. |
| `email` | Ringkasan tanpa nominal untuk body email (persen terpakai, jumlah amplop aman dan lewat batas, tren, satu kalimat sorotan); dihitung dan dibekukan sejak tahap 1 (keputusan rencana 5), dipakai email tahap 2. |

Nilai `null` yang sah (persen tanpa penyebut, pembanding tanpa snapshot, `hari_terboros`, amplop tagihan berikut, dll.)
didaftar di docstring `susun.py`; halaman dan PDF menampilkannya "—" dan tidak pernah menghitung ulang.

**`pencatat_id`** (Ruling R15; ditambahkan di versi 1, `versi` tetap 1 karena hanya bertambah): id user (teks UUID)
yang mencatat baris itu, di setiap baris yang memuat nama atau teks seorang pencatat (`terbesar[]`,
`langganan.terbayar[]`, `mutasi[]`; baris `masuk` = penerima). Dibekukan untuk hapus dan gabung akun (bagian Privasi),
tidak pernah ditampilkan di halaman maupun PDF. Nama tidak unik, jadi tidak bisa menggantikannya.

**Beku.** Setelah terbit, `data` tidak pernah diubah: transaksi bertanggal mundur, edit, atau recompute riwayat
sesudahnya tidak mengubah laporan yang sudah terbit. Satu-satunya pengecualian: hapus akun menganonimkan catatan
anggota yang menghapus akun di laporan anggota lain, dan gabung akun mengalihkan `pencatat_id` (Ruling R15, bagian
Privasi); angka tidak pernah berubah.

## Privasi

- Keterangan transaksi hanya lewat `visibility.masked_description`: transaksi privat anggota lain → "Transaksi privat".
  Penanda tagihan (`"🔄 "`) hanya dibaca dari keterangan yang boleh dilihat penerima, jadi awalan keterangan privat
  anggota lain tidak bocor lewat `langganan.terbayar`. Agregat (terpakai, alokasi) menghitung semua transaksi.
- Endpoint hanya melayani laporan milik pemanggil: satu kueri `id` + `user_id`; "tidak ada" dan "milik orang lain"
  sama-sama 404 dengan kueri yang sama. Anggota satu rumah pun tidak bisa membuka laporan anggota lain.
- Nominal hanya di aplikasi dan di PDF ber-AES-256; notifikasi dan Telegram tanpa nominal.
- **Hapus akun** (Ruling R15, `pencatat.anonimkan_pencatat` dari `account_deletion.delete_account`, setelah catatan
  hidupnya dianonimkan dan sebelum baris `users` dihapus): di laporan beku milik user **lain** (anggota serumah sekarang
  atau dulu, juga laporan yang household-nya ikut terhapus), persis baris yang `pencatat_id`-nya akun itu ditulis ulang
  seperti catatan hidupnya: `pencatat` → "Mantan anggota", `pencatat_id` → id Mantan anggota, `keterangan` (dan `nama`
  tagihan terbayar) → "Transaksi mantan anggota" (baris masuk: "Pemasukan mantan anggota"); "Transaksi privat" tetap
  "Transaksi privat", seperti aplikasi menampilkan catatan privat yang sudah dianonimkan. Angka, tanggal, dan amplop
  tidak berubah; baris tagihan tetap di `langganan.terbayar` walau catatan hidupnya kehilangan penanda tombol Bayar.
  Laporan akun itu sendiri ikut terhapus. Ini satu-satunya perubahan `data` setelah terbit. Laporan dicari dengan
  `CAST(data AS TEXT) LIKE '%<id>%'` (memindai tabel `reports`; ringan di skala sekarang), lalu barisnya dipilih menurut
  `pencatat_id` di Python dan disimpan sebagai objek baru (UPDATE).
- **Gabung akun** (`pencatat.alihkan_pencatat` dari `merge.merge_users`, langkah 2e): `pencatat_id` sumber → target di
  semua laporan (termasuk laporan sumber yang pindah ke target); nama dan teks tetap seperti saat terbit. Hapus akun
  target kelak ikut menganonimkan baris yang dicatat sumber.
- **`pencatat_id` di respons** `GET /laporan/{id}` (di dalam `data`) tidak membuka hal baru: id anggota serumah sudah
  terlihat satu sama lain lewat `GET /household/members` dan `/household/leaderboard` (`user_id`) dan `GET /transactions/`
  (`user_id` setiap transaksi di amplop bersama). Halaman dan PDF tidak pernah menampilkannya (dijaga tes PDF).
- Nama amplop, target tabungan, dan langganan (`jatuh_tempo`) tidak menyimpan pembuatnya, dan hapus akun di aplikasi
  juga membiarkannya (benda rumah); salinan bekunya di laporan ikut dibiarkan.

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

## Email laporan (tahap 2)

Laporan yang terbit dikirim ke `users.email` bila alamatnya **terverifikasi** (`email_verified_at` tidak NULL) dan
`report_settings.email_on` true (bawaan). Tanpa nominal rupiah di badan maupun subjek; nominal hanya di PDF terlampir.

**Verifikasi.** `POST /user/email/verifikasi` (tombol "Kirim tautan verifikasi") mengirim email "Verifikasi email Jatahku
kamu" lewat `email_service.send_verifikasi_email` ke alamat akun pemanggil sendiri. Tautannya
`{API_URL}/auth/verifikasi-email?token=…`; token JWT (`JWT_SECRET`) bertujuan `verifikasi_email` dengan klaim `sub` (id
user) dan `eh` (sidik alamat, lihat di bawah), berlaku 24 jam. **Membuka tautan (GET) tidak mengubah apa pun** (Ruling F-4): pemindai
tautan di layanan email membuka GET, jadi yang tampil halaman "Verifikasi email kamu" ("Klik tombol di bawah untuk
memverifikasi {email} sebagai alamat penerima laporan Jatahku.") dengan tombol "Verifikasi email". Tombol itu mengirim
POST ke alamat yang sama; hanya POST yang memverifikasi, lalu 303 ke Pengaturan (`?email_verifikasi=berhasil`). Pola ini
sama dengan tautan berhenti berlangganan. Yang diverifikasi alamat **akun di database, dan hanya bila sidiknya cocok
dengan token**: bila alamat akun sudah berganti sejak tautan dikirim hasilnya `berubah` dan tidak ada yang ditulis
(alamat yang hanya berbeda huruf besar-kecil atau spasi tepi tetap cocok). Alamat di halaman konfirmasi juga dari database.
Tautan yang tidak perlu atau tidak bisa dikonfirmasi tidak menampilkan halaman: GET langsung 303 dengan `tidak_berlaku`,
`berubah`, atau `berhasil` (alamat ini sudah terverifikasi). Login atau tautan Google dengan email yang sama dengan email
akun juga memverifikasi (Google menjamin alamatnya). Mengganti email lewat jalur ORM mana pun mengosongkan verifikasi
(bagian Model data).

**Token verifikasi tidak memuat alamat** (11 Nov 2026). Badan JWT hanya base64url dan token ada di URL (email, riwayat
peramban, log akses), jadi klaim `email` yang lama membuat alamat terbaca siapa pun yang memegang tautan. Gantinya klaim
`eh`: HMAC-SHA256 (hex) dari alamat yang dinormalkan (`models.email_normal`: strip + huruf kecil), dengan kunci
`HMAC-SHA256(JWT_SECRET, "verifikasi-email/v1")` (pemisah domain; tanpa kunci `.env` baru). Hash tanpa kunci tidak
cukup: alamat yang mudah ditebak bisa dicocokkan. `verifikasi_email.cocok_email(user.email, sidik)` membandingkan
dengan `hmac.compare_digest`; alamat kosong tidak pernah cocok. **Token bentuk lama (klaim `email`, tanpa `eh`) ditolak
sebagai `tidak_berlaku`** walau belum 24 jam: user menekan "Kirim tautan verifikasi" lagi. Mengganti `JWT_SECRET`
membatalkan token ini seperti semua token.

**Isi email laporan** (`surel.isi_email_laporan`, fungsi murni; semua isi dari user atau data lewat `email_service.h`),
bergaya pernyataan resmi (sejak 10 Nov 2026, sesudah tayang): subjek `"{judul} · Jatahku"`; judul laporan sebagai kepala;
sapaan `"Yth. Bapak/Ibu {nama},"` (nama kosong → `"Yth. Bapak/Ibu,"`); pembuka `"Laporan keuangan periodik Anda untuk
periode {27 Sep – 26 Okt 2026} telah terbit. "` + `"Rincian lengkapnya tersedia dalam berkas PDF terlampir."` (`terlampir`)
atau `"Rincian lengkapnya dapat dilihat di aplikasi."` (lainnya); periode tak terbaca → `"Laporan keuangan periodik Anda
telah terbit. …"` dan tanpa baris ©. Kotak **RINGKASAN PERIODE**: `"Anggaran terpakai: {persen}%"` (null → `—`),
`"Amplop aman: {n} · Lewat batas: {m}"`, tren `"Pengeluaran: naik/turun {x}% dibanding periode sebelumnya"` atau
`"Pengeluaran: sama dengan periode sebelumnya"` (null → tanpa baris), dan `"Rekor mencatat: {n} hari berturut-turut"` dari
`data.sorotan.beruntun_terpanjang` (hanya bila ≥ 2). Kotak PDF (judul + isi, per status lampiran, di bawah). Tombol
"Buka Laporan di Jatahku →" → `{APP_URL}/laporan/{id}`. Penutup: "(Email ini dibuat secara otomatis oleh sistem, mohon
tidak membalas email ini.)" dan **Keterangan** (1. dibuat secara komputerisasi tanpa tanda tangan; 2. bukan pemilik akun
→ abaikan dan hapus email beserta lampirannya; 3. "Untuk bantuan, hubungi hi@jatahku.com." — `surel.KONTAK_BANTUAN`).
Kaki: "Tidak ingin menerima laporan lewat email? Berhenti berlangganan", lalu baris "© {tahun akhir periode}
Jatahku.com". Yang dibaca dari `data` hanya `judul`, `periode`, `email` (persen, hitungan amplop, tren) dan
`sorotan.beruntun_terpanjang`: tidak ada nominal, dan kata sandi tidak pernah disebut atau dicontohkan (kata sandi laporan
dipilih sendiri oleh user). Header `List-Unsubscribe` (tautan berhenti dan `mailto:`) dan `List-Unsubscribe-Post:
List-Unsubscribe=One-Click` (RFC 8058). Kotak PDF: `terlampir` "🔒 Membuka berkas PDF" — "Berkas PDF terlampir dilindungi
kata sandi laporan yang Anda atur di Pengaturan → Laporan. Demi keamanan, kata sandi tidak pernah dikirim lewat email.
Lupa kata sandi? Atur ulang di Pengaturan → Laporan, lalu unduh PDF dari halaman laporan."; `belum_diatur` "🔒 Berkas PDF"
— "PDF belum dilampirkan karena kata sandi laporan belum diatur. Atur di Pengaturan → Laporan agar laporan berikutnya
disertai PDF terkunci."; `tidak_tersedia` (dan kode tak dikenal) "🔒 Berkas PDF" — "PDF tidak dapat dilampirkan kali ini.
Rincian lengkap tetap tersedia di aplikasi.". Versi teks polos memuat isi yang sama. PDF dibuat dengan
`pdf.buat_pdf` dan kata sandi laporan user (nama berkas sama dengan unduhan). Lampiran jatuh dengan anggun
(`lampiran_untuk`, keputusan rencana 6), sama dengan jalur unduh: token kata sandi tak terbaca atau kata sandi yang kini
ditolak → tanpa lampiran, baris `belum_diatur` (409 di unduh); kunci server tidak ada (503 di unduh) atau galat PDF tak
terduga → tanpa lampiran, baris `tidak_tersedia`. Email tetap terkirim.

**Status.** `menunggu` → `mengirim` → `terkirim`; `gagal` (alasan `smtp`); `dilewati` (alasan `belum_verifikasi`,
`tanpa_email`, `dimatikan`). Laporan tahap 1 (`email_status` NULL) tidak pernah dikirim, juga bila penerimanya kini
terverifikasi (keputusan rencana 7).

**Antrean** (`antrean_email.putaran_antrean`; dijalankan worker `jatahku-worker`, bukan `laporan_job`). Satu putaran:
1. Klaim `mengirim` lebih tua dari `BATAS_MENGIRIM` = 30 menit (proses berhenti di tengah kiriman) → kembali `menunggu`,
   atau `gagal`/`smtp` + `logger.error` bila percobaannya sudah `MAKS_PERCOBAAN` = 3.
2. Paling banyak `KELOMPOK` = 100 laporan `menunggu` yang belum pernah diklaim atau diklaim terakhir ≥
   `JEDA_COBA_ULANG` = 55 menit lalu, terbit terlama dulu (jeda coba ulang "paling cepat 1 jam" dengan kelonggaran 5 menit; praktisnya percobaan berikutnya
   jatuh sekitar satu jam kemudian).
3. Per laporan, klaim dulu: `UPDATE … WHERE email_status = 'menunggu'` (dan jeda lewat) → `mengirim`, `email_terakhir_at` =
   waktu klaim, `email_percobaan` + 1; harus mengenai tepat satu baris, jadi dua pengirim yang bersamaan (worker dan jalan
   manual dari shell) tidak pernah mengirim laporan yang sama bersamaan (keputusan rencana 5). **Setiap klaim = satu
   percobaan** (R-T3-2): `email_percobaan` menghitung klaim, jadi kiriman pertama yang berhasil terbaca 1, dan satu
   laporan paling banyak dikirim 3 kali. Sesudah klaim, user dan pengaturannya dibaca ulang: yang kini tidak lolos
   `status_awal` (email diganti atau dihapus, email laporan dimatikan) menjadi `dilewati`. Selainnya PDF, isi email, dan
   SMTP di thread (koneksi database tidak dipegang). Berhasil → `terkirim` + `email_terkirim_at`. Gagal → `menunggu`
   (dicoba lagi paling cepat 55 menit kemudian), atau `gagal`/`smtp` + `logger.error` bila ini percobaan ke-3.
4. Setiap tulis hasil hanya mendarat bila klaimnya masih milik pengirim ini (masih `mengirim` dengan `email_terakhir_at`
   yang sama); kiriman lambat yang klaimnya sudah dikembalikan langkah 1 hanya dicatat INFO.

**Worker** (`app/services/laporan/worker_email.py`, `python -m app.services.laporan.worker_email` dari `/opt/jatahku/app`,
unit `deploy/jatahku-worker.service`, user `jatahku`; membaca `/opt/jatahku/.env` lewat `get_settings`, tanpa FastAPI,
scheduler, atau bot). Loop: tulis tanda hidup, jalankan satu `putaran_antrean`. Putaran yang mengambil tepat `KELOMPOK`
laporan (`penuh`) langsung disusul putaran berikutnya; putaran yang tidak penuh, atau yang galat (dicatat
`logger.exception`: `putaran email laporan gagal; dicoba lagi dalam 60 detik`), disusul jeda `JEDA_KOSONG` = 60 detik.
Antrean baru (laporan terbit, kirim ulang manual) jadi terlihat dalam ±1 menit.
- **Laju tetap** (`EMAIL_LAPORAN_PER_DETIK` di `.env`, bawaan 3): `Pemacu` menjaga jarak `1 / laju` detik antara
  **awal** dua kiriman, jadi kiriman lambat tidak menambah jeda dan kiriman yang lebih lambat dari jarak itu tidak
  dihentikan (laju sebenarnya lalu ditentukan kecepatan kirim, bukan pacu). Nilainya teks yang diurai
  `laju_dari_pengaturan`: kosong atau bukan angka → 3 (WARNING `EMAIL_LAPORAN_PER_DETIK bukan angka; dipakai bawaan 3.0
  email per detik`, tanpa isi nilainya); di luar 0,1–20 → batas terdekat (WARNING). Nilai `.env` apa pun tidak menggagalkan
  API maupun worker. Ubah → `sudo systemctl restart jatahku-worker`. Pada 3/detik, 10.000 email ±56 menit pacu.
  **Satu worker paling cepat ±8 email per detik**, karena tiap email membuat PDF (±0,12 detik CPU) di satu proses:
  `EMAIL_LAPORAN_PER_DETIK` di atas itu tidak berpengaruh (dibatasi 20, tetapi tidak tercapai). Diukur lokal (SQLite in
  memory, pengirim tiruan, PDF sungguhan): 2.000 email pada 20/detik selesai dalam 262 detik dengan CPU 95% dari satu inti
  (±7,6 email/detik); 200 email pada 3/detik selesai dalam 66,7 detik dengan CPU 25,5 detik, jadi pada laju bawaan worker
  memakai ±40% satu inti selama mengirim. Angka produksi bergantung pada CPU VPS dan waktu SMTP.
- **Tanda hidup:** kunci Redis `laporan:worker_email:hidup` (`KUNCI_HIDUP`), nilai waktu UTC ISO, TTL 900 detik, ditulis di
  awal setiap putaran dan diperbarui di tengah putaran panjang (dicek sebelum tiap laporan) bila sudah `JEDA_TANDA` = 60
  detik sejak tanda terakhir. Worker dianggap hidup bila
  tandanya ≤ 10 menit (`pantau_email.BATAS_HIDUP`). Redis tidak terjangkau tidak menghentikan pengiriman: dicatat sekali
  per putaran (`tanda hidup worker email laporan tidak bisa ditulis ke Redis; pengiriman lanjut`, tanpa pesan galatnya),
  dan kartu Admin menampilkan worker tidak hidup.
- **Berhenti** (`systemctl stop`/`restart`, SIGTERM atau SIGINT): `putaran_antrean` memeriksa permintaan berhenti sebelum
  dan sesudah pacu, tepat sebelum klaim, jadi tidak ada putaran atau klaim baru; kiriman yang sedang berjalan
  diselesaikan dan hasilnya ditulis, lalu proses keluar 0. Jeda 60 detik terputus seketika. Unit memberi `TimeoutStopSec=60`
  (cukup untuk satu kiriman: batas SMTP 30 detik). Klaim yang tertinggal karena proses mati paksa dikembalikan langkah 1
  sesudah 30 menit.
- Unit: `Restart=always`, `RestartSec=5`, `Nice=5`, tanpa `EnvironmentFile` (aplikasi membaca `.env` sendiri).
- Hanya **satu** worker: dua worker tidak menggandakan email (klaim bersyarat), tetapi laju totalnya dua kali; naikkan laju
  lewat `EMAIL_LAPORAN_PER_DETIK`, bukan dengan worker kedua.

Jadi SMTP mati berjam-jam menghasilkan paling banyak tiga percobaan per laporan, berjarak ≥ 55 menit (praktisnya ±1 jam
berurutan), lalu `gagal`; satu laporan gagal tidak menghentikan antrean. **Batas waktu SMTP 30 detik**
(`email_service.SMTP_TIMEOUT`, di `_deliver`, untuk setiap email): server SMTP yang macet harus gagal cepat dan tidak
menahan antrean; batas yang terlampaui menjadi kiriman gagal biasa. Kasus langka: kiriman berhasil tetapi hasilnya tidak bisa
disimpan (proses mati) → klaim basi dikembalikan langkah 1 dan email terkirim dua kali; dipilih daripada email hilang.
Worker mati tidak menghentikan penerbitan dan notifikasi, hanya menunda email: laporan tetap `menunggu` dan terkirim
begitu worker hidup lagi (alarm `worker_mati`, bagian berikut).

**Laporan yang dilewati dihidupkan lagi** (`hidupkan_lagi`, keputusan rencana 2), hanya yang terbit ≤
`JENDELA_TERBIT_HARI` = 7 hari lalu: verifikasi berhasil → alasan `belum_verifikasi` dan `tanpa_email` kembali `menunggu`;
`email_on` dinyalakan (PATCH) → alasan `dimatikan`. Yang lebih tua tidak dikirim. Percobaan yang sudah terpakai dan
`email_terakhir_at` tidak direset (jeda 55 menit tetap berlaku). Verifikasi lewat Google juga menghidupkan lagi (Ruling
F-6): login atau tautan Google yang memverifikasi alamat akun yang sudah ada (alamatnya sama dengan email Google)
menjalankan `hidupkan_lagi` yang sama dalam transaksinya; alamat yang berbeda tidak memverifikasi dan tidak menghidupkan.

**Berhenti berlangganan.** Setiap email memuat tautan `{API_URL}/laporan/berhenti-email?token=…` (token bertujuan
`berhenti_email_laporan`, klaim `sub`, **tanpa `exp`**: tautan di email lama harus tetap berfungsi). `GET` hanya
menampilkan halaman konfirmasi dan tidak mengubah apa pun, karena pemindai tautan di layanan email membuka GET
(keputusan rencana 4); hanya `POST` (tombol halaman atau one-click RFC 8058) mematikan `email_on`. Halaman: "Berhenti
menerima email laporan?" → "Email laporan dimatikan" ("Laporan tetap terbit di aplikasi. Kamu bisa menyalakannya lagi
di Pengaturan → Laporan."), dan "Tautan tidak berlaku" (400). Menyalakan lagi: saklar "Kirim laporan ke email".

**Log** (hanya id laporan/user, angka, dan teks tetap; tidak pernah alamat, kata sandi, token, atau isi laporan; galat
SMTP hanya dengan nama jenisnya karena pesannya bisa memuat alamat). **Sejak worker, baris pengiriman email laporan ada di
journal `jatahku-worker`, bukan `jatahku`** (worker mencatat INFO ke stderr, jadi semuanya tampil):
```bash
sudo journalctl -u jatahku-worker --since "1 hour ago" | grep -iE "email laporan|PDF laporan"
sudo journalctl -u jatahku-worker -n 50 --no-pager
```
Baris di journal `jatahku-worker`: `worker email laporan menyala: N email per detik` dan `worker email laporan berhenti` (setiap
start dan stop), `email laporan: N terkirim, M gagal, K dilewati, L dicoba lagi` (satu baris per putaran yang memproses sesuatu),
`Email laporan terkirim` / `Email laporan gagal dikirim (<jenis galat>)` (`email_service`), `email laporan <id> gagal pada
percobaan ke-N; tidak dicoba lagi (alasan smtp)`, `email laporan <id> masih berstatus mengirim lebih dari 30 menit …`,
`email laporan <id> gagal diproses …`, peringatan lampiran (`… email laporan dikirim tanpa lampiran PDF`), `PDF laporan <id> gagal
dibuat (<jenis galat>); email dikirim tanpa lampiran`, peringatan laju (`EMAIL_LAPORAN_PER_DETIK …`), peringatan tanda hidup
Redis, dan `putaran email laporan gagal; dicoba lagi dalam 60 detik`. `grep -iE "email laporan|PDF laporan"` menangkap
semuanya kecuali peringatan laju (`EMAIL_LAPORAN_PER_DETIK …`).

Yang tetap di journal `jatahku` (proses API): baris penerbitan `laporan_job` (`household=… payday=…`, `laporan_job
melewati batas 40 menit …`, `laporan_job selesai dalam …`, notifikasi), baris alarm (`email laporan: alarm <kode> gagal
dikirim`, `email laporan: alarm tidak dikirim, token atau ADMIN_TELEGRAM_ID kosong`, `email laporan: alarm tidak terkirim ke
Telegram (<jenis galat>)`, `pemeriksaan alarm email laporan gagal …`), `email laporan: tanda hidup worker tidak terbaca dari
Redis` (kartu Admin atau alarm tidak bisa membaca Redis), dan email verifikasi (`Email verifikasi terkirim` / `Email
verifikasi gagal dikirim (<jenis galat>)`, `Tautan verifikasi email user <id> gagal dikirim`; `grep -i verifikasi`). Proses
API tidak mengatur logging, jadi hanya WARNING dan ERROR yang sampai ke journal `jatahku`: baris INFO job (durasi
`laporan_job selesai …`, ringkasan penerbitan) tidak muncul di sana, sedangkan WARNING penundaan dan baris alarm muncul. Peringatan startup `REPORT_SECRET_KEY kosong atau tidak valid: kata sandi dan PDF laporan nonaktif`
tercatat di journal `jatahku` (startup API). Sejak 11 Nov 2026
pengirim lain di `email_service` juga tanpa alamat: `send_email` (reset password, hapus akun, selamat datang, peringatan)
mencatat `Email terkirim` / `Email gagal dikirim (<jenis galat>)` dan backup `Email backup terkirim` / `Email backup gagal
dikirim (<jenis galat>)`, tanpa alamat, subjek, atau pesan galat SMTP; `notification_service` mencatat `Email notifikasi user
<id> gagal (<jenis galat>)`. Satu-satunya pesan galat yang dicatat utuh adalah `SMTP_PASSWORD kosong di .env, email tidak
dikirim` (`SmtpPasswordKosong`, teks tetap). Pesan alarm dan respons Admin tidak memuat alamat maupun id user.

## Pemantauan dan alarm

**Kartu "Email laporan" di halaman Admin** (`EmailLaporanCard.jsx`, memuat `GET /admin/email-laporan`; `require_admin`): Worker
("Hidup · terakhir HH.MM" di zona pemirsa, atau "Tidak memberi tanda hidup"), Menunggu (jumlah dan umur tertua), Terkirim 24
jam, Gagal 7 hari, Penerima `N / 300`, Laju (email/detik), dan satu baris peringatan per alarm yang sedang berlaku. Gagal
memuat → teks galat di kartu saja; bagian Admin lain tetap tampil. Respons endpoint (`pantau_email.keadaan_email`, ditambah
`alarm`): `worker_hidup`, `worker_terakhir`, `menunggu`, `tertua_menit`, `mengirim`, `terkirim_24_jam`, `gagal_7_hari`,
`penerima` (user dengan email terverifikasi, bukan akun `deleted_`/`banned_`, dan `email_on` tidak false; tanpa baris
pengaturan = menyala), `ambang_penerima` (300), `smtp_lokal`, `laju_per_detik`, `alarm` (daftar kode). Hanya angka, waktu,
dan kode; tanpa alamat dan tanpa id user. Redis mati → tetap 200 dengan `worker_hidup` false.

**Alarm** (`pantau_email.periksa_alarm`, dipanggil `laporan_job` tiap jam di menit :30, jadi jeda deteksi sampai ±1 jam;
dikirim lewat Telegram bot ke `ADMIN_TELEGRAM_ID`, teks polos):

| Kode | Syarat | Ulang paling cepat | Teks |
|---|---|---|---|
| `pindah_penyedia` | `penerima` ≥ 300 dan `smtp_lokal` (`SMTP_HOST` = `localhost`/`127.0.0.1`/`::1`) | 30 hari | `📬 Penerima email laporan sudah N. Saatnya pindah ke penyedia email transaksional — langkahnya di AGENTS.md bagian 'Pindah penyedia email'.` |
| `worker_mati` | tanda hidup tidak ada atau > 10 menit | 24 jam | `⚠️ Worker email laporan tidak memberi tanda hidup sejak HH:MM WIB. Cek: sudo systemctl status jatahku-worker` (tanpa "sejak …" bila tanda tak pernah ada) |
| `antrean_tersendat` | umur laporan `menunggu` tertua > 360 menit | 24 jam | `⚠️ Antrean email laporan tersendat: N menunggu, tertua X jam. Cek: sudo journalctl -u jatahku-worker -n 50` |
| `email_gagal` | ada laporan `gagal` yang `email_terakhir_at`-nya sesudah alarm ini terakhir terkirim (pertama kali: 24 jam terakhir) | 24 jam | `⚠️ Ada email laporan yang gagal dikirim (N dalam 7 hari). Periksa SMTP, lalu ikuti "kirim ulang email" di docs/laporan-berkala.md.` |

- **Masa tenang:** `worker_mati` tidak dikirim dalam 15 menit pertama sesudah proses API menyala (`pantau_email.API_MENYALA`, diisi
  `lifespan`), karena worker ikut di-restart saat deploy. Alarm lain tidak punya masa tenang. `API_MENYALA` kosong (jalan
  manual dari shell) = tanpa masa tenang.
- **Waktu kirim terakhir** disimpan di tabel `app_settings`, kunci `alarm_email_laporan:<kode>`, nilai waktu UTC ISO, dan
  **hanya ditulis bila pesan benar-benar terkirim**. Lihat: `sudo -u postgres psql jatahku_db -c "SELECT key, value FROM
  app_settings WHERE key LIKE 'alarm_email_laporan:%'"`. Menghapus barisnya membuat alarm yang masih berlaku terkirim lagi
  pada jalan job berikutnya.
- **Telegram admin belum diatur** (`TELEGRAM_BOT_TOKEN` atau `ADMIN_TELEGRAM_ID` kosong) atau pengiriman gagal: tidak ada
  alarm yang terkirim, WARNING dicatat di journal `jatahku` (`email laporan: alarm tidak dikirim, token atau ADMIN_TELEGRAM_ID
  kosong`, atau `… tidak terkirim ke Telegram (<jenis galat>)`), waktu kirim tidak ditulis, dan alarm dicoba lagi tiap jam
  sampai berhasil. Kartu Admin tetap menampilkan alarm yang berlaku, jadi pemantauan tidak bergantung pada Telegram.
- `email_gagal` terkirim sekali per kelompok kegagalan baru, bukan tiap jam selama ada `gagal` lama: laporan `gagal` yang
  sudah diberi tahu tidak memicu alarm lagi. Kartu Admin (`gagal_7_hari`) tetap menghitungnya selama 7 hari.

## Halaman web

- **Desktop (≥ 1024 px):** menu "Laporan" di sidebar setelah Analitik; `/laporan` arsip (terbaru di atas, 24 per
  halaman dengan "Tampilkan lebih banyak" yang hilang setelah halaman yang tidak penuh; laporan yang sama tidak tampil
  dua kali bila ada yang terbit di antara dua muatan); `/laporan/:id` laporan lengkap bagian 1–8 (grafik recharts,
  mutasi 50 baris per langkah dengan "Tampilkan lebih banyak").
- **HP dan tablet (< 1024 px):** `/laporan/:id` tampil sebagai layar ringkas (judul, periode, angka utama, sorotan, tren,
  tombol besar "Unduh PDF"). Tidak ada menu laporan di HP; layar ini dibuka dari lonceng, tautan Telegram, atau arsip
  `/laporan` lewat tautan "Lihat laporan" di Pengaturan → 📄 Laporan.
- **Banner** (tautan `/settings#laporan`): "Atur kata sandi laporan untuk mengunduh PDF." bila kata sandi belum diatur;
  bila sudah, "Verifikasi email untuk menerima laporan lewat email." untuk akun beremail yang belum terverifikasi dan
  `email_on` true. Satu banner sekaligus, kata sandi didahulukan.
- **Unduh:** 200 → `native.files.save` dengan nama dari `nama_file` di JSON (CORS tidak membuka `Content-Disposition`);
  409 → dialog kata sandi, lalu diulang sekali; 429 → "Terlalu sering mengunduh. Coba lagi sebentar lagi."
- **Pengaturan → 📄 Laporan** (`#laporan`): baris status email ("Email … terverifikasi." / "Email … belum
  terverifikasi." / "Belum ada email di akun ini. Laporan tetap terbit di aplikasi dan Telegram."), tombol "Kirim tautan
  verifikasi" (hanya bila email ada dan belum terverifikasi; sukses "Tautan verifikasi dikirim ke … Berlaku 24 jam."),
  saklar "Kirim laporan ke email" (`PATCH`, optimistis dan dikembalikan bila gagal; **selalu tampil dan bisa dinyalakan**,
  juga tanpa email atau tanpa verifikasi, supaya pilihan user tersimpan untuk saat emailnya siap), status kata sandi,
  formulir "Atur kata sandi"/"Ganti kata sandi", dan tautan "Lihat laporan" ke `/laporan` (tetap tampil bila pengaturan
  gagal dimuat). Saklar kuartalan dan tahunan belum tampil (tahap 3).
- **Pesan sesudah verifikasi lewat tautan** (`?email_verifikasi=berhasil|tidak_berlaku|berubah`, dari tombol "Verifikasi
  email" atau dari tautan yang langsung dialihkan): ditampilkan sekali di atas kartu, lalu parameter dihapus dari URL
  (hash dan query lain tetap). Bunyinya di `laporanView.js` (`pesanVerifikasi`).
- Tombol top bar ekspor manual (PDF/CSV) kini bernama "Ekspor" / "Ekspor {periode}".

## API

| Endpoint | Perilaku dan status |
|---|---|
| `GET /laporan?limit=24&offset=0` | Laporan milik pemanggil `[{id, jenis, judul, periode_mulai, periode_akhir, terbit_at, nama_file}]`, terbit terbaru dulu lalu periode terbaru. `limit` 1–100, `offset` 0–100000 (di luar → 422). `judul` dibaca dari JSONB oleh database (`data ->> 'judul'`), `data` utuh tidak ikut terbaca. |
| `GET /laporan/{id}` | Bentuk di atas + `data`. Bukan milik pemanggil atau tidak ada → 404 `"Laporan tidak ditemukan"`. |
| `GET /laporan/{id}/pdf` | 200 `application/pdf` (`Content-Disposition: attachment; filename="…"`, `no-store`). Galat menurut urutan pemeriksaan di route: 404; 503 `{"detail": …, "kode": "kunci_belum_diatur"}`; 409 `{"detail": "Atur kata sandi laporan dulu untuk mengunduh PDF.", "kode": "kata_sandi_belum_diatur"}`. Lebih dari 10/menit → 429 (diperiksa sebelum route). |
| `GET /user/laporan-pengaturan` | `{kata_sandi_diatur, email, email_terverifikasi, email_on, kuartalan_on, tahunan_on, pro}`; tanpa baris = bawaan dan tidak ada baris yang dibuat. |
| `PUT /user/laporan-pengaturan` | Badan `{"kata_sandi": "…"}` (hanya kata sandi) → bentuk GET. 422: `detail` kalimat siap tampil untuk panjang dan karakter, atau daftar `{type, loc, msg}` untuk badan salah bentuk; 503 `kunci_belum_diatur`; 429 (5/jam). |
| `PATCH /user/laporan-pengaturan` | (tahap 2) Badan `{"email_on": true\|false}`, semua field opsional; hanya yang dikirim berubah, kata sandi tidak tersentuh → bentuk GET. Badan kosong, `null`, atau field asing → 422. Menyalakan `email_on` menghidupkan lagi laporan `dilewati` karena `dimatikan` yang terbit ≤ 7 hari lalu. 30/jam per user, ember terpisah dari PUT. Tahap 3 menambah `kuartalan_on`/`tahunan_on` di sini. |
| `POST /user/email/verifikasi` | (tahap 2) Kirim tautan verifikasi ke email akun pemanggil → `{"status": "terkirim"}`. Tanpa email → 422 `tanpa_email`; sudah terverifikasi → 409 `sudah_terverifikasi`; SMTP gagal → 502 `gagal_kirim` (semua `{detail, kode}`); 3/jam per user. |
| `GET /auth/verifikasi-email?token=` | (tahap 2, tanpa login; tautan di email) **Tidak pernah mengubah apa pun** (Ruling F-4). Halaman konfirmasi "Verifikasi email kamu" dengan tombol "Verifikasi email" (200, `Cache-Control: no-store`) bila tautan masih bisa memverifikasi; selainnya 303 ke `{APP_URL}/settings?email_verifikasi=<hasil>#laporan` (`no-store`): `tidak_berlaku` (token rusak, kedaluwarsa, bertujuan lain, atau user tidak ada: tidak dibedakan), `berubah` (alamat akun sudah berganti sejak tautan dikirim), atau `berhasil` (alamat ini sudah terverifikasi). 30/menit per IP. |
| `POST /auth/verifikasi-email?token=` | (tahap 2, tanpa login; tombol "Verifikasi email") Selalu 303 ke `{APP_URL}/settings?email_verifikasi=<hasil>#laporan` (`no-store`): `berhasil` (menulis `email_verified_at` dan menghidupkan lagi laporan 7 hari terakhir yang `dilewati` karena `belum_verifikasi`/`tanpa_email`), `berubah` atau `tidak_berlaku` (seperti GET; tidak ada yang ditulis). Badan tidak dibaca; aman diulang (yang sudah terverifikasi tetap `berhasil`, waktunya tidak berubah). 30/menit per IP, ember terpisah dari GET. |
| `GET /laporan/berhenti-email?token=` | (tahap 2, tanpa login) Halaman konfirmasi "Berhenti menerima email laporan?" (200); token tidak sah atau akun tidak ada → halaman "Tautan tidak berlaku" (400). **Tidak pernah mengubah apa pun.** 30/menit per IP. |
| `POST /laporan/berhenti-email?token=` | (tahap 2, tanpa login) Mematikan `email_on` (membuat baris `report_settings` bila belum ada) → halaman "Email laporan dimatikan" (200), atau 400 "Tautan tidak berlaku". Menerima tombol halaman dan one-click RFC 8058 (`List-Unsubscribe=One-Click`); badan tidak dibaca; aman diulang. 30/menit per IP. |

Semua endpoint baru kecuali `PATCH /user/laporan-pengaturan`, yang menambah metode di path yang sudah ada; API tetap hanya
bertambah (`openapi_cek`). Nama tidak bentrok dengan rencana Buku Usaha (`/p/buku_usaha/laporan`).
`/laporan/berhenti-email` dideklarasikan sebelum `/laporan/{report_id}` supaya tidak ditelan sebagai id.

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
- **Tahap 2, batas frekuensi** (slowapi, memori proses): kirim tautan verifikasi 3/jam per user; `PATCH
  /user/laporan-pengaturan` 30/jam per user (ember sendiri, tidak memakan 5/jam PUT kata sandi); `GET` dan `POST
  /auth/verifikasi-email`, serta `GET` dan `POST /laporan/berhenti-email`, masing-masing 30/menit per IP dalam **ember
  terpisah** (`shared_limit` scope `verifikasi_email_get`/`verifikasi_email_post` dan
  `berhenti_email_get`/`berhenti_email_post`), supaya pemindai tautan yang membuka GET tidak menghabiskan jatah tombol
  halaman atau POST one-click.
- **Tautan dari email tidak bertindak lewat GET** (keputusan rencana 4, Ruling F-4): verifikasi dan berhenti
  berlangganan sama-sama GET = halaman konfirmasi yang tidak mengubah apa pun, POST = tindakannya. Pemindai tautan di
  layanan email (mis. Safe Links) membuka GET dan umumnya tidak mengirim formulir; halamannya tanpa skrip.
- **Token bertujuan** (`create_purpose_token`/`decode_purpose_token`, `app/core/security.py`): JWT `JWT_SECRET`, klaim `type`
  = tujuan (`verifikasi_email`, `berhenti_email_laporan`). Token login menolak `type` selain `access` (dan refresh
  `refresh`), jadi token tujuan tidak pernah lolos sebagai sesi, dan sebaliknya; kedua fungsi juga menolak tujuan
  `access`/`refresh` (`ValueError`). `berlaku` wajib disebut (Ruling F-2): `berlaku=None` (tanpa `exp`) hanya bila
  diminta terang-terangan, yaitu token berhenti. Verifikasi berlaku 24 jam dan membawa sidik alamat (HMAC berkunci,
  bagian "Email laporan"), bukan alamatnya; berhenti tanpa `exp`, hanya mematikan satu saklar milik user itu. Kode
  aplikasi tidak pernah mencatat token. Tautan verifikasi dan halaman berhenti menjawab `Cache-Control: no-store`.
  `Referrer-Policy` adalah header global `strict-origin-when-cross-origin` (`SecurityHeadersMiddleware`, `app/main.py`;
  Ruling F-3): ke origin lain hanya origin yang terkirim, jadi token di path atau query tidak pernah keluar lewat
  `Referer`.
- **Email hanya ke alamat terverifikasi**, dibaca ulang dari `users` tepat sebelum mengirim (email diganti sesudah
  terbit tidak mengirim ke alamat baru yang belum terverifikasi). Email laporan tanpa nominal; PDF ber-AES-256 dengan kata
  sandi laporan user.
- **Access log uvicorn tanpa token** (11 Nov 2026, `app/core/log_akses.py`): filter di logger `uvicorn.access` menulis
  nilai parameter query `token` dan `code` sebagai `***` (`/auth/verifikasi-email`, `/laporan/berhenti-email`,
  `/auth/tg-login`, `/household/join`, `/auth/cms-oauth/callback`), juga nilai parameter apa pun yang memuat alamat
  email (mis. `/admin/users?search=`). Path, nama parameter, dan parameter lain tetap. Dipasang saat `app.main` dimuat;
  bila penyamaran sendiri galat, seluruh query dibuang dan baris log tetap terbit. Rahasia baru lewat query: tambahkan
  namanya ke `PARAM_RAHASIA`. Log akses **nginx** di depan API dan web tidak lewat filter ini (bagian Batasan).
- **Log tanpa alamat**: lihat bagian "Email laporan" (semua pengirim email, bukan hanya laporan). Galat SQL yang tak
  tertangani juga tanpa nilai parameter kueri (`hide_parameters` di `app/core/database.py`, menyala di luar
  `APP_ENV=development`): traceback di journal tidak memuat alamat email atau keterangan transaksi. Cek operasional di
  AGENTS.md, checklist "Log tanpa token dan alamat email" (`grep -c @` → 0).

## Batasan yang diketahui

- **Cakupan:** laporan kuartalan dan tahunan (tahap 3) belum ada; `kuartalan_on`/`tahunan_on` belum bisa diubah. PDF tidak
  dikirim lewat bot Telegram atau chat web.
- **Email laporan (tahap 2):** laporan tahap 1 (`email_status` NULL) tidak pernah dikirim. Laporan `dilewati` hanya
  dihidupkan lagi bila terbit ≤ 7 hari lalu; yang lebih tua tetap `dilewati`. Paling banyak 3 kiriman per laporan, lalu
  `gagal` tanpa pemberitahuan ke user (log ERROR di journal `jatahku-worker`, kartu Admin, dan alarm `email_gagal`; pemulihan:
  "Pemulihan"). Worker mengirim pada laju tetap `EMAIL_LAPORAN_PER_DETIK` (bawaan 3/detik), jadi gelombang besar
  (mis. banyak household bergajian sama) tersebar menurut laju itu, bukan menurut jam. Worker mati menunda semua email
  sampai hidup lagi (laporan tetap `menunggu`; alarm `worker_mati` ±1 jam kemudian). Hanya satu worker yang didukung. Email
  terkirim dua kali dalam kasus yang sangat langka (kiriman berhasil, hasil tak tersimpan). Sumber kebenaran tujuan
  adalah `users.email`: mengubah alamat sesudah terbit membuat laporan `menunggu` dilewati (`belum_verifikasi`) sampai
  diverifikasi lagi.
- **Alarm email paling cepat terdeteksi tiap jam** (diperiksa `laporan_job` di menit :30), dan hanya sampai bila Telegram
  admin diatur; selainnya kartu Admin. Antrean tidak tahu email yang ditolak sesudah diterima server SMTP (bounce).
- **Pesan `?email_verifikasi=` bisa hilang:** pesannya ditampilkan sekali. Reload ambil-alih service worker (aplikasi
  memuat ulang saat `controllerchange`) atau browser yang sedang logout (dialihkan ke login) dapat menghilangkannya;
  verifikasinya sendiri sudah berhasil, dan baris status di kartu ("Email … terverifikasi.") menunjukkan hasilnya.
- **Tautan verifikasi dibuka saat login di akun lain** (mis. browser bersama): yang diverifikasi user pada token, bukan
  yang sedang login, tetapi pesan `?email_verifikasi=` tampil di Pengaturan akun yang sedang login (pesannya hanya dari
  parameter URL). Baris status di kartu tetap menunjukkan status akun yang dilihat.
- **Token masih ada di log akses nginx** sampai langkah manual dijalankan: access log uvicorn sudah menyamarkannya
  (bagian Keamanan), tetapi nginx (HestiaCP) di depan `api.jatahku.com` dan `jatahku.com` mencatat URL lengkap, termasuk
  `?token=` tautan email ini dan halaman `/reset-password`, `/hapus-akun`, `/auth/tg`. Konfigurasi nginx tidak ada di
  repo; langkahnya (format log tanpa query, pembersihan log lama) ada di AGENTS.md, checklist "Log tanpa token dan
  alamat email", dan dijalankan pemilik server. Token verifikasi kedaluwarsa dalam 24 jam dan hanya memverifikasi alamat
  yang memang tercatat di akun itu; token berhenti tidak kedaluwarsa, tetapi hanya bisa mematikan email laporan
  (menyalakannya lagi hanya dari Pengaturan). **Baris lama** (sebelum 11 Nov 2026) di journal dan log nginx masih
  memuat token dan alamat sampai dibersihkan atau terputar.
- **Access log uvicorn hanya menyamarkan query.** Rahasia di path, header, atau badan tidak pernah dicatat uvicorn;
  parameter query sensitif yang namanya bukan `token`/`code` dan nilainya tidak memuat `@` tidak tersamar sampai
  namanya ditambahkan ke `PARAM_RAHASIA` (`app/core/log_akses.py`).
- **Tombol ditekan orang yang tidak meminta:** pemilik alamat yang menerima email verifikasi yang tidak pernah dimintanya
  (mis. akun didaftarkan orang lain dengan alamatnya) lalu tetap menekan "Verifikasi email" memverifikasi alamat itu, dan
  laporan akun tersebut mulai dikirim ke sana; emailnya meminta mengabaikan bila tidak meminta. Pemindai tautan yang
  hanya membuka tautan tidak lagi memverifikasi (GET hanya menampilkan halaman konfirmasi).
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
- **Notifikasi** (Ruling R16): yang gagal atau terputus restart disusulkan sapu tiap jam selama 7 hari sejak laporan
  terbit; sesudah itu tidak lagi (kirim manual: bagian "Pemulihan"). Telegram best-effort dan paling banyak sekali per
  laporan: gagal tidak diulang, dan restart tepat di antara commit lonceng dan pengiriman Telegram melewatkan Telegram
  laporan itu (lonceng tetap ada).
- **Cache advisor** household dikosongkan setelah refresh walau refresh itu melaporkan error (tidak berbahaya: hanya
  dihitung ulang).
- **Gerbang refresh R9** menghitung aktivitas di semua amplop household, termasuk amplop pribadi anggota lain: bila hanya
  amplop itu yang beraktivitas dan ada calon tanpa aktivitas, refresh paksa berjalan tiap jam sampai jendela 7 hari
  habis (hanya biaya; laporan kosong tetap tidak terbit).
- **Snapshot yang belum ada** dicatat DEBUG; WARNING hanya di hari terakhir jendela dan hanya untuk household yang
  beraktivitas di periode itu, satu baris tiap jam sepanjang hari itu.
- **Hapus akun dan nama buatan anggota:** nama amplop bersama, target tabungan, dan langganan yang dibuat anggota yang
  menghapus akun tetap terbaca, di aplikasi maupun di laporan beku (`amplop[]`, `sorotan`, `langganan.jatuh_tempo[]`):
  tabelnya tidak menyimpan pembuat.
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
  terverifikasi tanpa nominal. Lampiran PDF ada di kotak masuk user selama user menyimpannya.

## Pemulihan

- **Household gagal** (`laporan household=… ditunda ke jam berikutnya` atau `penerbitan laporan household=… gagal`): job
  mencoba lagi tiap jam selama jendela 7 hari, tanpa tindakan. Pantau: `journalctl -u jatahku | grep -i laporan`
  (baris penerbitan ada di journal API; baris pengiriman email di `jatahku-worker`).
- **Worker tidak berjalan** (kartu Admin "Tidak memberi tanda hidup", atau alarm `worker_mati`). Laporan tetap `menunggu` dan
  terkirim begitu worker hidup; tidak ada yang hilang. Periksa dan nyalakan:
  ```bash
  sudo systemctl status jatahku-worker          # active (running) dan enabled
  sudo journalctl -u jatahku-worker -n 50 --no-pager
  sudo systemctl restart jatahku-worker         # lalu: journalctl -u jatahku-worker -n 5 → "worker email laporan menyala: …"
  sudo systemctl enable --now jatahku-worker    # bila unit belum di-enable atau tidak dikenal
  ```
  Unit hilang (`Unit jatahku-worker.service not found`): jalankan deploy (`sudo /opt/jatahku/deploy.sh`, atau jalankan ulang
  workflow "Deploy Jatahku"), yang memasangnya dari `deploy/jatahku-worker.service`. Worker restart terus (`NRestarts`
  bertambah: `systemctl show -p NRestarts --value jatahku-worker`): lihat traceback di journal; sebab umum `.env` salah, database
  atau Redis tidak terjangkau. Kartu Admin hanya menampilkan "Hidup" bila tanda hidup di Redis ≤ 10 menit, jadi Redis
  mati membuatnya tampak mati walau worker mengirim (peringatan di journal worker).
- **Menjalankan job manual** (mis. scheduler tidak berjalan): dari shell di VPS, **jauh dari menit :30** (job terjadwal),
  jauh dari 00:05 (job snapshot), dan tidak selagi tanggal gajian diubah. `household_lock` hanya berlaku di dalam satu
  proses, jadi proses shell tidak diserialkan dengan penulis snapshot di proses API. Laporan dobel tetap tidak mungkin
  (kunci unik), tetapi refresh snapshot yang bertabrakan menggagalkan household itu.
  ```bash
  cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -c "import asyncio, logging; \
  logging.basicConfig(level=logging.INFO); from app.services.laporan.job import laporan_job; print(asyncio.run(laporan_job()))"
  ```
  Keluaran terakhir `{'terbit': N, 'gagal': M, 'ditunda': K}` (`ditunda` = household yang tidak dimulai karena melewati
  `BATAS_JALAN` 40 menit; 0 pada jalan biasa). Job ini **tidak** mengirim email, tetapi ikut memeriksa alarm (bisa mengirim
  Telegram ke admin). Jalankan **tanpa** argumen tanggal: `laporan_job(today=<tanggal lampau>)`
  melewati jendela 7 hari dan me-refresh paksa periode yang sudah punya snapshot penerus, sehingga rantai rollover
  sesudahnya tidak lagi cocok.
- **Kirim ulang notifikasi** laporan yang `notified_at`-nya NULL. Dalam 7 hari sejak terbit sapu job melakukannya
  sendiri tiap jam; perintah ini untuk yang lebih lama. Laporan yang sudah diberi tahu dilewati, dan lonceng tidak pernah
  dobel:
  ```bash
  sudo -u postgres psql jatahku_db -c "SELECT id, terbit_at FROM reports WHERE notified_at IS NULL ORDER BY terbit_at"
  cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -c "import asyncio, uuid; \
  from app.services.laporan.job import kirim_notifikasi_laporan as k; asyncio.run(k(uuid.UUID('<id>')))"
  ```
- **Kirim ulang email** laporan yang `gagal` (atau `dilewati` yang terbit lebih dari 7 hari lalu dan memang ingin
  dikirim). Cari dulu: `SELECT id, email_status, email_alasan, email_percobaan, email_terakhir_at FROM reports WHERE
  email_status IN ('gagal','dilewati') ORDER BY terbit_at DESC`. Mengubah `email_status` saja **tidak cukup**: antrean
  menghitung setiap klaim sebagai percobaan, jadi laporan yang `email_percobaan`-nya sudah 3 langsung `gagal` lagi pada
  kiriman pertama yang gagal, dan `email_terakhir_at` yang masih baru menahannya sampai jeda 55 menit lewat. Atur ulang
  keduanya:
  ```bash
  sudo -u postgres psql jatahku_db -c "UPDATE reports SET email_status='menunggu', email_alasan=NULL, email_percobaan=0, email_terakhir_at=NULL WHERE id='<id laporan>' AND email_status IN ('gagal','dilewati')"
  ```
  Worker mengambilnya dalam ±1 menit (jeda antar putaran 60 detik) dan mengirimnya dengan tiga percobaan baru, pada laju
  worker; tidak perlu menjalankan `proses_antrean_email` manual (antrean tidak punya batas umur terbit). Lihat hasilnya:
  `SELECT email_status, email_alasan, email_percobaan FROM reports WHERE id='<id laporan>'` → `terkirim`. Syaratnya masih berlaku saat dikirim: user punya email **terverifikasi** dan `email_on`; bila
  tidak, laporan menjadi `dilewati` lagi dengan alasannya. Jangan menyentuh `mengirim` (sedang berjalan; klaim basi > 30
  menit dikembalikan sendiri) dan `terkirim` (akan terkirim dua kali). Penyebab `gagal` biasanya SMTP: periksa dulu
  `sudo journalctl -u jatahku-worker | grep -iE "email laporan|PDF laporan"` dan kredensial `SMTP_*` di `.env`. Menjalankan
  satu putaran antrean manual masih bisa (mis. saat worker dimatikan), tidak diserialkan dengan worker tetapi klaim
  bersyarat mencegah email ganda; tanpa pacu, paling banyak 100 laporan, hasil `{'terkirim': …, 'gagal': …, 'dilewati': …,
  'dicoba_lagi': …}`:
  ```bash
  cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -c "import asyncio, logging; \
  logging.basicConfig(level=logging.INFO); from app.services.laporan.antrean_email import proses_antrean_email; print(asyncio.run(proses_antrean_email()))"
  ```
- **Menjalankan worker manual** (mis. mencoba perubahan; hentikan dulu yang berjalan, karena dua worker menggandakan laju):
  `sudo systemctl stop jatahku-worker`, lalu `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m
  app.services.laporan.worker_email` (Ctrl+C berhenti rapi; log di terminal); nyalakan lagi dengan `sudo systemctl start
  jatahku-worker`.
- **Alarm yang terus berulang atau tidak terkirim:** tabel `app_settings` (kunci `alarm_email_laporan:<kode>`) dan syarat tiap
  kode ada di bagian "Pemantauan dan alarm".
- **`REPORT_SECRET_KEY` hilang atau tidak valid** (startup mencatat peringatannya; PUT dan unduh 503): isi kunci di
  `.env`, lalu `sudo systemctl restart jatahku jatahku-worker` (worker juga membaca kunci untuk lampiran PDF). Kunci **lain** dari sebelumnya membuat kata sandi tersimpan tak terbaca:
  user diminta mengatur ulang (409 dan banner), laporannya sendiri tidak terpengaruh.

## Pengujian

- Backend (tanpa Postgres): `test_laporan_model` (tabel, DDL, lifespan, revisi alembic termasuk bawaan server),
  `test_laporan_rahasia`, `test_laporan_hitung`, `test_laporan_susun`, `test_laporan_muat` (SQLite: lingkup, penyamaran,
  R2/R3/R8), `test_laporan_job` (unit + ujung ke ujung SQLite: refresh R4, idempoten, jendela, notifikasi, sapu dan
  WARNING R16), `test_laporan_pdf` (pypdfium2: terbuka hanya dengan kata sandi, multi-halaman, emoji, `pencatat_id` tidak
  tercetak), `test_laporan_api` (IDOR, 409/503, kata sandi tidak pernah dikembalikan, batas frekuensi per user),
  `test_laporan_akun` (hapus dan gabung akun; R15: anonimisasi laporan beku anggota lain dibandingkan dengan susunan
  ulang dari catatan hidup, pengalihan `pencatat_id`), `test_rate_limit`.
- Tahap 2: `test_laporan_antrean_email` (SQLite berkas: klaim, coba ulang, klaim basi, dua jalan bersamaan, lampiran
  jatuh dengan anggun, log tanpa alamat), `test_laporan_surel` (isi, tanpa "Rp", halaman berhenti dan halaman
  konfirmasi verifikasi), `test_verifikasi_email` (token, juga tanpa `aiosqlite`; penjaga `email_verified_at`),
  `test_verifikasi_email_api` (kirim tautan; GET konfirmasi tanpa INSERT/UPDATE/DELETE, POST memverifikasi, ember
  GET/POST terpisah), serta tambahan di `test_laporan_api` (PATCH, berhenti email GET/POST, batas frekuensi, header
  halaman bertoken lewat `app.main`), `test_laporan_job` (status awal; antrean dalam job sebelum worker), `test_email_smtp_config`
  (`SMTP_TIMEOUT`), dan `test_google_auth`.
- Worker email laporan (12 Nov 2026): `test_laporan_antrean_email` (`putaran_antrean`: `KELOMPOK`, berhenti sebelum dan
  sesudah pacu, `penuh`), `test_laporan_worker_email` (laju dan `laju_dari_pengaturan`, pacu, tanda hidup dan TTL, jeda
  kosong yang terputus berhenti, Redis mati, galat putaran, log tanpa alamat), `test_laporan_pantau_email` (`keadaan_email`,
  tiap alarm, batas ulang, pencatatan hanya bila terkirim, masa tenang, pesan tanpa `@`), `test_kotak_worker` (`LifespanTests`: `lifespan` mengisi `API_MENYALA` dengan waktu UTC berzona dan mengembalikannya), `test_laporan_job` (job tanpa email,
  `BATAS_JALAN`, hasil `{terbit, gagal, ditunda}`, galat alarm tidak mengubah hasil), `test_admin_email_laporan` (hanya
  admin, angka, tanpa alamat dan id user, Redis mati), `test_deploy_worker` (perilaku blok worker di `deploy.sh`: unit
  dipasang bila berbeda atau belum di-enable, penghitung `NRestarts`, deploy gagal bila worker tidak stabil). Frontend:
  `emailLaporanView.test.js`. Uji beban lokal (skrip sementara, tidak di repo): hasilnya di PR worker.
- Log tanpa token dan alamat (11 Nov 2026): `test_log_akses` (penyamaran query; filter terpasang di `uvicorn.access`
  sesudah `app.main` diimpor), `test_log_tanpa_alamat` (semua pengirim `email_service` dan email notifikasi, sukses dan
  gagal, tanpa `@`), `test_log_parameter_sql` (`hide_parameters`), serta `test_verifikasi_email` dan
  `test_verifikasi_email_api` (sidik HMAC, token tanpa alamat, token bentuk lama ditolak, alamat halaman dari database).
- Frontend: `node --test src/lib/*.test.js src/native/*.test.js` (`laporanView` termasuk halaman daftar, banner, status
  email, pesan verifikasi; `laporanFormat`, `exportPeriod`), lalu `npm run build`.
- PostgreSQL 16 nyata (4 Nov 2026, klaster sementara): `cek-migrasi.sh`; perbandingan skema migrasi vs lifespan; dan
  tes ber-SQLite (`test_laporan_model` integrasi, `test_laporan_muat`, ujung ke ujung `test_laporan_job`,
  `test_laporan_api`, `test_laporan_akun`; 110 tes) dijalankan ulang di Postgres. Semua lulus kecuali lima tes yang
  memeriksa SQL khas SQLite (`PRAGMA foreign_keys`, `JSON_EXTRACT`); di Postgres daftar laporan memakai
  `data ->> 'judul'` dan simpan kata sandi memakai `FOR NO KEY UPDATE`, keduanya jalan. Gelombang perbaikan akhir (R15,
  R16): `test_laporan_akun`, `test_laporan_muat`, dan ujung ke ujung `test_laporan_job` (termasuk sapu notifikasi)
  dijalankan ulang di PostgreSQL 16; lulus kecuali empat tes `PRAGMA foreign_keys` yang sudah diketahui. Penyaring
  `CAST(data AS TEXT) LIKE` dan penulisan ulang JSONB jalan.
