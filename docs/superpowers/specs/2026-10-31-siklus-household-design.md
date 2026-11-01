# Siklus anggaran per household — desain

**Tanggal:** 31 Okt 2026 (diperbarui 1 Nov 2026 sesudah implementasi)
**Status:** desain disetujui pemilik produk di chat, bagian 1–9 (31 Okt 2026); spec tertulis disetujui 31 Okt 2026. **Diimplementasikan** di branch `feat/siklus-household` (1 Nov 2026, di atas main setelah Plugin R2 (#166) dan B3 (#167/#168)): revisi alembic `2d51b9031a6b`, PR berlabel `migrasi` menunggu merge. Perilaku final: `docs/siklus-household.md`. Yang berubah dari desain awal tercatat di "Penyesuaian saat implementasi" (butir 6–23) dan ditandai dengan nomornya di bagian yang bersangkutan; keputusan produk 1–8 tidak berubah, kecuali cara keputusan 7 dijalankan (penyesuaian 15). Rencana: `docs/superpowers/plans/2026-10-31-siklus-household.md`.

## Penyesuaian saat menyusun rencana implementasi (31 Okt 2026)

Membaca kode lebih dalam menghasilkan penyesuaian berikut; bagian di bawah sudah diperbarui.

1. **Join web rusak hari ini.** `POST /household/join` membaca `code` dari query, sedangkan `Settings.jsx` mengirimnya di body JSON → 422 (direproduksi dengan TestClient). Route menerima keduanya (bagian 3).
2. **Recompute diserialkan per household dan membaca payday terbaru.** Dua perubahan payday beruntun (mis. mengetik "2" lalu "25") bisa menjalankan dua recompute bersamaan dengan jendela berbeda; yang selesai terakhir menang, dan itu belum tentu payday terakhir. `household_cycle.recompute_history(hid, periods)` memegang `asyncio.Lock` per household dan membaca `households.payday_day` **di dalam** kunci. App berjalan satu proses uvicorn (scheduler APScheduler di dalam proses API; dua proses sudah menggandakan setiap job), jadi kunci dalam proses cukup. Settings menunda simpan payday 600 ms (debounce) untuk household sendirian.
3. **Signature dirapikan:** `can_change_payday(role, member_count)`, `set_household_payday(db, household, day, *, actor)`, `PaydayContext` + `payday_context(db, user)` sebagai satu titik baca untuk route, dan `pick_payday(rows)` murni untuk resolver dan dry-run skrip.
4. **Profil membawa `household_name` dan `household_member_count`** juga, supaya Settings bisa menyusun teks konfirmasi tanpa permintaan tambahan.
5. **Kompatibilitas dengan ruang usaha** (rencana Buku Usaha, tahap R1/R2 ruang usaha dari sesi lain) ditambahkan sebagai bagian 10.
**Klasifikasi:** arsitektural. Mengubah invarian yang dibaca ±25 call site (snapshot, rollover, advisor, analitik, langganan, struk), menyentuh web dan bot, dan butuh migrasi skema + data.
**Spec lanjutan:** laporan berkala (bulanan, kuartalan, tahunan) ditulis sebagai spec terpisah **setelah** fase ini tayang. Spec ini adalah fondasinya.

## Penyesuaian saat implementasi (1 Nov 2026)

Implementasi dan review per tugas menghasilkan penyesuaian berikut (nomor melanjutkan daftar di atas). Bagian di bawah
sudah diperbarui dan ditandai "(penyesuaian N)"; keputusan produk 1–8 tidak berubah, kecuali cara keputusan 7 dijalankan
(penyesuaian 15). Perilaku final ada di `docs/siklus-household.md`. "Plugin R1" dan "tahap R2/R4/R5" = tahap rencana
ruang usaha (bagian 10), yang didefinisikan di `docs/plugin/03-workflow.md` (Fase 2 · Ruang usaha).

6. **Pembacaan tanggal di dalam kunci hanya-baca.** Rancangan awal (`_current_payday` mengisi NULL lewat sesi
   sendiri dan commit) bisa menunggu selamanya pada UPDATE `households` milik transaksi pemanggil yang belum di-commit
   (tanpa timeout PG), padahal kunci recompute sedang dipegang. `current_payday` kini hanya membaca: nilai tersimpan, atau
   bila NULL `pick_payday(member_rows)` tanpa assign, flush, maupun commit. Pemanggil yang baru mengubah atau mengisi
   tanggal di sesinya **commit dulu** sebelum `recompute_history` atau pembuatan snapshot (`set_household_payday`, route
   `recompute`, `/snapshots/run`, tahap pertama job, skrip migrasi).
7. **Kunci dan pembacaan tanggal dipakai bersama job harian**, supaya job harian tidak menulis kunci snapshot bersamaan
   dengan recompute household yang sama. `household_lock(hid)` dan `current_payday(hid) -> int | None` publik; None bila
   household sudah dihapus (merge, hapus akun). `recompute_history` dan `payday_snapshot_job` (sejak penyesuaian 17 juga
   `POST /snapshots/run`) sama-sama memegang kunci, membaca tanggal DI DALAM kunci, dan membangun jendela darinya;
   `recompute_history` mengembalikan `[]` dengan warning untuk household yang hilang, job melewatinya. Tanpa ini, job yang
   membaca tanggal sebelum kunci bisa menulis ulang kunci periode berjalan yang baru dibuang recompute.
8. **Recompute membuang snapshot periode berjalan.** Snapshot hanya boleh ada untuk periode tertutup. Kunci
   snapshot hanya `(tahun, bulan awal)`, tanpa jendelanya, dan job tanpa `force` tidak menimpa kunci yang sudah ada:
   memindahkan payday lebih lambat (1 → 25 pada 10 Nov) meninggalkan kunci 2026-10 berisi angka 1–31 Okt, yang lalu terbaca
   rollover 25 Nov. `recompute_household` kini menghapus kunci periode berjalan menurut payday baru dan sesudahnya
   (sejak penyesuaian 16 sebelum, bukan sesudah, periode tertutup dibangun ulang).
9. **Recompute yang gagal tidak membatalkan perubahan.** `set_household_payday` menangkap exception dari
   `recompute_history` setelah tanggal di-commit: dicatat `logger.exception`, hasil `recomputed: 0`, notifikasi tetap
   terkirim tanpa kalimat "Riwayat … dihitung ulang". Pemulihannya dijalankan operator (skrip `--apply` atau `POST
   /snapshots/recompute`). Error per amplop di dalam satu periode dicatat `logger.error`, daftar hasil tetap dikembalikan.
10. **Urutan `--apply`.** `household_payday` → commit → `recompute_history` → `heal` → notifikasi. `heal`
    pindah ke sesudah recompute: recompute hanya membaca `households.payday_day`, jadi urutan ini tidak mengubah angkanya,
    dan recompute yang gagal meninggalkan anggota belum disamakan sehingga run ulang menemukan dan memberi tahu mereka.
11. **Ruang usaha sudah diimplementasikan (Task 8b di rencana).** Plugin R1 (`households.type`, satu user boleh di
    beberapa household) masuk `main` sebelum fase ini selesai. `mirrors_users(household)` memutuskan cermin; `membership`
    hanya ruang keluarga; `set_household_payday` dan `heal` hanya mencerminkan untuk ruang keluarga; join web dan bot hanya
    memanggil `adopt_household_payday` untuk ruang keluarga. Sisanya untuk rencana ruang usaha: bagian 10.
12. **Bentuk akhir fungsi.** `pick_payday(rows: Sequence[MemberRow])` menerima dataclass `MemberRow(user_id, name, role,
    created_at, payday_day)` dari `member_rows(db, household_id)`, bukan tuple. `household_payday(db, household,
    rows=None)` memakai baris yang sudah dimuat tanpa kueri kedua. Notifikasi lewat `notify_payday_changed` (dipakai juga
    skrip), tanpa `telegram_html`: `kirim` yang meng-escape.
13. **`POST /snapshots/run`: kunci `period` tingkat atas dihapus.** Respons `{"households": [...], "processed",
    "snapshots_created", "errors"}`; tiap entri membawa `household_id` dan `period` sendiri. Satu-satunya pengecualian dari
    "API hanya bertambah", disengaja: periode kini per household, endpoint khusus admin, dan tidak punya pemanggil (web,
    bot, mobile).
14. **Alur route profil dan Onboarding.** `PUT /user/profile` selalu `commit` di akhir: service tidak commit
    saat tanggalnya sama, padahal field lain (`income_type` dari Onboarding, yang mengirim `payday_day` berdampingan) sudah
    di-assign. Onboarding membaca profil dulu dan, untuk anggota yang terkunci, hanya mengirim `income_type`:
    PUT yang membawa `payday_day` ditolak 403 dan `income_type` ikut hilang (diperluas penyesuaian 20).

Dari review akhir seluruh branch (1 Nov 2026), sebagian terkonfirmasi di PostgreSQL 16 asli:

15. **Recompute mencakup seluruh riwayat household (cara menjalankan keputusan 7; bagian 2, 3, 4c, 6a).** Recompute 12
    periode meninggalkan batas di periode ke-13: periode tertua yang dihitung ulang membaca rollover kunci sebelumnya yang
    masih berjendela lama, jadi memundurkan tanggal membuat hari di antara kedua jendela tidak terhitung dan memajukannya
    membuatnya terhitung dua kali, dan rollover membawanya ke saldo selamanya (riwayat Jan 2025–Nov 2026, 1 → 25: rantai
    Rp3.570.000, seharusnya Rp3.950.000). Kini setiap recompute (perubahan tanggal, skrip `--apply`, `POST
    /snapshots/recompute`) memperlakukan `periods` sebagai batas BAWAH dan mundur sampai periode SEBELUM periode yang
    memuat aktivitas pertama household: `rollover.first_activity_date` (transaksi pertama, termasuk yang dihapus, atau
    pemasukan teralokasi pertama di amplop household, termasuk amplop nonaktif) dan `period.periods_to_cover`, dibatasi
    `MAX_RECOMPUTE_PERIODS = 120` dengan warning. Periode sebelumnya itu wajib: saat tanggal dimajukan (25 → 1, data
    pertama 5 Mar), kunci Februari masih menyimpan snapshot berjendela 25 Feb–24 Mar yang memuat data. Notifikasi
    menyebut jumlah periode yang benar-benar dihitung ulang (`len(results)`), dan kalimat riwayat dibuang bila jumlahnya
    0 atau recompute gagal, di kedua varian pesan. Dialog Settings: "…, dan riwayat anggarannya dihitung ulang.
    Lanjutkan?" (bukan "12 periode terakhir").
16. **Kunci periode berjalan dibuang LEBIH DULU (bagian 4c; mengubah penyesuaian 8).** DELETE kunci periode berjalan dan
    sesudahnya di-commit sebelum periode tertutup dibangun ulang. Kuncinya tidak pernah beririsan (setiap kunci tertutup
    < kunci periode berjalan), jadi angkanya sama; tetapi rebuild yang gagal di tengah jalan tidak lagi meninggalkan
    kunci periode berjalan basi yang tidak pernah ditimpa job.
17. **`POST /snapshots/run` hanya periode tertutup, di dalam kunci (bagian 3).** Menulis periode berjalan (angka setengah
    jalan) atau periode yang belum mulai (pendahulunya belum ada) membuat kunci yang tidak pernah ditimpa job tanpa
    `force`, dan rollover yang salah terbawa terus (payday 25, `run` bawaan pada 1 Nov: rollover ke periode 25 Des
    Rp170.000, seharusnya Rp1.910.000). Kini tiap household diproses di dalam `household_lock` dengan tanggal yang
    dibaca di dalam kunci; periode yang `period_end >= hari ini` dilewati (`"skipped": "periode belum tertutup"`),
    household yang hilang dilewati (`"skipped": "household tidak ada"`), dan kegagalan satu household menjadi entri
    `"errors": ["gagal: <kelas>"]` tanpa menghentikan yang lain. Pemulihan rantai lewat `POST /snapshots/recompute` atau
    skrip, bukan `run` (yang dengan `force` hanya menulis ulang satu mata rantai).
18. **Profil: anggota terkunci yang mengulang tanggal rumah (bagian 3).** `PUT /user/profile` dengan `payday_day` sama
    dengan tanggal rumah dari anggota yang tidak boleh mengubahnya tidak lagi 403: tanggalnya diabaikan dan field lain
    tersimpan. Klien lama (Onboarding sebelum fase ini mengirim `payday_day` bersama `income_type`) tidak kehilangan
    `income_type`; tanggal yang berbeda tetap 403.
19. **Join: `code` di body opsional (bagian 3).** `JoinRequest.code: str | None = None`: `{}` dan `{"code": null}` → 400
    "Kode invite wajib diisi" (bukan 422), dan `?code=X` dengan body `{}` kembali diterima.
20. **Onboarding tidak mengubah tanggal rumah lebih dari satu anggota (bagian 6a; memperluas penyesuaian 14).**
    `onboardingProfileBody` juga melewatkan `payday_day` untuk owner/admin household lebih dari satu anggota
    (`needsConfirm`): Onboarding tidak punya dialog konfirmasi, dan pekerja harian/mingguan akan mengirim tanggal 1 yang
    mereset siklus seluruh rumah dan menghitung ulang riwayatnya. Household sendirian tetap mengirimnya.
21. **Skrip dan runbook migrasi data (bagian 7, 9).** (a) `apply` menjumlahkan error per amplop semua periode ke ringkasan
    (`"errors"`), baris terakhir mencetaknya, dan kode keluarnya 1 bila tidak nol; notifikasi memakai jumlah periode yang
    dihitung ulang; `--help` menyebut urutan sebenarnya dan bahwa `--periods` hanya batas bawah. (b) Dry-run dan `--apply`
    pada hari yang sama dengan merge, sebelum job 00:05 berikutnya: job itu menyamakan anggota household campuran tanpa
    notifikasi, dan `--apply` sesudahnya tidak menemukan siapa pun untuk diberi tahu (bila terlewat, `journalctl … | grep
    menyimpang` mendaftar mereka). (c) Cadangkan `monthly_snapshots` sebelum `--apply`, dengan restore dalam satu
    transaksi. (d) Household yang tidak campuran TIDAK selalu menghasilkan angka identik: periode tertutup yang diubah
    setelah snapshot-nya dibuat (transaksi bertanggal mundur, diedit atau dihapus, alokasi terlambat) kini ikut
    terhitung, jadi sebagian saldo rollover bergeser (lebih benar).
22. **Hak tabel (bagian 1c, 9).** Untuk tabel yang bukan milik `jatahku`, obatnya `ALTER TABLE <tabel> OWNER TO jatahku`
    (seperti checklist `AGENTS.md`), bukan menjalankan DDL sebagai `postgres`: DDL `lifespan` berjalan di setiap start, dan
    `ADD COLUMN IF NOT EXISTS` tetap mensyaratkan pemilik walau kolomnya sudah ada (terverifikasi di PostgreSQL 16), jadi
    API gagal start di restart berikutnya.

Dari penggabungan dengan `main` setelah Plugin R2 (#166, resolver `ruang_aktif`) dan B3 (1 Nov 2026):

23. **Integrasi dengan resolver ruang Plugin R2 (bagian 2, 3, 6b, 10).** (a) Satu definisi keanggotaan ruang keluarga:
    `membership(db, user)` meneruskan ke `ruang.keanggotaan_keluarga`, tanpa kueri sendiri (dua ruang keluarga, yang
    tidak semestinya ada, → yang tertua, bukan galat). (b) Profil (`GET`/`PUT /user/profile`) tetap ruang keluarga dan
    tidak membaca header `X-Jatahku-Ruang`: cermin `users.payday_day` milik ruang keluarga. (c) `POST
    /snapshots/recompute` menerima ruang tulis R2 (`hid: RuangTulis`; sampai R3 selalu ruang keluarga) dan menghitung
    izinnya untuk household itu: `payday_context(db, user, household_id=hid)` memakai `ruang.keanggotaan(db, user.id,
    hid)`; tanpa household atau bukan anggotanya → `{"recomputed": 0, "periods": []}`; lalu commit dan
    `recompute_history(hid, periods)`. Hari ini perilakunya sama; sejak R3 recompute dan izinnya mengikuti ruang yang
    ditulis. (d) Join web dan bot menolak undangan ke household selain `rumah_tangga` sebelum keanggotaan apa pun berubah
    (perbaikan keamanan R2: web 400 "Kode invite tidak valid atau expired", bot "❌ Kode invite tidak valid atau sudah
    expired."), dan pindah ruang keluarga hanya menghapus keanggotaan ruang keluarga lama. Jadi `adopt_household_payday`
    hanya pernah dipanggil untuk ruang keluarga, dan cabang `mirrors_users` di kedua join (penyesuaian 11: respons ruang
    usaha membawa tanggal ruang itu, bot tanpa baris siklus) tidak terjangkau lagi dan dibuang. (e) Butir R2 di bagian 10
    selesai; butir R4 dan R5 tetap terbuka, ditambah satu butir terbuka sesudah R2 (jendela periode dari
    `user.payday_day` saat header membuka ruang lain).

## Masalah

Siklus anggaran Jatahku ditentukan `users.payday_day` (1–31), dan setiap angka periode dihitung dengan payday **orang yang sedang melihat**: dashboard (`envelope_balance.py:58-64`), analitik, export, advisor (`Snapshot.periods`), jendela bayar langganan, dan tanggal struk. Untuk household satu orang ini benar. Untuk household dengan anggota yang payday-nya berbeda, buku besarnya rusak:

- `payday_snapshot_job` (`scheduler.py:18-65`) mengelompokkan **user** per payday lalu memproses household mereka. Household campuran diproses sekali per nilai payday, dan `create_monthly_snapshots` melewati key `(amplop, tahun, bulan)` yang sudah ada. Dalam kondisi normal payday terkecil menang, karena periodenya tutup lebih dulu.
- `create_monthly_snapshots` menyapu **semua** amplop aktif household tanpa melihat `owner_id` (`rollover.py:94-99`). Jadi amplop **pribadi** anggota berpayday 25 pun di-snapshot dengan jendela payday 1. Transaksi 25–30 September terhitung di snapshot (jendela 1–30 Sep) *dan* di `spent` live periode 25 Sep–24 Okt miliknya.
- `POST /snapshots/recompute` bisa dipanggil anggota mana pun (`snapshots.py:98-121`) dan menimpa semua snapshot household dengan `force=True` memakai payday **pemanggil**.
- `POST /snapshots/run` (admin) memakai payday **admin** untuk semua household.
- Tidak ada tes household campuran.

Laporan berkala bergantung pada snapshot yang benar, jadi ini prasyarat, bukan pekerjaan paralel.

## Keputusan produk (diambil di chat, 31 Okt 2026)

1. **Satu household = satu siklus.** Laporan dan buku besar tidak bisa konsisten kalau satu kantong uang ditutup dengan dua jendela tanggal.
2. **Owner menentukan, anggota mengikuti.** Siklus adalah milik rumah, bukan preferensi tampilan.
3. **Sumber kebenaran: kolom baru `households.payday_day`.** `users.payday_day` tetap ada sebagai **cermin** nilai efektif, supaya ±25 call site tidak berubah.
4. **Invarian dijaga di satu service aplikasi** (`services/household_cycle.py`), bukan trigger DB dan bukan refactor semua call site. Job harian menyembuhkan penyimpangan.
5. **`income_type` tetap per user.** Hanya memengaruhi horizon "aman per hari" dan sinyal advisor.
6. **Kolom `allocated_amount` dan `spent_amount` ditambahkan ke `monthly_snapshots` sekarang**, diisi oleh recompute yang memang dijalankan migrasi data fase ini.
7. **Owner mengubah payday → 12 periode tertutup terakhir household dihitung ulang otomatis**, supaya riwayat semua anggota konsisten dengan jendela baru. (Penyesuaian 15: 12 menjadi batas bawah; recompute mundur sampai periode sebelum aktivitas pertama household, maks 120 periode, karena berhenti di periode ke-12 merusak rantai rollover di batas itu.)
8. Saat **bergabung** tidak ada yang dihitung ulang: amplop dan transaksi lama anggota tinggal di household lamanya.

## Tujuan

Setelah fase ini, untuk household mana pun berlaku: semua anggota memakai satu `payday_day`, setiap `(amplop, tahun, bulan)` di `monthly_snapshots` dihitung dengan jendela household itu, dan snapshot menyimpan alokasi dan pengeluaran periode, sehingga spec laporan bisa membaca `rollover_in`, `allocated`, `spent`, `closing`, `rollover_out` per periode tanpa menghitung ulang riwayat.

**Kriteria sukses**
1. Household campuran di produksi (kalau ada) setelah `--apply`: semua anggota payday sama, snapshot riwayatnya dihitung ulang (minimal 12 periode terakhir; penyesuaian 15), dashboard anggota yang payday-nya berubah menampilkan sisa yang cocok dengan buku besar (tanpa transaksi terhitung ganda).
2. Member household >1 anggota tidak bisa mengubah payday (403) dan tidak bisa `recompute` (403); UI menampilkannya read-only tanpa pernah memicu 403.
3. Owner mengubah payday: semua anggota berubah dalam satu transaksi, riwayat dihitung ulang (minimal 12 periode; penyesuaian 15), anggota lain menerima notifikasi (lonceng web + Telegram).
4. Join dari web, bot Telegram, dan chat web mengadopsi payday household, dengan kalimat yang menyebutkannya.
5. Job harian membuat tepat satu jendela per household; anggota yang menyimpang disamakan dan dicatat di log.
6. `openapi_cek`: tidak ada perubahan API yang memutus. Semua tes lama tetap hijau; tes baru menutup semua perilaku di bagian 8.

## 1. Model data & migrasi skema

### 1a. Kolom baru
- `households.payday_day INTEGER NULL`. Model: `Household.payday_day: Mapped[int | None]`. **NULL berarti belum dimigrasi**; resolver (bagian 2) mengisinya saat pertama dibaca. Tidak memakai `DEFAULT 1`, karena household yang owner-nya payday 25 akan terbaca 1 selama jendela antara restart dan migrasi, dan job akan "menyembuhkan" anggota ke nilai yang salah.
- `monthly_snapshots.allocated_amount NUMERIC(15,2) NULL` dan `monthly_snapshots.spent_amount NUMERIC(15,2) NULL`. NULL berarti snapshot lama yang belum dihitung ulang. Model: `Mapped[Decimal | None]`.

### 1b. Cara dipasang (pola Kotak Struk: dua jalur, idempoten)
- `main.py` `lifespan`, blok Postgres yang sudah ada: tiga `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, lalu satu backfill:
  ```sql
  UPDATE households h SET payday_day = sub.payday_day
  FROM (SELECT DISTINCT ON (hm.household_id) hm.household_id, u.payday_day
        FROM household_members hm JOIN users u ON u.id = hm.user_id
        ORDER BY hm.household_id,
                 CASE hm.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, hm.created_at) sub
  WHERE h.id = sub.household_id AND h.payday_day IS NULL;
  ```
  Household tanpa anggota tetap NULL dan tidak dipakai apa pun.
- Revisi alembic baru (label PR `migrasi`), isinya DDL dan backfill yang sama dengan `if_not_exists` / `IF NOT EXISTS`, jadi aman dijalankan sebelum atau sesudah deploy. **Dibuat paling akhir** dari `main` segar karena ada sesi pengembangan lain; `alembic heads` harus tetap satu (`a7c4e2b9d1f3` saat spec ini ditulis). **Implementasi:** revisi `2d51b9031a6b`, `down_revision` `b1d4a7c2e9f0` (Plugin B1), dibuat dari `main` 75610ed; diuji di PostgreSQL 16 dengan `.github/scripts/cek-migrasi.sh` (naik, `alembic check`, turun, naik).
- `HouseholdRole` disimpan sebagai `SAEnum` → nilai di DB `'owner'|'admin'|'member'` (cek saat implementasi dengan `\dT+ householdrole`; sesuaikan `CASE` bila label enum berbeda).

### 1c. Tabel yang butuh hak ALTER
`households` dan `monthly_snapshots` harus dimiliki user DB aplikasi (`jatahku`), seperti dicek di checklist Kotak Struk. Kalau salah satunya milik `postgres`, API gagal start; obatnya `ALTER TABLE <tabel> OWNER TO jatahku` sebagai `postgres` sebelum merge (penyesuaian 22; checklist bagian 9). Menjalankan DDL sebagai `postgres` tidak cukup: DDL `lifespan` berjalan di setiap start, dan `ADD COLUMN IF NOT EXISTS` tetap mensyaratkan pemilik walau kolomnya sudah ada (terverifikasi di PostgreSQL 16).

## 2. Service `app/services/household_cycle.py` — satu-satunya penulis payday

Semua fungsi menerima `db: AsyncSession` dan **tidak** `commit` sendiri kecuali disebut (`heal`, `set_household_payday`); pemanggil yang commit (pola repo). Pembaca tanggal untuk recompute dan job (`current_payday`, di bawah) memakai sesi sendiri yang hanya-baca, jadi pemanggil yang baru mengubah atau mengisi tanggal di sesinya commit dulu (penyesuaian 6).

- `async def household_payday(db, household, rows=None) -> int` (penyesuaian 12): kembalikan `household.payday_day`; bila NULL, turunkan dari anggota (`rows`, atau `member_rows` bila tidak diberikan) dengan urutan owner → admin → anggota tertua (`HouseholdMember.created_at`) → 1, tulis ke `household.payday_day`, `flush`, kembalikan.
- `def pick_payday(rows: Sequence[MemberRow]) -> int` (murni; penyesuaian 12): `rows` = `MemberRow(user_id, name, role, created_at, payday_day)` anggota; urutan owner → admin → member, lalu `created_at` tertua; tanggal kosong milik anggota terpilih dan tanpa anggota → 1. Dipakai `household_payday`, `current_payday`, dan dry-run skrip.
- `def mirrors_users(household) -> bool` (murni; penyesuaian 11): apakah siklus household dicerminkan ke `users.payday_day`, yaitu hanya ruang keluarga (`type` `rumah_tangga`; `type` kosong dihitung ruang keluarga). Dipakai `set_household_payday` dan `heal`; join web/bot memakainya sampai penyesuaian 23, yang menolak undangan selain ruang keluarga lebih dulu.
- `def can_change_payday(role, member_count: int) -> bool`: `role in (owner, admin)` → True; `member` → True hanya bila `member_count == 1`; selain itu False. `role` boleh enum atau string (`str(role)` / `.value`, aturan enum vs string di `AGENTS.md`).
- `@dataclass PaydayContext(household, role, payday_day, member_count, can_change, owner_name)` dan `async def payday_context(db, user, *, household_id=None) -> PaydayContext | None` (None bila bukan anggota): satu titik baca untuk route profil dan recompute (`GET /household/` memakai `_get_membership` + `household_payday`). Tanpa `household_id` ruang keluarga user (profil); dengan `household_id` keanggotaan user di household itu lewat `ruang.keanggotaan` (recompute, ruang tulis R2; penyesuaian 23). Keanggotaan ruang keluarga lewat satu helper `membership(db, user)`, supaya refactor `ruang_aktif` (bagian 10) cukup mengubah satu tempat; sejak penyesuaian 23 helper itu meneruskan ke `ruang.keanggotaan_keluarga` tanpa kueri sendiri. `membership` hanya mengembalikan keanggotaan **ruang keluarga** (penyesuaian 11): satu user boleh di beberapa household sejak Plugin R1, dan keanggotaan ruang usaha tidak boleh membuat `scalar_one_or_none` melempar.
- `def household_lock(household_id) -> asyncio.Lock` dan `async def current_payday(household_id) -> int | None` (publik; penyesuaian 7): kunci snapshot satu per household, dipegang semua penulis kunci `(envelope_id, year, month)` di proses ini (`recompute_history`, job harian, dan sejak penyesuaian 17 `POST /snapshots/run`; tidak re-entrant). `current_payday` membaca `households.payday_day` terbaru lewat sesi sendiri, **hanya-baca** (penyesuaian 6): nilai tersimpan, atau bila NULL `pick_payday(member_rows)` tanpa menulis; None bila household sudah dihapus (merge, hapus akun).
- `async def recompute_history(household_id, periods: int) -> list[dict]`: `async with household_lock(hid)`, membaca `current_payday` **di dalam** kunci, lalu `rollover.recompute_household(hid, payday, periods)`; `periods` adalah batas bawah, recompute mundur sampai aktivitas pertama household (penyesuaian 15). Household yang sudah tidak ada → `[]` dengan satu warning (penyesuaian 7). Error per amplop di dalam periode dicatat `logger.error` dan daftar hasil tetap dikembalikan (penyesuaian 9). Dipakai endpoint `recompute`, `set_household_payday`, dan skrip migrasi.
- `async def set_household_payday(db, household, day: int, *, actor) -> dict`:
  1. validasi `1 <= day <= 31` (`ValueError` → 400 di route);
  2. bila `day == await household_payday(db, household)` → no-op, kembalikan `{"changed": False}` (tanpa recompute, tanpa notifikasi);
  3. `household.payday_day = day`; untuk ruang keluarga (`mirrors_users`, penyesuaian 11) `payday_day` setiap anggota (dimuat lewat `User` ⨝ `HouseholdMember`) di-assign `day`; `commit` (recompute membaca lewat sesi lain, jadi perubahan harus sudah tersimpan);
  4. `advisor_cache.invalidate(household.id)`;
  5. `await recompute_history(household.id, RECOMPUTE_PERIODS_ON_CHANGE)` dengan `RECOMPUTE_PERIODS_ON_CHANGE = 12` (batas bawah; penyesuaian 15). Bila melempar exception (penyesuaian 9): perubahan yang sudah di-commit tetap, `logger.exception`, `recomputed: 0`, dan langkah 6 memakai pesan tanpa kalimat riwayat;
  6. notifikasi ke setiap anggota **selain actor** lewat `notify_payday_changed` → `notification_service.kirim(user, NotificationType.system, title, message, link="/settings")` (tanpa `telegram_html`: `kirim` yang meng-escape; penyesuaian 12). Judul `"Siklus anggaran rumah berubah"`, pesan `"Tanggal gajian {nama rumah} kini tanggal {day} (diubah {actor.name}). Riwayat {k} periode terakhir dihitung ulang."` dengan k = jumlah periode yang benar-benar dihitung ulang (penyesuaian 15; rancangan awal: "Riwayat 12 periode …"); bila recompute gagal atau k = 0: `"Tanggal gajian {nama rumah} kini tanggal {day} (diubah {actor.name})."`. Gagal kirim dicatat, tidak membatalkan perubahan;
  7. kembalikan `{"changed": True, "members": n, "recomputed": k}`.
- `async def adopt_household_payday(db, user, household) -> int`: `user.payday_day = await household_payday(db, household)`; kembalikan nilainya. Dipanggil join web dan bot **sebelum** commit keanggotaan baru, dalam transaksi yang sama, dan hanya untuk ruang keluarga: fungsinya sendiri tidak menjaga tipe, pemanggilnya yang menjaga (penyesuaian 11 lewat `mirrors_users`; sejak penyesuaian 23 join web dan bot menolak undangan selain ruang keluarga sebelum perubahan apa pun).
- `async def heal(db, household) -> list[User]`: untuk household ruang keluarga dengan `payday_day` terisi (ruang usaha dan household NULL dilewati; penyesuaian 11), samakan `users.payday_day` anggota yang berbeda, `commit` (hanya bila ada yang berubah), catat `logger.warning("payday anggota %s menyimpang (%s → %s)")`, kembalikan user yang diperbaiki (skrip migrasi memberi tahu mereka). Dipanggil job harian (bagian 4). Tidak memanggil recompute: penyimpangan hanya mungkin terjadi lewat jalur yang lupa memakai service ini, dan job yang sama menghitung snapshot dengan payday household.
- **Penulis tunggal, dikunci tes:** atribut `payday_day` hanya boleh di-assign di `app/services/household_cycle.py` (dan deklarasi kolom di `app/models/models.py`, backfill DDL di `app/main.py`). `user_settings.py:171` (`user.payday_day = req.payday_day`) diganti pemanggilan service; skrip migrasi (bagian 7) memakai service. Tes `test_household_cycle_sole_writer` memindai `app/**/*.py` (kecuali `app/tests`) dengan regex `\.payday_day\s*=(?!=)` (assignment atribut; argumen kata kunci `payday_day=` tidak ikut) dan `(?i)\bset\s+payday_day` (SQL), dan gagal bila ada file di luar daftar itu.
- `household_payday` boleh dipanggil dari handler GET (mengisi NULL saat dibaca); bila sesi GET tidak di-commit, nilainya tetap benar di respons dan job harian yang menyimpannya.

## 3. API (aditif; satu 403 baru)

- `GET /user/profile` +
  `household_payday_day` (int), `payday_locked` (bool: `not can_change_payday(...)`), `payday_owner_name` (nama owner, `null` bila pemanggil owner-nya), `household_name` (str | null), `household_member_count` (int). Tanpa keanggotaan: `household_payday_day = payday_day`, `payday_locked = false`, dua field nama `null`, `household_member_count = 1`. `payday_day` yang sudah ada tetap dikembalikan (= cermin). Profil (`GET` dan `PUT`) selalu ruang keluarga dan tidak membaca header `X-Jatahku-Ruang` (penyesuaian 23).
- `PUT /user/profile` dengan `payday_day`: cek izin dilakukan **paling awal**, sebelum perubahan apa pun: bila `can_change_payday` → lanjut memproses field lain lalu `set_household_payday`; bila tidak → `403` detail `"Tanggal gajian mengikuti rumah tangga ({nama rumah}, tanggal {N}). Minta owner yang mengubahnya."` tanpa menyimpan apa pun. Tanpa keanggotaan household (seharusnya tidak terjadi) → `400 "Belum punya household"`, seperti `incomes.py`. UI tidak pernah mengirim `payday_day` saat terkunci. Route selalu `commit` di akhir, juga bila service tidak commit karena tanggalnya sama, supaya field lain di request yang sama tetap tersimpan (penyesuaian 14). Anggota terkunci yang mengirim `payday_day` SAMA dengan tanggal rumah tidak mendapat 403: tanggalnya diabaikan (tanpa service) dan field lain tersimpan (penyesuaian 18); tanggal yang berbeda tetap 403.
- `GET /household/` (`HouseholdResponse`) + `payday_day`.
- `POST /household/join` response + `payday_day`. Route menerima `code` dari query **atau** body JSON `{"code": ...}` (hari ini hanya query, sedangkan `Settings.jsx:498` mengirim body → 422; terverifikasi). Keduanya kosong → 400 `"Kode invite wajib diisi"`. Kode di-`strip().upper()` seperti bot. Implementasi: query didahulukan; `code` di body opsional, jadi body tanpa kode (`{}`, `{"code": null}`) → 400 yang sama, dan `?code=X` dengan body `{}` diterima (penyesuaian 19; sebelumnya 422 karena `JoinRequest.code` wajib). Undangan ke household selain ruang keluarga → 400 "Kode invite tidak valid atau expired" sebelum perubahan apa pun (Plugin R2; penyesuaian 23).
- `POST /snapshots/recompute`: household-nya ruang tulis R2 (`hid: RuangTulis`; sampai R3 selalu ruang keluarga), dan izin dihitung untuk household itu juga, `payday_context(db, user, household_id=hid)` (penyesuaian 23); tanpa household atau bukan anggotanya → `{"recomputed": 0, "periods": []}` (perilaku lama); hanya `can_change_payday` (owner/admin; member hanya bila sendirian) → selain itu 403 `"Hanya owner atau admin rumah tangga yang bisa menghitung ulang riwayat."`; commit, lalu `recompute_history(hid, periods)` (payday household, bukan `user.payday_day`). Parameter `periods` tetap (default 6, maks 36), kini batas bawah: recompute mundur sampai aktivitas pertama household, karena endpoint ini alat pemulihan (penyesuaian 15).
- `POST /snapshots/run` (admin): untuk tiap household, `period = get_period_for_month(household_payday, year, month)` lalu `create_monthly_snapshots(..., household_ids=[hid], force=force)`. Respons: ringkasan per household, `{"households": [{"household_id", "period", ...hasil}], "processed", "snapshots_created", "errors"}`; kunci tingkat atas `period` dihapus (penyesuaian 13). Sejak penyesuaian 17: tahap pertama mengisi tanggal rumah yang NULL lalu commit; tiap household diproses di dalam `household_lock` dengan tanggal yang dibaca di dalam kunci (`current_payday`); hanya periode tertutup (`period_end < hari ini`) yang ditulis. Periode berjalan atau belum mulai → entri `"skipped": "periode belum tertutup"`, household yang hilang → `"skipped": "household tidak ada"` dengan `period` null (angka 0, `errors` kosong), dan exception di satu household → entri `"errors": ["gagal: <kelas exception>"]` tanpa menghentikan household berikutnya. `force=true` pada periode lampau hanya menulis ulang satu mata rantai; rantai diperbaiki lewat `POST /snapshots/recompute` atau skrip.
- Semua perubahan lolos `python -m app.scripts.openapi_cek`.

## 4. Job snapshot & rollover

### 4a. `payday_snapshot_job` (`scheduler.py`)
Iterasi **household**, bukan grup user, dalam dua tahap (penyesuaian 7):
```
# tahap 1, satu sesi: household yang punya anggota (yang kosong dilewati)
for household in households:
    await household_payday(db, household)            # mengisi NULL (flush)
    await heal(db, household)
    hids.append(household.id)
await db.commit()                                    # sesi ditutup sebelum tahap 2

# tahap 2, per household, di dalam kunci
for hid in hids:
    async with household_lock(hid):
        payday = await current_payday(hid)           # dibaca ulang DI DALAM kunci, hanya-baca
        if payday is None:                           # household sudah dihapus (merge, hapus akun)
            continue                                 # dilewati dengan warning
        for ps, pe in get_closed_periods(payday, today, CATCH_UP_PERIODS):   # lewat household_runs
            await create_monthly_snapshots(ps, pe, household_ids=[hid])
```
Tanggal dari tahap pertama sengaja tidak dipakai untuk jendela: pemilik bisa mengubah tanggal selagi job mengerjakan household lain, dan recompute-nya membuang kunci periode berjalan menurut tanggal baru; jendela basi akan menulisnya lagi dengan angka periode lama, dan job tanpa `force` tidak pernah menimpanya. `CATCH_UP_PERIODS = 3` dan jadwal (00:05) tidak berubah. Rencana jendela dipisah dari IO sebagai fungsi murni `household_runs(rows, today, catch_up) -> list[(hid, payday, [(ps, pe)])]` yang menerima `(household_id, payday)` dan diuji tanpa DB; job memanggilnya per household dengan tanggal yang dibaca di dalam kunci.

### 4b. `create_monthly_snapshots` (`rollover.py`)
- Menyimpan `allocated_amount=allocated` dan `spent_amount=spent` di setiap snapshot yang dibuat (termasuk `force`).
- Rumus diekstrak ke fungsi murni:
  ```python
  @dataclass(frozen=True)
  class SnapshotValues: opening: Decimal; closing: Decimal; rollover: Decimal; allocated: Decimal; spent: Decimal
  def snapshot_values(prev_rollover, allocated, spent, is_rollover) -> SnapshotValues
  ```
  dengan `opening = allocated + prev_rollover`, `closing = opening − spent`, `rollover = closing if is_rollover else 0`. Identitas yang dikunci tes: `opening − allocated == prev_rollover`; non-rollover me-reset sisa **maupun defisit** (closing negatif → rollover 0).
- Perilaku lain (key `(tahun, bulan awal periode)`, `get_previous_rollover` dengan bulan−1, hanya amplop `is_active`) tidak berubah.

### 4c. `recompute_household(hid, payday, periods) -> list[dict]` (`rollover.py`)
`get_closed_periods(payday, today, periods)` oldest-first, tiap periode `create_monthly_snapshots(ps, pe, force=True, household_ids=[hid])`. `periods` adalah batas bawah (penyesuaian 15): `first_activity_date(db, hid)` (yang lebih dulu dari transaksi pertama, termasuk yang dihapus, dan pemasukan teralokasi pertama di amplop household, termasuk amplop nonaktif) dan `period.periods_to_cover(payday, first, today)` menentukan jumlah periode tertutup dari periode SEBELUM periode yang memuat aktivitas pertama sampai periode tertutup terbaru; yang dipakai `max(periods, min(itu, MAX_RECOMPUTE_PERIODS = 120))`, dengan warning bila dibatasi. Dipanggil hanya lewat `household_cycle.recompute_history` (kunci per household + payday terbaru), yang dipakai endpoint `recompute`, `set_household_payday`, dan skrip migrasi (bagian 7). Deterministik, aman diulang.

**Membuang kunci periode berjalan (penyesuaian 8, 16).** Sesudah semua periode tertutup dibangun ulang (penyesuaian 16: kini SEBELUMNYA, dan di-commit lebih dulu, supaya rebuild yang gagal tidak meninggalkan kunci periode berjalan basi; kuncinya tidak pernah beririsan dengan yang dibangun ulang), `recompute_household` menghapus snapshot household itu pada kunci `(tahun, bulan)` yang sama dengan atau sesudah bulan AWAL periode berjalan menurut `payday` (relatif terhadap `today`), lewat sesinya sendiri. Snapshot hanya boleh ada untuk periode tertutup. Contoh: payday 1 → 25 pada 10 Nov 2026; kunci 2026-10 ditulis job 1 Nov dengan angka 1–31 Okt, padahal di bawah payday 25 itu periode berjalan 25 Okt–24 Nov. Dibiarkan, job 25 Nov melewatinya (sudah ada) dan rollover yang salah terbawa terus; dibuang, job membuatnya lagi dengan benar saat periodenya tutup.

## 5. `app/core/period.py`

- Tambah `get_period_for_month(payday_day, year, month) -> tuple[date, date]` = `get_budget_period(payday_day, _safe_date(year, month, payday_day))`.
- `export._resolve_period` (cabang `year`+`month`) dan `snapshots.run` memakainya; perilaku identik (dikunci tes kesetaraan).
- `get_report_period` **tidak** dibuat di fase ini (belum ada pemakai); masuk spec laporan.

## 6. Web & bot

### 6a. Settings (`frontend/src/pages/Settings.jsx`, kartu "📅 Tanggal Gajian")
- Bila `payday_locked`: input diganti teks read-only `"Mengikuti siklus rumah tangga: tanggal {N} (diatur {payday_owner_name})."` dan `payday_day` tidak pernah dikirim.
- Bila boleh mengubah dan `member_count > 1`: input tidak lagi menyimpan saat diketik; ada tombol Simpan yang membuka dialog konfirmasi in-app (pola dialog reset data di halaman yang sama, bukan `window.confirm`): `"Mengubah tanggal gajian berlaku untuk semua anggota {nama rumah}, dan riwayat anggarannya dihitung ulang. Lanjutkan?"` (penyesuaian 15; rancangan awal: "…, dan 12 periode terakhir dihitung ulang. …"). Household sendirian: tetap simpan saat berubah, ditunda 600 ms (debounce) supaya mengetik "25" tidak menyimpan "2" dulu.
- Logika keputusan di `lib/paydayLock.js` (`paydayLockState(profile) -> {locked, note, needsConfirm, confirmText}` dan `joinSuccessMessage(householdName, paydayDay)`; implementasi menambah `householdPayday`, `parsePaydayDay`, `PAYDAY_SAVE_DELAY_MS`, dan `onboardingProfileBody`) supaya bisa diuji `node --test`.
- Onboarding (`Onboarding.jsx`; penyesuaian 14, 20): profil dibaca dulu; `payday_day` hanya dikirim untuk household sendirian (`onboardingProfileBody`). Anggota yang tanggalnya terkunci hanya mengirim `income_type`, karena PUT yang membawa tanggal lain ditolak 403 dan `income_type` ikut hilang. Owner/admin household lebih dari satu anggota (`needsConfirm`) juga hanya mengirim `income_type` (penyesuaian 20): Onboarding tidak punya dialog konfirmasi, dan income harian/mingguan mengirim tanggal 1 yang mereset siklus seluruh rumah; tanggal rumah diubah di Settings.

### 6b. Join
- Web (`Settings.jsx` `joinHousehold`): flash `"Berhasil bergabung ke {rumah}! Siklus anggaranmu sekarang mengikuti rumah ini: tanggal {payday_day}."`, lalu `load()` memuat profil baru.
- Bot `cmd_join` (`household_cmd.py`, juga dipakai chat web lewat registry handler yang sama): hanya undangan ruang keluarga (Plugin R2; penyesuaian 23); panggil `adopt_household_payday` sebelum commit; pesan sukses ditambah baris `"Siklus anggaranmu sekarang mengikuti rumah ini: tanggal {N}."`.

### 6c. Alokasi (`frontend/src/pages/Allocate.jsx`)
Banner inline di baris amplop tujuan bila `!env.is_rollover` **dan** sisa hari periode berjalan ≤ 7 **dan** nilai alokasi > 0:
`"Amplop ini tidak membawa sisa ke periode berikutnya. Yang tidak terpakai di-reset {period_end} ({n} hari lagi)."`
Data sudah ada di halaman: `is_rollover` dari `/envelopes/summary`, `period_end` periode berjalan dari `/analytics/periods`. Logika di `lib/nonRolloverWarning.js` (`nonRolloverWarning(env, periodEnd, today, amount) -> string | null`), diuji `node --test`. Hanya web: alokasi tidak pernah terjadi lewat bot.

### 6d. Notifikasi
Lewat `notification_service.kirim` dengan `NotificationType.system` (tanpa enum DB baru, tanpa email): lonceng web + Telegram bila tertaut, `link="/settings"`. Teks di bagian 2.

## 7. Migrasi data sekali jalan: `app/scripts/siklus_household.py`

Dijalankan admin di VPS setelah deploy (pola `app/scripts/kotak_corpus.py`, `argparse`, `python -m`):
- `--dry-run` (default): per household cetak id, nama, jumlah anggota, payday tiap anggota, payday household yang akan dipakai, dan tanda **campuran** bila anggota ruang keluarga punya payday berbeda (`COUNT(DISTINCT users.payday_day) > 1`; ruang usaha ditandai `[usaha]` dan tidak pernah campuran, penyesuaian 11). Tidak menulis apa pun.
- `--apply [--periods 12]`: untuk tiap household, urutan (penyesuaian 10): `household_payday` (mengisi NULL) → `commit` (penyesuaian 6) → `recompute_history(hid, periods)` untuk **semua** household (minimal `periods`, mundur sampai aktivitas pertama household, penyesuaian 15; mengisi `allocated_amount`/`spent_amount`) → `heal` (menyamakan anggota) → notifikasi (bagian 6d, tanpa `actor`) ke anggota yang payday-nya berubah, dengan pesan `"Siklus anggaranmu kini mengikuti {rumah}: tanggal {N}. Riwayat {k} periode terakhir dihitung ulang."` (k = periode yang dihitung ulang household itu). Rancangan awal menjalankan `heal` sebelum recompute. Rancangan awal juga menyatakan household non-campuran menghasilkan angka identik; itu hanya berlaku bila tidak ada periode tertutup yang diubah setelah snapshot-nya dibuat (transaksi bertanggal mundur, diedit atau dihapus, alokasi terlambat). Recompute kini memasukkan perubahan itu, jadi sebagian saldo rollover household non-campuran bisa bergeser (lebih benar), tanpa notifikasi (penyesuaian 21).
- Idempoten: menjalankan `--apply` dua kali menghasilkan DB yang sama dan tidak mengirim notifikasi kedua (tidak ada anggota yang berubah lagi). Kegagalan tidak ditangkap (traceback, kode keluar 1); household yang sudah diproses tersimpan dan run yang gagal cukup diulang. Error per amplop di dalam recompute dijumlahkan dan membuat kode keluar 1 juga (penyesuaian 21).
- Keluaran akhir: jumlah household, jumlah campuran, jumlah snapshot ditulis, anggota yang diberi tahu, dan jumlah error per amplop (penyesuaian 21).
- Dijalankan pada hari yang sama dengan merge, sebelum job 00:05 berikutnya (penyesuaian 21): job itu menyamakan anggota household campuran tanpa notifikasi, dan `--apply` sesudahnya tidak menemukan siapa pun untuk diberi tahu; bila terlewat, `journalctl -u jatahku --since "<waktu deploy>" | grep menyimpang` mendaftar mereka untuk diberi tahu manual. Di jam sepi, bukan sekitar 00:05: skrip berjalan di proses terpisah, jadi `household_lock` tidak menyerialkannya dengan API maupun job harian.
- Sebelum `--apply`, tabel `monthly_snapshots` dicadangkan (`pg_dump -Fc -t monthly_snapshots`), dengan restore dalam satu transaksi (TRUNCATE lalu `pg_restore --data-only`); perintahnya di checklist `AGENTS.md` (penyesuaian 21).

## 8. Pengujian (semua tanpa Postgres; fungsi murni + `db` tiruan seperti `test_export.py`)

| Area | Tes |
|---|---|
| `period.py` | `get_period_for_month` untuk payday 1, 25, 31 (Jan 31–Feb 27, Feb 28–Mar 30, Mar 31–Apr 29 di 2026); setara dengan `_resolve_period(year, month)` lama. `periods_to_cover` (penyesuaian 15): payday 1/15/25/29/30/31, hari pertama di periode berjalan (1) dan di periode tertutup terbaru (2), lintas tahun, sekitar Februari, contoh 25 → 1. |
| `household_cycle` | `pick_payday`; `can_change_payday` (owner, admin, member sendirian, member berdua, enum maupun string); `payday_context`; `recompute_history` serial per household dan memakai payday terbaru; `household_payday` mengisi NULL dari owner → admin → tertua; `set_household_payday` menulis household + semua anggota, no-op bila sama, memanggil `recompute_history(…, 12)` dan `advisor_cache.invalidate`, notifikasi ke anggota selain actor; `adopt_household_payday`; `heal` memperbaiki dan mencatat warning; `test_household_cycle_sole_writer`. |
| `rollover` | `snapshot_values`: `opening − allocated == prev_rollover`; rollover vs non-rollover; closing negatif → rollover 0 (non-rollover) atau defisit penuh (rollover); `create_monthly_snapshots` menyimpan dua kolom baru, meneruskan `is_rollover` tiap amplop, dan `force` mengganti baris kunci yang sama (mock session); `first_activity_date`; `recompute_household` diperpanjang sampai aktivitas pertama (maks 120, warning) dan membuang kunci periode berjalan sebelum membangun ulang (penyesuaian 15, 16). |
| `scheduler` | `household_runs` menghasilkan tepat satu jendela per household untuk household campuran (payday 1 dan 25), 3 periode tertutup. |
| rute | `PUT /user/profile`: owner → service dipanggil; member → 403 dan field lain tetap tersimpan; `GET /user/profile` field baru; `recompute` 403 untuk member, memakai payday household, izin dihitung untuk ruang tulis R2 (`hid`, dengan keanggotaan ruang keluarga tiruan yang berbeda; penyesuaian 23); profil tetap ruang keluarga walau header membuka ruang usaha; join ke ruang usaha ditolak tanpa adopsi (Plugin R2); `snapshots/run` per household, hanya periode tertutup, di dalam kunci dengan tanggal yang dibaca di dalam kunci, isolasi per household (penyesuaian 17); anggota terkunci yang mengulang tanggal rumah (penyesuaian 18); join dengan body tanpa kode (penyesuaian 19); `household/join` web mengadopsi payday dan response berisi `payday_day`. |
| bot | `cmd_join` memanggil `adopt_household_payday` dan pesannya menyebut tanggal. |
| skrip | `--dry-run` tidak menulis; household tanpa anggota dilewati; `--apply` memanggil heal + recompute per household dan notifikasi hanya untuk yang berubah; idempoten pada panggilan kedua; error per periode dijumlahkan dan membuat kode keluar 1 (penyesuaian 21). |
| frontend | `paydayLockState` (teks konfirmasi, penyesuaian 15), `onboardingProfileBody` (`needsConfirm`, penyesuaian 20), `nonRolloverWarning` (`node --test`); `npm run build`. |
| API | `python -m app.scripts.openapi_cek` → tidak ada yang memutus. |

Semua tes ditulis lebih dulu (TDD), per tugas di rencana implementasi.

## 9. Deploy & rollout (checklist di `AGENTS.md`, label PR `migrasi`)

1. Sebelum merge: cek pemilik `households` dan `monthly_snapshots` (query pemilik tabel di checklist Kotak Struk); bila bukan `jatahku`, `ALTER TABLE <tabel> OWNER TO jatahku` sebagai `postgres` sebelum merge (penyesuaian 22; menjalankan DDL sebagai `postgres` tidak bertahan, karena DDL `lifespan` butuh hak pemilik di setiap start).
2. Merge → deploy. Restart pertama menjalankan DDL + backfill di `lifespan`; API tetap 200 (kolom nullable, model menerima NULL). Run deploy boleh berakhir "Deploy GAGAL" karena `alembic current ≠ heads`.
3. `alembic upgrade head` (urutan "merge PR bermigrasi" di `AGENTS.md`), `alembic current` = revisi baru (`2d51b9031a6b`), restart, re-run job deploy yang gagal.
4. Pada hari yang sama dengan merge, sebelum job 00:05 berikutnya, di jam sepi yang tidak di sekitar 00:05 (penyesuaian 21): `python -m app.scripts.siklus_household --dry-run` → baca daftar campuran; cadangkan `monthly_snapshots`; lalu `--apply` (kode keluar 1 dengan "N error" = ada error per amplop, lihat log). Bila job 00:05 sudah jalan lebih dulu, `journalctl -u jatahku --since "<waktu deploy>" | grep menyimpang` mendaftar anggota yang harus diberi tahu manual. Owner diberi tahu bahwa saldo rollover household non-campuran bisa bergeser bila periode tertutupnya diubah setelah snapshot-nya dibuat.
5. Verifikasi: `GET /user/profile` dua anggota satu household → `household_payday_day` sama; esok harinya `journalctl -u jatahku | grep menyimpang` kosong; bila ada household campuran, dashboard anggota yang berubah dicek sisa amplopnya masuk akal.
6. Dokumentasi: `docs/siklus-household.md` (perilaku final, seperti `docs/kotak-struk.md`), satu baris di `CLAUDE.md` "Key Decisions" ("Siklus anggaran milik household: `households.payday_day`, `users.payday_day` cermin; penulis tunggal `services/household_cycle.py`"). Selesai (1 Nov 2026); checklist deploy di `AGENTS.md` bagian "Deploy Checklist — Siklus anggaran per household (2d51b9031a6b)".

## 10. Kompatibilitas dengan ruang usaha (rencana Buku Usaha, sesi lain)

`claude/buku-usaha-rencana-development.md` merencanakan tahap R1 (`households.type` = `rumah_tangga` | `usaha`, satu user boleh anggota beberapa household) dan tahap R2 (`ruang_aktif` menggantikan kueri keanggotaan di 31 file); tahap-tahap ruang usaha didefinisikan di `docs/plugin/03-workflow.md` (Fase 2 · Ruang usaha). Fase ini dirancang supaya cocok:
- `households.payday_day` berlaku **per ruang**: ruang usaha punya siklusnya sendiri, job snapshot (per household) langsung benar untuk ruang usaha.
- `users.payday_day` adalah cermin siklus **ruang keluarga** user. Sampai Plugin R1 tayang, setiap household adalah ruang keluarga. Saat Plugin R1 tayang, `set_household_payday` dan `heal` hanya mencerminkan ke `users.payday_day` untuk household `rumah_tangga`, dan `adopt_household_payday` hanya dipanggil saat bergabung ke ruang keluarga. **Plugin R1 sudah live** (masuk `main` sebelum fase ini selesai), jadi bagian ini **sudah diimplementasikan** di Task 8b rencana (penyesuaian 11): `mirrors_users(household)` memutuskan cermin, `membership` dan `payday_context` hanya ruang keluarga, `set_household_payday`/`heal` melewatkan cermin untuk ruang usaha, dan join web/bot hanya memanggil `adopt_household_payday` untuk ruang keluarga. Sejak penyesuaian 23 (Plugin R2) `payday_context` juga menerima `household_id` (recompute), dan join web/bot menolak undangan selain ruang keluarga sebelum perubahan apa pun.
- Setelah tahap R2 ruang usaha, call site sebaiknya membaca `ruang.payday_day` dari ruang aktif, bukan `user.payday_day`; cermin bisa dipensiunkan saat itu.
- Kueri keanggotaan di `household_cycle.py` lewat satu helper `membership(db, user)`; sejak Plugin R2 helper itu meneruskan ke `ruang.keanggotaan_keluarga` (penyesuaian 23).
- Revisi alembic fase ini kemungkinan tayang lebih dulu; Plugin R1 merevisi dari head yang ada saat itu. **Urutan sebenarnya terbalik:** Plugin R1 (`1c7e5a9d3b20`) dan Plugin B1 (`b1d4a7c2e9f0`) masuk `main` lebih dulu, dan revisi fase ini (`2d51b9031a6b`) merevisi dari head B1.

**Yang tersisa untuk rencana ruang usaha (tahap R2/R4/R5 di `docs/plugin/03-workflow.md`, Fase 2 · Ruang usaha)** — catatan serah-terima dari Task 8b, juga di `docs/siklus-household.md`, dengan tahap tempat tiap butir dikerjakan. **Plugin R2 (#166) sudah di `main`** dan fase ini digabung di atasnya (penyesuaian 23):
- **R2 (selesai):** kueri keanggotaan per `user_id` saja di `join_household`, `POST /household/invite`, `GET /household/`, `/household/members`, `/household/leaderboard`, `cmd_join`, dan `cmd_invite` diganti resolver ruang (`app/services/ruang.py`); `membership` meneruskan ke `ruang.keanggotaan_keluarga`; `POST /snapshots/recompute` memakai ruang tulis R2 dengan izin untuk household itu; profil tetap ruang keluarga.
- **Terbuka sesudah R2 (sebelum ruang usaha bisa dibuka di R4):** jendela periode (ringkasan amplop, analitik, export) masih dihitung dari `user.payday_day`, cermin ruang keluarga, juga saat header `X-Jatahku-Ruang` membuka ruang lain; bacalah `households.payday_day` ruang aktif. Laten hari ini (belum ada klien yang mengirim header, belum ada ruang usaha).
- **R4:** pembuatan ruang usaha harus mengisi `households.payday_day` secara eksplisit: NULL diturunkan dari anggota (`household_payday`, `current_payday`, `pick_payday`) memakai `users.payday_day` mereka, yaitu siklus ruang keluarga.
- **R4:** mengubah tanggal ruang usaha butuh pintu masuk sendiri (`PUT /user/profile` dan `payday_context` tanpa `household_id` hanya menjangkau ruang keluarga; `POST /snapshots/recompute` mengikuti ruang tulis R2, sampai R3 ruang keluarga); `set_household_payday` dan `recompute_history` sudah bekerja untuk ruang usaha, izin diputuskan pemanggil.
- **R5:** bergabung ke ruang usaha. Hari ini join web dan `cmd_join` menolak undangan selain ruang keluarga sebelum perubahan apa pun (Plugin R2), dan pindah ruang keluarga hanya menghapus keanggotaan ruang keluarga lama. Jalur undangan ruang usaha tidak boleh memanggil `adopt_household_payday` (fungsinya tidak memeriksa tipe; pakai `household_payday`) dan tidak boleh menghapus keanggotaan ruang keluarga user. Judul dan pesan notifikasi perubahan siklus menyebut "rumah" dan juga terkirim untuk ruang usaha.

## Di luar cakupan

- Desain laporan berkala (PDF, email berpassword, halaman analitik, notifikasi rilis) — spec berikutnya. Yang bisa diasumsikan spec itu dari fase ini: satu jendela per household, `get_period_for_month`, snapshot berisi `allocated_amount`/`spent_amount`, `recompute_household`.
- `get_report_period` / agregasi N periode.
- Mengubah tanggal "hari ini" job (`date.today()` server) ke zona waktu user.
- Endpoint keluar/keluarkan anggota household (belum ada); household lama yang yatim saat join (perilaku lama).
- Perbaikan `payday_day` lewat admin panel (admin hanya membaca).

## Risiko & mitigasi

- **Jendela nilai salah saat migrasi.** Dihindari dengan kolom NULL + backfill dalam DDL startup, sebelum job pertama berjalan.
- **Jalur baru lupa memakai service** → invarian bocor. Mitigasi: tes penulis tunggal + `heal` harian; akibat terburuk satu hari penyimpangan, bukan rantai rollover rusak.
- **Owner mengganti payday berulang** memicu recompute seluruh riwayat (minimal 12 periode; penyesuaian 15) tiap kali. Skala sekarang (29 user) hitungan detik; bila nanti membesar, pindahkan ke tugas latar (`asyncio.create_task`). Recompute bersamaan untuk satu household diserialkan dan selalu memakai payday terbaru (penyesuaian 2), jadi hasil akhir mengikuti perubahan terakhir.
- **Recompute gagal setelah tanggal tersimpan** (penyesuaian 9): riwayat bisa tertinggal separuh jadi, dan mengulang tanggal yang sama tidak memperbaikinya (no-op). Mitigasi: perubahan tidak dibatalkan dan request tidak jadi 500, kegagalan dicatat `logger.exception`, notifikasi tidak mengklaim riwayat dihitung ulang, dan pemulihannya dijalankan operator lewat skrip `--apply` atau `POST /snapshots/recompute`.
- **Riwayat anggota berubah** saat payday household berubah atau saat migrasi: itu memang konsekuensi keputusan #7, dan dikomunikasikan lewat notifikasi.
- **Konflik dengan sesi pengembangan lain:** perubahan dijaga lokal; `models.py`, `main.py` hanya baris aditif; `AGENTS.md` hanya tambah satu bagian; revisi alembic dibuat terakhir; rebase sebelum PR.

## Dampak ke rencana lain

- **Mobile (AGENTS.md "API hanya bertambah"):** semua field/endpoint lama tetap; 403 baru di `PUT /user/profile` dan `POST /snapshots/recompute` hanya untuk kombinasi yang UI tidak pernah kirim. Satu pengecualian disengaja: kunci tingkat atas `period` di respons `POST /snapshots/run` (admin, tanpa pemanggil) dihapus (penyesuaian 13). Dicatat di `docs/mobile` paritas bila aplikasi sudah terpasang saat fase ini tayang.
- **AI Advisor v2:** tidak ada perubahan angka; `advisor_cache.invalidate(hid)` dipanggil saat payday berubah.
- **Kotak Struk:** `document_date_kind` memakai `user.payday_day` (cermin) — tidak berubah.
