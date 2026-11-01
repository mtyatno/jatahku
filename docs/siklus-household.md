# Siklus anggaran per household

Satu household = satu siklus anggaran (tanggal gajian, 1–31). Owner yang menentukannya, anggota lain mengikuti.
Sumber kebenarannya kolom `households.payday_day`; `users.payday_day` tetap ada sebagai **cermin** untuk ruang
keluarga, supaya ±25 call site yang membaca `user.payday_day` (dashboard, analitik, export, advisor, langganan,
tanggal struk) tidak berubah. Setiap snapshot `monthly_snapshots` dihitung dengan jendela household-nya dan menyimpan
alokasi serta pengeluaran periode itu, jadi laporan berkala (spec berikutnya) bisa membacanya tanpa menghitung ulang
riwayat. Desain dan keputusan produk: `docs/superpowers/specs/2026-10-31-siklus-household-design.md`; rencana:
`docs/superpowers/plans/2026-10-31-siklus-household.md`. Catatan "(penyesuaian N)" di bawah menunjuk butir N di
bagian "Penyesuaian saat implementasi" spec itu, yang memuat alasan tiap perubahan dari desain awal.

**Status (1 Nov 2026).** Selesai di kode di branch `feat/siklus-household` (dasar `main` 75610ed, Plugin B1); PR
berlabel `migrasi` menunggu merge; revisi alembic `2d51b9031a6b`. Tanpa saklar fitur: begitu tayang, setiap household
memakai satu siklus. Langkah merge dan migrasi data ada di `AGENTS.md`, "Deploy Checklist — Siklus anggaran per
household (2d51b9031a6b)". Perbarui bagian ini saat status berubah.

## Model data

| Kolom | Arti |
|---|---|
| `households.payday_day` INTEGER NULL | Tanggal gajian rumah. NULL = belum dimigrasi: diturunkan dari anggota saat pertama dibaca (owner, lalu admin, lalu yang tertua; tanpa anggota 1). Sengaja tanpa DEFAULT: `DEFAULT 1` membuat rumah yang owner-nya gajian tanggal 25 terbaca 1 sampai migrasi data jalan. |
| `users.payday_day` | Cermin siklus ruang keluarga user (tidak NULL). Dibaca ±25 call site; hanya `household_cycle` yang menulisnya. |
| `monthly_snapshots.allocated_amount`, `spent_amount` NUMERIC(15,2) NULL | Alokasi dan pengeluaran periode itu, ditulis `create_monthly_snapshots` (juga saat `force`). NULL = snapshot lama yang belum dihitung ulang, bukan nol. |

**Pemasangan** (dua jalur, idempoten, pola Kotak Struk): `lifespan` (`app/main.py`) menjalankan `HOUSEHOLD_CYCLE_DDL`
(`app/services/household_cycle_schema.py`: tiga `ADD COLUMN IF NOT EXISTS` dan satu backfill yang hanya menyentuh
household bernilai NULL, urutan owner → admin → anggota tertua, sama dengan `pick_payday`), dan revisi `2d51b9031a6b`
menjalankan daftar yang sama. Urutan restart dan `alembic upgrade` bebas; household tanpa anggota tetap NULL.
`downgrade` membuang tiga kolom (`IF EXISTS`, tanpa `DROP TYPE`) dan hanya bermakna bersama kode lama, karena kode ini
menambahkannya lagi saat API restart. Diuji di PostgreSQL 16 asli (1 Nov 2026): `.github/scripts/cek-migrasi.sh` (naik,
`alembic check`, turun, naik) dan backfill berdata, dalam urutan lifespan-dulu maupun alembic-dulu.

**Snapshot.** Key `(envelope_id, year, month)` = bulan AWAL periode. `rollover.snapshot_values(prev_rollover,
allocated, spent, is_rollover)` murni: `opening = allocated + prev_rollover`, `closing = opening − spent`, `rollover =
closing` (positif maupun negatif) bila amplop `is_rollover`, selain itu 0 (sisa maupun defisit di-reset). Snapshot hanya
ada untuk periode TERTUTUP (lihat "Recompute dan kunci").

## Penulis tunggal: `app/services/household_cycle.py`

Atribut `payday_day` (user maupun household) hanya di-assign di modul ini, dan SQL `SET payday_day` hanya di
`household_cycle_schema.py`. Jalur lain membaca lewat `household_payday` / `payday_context` dan mengubah lewat
service, supaya cermin tidak menyimpang. Dikunci `test_household_cycle_sole_writer`, yang memindai `app/**/*.py` selain
tes dengan `\.payday_day\s*=(?!=)` dan `(?i)\bset\s+payday_day` (argumen kata kunci dan deklarasi kolom tidak ikut);
`setattr`, `+=`, `.values(payday_day=…)`, dan SET multi-kolom tidak tertangkap, jadi tetap ditinjau manual.

| Fungsi | Tugas |
|---|---|
| `household_payday(db, household, rows=None)` | Tanggal rumah. Terisi → apa adanya; NULL → `pick_payday(rows)` ditulis ke `household.payday_day` dan `flush` (tidak commit; boleh dari GET, nilai di respons benar walau sesinya tidak di-commit). |
| `pick_payday(rows: Sequence[MemberRow])` | Murni. Owner, lalu admin, lalu yang lain; sesama peran `created_at` tertua; tanggal kosong → 1; tanpa anggota → 1. |
| `can_change_payday(role, member_count)` | Owner/admin → ya; member → ya hanya bila `member_count == 1`. Peran enum atau string (`str(getattr(role, "value", role))`). |
| `mirrors_users(household)` | Murni. Hanya ruang keluarga (`type` `rumah_tangga`; `type` kosong dihitung ruang keluarga) dicerminkan ke `users.payday_day`. |
| `membership(db, user)` | Satu-satunya kueri keanggotaan di modul ini: ruang keluarga user saja. Plugin R1 mengizinkan satu user di beberapa household, jadi keanggotaan ruang usaha tidak ikut terpilih dan `scalar_one_or_none` tidak melempar. |
| `payday_context(db, user)` | `PaydayContext(household, role, payday_day, member_count, can_change, owner_name)` atau None (tanpa ruang keluarga). Satu titik baca untuk profil, recompute, dan household; `owner_name` None bila pemanggil sendiri owner-nya. |
| `adopt_household_payday(db, user, household)` | `user.payday_day = household_payday(...)`. Dipanggil join web dan bot sebelum commit keanggotaan; pemanggil menjaganya dengan `mirrors_users`. Tidak commit. |
| `heal(db, household)` | Samakan `users.payday_day` anggota yang menyimpang dari household. Ruang usaha dan household bertanggal NULL dilewati. Mencatat warning `payday anggota <id> menyimpang (a → b)`, commit hanya bila ada yang berubah, mengembalikan user yang diperbaiki. Tidak menghitung ulang riwayat. |
| `set_household_payday(db, household, day, *, actor)` | Ubah tanggal (bagian "Mengubah tanggal"). |
| `household_lock`, `current_payday`, `recompute_history` | Bagian "Recompute dan kunci". |
| `notify_payday_changed(users, ...)` | Notifikasi perubahan siklus (bagian "Mengubah tanggal", dan skrip migrasi). |

**Kontrak commit.** Fungsi yang menerima `db` tidak commit; pemanggil yang commit (pola repo). Pengecualian: `heal`, dan
`set_household_payday` (commit sebelum recompute). `current_payday`, dan karenanya `recompute_history` serta job harian,
membaca lewat sesi sendiri yang HANYA-BACA (penyesuaian 6). Pemanggil yang baru mengubah atau mengisi
`households.payday_day` di sesinya harus **commit lebih dulu**; route `recompute`, `/snapshots/run`, skrip `--apply`,
tahap pertama job, dan `set_household_payday` melakukannya. Menulis lewat koneksi kedua bisa menunggu selamanya pada baris
household yang dikunci transaksi pemanggil.

## Siapa yang boleh mengubah

| Peran di rumah | Anggota | Boleh mengubah tanggal dan menghitung ulang riwayat |
|---|---|---|
| owner, admin | berapa pun | ya |
| member | 1 (sendirian) | ya |
| member | lebih dari 1 | tidak: 403, UI hanya membaca |

Di `PUT /user/profile` cek ini dilakukan paling awal, sebelum field apa pun diubah, jadi 400/403 tidak menyimpan
apa-apa.

## Bergabung

Join web (`POST /household/join`), bot Telegram (`/join`), dan chat web (handler yang sama) memanggil
`adopt_household_payday` SEBELUM commit keanggotaan baru, dalam satu transaksi: anggota baru tidak pernah "sudah
anggota tapi masih siklus lama". Tidak ada yang dihitung ulang; amplop dan transaksi lama anggota tinggal di household
lamanya. Respons web membawa `payday_day`, dan Settings menampilkan "Berhasil bergabung ke {rumah}! Siklus anggaranmu
sekarang mengikuti rumah ini: tanggal {N}."; bot menambah baris "Siklus anggaranmu sekarang mengikuti rumah ini: tanggal
{N}." Ruang usaha tidak diadopsi (web: respons membawa tanggal ruang itu; bot: tanpa baris siklus). Route web menerima
kode dari query `?code=` atau body JSON `{"code": …}` (query didahulukan, `strip().upper()`, kosong → 400 "Kode invite
wajib diisi"); sebelumnya join dari Settings selalu 422 karena kodenya dikirim di body.

## Mengubah tanggal

`PUT /user/profile {"payday_day": N}` → `set_household_payday(db, household, day, *, actor)`:

1. `day` di luar 1–31 → `ValueError` (route: 400). Sama dengan tanggal sekarang → `{"changed": False}`, tanpa
   recompute dan tanpa notifikasi.
2. `household.payday_day = day` dan, untuk ruang keluarga, `users.payday_day` semua anggota: satu transaksi, commit.
3. `advisor_cache.invalidate(household.id)`.
4. `recompute_history(household.id, 12)` (`RECOMPUTE_PERIODS_ON_CHANGE`): 12 periode tertutup terakhir dihitung ulang.
5. Notifikasi ke setiap anggota selain pelaku (`notification_service.kirim`, `NotificationType.system`,
   `link="/settings"`, lonceng web dan Telegram bila tertaut, tanpa email). Judul "Siklus anggaran rumah berubah",
   pesan "Tanggal gajian {rumah} kini tanggal {N} (diubah {nama pelaku}). Riwayat 12 periode terakhir dihitung ulang."
   Judul dan pesan tidak dikirim sebagai `telegram_html`: `kirim` yang meng-escape untuk Telegram, jadi nama rumah atau
   orang berisi `<` atau `&` aman. Tiap kirim dibungkus tersendiri: yang gagal dicatat dan tidak menghentikan yang lain,
   apalagi membatalkan perubahan.
6. Hasil `{"changed": True, "members": n, "recomputed": k}`.

**Recompute yang gagal** (exception; penyesuaian 9): perubahan yang sudah di-commit tetap, dicatat dengan
`logger.exception`, hasilnya `recomputed: 0`, dan notifikasi tetap terkirim tanpa kalimat riwayat ("Tanggal gajian
{rumah} kini tanggal {N} (diubah {nama pelaku}).") supaya tidak mengklaim yang tidak terjadi. Request tidak menjadi 500
yang tak bisa diulang, tetapi mengulang tanggal yang sama juga tidak memperbaikinya (no-op): lihat "Pemulihan". Error per
amplop di dalam satu periode hanya dicatat `logger.error` (penyesuaian 9) dan periodenya tetap terhitung ter-recompute.

Setelah `set_household_payday`, `update_profile` selalu `commit` (penyesuaian 14): service tidak commit pada tanggal yang
sama, padahal field lain (mis. `income_type` dari Onboarding, yang mengirim `payday_day` berdampingan) sudah di-assign
di sesi itu.

## Recompute dan kunci

- **`household_lock(household_id)`**: satu `asyncio.Lock` per household, dipegang semua penulis kunci snapshot
  `(envelope_id, year, month)` di proses ini: `recompute_history` dan job harian. Kunci dalam proses cukup karena API
  berjalan sebagai satu proses uvicorn dengan scheduler di dalamnya. Tidak re-entrant. Dict kuncinya tumbuh satu entri
  per household (kecil, dibiarkan).
- **`current_payday(household_id) -> int | None`**: tanggal terbaru di DB lewat sesi sendiri, hanya-baca. NULL →
  `pick_payday(member_rows)` tanpa menulis; household yang sudah dihapus (merge, hapus akun) → None.
- **`recompute_history(household_id, periods)`**: `async with household_lock`, baca `current_payday` DI DALAM kunci,
  lalu `rollover.recompute_household(...)`. Dua perubahan beruntun (mengetik "2" lalu "25") jadi berurutan: yang kedua
  menunggu yang pertama lalu memakai tanggal tersimpan terbaru, jadi hasil akhir mengikuti perubahan terakhir. Household
  yang sudah tidak ada → `[]` dan satu warning, bukan error.
- **`rollover.recompute_household(household_id, payday_day, periods, today=None)`**: `get_closed_periods(payday_day,
  today, periods)` oldest-first, tiap periode `create_monthly_snapshots(ps, pe, force=True, household_ids=[hid])`
  supaya rantai rollover terbangun ulang berurutan. Lalu (penyesuaian 8) membuang snapshot household itu pada kunci periode
  BERJALAN dan sesudahnya menurut `payday_day`: snapshot hanya boleh ada untuk periode tertutup. Contoh: gajian 1 → 25
  pada 10 Nov 2026. Kunci 2026-10 ditulis job 1 Nov dengan angka 1–31 Okt, padahal di bawah tanggal 25 itu periode
  berjalan 25 Okt–24 Nov; dibiarkan, job 25 Nov melewatinya (sudah ada) dan rollover yang salah terbawa terus. Dibuang,
  job membuatnya lagi dengan benar saat periodenya tutup. Deterministik, aman diulang.

## Job harian

`scheduler.payday_snapshot_job` (00:05 waktu server, `CATCH_UP_PERIODS = 3`) beriterasi **household**, bukan grup
user: satu household satu jendela, household campuran tidak lagi diproses sekali per tanggal. Dua tahap:

1. Satu sesi: untuk tiap household yang punya anggota (yang kosong dilewati), `household_payday` (mengisi NULL) lalu
   `heal`, lalu commit dan sesi ditutup: `create_monthly_snapshots` memakai sesinya sendiri dan tidak boleh berhadapan
   dengan UPDATE yang belum di-commit.
2. Per household di dalam `household_lock`: tanggal DIBACA ULANG (`current_payday`, penyesuaian 7) dan jendela dibangun
   darinya, bukan dari tahap pertama. Pemilik bisa mengubah tanggal selagi job mengerjakan household lain, dan
   recompute-nya lalu membuang kunci periode berjalan menurut tanggal baru; jendela basi akan menulis kunci itu lagi
   dengan angka periode lama, dan job tanpa `force` tidak pernah menimpanya. Household yang sudah dihapus dilewati dengan
   warning. Jendela dari fungsi murni `household_runs(rows, today, catch_up)`; tiap periode tertutup oldest-first
   `create_monthly_snapshots(ps, pe, household_ids=[hid])` tanpa `force` (yang sudah ada tidak disentuh).

Penyimpangan cermin muncul di log sebagai `payday anggota <id> menyimpang (a → b)` (`journalctl -u jatahku | grep
menyimpang`); setelah migrasi data seharusnya kosong.

## Skrip migrasi data

`app/scripts/siklus_household.py`, dijalankan operator di VPS sesudah deploy dan `alembic upgrade head`:

```bash
cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.siklus_household            # sama dengan --dry-run
cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.siklus_household --apply    # [--periods 12]
```

- **`--dry-run`** (bawaan): satu baris per household yang punya anggota: id, nama, jumlah anggota, payday tiap anggota,
  `target` (payday yang akan dipakai), dan `CAMPURAN` bila anggota ruang keluarga berbeda payday. Ruang usaha ditandai
  `[usaha]` dan tidak pernah CAMPURAN. Tidak menulis apa pun.
- **`--apply`**, per household, urutan (penyesuaian 10): `household_payday` (mengisi NULL) → commit → `recompute_history(hid,
  periods)` untuk SEMUA household (mengisi `allocated_amount`/`spent_amount`; household tidak campuran menghasilkan angka
  identik) → `heal` → notifikasi ke anggota yang payday-nya berubah, tanpa pelaku: "Siklus anggaranmu kini mengikuti
  {rumah}: tanggal {N}. Riwayat {periods} periode terakhir dihitung ulang." `heal` sengaja sesudah recompute: recompute
  hanya membaca `households.payday_day` (sudah tersimpan), tidak pernah cermin anggota, jadi recompute yang gagal
  meninggalkan anggota belum disamakan dan run ulang menemukan serta memberi tahu mereka.
- **Idempoten**: run kedua tidak menemukan anggota yang berubah, jadi tidak ada notifikasi kedua. Kegagalan (database,
  recompute) tidak ditangkap: traceback dan kode keluar 1; household yang sudah diproses tersimpan, dan run yang gagal
  cukup diulang. Keluaran akhir: "Selesai: N household diproses (K campuran), S snapshot ditulis, M anggota diberi tahu."
- **Jam sepi, bukan sekitar 00:05.** Skrip berjalan di proses terpisah, jadi `household_lock` tidak menyerialkannya dengan
  API maupun job harian, padahal recompute dan job menulis kunci unik `(envelope_id, year, month)` yang sama.

## API

Aditif: field dan endpoint lama tidak berubah artinya (`python -m app.scripts.openapi_cek` bersih). Satu-satunya perilaku
baru yang menolak adalah 403 di `PUT /user/profile` dan `POST /snapshots/recompute`, dan UI tidak pernah memicunya.

- **`GET /user/profile`** +: `household_payday_day`, `payday_locked`, `payday_owner_name` (null bila pemanggil owner-nya),
  `household_name`, `household_member_count`. Tanpa ruang keluarga: `household_payday_day = payday_day`, `payday_locked =
  false`, dua nama null, `household_member_count = 1`. `payday_day` tetap = cermin.
- **`PUT /user/profile`** dengan `payday_day`: 400 "Belum punya household"; 400 "payday_day harus antara 1 dan 31"; 403
  "Tanggal gajian mengikuti rumah tangga ({rumah}, tanggal {N}). Minta owner yang mengubahnya." Semuanya sebelum field apa
  pun diubah.
- **`GET /household/`** + `payday_day`. **`POST /household/join`** + `payday_day`, kode di query atau body.
- **`POST /snapshots/recompute?periods=6`** (default 6, maks 36): tanpa ruang keluarga `{"recomputed": 0, "periods": []}`;
  bukan yang boleh mengubah → 403 "Hanya owner atau admin rumah tangga yang bisa menghitung ulang riwayat."; selain itu
  `recompute_history` dengan tanggal RUMAH (bukan `user.payday_day`).
- **`POST /snapshots/run?year&month&force`** (admin): per household, `get_period_for_month(household_payday, year, month)`
  lalu `create_monthly_snapshots(..., household_ids=[hid], force=force)`. Respons `{"households": [{"household_id",
  "period", ...hasil}], "processed", "snapshots_created", "errors"}`. **Pengecualian disengaja** dari "API hanya
  bertambah": kunci tingkat atas `period` dihapus karena periode kini per household; endpoint ini khusus admin dan tidak
  punya pemanggil (web, bot, maupun mobile).
- `export._resolve_period` (cabang tahun + bulan) memakai `core.period.get_period_for_month`; hasilnya identik dengan
  rumus lama (dikunci tes kesetaraan).

## Web

Keputusan tampilan ada di modul murni `frontend/src/lib/` yang diuji `node --test`; komponen JSX hanya merender.

- **Settings**, kartu "Tanggal Gajian" (`paydayLock.js`: `paydayLockState`, `householdPayday`, `parsePaydayDay`,
  `joinSuccessMessage`, `PAYDAY_SAVE_DELAY_MS = 600`):
  - `payday_locked` → teks read-only "Mengikuti siklus rumah tangga: tanggal {N} (diatur {nama owner})." (tanpa nama
    owner: tanpa kurung), dan `payday_day` tidak pernah dikirim.
  - Owner/admin household lebih dari satu anggota → input tidak menyimpan saat diketik; tombol Simpan membuka dialog
    in-app (`PaydayConfirmDialog`, bukan `window.confirm`): "Mengubah tanggal gajian berlaku untuk semua anggota {rumah},
    dan 12 periode terakhir dihitung ulang. Lanjutkan?"
  - Household sendirian → simpan saat berubah, ditunda 600 ms (debounce) supaya mengetik "25" tidak menyimpan "2" dulu;
    simpan tertunda dibuang bila halaman ditinggalkan. Setelah simpan, juga yang ditolak, profil dimuat ulang.
- **Onboarding** (penyesuaian 14): profil dibaca dulu; anggota yang tanggalnya terkunci hanya mengirim `income_type`
  (`onboardingProfileBody`), karena PUT yang membawa `payday_day` ditolak 403 dan `income_type` ikut hilang.
- **Alokasi** (`nonRolloverWarning.js`): baris amplop dengan `is_rollover === false`, nilai alokasi > 0, dan periode
  berjalan berakhir dalam 7 hari atau kurang (`period_end` = periode terakhir `GET /analytics/periods`, dibandingkan
  dengan tanggal lokal browser) menampilkan "Amplop ini tidak membawa sisa ke periode berikutnya. Yang tidak terpakai
  di-reset {tgl} ({n} hari lagi)." (`{tgl}` = "{hari} {Jan Feb Mar Apr Mei Jun Jul Agu Sep Okt Nov Des}"; di hari
  terakhir: "(hari ini)"). Hanya web: alokasi tidak pernah lewat bot.

## Pemulihan

- **Riwayat basi** (recompute gagal setelah tanggal tersimpan, penyesuaian 9, atau kunci snapshot dicurigai): operator
  menjalankan skrip `--apply` (semua household), atau owner/admin rumah itu memanggil `POST /snapshots/recompute?periods=12`.
  Admin aplikasi juga bisa membangun ulang satu bulan lewat `POST /snapshots/run?year=&month=&force=true`.
- **Rollback kode lalu deploy ulang**: perubahan `users.payday_day` yang dibuat kode lama di antaranya akan dikembalikan
  `heal` ke tanggal household. Bila yang diinginkan nilai user, jalankan `UPDATE households SET payday_day = NULL` sebelum
  restart: backfill `lifespan` menurunkannya lagi dari owner.

## Catatan untuk rencana ruang usaha (R2/R4/R5)

Plugin R1 sudah di `main` (`households.type`, satu user boleh di beberapa household), dan fase ini sudah mengikutinya:
`mirrors_users` membatasi cermin ke ruang keluarga, `membership` hanya ruang keluarga, `set_household_payday` dan `heal`
tidak menyentuh `users.payday_day` untuk ruang usaha, dan job harian serta `/snapshots/run` sudah benar per household.
Yang masih harus dikerjakan rencana ruang usaha:

- **Kueri keanggotaan per `user_id` saja** masih ada di `join_household` (web, `_get_membership`), `POST /household/invite`,
  `GET /household/`, `/household/members`, `/household/leaderboard`, serta `cmd_join` dan `cmd_invite` di bot.
  `scalar_one_or_none` melempar `MultipleResultsFound` begitu user ada di dua ruang, dan join ke ruang usaha akan
  menghapus keanggotaan ruang keluarganya (jalur "keanggotaan lama" di join web dan `cmd_join`). Ganti dengan resolver
  ruang (R2) sebelum ruang usaha bisa diikuti.
- **Pembuatan ruang usaha harus mengisi `households.payday_day` secara eksplisit.** NULL diturunkan dari anggota
  (`household_payday`, `current_payday`, `pick_payday`) memakai `users.payday_day` mereka, yaitu siklus ruang KELUARGA
  mereka, bukan siklus usaha.
- **`adopt_household_payday` tidak menjaga tipe household**; pemanggil yang menjaganya lewat `mirrors_users` (join web
  dan `cmd_join`). Jalur baru yang memasukkan user ke ruang usaha tidak boleh memanggilnya (pakai `household_payday`).
- **Judul dan pesan notifikasi** ("Siklus anggaran rumah berubah", "Tanggal gajian {rumah} kini tanggal …") juga terkirim
  untuk ruang usaha, karena `set_household_payday` memberi tahu semua anggota ruang itu; ganti kata "rumah" per tipe bila perlu.
- **Mengubah tanggal ruang usaha** butuh pintu masuk sendiri: `payday_context` dan `POST /snapshots/recompute` hanya
  menjangkau ruang keluarga. `set_household_payday` dan `recompute_history` sudah bekerja untuk ruang usaha (tanpa cermin
  ke user), tetapi izin (`can_change_payday`) diputuskan pemanggil.
- Setelah R2, call site membaca `ruang.payday_day` dari ruang aktif dan cermin `users.payday_day` bisa dipensiunkan.

## Batasan yang diketahui

- **Kunci hanya dalam proses.** Skrip migrasi berjalan di proses lain. `POST /snapshots/run` (admin) juga tidak memegang
  `household_lock` dan tidak membaca tanggal di dalam kunci, padahal `force=true` menimpa kunci yang sama: pakai di jam
  sepi.
- **`heal` membandingkan dengan objek household yang dibaca lebih awal** (job: tahap pertama; skrip: saat survei). Bila owner
  meng-commit perubahan tanggal di antaranya, cermin anggota bisa dikembalikan ke tanggal lama sampai job berikutnya;
  `households.payday_day` sendiri tidak terpengaruh.
- **Job tidak mengisolasi kegagalan per household**: exception di satu household menghentikan sisanya hari itu (dicatat
  APScheduler); job besoknya mengejar (`CATCH_UP_PERIODS`).
- **Error per amplop** di dalam recompute tetap menghitung periodenya sebagai ter-recompute (`recomputed`, kalimat "dihitung
  ulang"); yang menandainya hanya log `jatahku.household_cycle` ("punya error") dan daftar `errors` di respons route.
- **Onboarding untuk owner/admin household lebih dari satu anggota** tetap mengirim `payday_day` tanpa konfirmasi; income
  harian/mingguan mengirim tanggal 1 dan mereset siklus seluruh rumah. Onboarding hanya tampil untuk user baru, jadi jarang.
  Perbaikan: lewati `payday_day` bila `locked || needsConfirm`.
- **Join web**: body `{}` atau `{"code": null}` → 422 (field `code` wajib di `JoinRequest`); tanpa query dan tanpa body → 400.

## Berkas dan tes

- Backend: `app/services/household_cycle.py`, `household_cycle_schema.py`, `rollover.py` (`snapshot_values`,
  `create_monthly_snapshots`, `recompute_household`), `scheduler.py` (`household_runs`, `payday_snapshot_job`),
  `app/core/period.py` (`get_period_for_month`), `api/routes/user_settings.py`, `household.py`, `snapshots.py`,
  `bot/household_cmd.py`, `scripts/siklus_household.py`, `alembic/versions/2d51b9031a6b_siklus_household.py`.
- Frontend: `src/lib/paydayLock.js`, `nonRolloverWarning.js`, `src/pages/Settings.jsx`, `Allocate.jsx`,
  `src/components/Onboarding.jsx`.
- Tes backend (`app/tests/`, tanpa PostgreSQL): `test_household_cycle.py`, `test_household_cycle_change.py`,
  `test_household_cycle_r1.py`, `test_household_cycle_schema.py`, `test_household_cycle_sole_writer.py`,
  `test_household_join_payday.py`, `test_profile_payday.py`, `test_snapshots_household.py`,
  `test_scheduler_household_runs.py`, `test_rollover_snapshot_values.py`, `test_period_for_month.py`,
  `test_siklus_household_script.py`. Frontend: `paydayLock.test.js`, `nonRolloverWarning.test.js`.
  Perintah: `DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python3 -m unittest
  discover -s app/tests -t .` dan `cd frontend && node --test src/lib/*.test.js src/native/*.test.js`.
