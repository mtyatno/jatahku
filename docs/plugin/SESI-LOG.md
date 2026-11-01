# Plugin — catatan serah-terima

Entri terbaru di atas. Format: **Kode sesi · nama · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## B2 · Beranda dari registry · 2026-11-01 · pemilik produk + Claude

**Selesai** (status review, PR #PR, issue #139)
- **Temuan keamanan, diperbaiki lebih dulu** (commit terpisah): cache offline `jatahku_cache_*` (profil, ringkasan amplop, transaksi periode berjalan) tidak dihapus saat logout dan kuncinya tidak per user; user berikutnya di perangkat yang sama bisa melihat data user sebelumnya lewat jalur offline `api.js`. `clearAllCache()` di `localCache.js`, dipanggil `logout()`; tes `localCache.test.js`; dicek di browser (cache kosong setelah logout).
- Backend: `GET /dashboard/layout` membawa `enabled` (AppSetting `beranda_registry_users`, daftar id atau `*`), aditif; kontrak §4 dan tes.
- `Dashboard.jsx` = pemilih: `enabled` → `BerandaRegistry.jsx`, selain itu `BerandaLama.jsx`. Tata letak terakhir disimpan di localCache per user (`beranda_layout:<uid>`), jadi kunjungan berikutnya langsung memakai Beranda yang benar.
- `BerandaRegistry.jsx`: satu `POST /dashboard/data` untuk semua instans yang tidak disembunyikan; respons periode berjalan di localCache per user (`beranda_data:<uid>`) untuk offline; muat ulang lewat event `refresh_on` kartu; permintaan basi diabaikan.
- `src/cards/`: `CardRegistry.js`, `DashboardGrid.jsx` (urutan + ukuran, kartu terakhir di baris melebar, P1 1,65 : 1, jarak antarbaris meniru Beranda lama: KPI 12, kelompok yang di ≥1280 px sebaris lalu bertumpuk 16, lainnya 24), `CardFrame.jsx` (error boundary, kerangka, galat per kartu), `core/index.jsx` (15 kartu inti; `kosong` untuk kartu yang Beranda lama tidak gambar: AI Advisor dan Cocokkan saldo di periode lalu, amplop/target tanpa isi, Ke mana uangmu tanpa belanja, Papan disiplin < 2 anggota).
- Bagian bersama supaya kedua Beranda tidak menyimpang: `lib/berandaModel.js` (turunan angka dari Dashboard.jsx lama, murni + tes), `components/BerandaKpi.jsx` (enam KPI), `components/BerandaHeader.jsx` (banner, periode, kepala HP), `hooks/useBerandaShell.js`. `BerandaLama.jsx` = Dashboard.jsx lama yang memakai bagian itu.
- Tes: `node --test` 608 lulus (583 di `src/lib`) · build ok · unittest 2110 (1 gagal, juga gagal di `main`: #164) · `openapi_cek` tanpa perubahan memutus.
- **Uji tampilan lokal** (backend + PostgreSQL + Redis + Vite lokal, Chrome headless, data contoh): Beranda lama vs registry **identik piksel** di 390/820/1100/1440 px (periode berjalan, tema gelap), periode lalu dengan tema terang (HP, desktop), dan flag advisor mati (HP, desktop). Permintaan API Beranda saat dimuat ulang 49 → 24.

**Digantung**
- Gerbang B (B3): paritas untuk semua user produksi dan p95 ≤ 500 ms di data nyata; perbandingan tampilan di perangkat sungguhan (Android/iOS, tablet).
- Kunjungan pertama setelah flag menyala masih memuat Beranda lama sekali (belum ada tata letak di cache), lalu berpindah ke registry.
- Endpoint lama yang masih dipanggil saat Beranda registry tampil berasal dari luar Beranda (sidebar/Layout: `/envelopes/summary`, `/recurring/`, notifikasi) dan kepala halaman (`/analytics/periods`, `/user/streak`, `/household/leaderboard`).
- `BerandaLama.jsx` dihapus setelah B3 menyalakan flag untuk semua user (`*`) dan stabil.
- `value` KPI Tabungan dan teks KPI masih dari frontend (catatan B1).

**Jebakan**
- `-mt-1` pada tautan Cocokkan saldo di Beranda lama tidak berlaku (kalah spesifisitas dari `space-y-6`), jadi jaraknya 24 px, bukan 20. Diukur, bukan ditebak: skrip Playwright membandingkan posisi kartu dan piksel.
- Komponen yang `return null` saat kosong (`SpendBreakdown`) tidak menyisakan jarak di Beranda lama; di grid registry kartu itu harus ditandai `kosong`, kalau tidak muncul jarak 24 px.
- Mode dev memakai `React.StrictMode`, jadi `POST /dashboard/data` terlihat dua kali saat dimuat di dev; di produksi sekali.
- `pkill -f <pola>` di Bash tool ikut mematikan shell-nya sendiri (pola cocok dengan baris perintahnya); hentikan proses dengan PID.
- Tes kuota yang bergantung jam: dua lulus lagi setelah 07:00 WIB; `test_basic_quota_bot_fund_shift_finishes_started_input` tetap gagal karena tanggal struk tetap `2026-10-10` (#164).

**Keputusan kecil**
- Flag dikirim lewat field `enabled` di `GET /dashboard/layout` (bukan endpoint baru), seperti `{"enabled": false}` di `/advisor/dashboard`.
- Breakpoint dibaca dari lebar layar di JS (`useBreakpoint`) supaya kartu terakhir di baris bisa melebar dan grid tetap satu sumber; urutan DOM tetap urutan tata letak.
- Saat batch gagal: periode berjalan memakai cache bila ada, selain itu setiap kartu menampilkan galat sendiri; respons cache dari periode lain tidak ditampilkan (kerangka sampai data periode itu datang).
- Galat sumber `insights` di kartu Perlu perhatian kini menjadi galat kartu (CardFrame), bukan pesan di dalam kartu seperti di UI lama.

**Cara melanjutkan**
- Merge PR ini aman: tanpa migrasi, dan flag `beranda_registry_users` belum ada di produksi, jadi semua user tetap memakai Beranda lama. Uji dengan menambah id sendiri: AppSetting `beranda_registry_users` = `<user_id>`.
- Berikutnya `/sesi-plugin B3` (skrip paritas pola `advisor_paritas` untuk semua user, perbandingan tampilan desktop dan HP, flag menjadi `*`), atau `/sesi-plugin R2` di jalur ruang.

---

## B1 · Registry kartu dan data batch · 2026-11-01 · pemilik produk + Claude

**Selesai** (status review, PR #162, issue #138)
- `app/services/dashboard/`: `registry.py` (15 kartu inti, template Beranda = Beranda sekarang, 14 kartu a1–a14; Papan disiplin hanya di katalog), `providers.py` (satu penyedia per kartu, tanpa rumus), `sources.py` (endpoint lama yang dipanggil `Dashboard.jsx`, dimuat sekali per permintaan dan dipakai bersama), `batch.py` (galat per kartu, log anggaran 500/150 ms), `layout.py` (tata letak efektif, validasi, `if_version`).
- `app/api/routes/dashboard.py`: `GET`/`PUT /dashboard/layout`, `GET /dashboard/cards`, `POST /dashboard/data`, `GET /dashboard/data/{id}`. Belum dipanggil frontend (B2), jadi belum perlu flag.
- Model `DashboardLayout` + migrasi `b1d4a7c2e9f0` (revisi dari R1 `1c7e5a9d3b20`; idempoten, `downgrade` menghapus tabel). Checklist deploy di `AGENTS.md`.
- `04-kontrak-api.md` §4 v1 (termasuk tabel sumber dan kartu) dan kode galat baru di §7; peta kode di `00-indeks.md`.
- Tes baru `app/tests/test_dashboard_registry.py` (19): paritas lewat HTTP terhadap endpoint lama (periode berjalan dan lalu, advisor aktif dan mati, anggota lain), amplop pribadi anggota lain dan household lain tidak bocor, `ruang_id` di body diabaikan, tata letak (409, `instans_hilang`, validasi, parkir), galat per kartu, p95 < 500 ms di SQLite. Uji mutasi: mengubah satu parameter sumber membuat 4 tes paritas gagal.
- Tes: unittest 2068 (3 gagal, sama dengan `main`, lihat jebakan R1) · node --test 562 lulus · build ok · `cek-migrasi.sh origin/main` di PostgreSQL 16 ok · `openapi_cek` tanpa perubahan memutus. Uji manual: `create_all` lebih dulu lalu `alembic upgrade head` tetap lulus (urutan produksi).

**Digantung**
- Gerbang B (paritas semua user produksi, p95 ≤ 500 ms di data nyata) diuji di B3, bukan di sini. Anggaran di produksi baru terlihat dari log `jatahku.dashboard`.
- `value` kartu Tabungan masih `null` (total dijumlah frontend); teks KPI (footer, sufiks) masih dirakit frontend. Memindahkannya ke layanan dan templat server = pekerjaan terpisah, paling lambat sebelum kartu dipakai aplikasi lain selain web.
- Penyedia memanggil handler route lama (impor tertunda). Memindahkan rumus `daily_spending`, `envelope_breakdown`, `spending_prediction`, dll. dari route ke services = refactor terpisah; tes paritas menjaga hasilnya tetap sama.
- Gerbang keamanan "Karyawan tidak melihat laporan" untuk `/dashboard/data`: belum ada kartu laporan dan belum ada peran ruang usaha, jadi belum bisa diuji. Saat U4 menambah kartu laporan, katalog dan data harus menyaring peran `member` (403 `khusus_admin`).

**Jebakan**
- R1 di-merge saat sesi ini berjalan: branch di-rebase ke `225122e`, migrasi B1 kini merevisi `1c7e5a9d3b20`, dan checklist B1 menunggu migrasi R1 jalan dulu.
- Deploy R1 (#161, run 41246922327) **gagal** di "Deploy to VPS", kemungkinan besar `deploy.sh` exit 2 karena migrasi `1c7e5a9d3b20` belum dijalankan (log run tidak bisa dibuka dari sesi cloud). Jalankan checklist R1, lalu jalankan ulang job deploy, sebelum merge B1.
- R1 membolehkan satu user anggota beberapa household. `get_household_id` (`scalar_one_or_none`) akan galat begitu ada user dengan dua household (mulai R4). `app/api/routes/dashboard.py` memakai `get_household_id` dari `envelope_balance.py`, jadi ikut diganti `ruang_aktif` di R2.
- Clone dangkal hanya melacak `main`: setelah push branch baru, tambahkan refspec (`git config --add remote.origin.fetch '+refs/heads/<branch>:refs/remotes/origin/<branch>'`) supaya hook stop tidak mengira branch belum di-push.
- PostgreSQL lokal bisa mati di antara giliran; jalankan ulang `pg_ctl ... start` sebelum `cek-migrasi.sh`.

**Keputusan kecil**
- `periode` di `POST /dashboard/data` = `period_start` dari `GET /analytics/periods` (24 terakhir) atau `null`, bukan `"2026-10"` seperti v0: periode Jatahku mengikuti tanggal gajian. Rentang bebas ditolak (`periode_tidak_dikenal`).
- Kartu inti membawa `sumber` (respons endpoint lama) supaya B2 bisa menggambar komponen yang sama tanpa perubahan tampilan; bentuk baru `inti` untuk kartu inti dengan komponen sendiri. `value` KPI hanya diisi bila angkanya utuh di respons server.
- Potongan `advisor` per kartu: KPI mendapat metrik tanpa deret harian + chip kartunya; Pengeluaran harian mendapat deret harian + `grafik`; kartu AI Advisor mendapat muatan utuh. Saat flag advisor mati, kartu AI Advisor ikut membawa sumber UI Perlu perhatian.
- `GET /dashboard/layout` tidak menyimpan apa pun; dokumen pertama dibuat `PUT` dengan `if_version: 0`. `PUT` menyimpan hanya field yang dikenal (whitelist), bukan JSON bebas dari klien.
- `GET /dashboard/data/{id}` membaca kartu dan pengaturan dari tata letak tersimpan user sendiri, bukan dari query.

**Cara melanjutkan**
- Sebelum merge B1: deploy R1 harus hijau (migrasi `1c7e5a9d3b20` jalan, job deploy diulang). Lalu ikuti "Urutan merge PR bermigrasi" dan checklist "Plugin B1" di `AGENTS.md`; `alembic current` harus `1c7e5a9d3b20` sebelum upgrade.
- Berikutnya `/sesi-plugin B2` (Beranda dari registry di balik `beranda_registry_users`; merge dulu PR terbuka yang menyentuh `Dashboard.jsx`), atau `/sesi-plugin R2` di jalur ruang.

---

## R1 · Model ruang · 2026-11-01 · pemilik produk + Claude

**Selesai** (status review, PR #161, issue #141)
- `households.type` (`rumah_tangga` | `usaha`, bawaan `rumah_tangga`) dan `incomes.kind` (`pemasukan` | `transfer` | `top-up` | `penyesuaian`, bawaan `pemasukan`), konstanta `HouseholdType` dan `IncomeKind` di `models.py` (String, bukan SAEnum).
- Unik `uq_household_members_user_household` `(user_id, household_id)`: satu user boleh anggota beberapa household, sekali per household. Belum ada jalan membuat household kedua (R4, di balik `ruang_usaha_users`).
- `app/services/ruang_schema.py`: `RUANG_DDL` (kolom, idempoten) dijalankan di `lifespan` dan migrasi; `KIND_BACKFILL` hanya di migrasi `1c7e5a9d3b20`. Migrasi berhenti dengan daftar baris bila ada keanggotaan ganda, tanpa menghapus apa pun.
- Penulis `Income` mengisi `kind`: `fund_shift.record_transfer` dan refund/tutup minus saat hapus amplop → `transfer`; `record_topup` (bot) → `top-up`; `apply_balance_check` → `penyesuaian`; `POST /incomes/` menerima `kind` opsional (`pemasukan` | `top-up`, lainnya 422).
- API aditif: `type` di `GET /household/`, `kind` di respons `POST /incomes/` dan item `GET /incomes/` (`04-kontrak-api.md` bagian 0, v1). `openapi_cek`: tidak ada perubahan memutus.
- Checklist deploy R1 di `AGENTS.md`; tes baru `app/tests/test_ruang_model.py` (22 tes, SQLite).
- Tes: unittest 2049 (3 gagal, sama dengan `main`, lihat jebakan) · node --test 562 lulus · build ok · `cek-migrasi.sh origin/main` di PostgreSQL 16 ok. Uji manual di PostgreSQL: urutan produksi (restart → DDL, lalu migrasi → backfill) mengisi keempat jenis; keanggotaan ganda membuat migrasi berhenti dan tergulung balik.

**Digantung**
- #160: web (`FundEnvelopeModal.jsx`, `Envelopes.jsx`) belum mengirim `kind: 'top-up'`, jadi top-up web baru tersimpan `pemasukan`. Belum ada pembaca `kind`, jadi belum berdampak.
- `incomes.kind` belum dipakai di mana pun (mis. hitungan "ditambal N×" atau `type` di `GET /incomes/`, yang masih diturunkan dari nominal 0).
- Rencana siklus household (`households.payday_day`, project claude.ai) belum di repo; migrasinya sekarang harus merevisi dari `1c7e5a9d3b20` (atau sebaliknya bila tayang lebih dulu).

**Jebakan**
- 3 tes kuota (`test_basic_quota_bot_fund_shift_finishes_started_input`, `test_quota_endpoint_counts_scans_but_never_limits`, `test_basic_has_no_scan_quota`) gagal juga di `main` tanpa perubahan R1 saat dijalankan 1 Nov 04:00 WIB (UTC masih 31 Okt): baris dibuat dengan waktu UTC, hitungan bulan memakai tanggal lokal. Tidak disentuh; perlu dicek ulang setelah 07:00 WIB dan dibuat tidak bergantung jam bila tetap muncul.
- Unit-of-work SQLAlchemy menjalankan INSERT sebelum DELETE dalam satu flush. Pindah household (hapus keanggotaan lama + tambah baru) aman karena `household_id` berbeda; tapi kode baru yang menghapus lalu menambah keanggotaan ke household yang **sama** dalam satu flush akan kena constraint unik. Flush di antaranya.
- PostgreSQL lokal: direktori scratchpad tidak bisa diakses user `claude`; pakai direktori di `/home/claude` untuk `initdb`.

**Keputusan kecil**
- Backfill `kind` hanya di migrasi, bukan tiap start: aturan teks "Top-up" menebak, dan baris baru sudah ditulis benar oleh jalurnya. Backfill hanya mengubah baris yang masih `pemasukan`, berurutan penyesuaian → transfer → top-up.
- Aturan top-up: keterangan `Top-up` persis atau diawali `Top-up ` (bot, bawaan modal web, form amplop baru); "Top-upan …" tetap `pemasukan`.
- Klien tidak boleh menulis `transfer` atau `penyesuaian` lewat `POST /incomes/`.
- Jenis usaha (penjualan, modal, pinjaman) tidak masuk `incomes.kind`; milik tabel Buku Usaha (U1–U2).
- `PROGRESS.md`: F0 ditandai `selesai` (PR #159 sudah di-merge).

**Cara melanjutkan**
- Sebelum merge: jalankan langkah 1–2 checklist "Plugin R1" di `AGENTS.md` (hak tabel, cek keanggotaan ganda), lalu ikuti "Urutan merge PR bermigrasi". Merge hanya oleh orang yang bisa menjalankan migrasi di VPS pada jam yang sama.
- Berikutnya `/sesi-plugin R2` (dua sesi, satu PR, review keamanan) setelah R1 di-merge dan migrasinya jalan; atau `/sesi-plugin B1` di jalur Beranda.

---

## F0 · Bootstrap repo dan CI migrasi · 2026-10-31 · pemilik produk + Claude

**Selesai** (sesi selesai; status review, PR #159, issue #137)
- `docs/plugin/`: `00-indeks.md`; `01-kajian.md` (salinan kajian di claude.ai per 31 Okt, rujukan dokumen project diganti file repo); `02-adr.md` (ADR-P1–P19, plus keputusan kajian no. 7, 9, 11 yang belum diambil); `03-workflow.md` (rencana development yang disetujui, dengan kolom issue, tabel keputusan pendukung sebagai ADR, dan template PR); `04-kontrak-api.md` v0; `05-desain-buku-usaha.md` (mockup kanvas + keputusan ruang usaha); `PROGRESS.md` (23 sesi + tabel gerbang); file ini.
- `AGENTS.md`: bagian baru "Plugin dan ruang" (sembilan aturan, flag, migrasi) dan satu butir di "Database Schema" tentang workflow "Migrasi", karena berlaku untuk semua sesi yang menyentuh model.
- `.claude/commands/sesi-plugin.md` dan `tutup-sesi-plugin.md`, turunan `/sesi` dan `/tutup-sesi` mobile.
- `.github/workflows/migrasi.yml` + `.github/scripts/cek-migrasi.sh`: di PR yang menyentuh model atau migrasi, skema awal dibuat seperti produksi (`create_all` dari model commit dasar + `alembic stamp head`), lalu `upgrade head`, `alembic check`, `downgrade` ke head dasar, `upgrade head`. Diuji lokal di PostgreSQL 16: `main` tanpa perubahan lulus; model + migrasi baru lulus; model baru tanpa migrasi gagal di `alembic check` (kode keluar bukan 0).
- GitHub: label `plugin` dan `review-keamanan` (label `migrasi` sudah ada), milestone "Plugin Fase 0 — Persiapan" sampai "Plugin Fase 5 — Beta", issue #137–#158 (satu per sesi, berlabel sesuai tanda).
- Artifact "Tracker Plugin Jatahku" di claude.ai untuk manusia.

**Digantung**
- `04-kontrak-api.md` masih v0 dari kajian. Sesi pembuat endpoint (B1, R2, R4, R5, R7, H1, H3, U1–U3) menetapkannya menjadi v1 di PR-nya sendiri. Yang paling mungkin berubah: endpoint Buku Usaha (bagian 6) dan respons 202 untuk draf persetujuan.
- Keputusan kajian no. 7 (Beranda bawaan dari pemilik), no. 9 (payment gateway), no. 11 (harga di toko aplikasi) belum diputuskan; tidak menghalangi sesi mana pun sampai V1.
- Tafsiran di `05-desain-buku-usaha.md` B1 (ruang usaha dan adminnya tidak punya akses ke ruang keluarga anggota, fitur household yang sekarang tetap ada) masih perlu dikonfirmasi pemilik produk sebelum R5.
- Sebelum beta: klausul pemrosesan data di S&K ruang usaha dan penilaian dampak ringkas UU PDP (`03-workflow.md`, "Keamanan lebih dulu").
- Dokumen "Rencana Development Plugin Buku Usaha" di claude.ai disalin dari `03-workflow.md`; perubahan rencana berikutnya dibuat di repo dulu.

**Jebakan**
- `alembic upgrade head` dari database kosong **gagal** (`relation "notification_preferences" does not exist`): migrasi awal hanya membuat 11 tabel, sisanya dibuat `create_all` saat start. Karena itu cek migrasi membangun skema dasar dengan `create_all` dari model commit dasar, bukan dari migrasi.
- `alembic check` kini menjadi gerbang untuk **semua** PR yang menyentuh `app/models/**`, termasuk sesi mobile dan AI Advisor: model yang berubah tanpa migrasi gagal. Di `main`, `alembic check` tidak menemukan selisih palsu antara model dan skema hasil `create_all` (dicek lokal), jadi kegagalan berarti selisih sungguhan.
- `cek-migrasi.sh` memakai `git worktree` pada commit dasar; di clone dangkal ambil dulu commitnya (`git fetch --depth=1 origin <sha>`, sudah ada di workflow). Butuh `psycopg2-binary` (tidak ada di `requirements-test.txt`; workflow memasangnya sendiri).
- Di lingkungan Claude Code cloud, `gh` lewat GraphQL ditolak (403): pakai REST (`gh api repos/mtyatno/jatahku/...`) untuk label, issue, dan PR.
- PostgreSQL lokal untuk uji: `initdb` dan `pg_ctl` harus dijalankan sebagai user non-root (mis. `runuser -u claude -- /usr/lib/postgresql/16/bin/pg_ctl ...`).

**Keputusan kecil**
- Cek migrasi ditambah `alembic check` (lebih ketat dari rencana yang hanya menyebut upgrade dan downgrade), karena `create_all` saat start bisa menutupi migrasi yang terlupa sampai deploy berikutnya.
- Workflow "Migrasi" hanya berjalan bila PR menyentuh model, migrasi, `database.py`, `requirements.txt`, atau file workflow itu sendiri; PR lain tidak melambat.
- Galat baru tetap memakai `detail` berupa teks (klien sekarang menampilkannya langsung) dan menambah field `kode` (`04-kontrak-api.md`, aturan 6).
- Data contoh kanvas (Dapur Nusa) diusulkan menjadi fixture tes Buku Usaha (`05-desain-buku-usaha.md` A3).

**Cara melanjutkan**
- Pemilik produk: PR ini hanya dokumen, perintah sesi, dan CI; tidak mengubah kode yang berjalan, jadi aman di-merge kapan saja. Workflow "Migrasi" ikut berjalan di PR ini (menyentuh file workflow-nya) dan harus hijau.
- Bila dikerjakan sendiri: `/sesi-plugin B1` (Beranda registry; lebih kecil, di balik flag, dan B2 dibutuhkan R6). Bila dua orang: B1 dan `/sesi-plugin R1` paralel.
- R2 adalah sesi paling berisiko (86 titik di 31 file, dua sesi di satu PR): jadwalkan setelah R1 di-merge dan saat tidak ada PR mobile atau AI Advisor lain yang menyentuh `bot/handlers.py` dan `envelope_balance.py`.
