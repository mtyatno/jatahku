# Siklus anggaran per household

Satu household = satu siklus anggaran (tanggal gajian, 1–31). Owner yang menentukannya, anggota lain mengikuti.
Sumber kebenarannya kolom `households.payday_day`; `users.payday_day` tetap ada sebagai **cermin** untuk ruang
keluarga, supaya ±25 call site yang membaca `user.payday_day` (dashboard, analitik, export, advisor, langganan,
tanggal struk) tidak berubah. Setiap snapshot `monthly_snapshots` dihitung dengan jendela household-nya dan menyimpan
alokasi serta pengeluaran periode itu, jadi laporan berkala (spec berikutnya) bisa membacanya tanpa menghitung ulang
riwayat. Desain dan keputusan produk: `docs/superpowers/specs/2026-10-31-siklus-household-design.md`; rencana:
`docs/superpowers/plans/2026-10-31-siklus-household.md`. Catatan "(penyesuaian N)" di bawah menunjuk butir N di
bagian "Penyesuaian saat implementasi" spec itu, yang memuat alasan tiap perubahan dari desain awal.

**Status (1 Nov 2026).** Selesai di kode di branch `feat/siklus-household`, di atas main setelah Plugin R2 (#166) dan B3
(#167/#168); PR berlabel `migrasi` menunggu merge; revisi alembic `2d51b9031a6b`. Tanpa saklar fitur: begitu tayang, setiap household
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
| `membership(db, user)` | Keanggotaan ruang keluarga user: diteruskan ke `ruang.keanggotaan_keluarga` (resolver Plugin R2), tanpa kueri sendiri, jadi seluruh aplikasi memakai satu definisi. Keanggotaan ruang usaha tidak ikut terpilih; dua ruang keluarga (tidak semestinya) → yang tertua, tanpa galat (penyesuaian 23). |
| `payday_context(db, user, *, household_id=None)` | `PaydayContext(household, role, payday_day, member_count, can_change, owner_name)` atau None (bukan anggota). Tanpa `household_id`: ruang keluarga (`membership`), dipakai route profil. Dengan `household_id`: keanggotaan di household itu (`ruang.keanggotaan`), dipakai `POST /snapshots/recompute` untuk ruang tulis R2 (penyesuaian 23). `GET /household/` memakai `_get_membership` + `household_payday`. `owner_name` None bila pemanggil sendiri owner-nya. |
| `adopt_household_payday(db, user, household)` | `user.payday_day = household_payday(...)`. Dipanggil join web dan bot sebelum commit keanggotaan; keduanya hanya menerima undangan ruang keluarga (Plugin R2), dan fungsinya sendiri tidak memeriksa tipe. Tidak commit. |
| `heal(db, household)` | Samakan `users.payday_day` anggota yang menyimpang dari household. Ruang usaha dan household bertanggal NULL dilewati. Mencatat warning `payday anggota <id> menyimpang (a → b)`, commit hanya bila ada yang berubah, mengembalikan user yang diperbaiki. Tidak menghitung ulang riwayat. |
| `set_household_payday(db, household, day, *, actor)` | Ubah tanggal (bagian "Mengubah tanggal"). |
| `household_lock`, `current_payday`, `recompute_history` | Bagian "Recompute dan kunci". |
| `notify_payday_changed(users, ...)` | Notifikasi perubahan siklus (bagian "Mengubah tanggal", dan skrip migrasi). |

**Kontrak commit.** Fungsi yang menerima `db` tidak commit; pemanggil yang commit (pola repo). Pengecualian: `heal`, dan
`set_household_payday` (commit sebelum recompute). `current_payday`, dan karenanya `recompute_history` serta job harian,
membaca tanggal lewat sesi sendiri yang HANYA-BACA (penyesuaian 6); recompute sendiri menulis lewat sesinya sendiri dan
commit di sana (`rollover.recompute_household`, `create_monthly_snapshots`). Pemanggil yang baru mengubah atau mengisi
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
apa-apa. Member terkunci yang mengirim tanggal yang SAMA dengan tanggal rumah tidak mengubah apa pun: `payday_day`
diabaikan tanpa 403 dan tanpa service, field lain tersimpan (klien lama atau ber-cache, mis. Onboarding lama yang
mengirim `payday_day` bersama `income_type`; penyesuaian 18). Tanggal yang berbeda tetap 403.

## Bergabung

Join web (`POST /household/join`), bot Telegram (`/join`), dan chat web (handler yang sama) memanggil
`adopt_household_payday` SEBELUM commit keanggotaan baru, dalam satu transaksi: anggota baru tidak pernah "sudah
anggota tapi masih siklus lama". Tidak ada yang dihitung ulang; amplop dan transaksi lama anggota tinggal di household
lamanya. Respons web membawa `payday_day`, dan Settings menampilkan "Berhasil bergabung ke {rumah}! Siklus anggaranmu
sekarang mengikuti rumah ini: tanggal {N}."; bot menambah baris "Siklus anggaranmu sekarang mengikuti rumah ini: tanggal
{N}." Undangan ke household selain ruang keluarga ditolak lebih dulu, sebelum keanggotaan apa pun berubah (Plugin R2: web
400 "Kode invite tidak valid atau expired", bot "❌ Kode invite tidak valid atau sudah expired."), jadi yang diadopsi
selalu siklus ruang keluarga (penyesuaian 23); undangan ruang usaha menyusul di R5. Route web menerima
kode dari query `?code=` atau body JSON `{"code": …}` (query didahulukan, `strip().upper()`, kosong → 400 "Kode invite
wajib diisi"); sebelumnya join dari Settings selalu 422 karena kodenya dikirim di body. `code` di body opsional
(penyesuaian 19): `{}` atau `{"code": null}` → 400 yang sama, dan `?code=X` dengan body `{}` diterima.

## Mengubah tanggal

`PUT /user/profile {"payday_day": N}` → `set_household_payday(db, household, day, *, actor)`:

1. `day` di luar 1–31 → `ValueError` (route: 400). Sama dengan tanggal sekarang → `{"changed": False}`, tanpa
   recompute dan tanpa notifikasi.
2. `household.payday_day = day` dan, untuk ruang keluarga, `users.payday_day` semua anggota: satu transaksi, commit.
3. `advisor_cache.invalidate(household.id)`.
4. `recompute_history(household.id, 12)` (`RECOMPUTE_PERIODS_ON_CHANGE`): riwayat dihitung ulang, minimal 12 periode
   tertutup terakhir dan selalu mundur sampai periode sebelum aktivitas pertama household (penyesuaian 15; lihat
   "Recompute dan kunci").
5. Notifikasi ke setiap anggota selain pelaku (`notification_service.kirim`, `NotificationType.system`,
   `link="/settings"`, lonceng web dan Telegram bila tertaut, tanpa email). Judul "Siklus anggaran rumah berubah",
   pesan "Tanggal gajian {rumah} kini tanggal {N} (diubah {nama pelaku}). Riwayat {k} periode terakhir dihitung ulang."
   dengan k = jumlah periode yang benar-benar dihitung ulang (bisa lebih dari 12); kalimat riwayat tidak ada bila k = 0
   (household sudah tidak ada saat recompute). Judul dan pesan tidak dikirim sebagai `telegram_html`: `kirim` yang
   meng-escape untuk Telegram, jadi nama rumah atau orang berisi `<` atau `&` aman. Tiap kirim dibungkus tersendiri: yang
   gagal dicatat dan tidak menghentikan yang lain, apalagi membatalkan perubahan.
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
  `(envelope_id, year, month)` di proses ini: `recompute_history`, job harian, dan `POST /snapshots/run` (penyesuaian
  17). Kunci dalam proses cukup karena API berjalan sebagai satu proses uvicorn dengan scheduler di dalamnya. Tidak
  re-entrant. Dict kuncinya tumbuh satu entri per household (kecil, dibiarkan).
- **`current_payday(household_id) -> int | None`**: tanggal terbaru di DB lewat sesi sendiri, hanya-baca. NULL →
  `pick_payday(member_rows)` tanpa menulis; household yang sudah dihapus (merge, hapus akun) → None.
- **`recompute_history(household_id, periods)`**: `async with household_lock`, baca `current_payday` DI DALAM kunci,
  lalu `rollover.recompute_household(...)`. Dua perubahan beruntun (mengetik "2" lalu "25") jadi berurutan: yang kedua
  menunggu yang pertama lalu memakai tanggal tersimpan terbaru, jadi hasil akhir mengikuti perubahan terakhir. Household
  yang sudah tidak ada → `[]` dan satu warning, bukan error.
- **`rollover.recompute_household(household_id, payday_day, periods, today=None)`**, tiap langkah lewat sesinya sendiri:
  1. **Berapa periode** (penyesuaian 15): `periods` hanya batas bawah. `first_activity_date(db, hid)` = yang lebih dulu
     dari transaksi pertama (termasuk yang sudah dihapus) dan pemasukan teralokasi pertama di amplop household (termasuk
     amplop nonaktif); `period.periods_to_cover(payday_day, first, today)` = jumlah periode tertutup dari periode
     SEBELUM periode yang memuat hari itu sampai periode tertutup terbaru. Yang dihitung ulang
     `max(periods, min(itu, MAX_RECOMPUTE_PERIODS))`, dengan batas 120 periode dan warning di log `jatahku.rollover`
     bila riwayatnya lebih panjang. Berhenti di periode ke-12 meninggalkan batas: periode tertua yang dihitung ulang
     membaca rollover kunci sebelumnya yang masih berjendela LAMA, jadi memundurkan tanggal membuat hari di antara kedua
     jendela tidak terhitung, memajukannya membuatnya terhitung dua kali, dan rollover membawanya ke saldo selamanya.
     Periode SEBELUM aktivitas pertama ikut dihitung karena saat tanggal dimajukan (25 → 1, data pertama 5 Mar), kunci
     tepat sebelum periode pertama menurut tanggal baru (Februari, di bawah tanggal 25 berjendela 25 Feb–24 Mar) masih
     menyimpan snapshot lama yang memuat data.
  2. **Membuang kunci periode berjalan** (penyesuaian 8), dan sejak penyesuaian 16 LEBIH DULU (lalu commit), sebelum
     membangun ulang: snapshot household itu pada kunci periode BERJALAN dan sesudahnya menurut `payday_day`. Snapshot
     hanya boleh ada untuk periode tertutup, dan rebuild yang gagal di tengah jalan tidak boleh meninggalkan kunci
     periode berjalan basi. Kuncinya tidak pernah beririsan dengan yang dibangun ulang (setiap kunci tertutup < kunci
     periode berjalan). Contoh: gajian 1 → 25 pada 10 Nov 2026. Kunci 2026-10 ditulis job 1 Nov dengan angka 1–31 Okt,
     padahal di bawah tanggal 25 itu periode berjalan 25 Okt–24 Nov; dibiarkan, job 25 Nov melewatinya (sudah ada) dan
     rollover yang salah terbawa terus. Dibuang, job membuatnya lagi dengan benar saat periodenya tutup.
  3. **Membangun ulang**: `get_closed_periods(payday_day, today, periods)` oldest-first, tiap periode
     `create_monthly_snapshots(ps, pe, force=True, household_ids=[hid])`, supaya rantai rollover terbangun ulang
     berurutan. Deterministik, aman diulang.

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

`app/scripts/siklus_household.py`, dijalankan operator di VPS sesudah deploy dan `alembic upgrade head`, **pada hari
yang sama dengan merge, sebelum job snapshot harian 00:05 berikutnya**, dan dengan `monthly_snapshots` dicadangkan dulu
(perintah backup dan restore di checklist `AGENTS.md`, langkah 4–6; penyesuaian 21):

```bash
cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.siklus_household            # sama dengan --dry-run
cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.siklus_household --apply    # [--periods 12]
```

- **`--dry-run`** (bawaan): satu baris per household yang punya anggota: id, nama, jumlah anggota, payday tiap anggota,
  `target` (payday yang akan dipakai), dan `CAMPURAN` bila anggota ruang keluarga berbeda payday. Ruang usaha ditandai
  `[usaha]` dan tidak pernah CAMPURAN. Tidak menulis apa pun.
- **`--apply`**, per household, urutan (penyesuaian 10): `household_payday` (mengisi NULL) → commit → `recompute_history(hid,
  periods)` untuk SEMUA household (minimal `--periods`, bawaan 12, dan mundur sampai aktivitas pertama household,
  penyesuaian 15; mengisi `allocated_amount`/`spent_amount`) → `heal` → notifikasi ke anggota yang payday-nya berubah,
  tanpa pelaku: "Siklus anggaranmu kini mengikuti {rumah}: tanggal {N}. Riwayat {k} periode terakhir dihitung ulang."
  (k = periode yang dihitung ulang household itu; kalimat riwayat tidak ada bila k = 0). `heal` sengaja sesudah
  recompute: recompute hanya membaca `households.payday_day` (sudah tersimpan), tidak pernah cermin anggota, jadi
  recompute yang gagal meninggalkan anggota belum disamakan dan run ulang menemukan serta memberi tahu mereka.
- **Angka yang bisa berubah.** Household campuran berubah karena siklusnya disamakan. Household yang tidak campuran
  biasanya tetap dengan angka yang sama, KECUALI bila periode tertutupnya diubah setelah snapshot-nya dibuat (transaksi
  bertanggal mundur, transaksi yang diedit atau dihapus, alokasi yang terlambat): saldo live membaca snapshot lama yang
  beku, sedangkan recompute memasukkan perubahan itu, jadi sebagian saldo rollover bergeser (lebih benar) tanpa
  notifikasi (penyesuaian 21; terkonfirmasi di PostgreSQL asli: satu pengeluaran bertanggal September yang dicatat
  belakangan menggeser rollover ke periode berjalan dari Rp1.360.000 ke Rp1.110.000).
- **Idempoten**: run kedua tidak menemukan anggota yang berubah, jadi tidak ada notifikasi kedua. Kegagalan (database,
  recompute) tidak ditangkap: traceback dan kode keluar 1; household yang sudah diproses tersimpan, dan run yang gagal
  cukup diulang. Keluaran akhir: "Selesai: N household diproses (K campuran), S snapshot ditulis, M anggota diberi tahu,
  E error." E = jumlah error per amplop di semua periode yang dihitung ulang (yang hanya tercatat di log
  `jatahku.household_cycle`, "punya error"); E > 0 → kode keluar 1 (penyesuaian 21).
- **Hari merge, sebelum job 00:05 berikutnya, di jam sepi.** Job 00:05 pertama sesudah deploy menyamakan anggota
  household campuran lewat `heal` TANPA notifikasi (hanya warning `payday anggota <id> menyimpang (a → b)` di log), dan
  `--apply` sesudahnya tidak menemukan siapa pun untuk diberi tahu (terkonfirmasi di PostgreSQL asli). Bila job itu
  sudah jalan lebih dulu: `journalctl -u jatahku --since "<waktu deploy>" | grep menyimpang` mendaftar anggota yang
  tanggalnya dipindahkan, untuk diberi tahu manual; `--apply` tetap menghitung ulang riwayat. Jam sepi yang tidak di
  sekitar 00:05, karena skrip berjalan di proses terpisah: `household_lock` tidak menyerialkannya dengan API maupun job
  harian, padahal recompute dan job menulis kunci unik `(envelope_id, year, month)` yang sama.
- **Cadangan.** `--apply` menulis ulang snapshot semua household dengan `force`; tanpa cadangan nilai lamanya tidak bisa
  diambil lagi. Checklist `AGENTS.md` memuat `pg_dump` tabel `monthly_snapshots` dan restore-nya (TRUNCATE lalu
  `pg_restore --data-only`, dalam satu transaksi supaya restore yang gagal tidak mengosongkan tabel).

## API

Aditif: field dan endpoint lama tidak berubah artinya (`python -m app.scripts.openapi_cek` bersih). Satu-satunya perilaku
baru yang menolak adalah 403 di `PUT /user/profile` dan `POST /snapshots/recompute`, dan UI tidak pernah memicunya.

- **`GET /user/profile`** +: `household_payday_day`, `payday_locked`, `payday_owner_name` (null bila pemanggil owner-nya),
  `household_name`, `household_member_count`. Tanpa ruang keluarga: `household_payday_day = payday_day`, `payday_locked =
  false`, dua nama null, `household_member_count = 1`. `payday_day` tetap = cermin. Profil (`GET` dan `PUT`) selalu
  ruang keluarga dan tidak membaca header `X-Jatahku-Ruang` (penyesuaian 23).
- **`PUT /user/profile`** dengan `payday_day`: 400 "Belum punya household"; 400 "payday_day harus antara 1 dan 31"; 403
  "Tanggal gajian mengikuti rumah tangga ({rumah}, tanggal {N}). Minta owner yang mengubahnya." Semuanya sebelum field apa
  pun diubah. Member terkunci yang mengirim tanggal yang sama dengan tanggal rumah: `payday_day` diabaikan, field lain
  tersimpan, 200 (penyesuaian 18).
- **`GET /household/`** + `payday_day` (household ruang aktif, Plugin R2). **`POST /household/join`** + `payday_day`, kode
  di query atau body; `code` di body opsional, jadi `{}` / `{"code": null}` → 400 "Kode invite wajib diisi" dan `?code=X`
  dengan body `{}` → 200 (penyesuaian 19). Undangan ke household selain ruang keluarga → 400 "Kode invite tidak valid atau
  expired" tanpa perubahan apa pun (Plugin R2).
- **`POST /snapshots/recompute?periods=6`** (default 6, maks 36): household-nya ruang tulis R2 (`hid: RuangTulis`; sampai
  R3 selalu ruang keluarga), dan izin dihitung untuk household itu juga (`payday_context(db, user, household_id=hid)`,
  penyesuaian 23). Tanpa household atau bukan anggotanya `{"recomputed": 0, "periods": []}`; bukan yang boleh mengubah →
  403 "Hanya owner atau admin rumah tangga yang bisa menghitung ulang riwayat."; selain itu commit lalu
  `recompute_history(hid, periods)` dengan tanggal RUMAH (bukan `user.payday_day`). `periods` hanya batas bawah: recompute selalu
  mundur sampai aktivitas pertama household (penyesuaian 15), karena endpoint ini alat pemulihan dan rantai hanya utuh
  bila dibangun dari awal. `recomputed` = jumlah periode yang benar-benar dihitung ulang.
- **`POST /snapshots/run?year&month&force`** (admin/debug, penyesuaian 17): tahap pertama mengisi tanggal rumah yang NULL
  dan commit; lalu per household di dalam `household_lock`, tanggal dibaca ulang di dalam kunci (`current_payday`),
  `get_period_for_month(payday, year, month)`, dan `create_monthly_snapshots(..., household_ids=[hid], force=force)`
  HANYA bila periodenya sudah tertutup (hari terakhirnya sebelum hari ini). Periode berjalan atau belum mulai → entri
  `"skipped": "periode belum tertutup"` (tanpa year/month = bulan berjalan, jadi selalu dilewati); household yang sudah
  dihapus → `"skipped": "household tidak ada"` dengan `period` null; exception di satu household → entri
  `"errors": ["gagal: <kelas exception>"]` (dicatat lengkap di log `jatahku.snapshots`), household lain tetap diproses.
  Respons `{"households": [{"household_id", "period", "processed", "snapshots_created", "errors"[, "skipped"]}],
  "processed", "snapshots_created", "errors"}`. `force=true` pada periode lampau hanya menulis ulang SATU mata rantai;
  periode sesudahnya tetap membawa rollover lama (lihat "Pemulihan"). **Pengecualian disengaja** dari "API hanya
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
    dan riwayat anggarannya dihitung ulang. Lanjutkan?" (penyesuaian 15)
  - Household sendirian → simpan saat berubah, ditunda 600 ms (debounce) supaya mengetik "25" tidak menyimpan "2" dulu;
    simpan tertunda dibuang bila halaman ditinggalkan. Setelah simpan, juga yang ditolak, profil dimuat ulang.
- **Onboarding** (penyesuaian 14, 20): profil dibaca dulu; `payday_day` hanya dikirim untuk household sendirian
  (`onboardingProfileBody`). Anggota yang tanggalnya terkunci hanya mengirim `income_type`, karena PUT yang membawa tanggal
  lain ditolak 403 dan `income_type` ikut hilang; owner/admin household lebih dari satu anggota (`needsConfirm`) juga,
  karena mengubah tanggal rumah menghitung ulang riwayat dan memberi tahu semua anggota, dan Onboarding tidak punya
  dialog konfirmasi (pekerja harian/mingguan akan mengirim tanggal 1 tanpa sadar). Tanggal rumah diubah di Settings.
- **Alokasi** (`nonRolloverWarning.js`): baris amplop dengan `is_rollover === false`, nilai alokasi > 0, dan periode
  berjalan berakhir dalam 7 hari atau kurang (`period_end` = periode terakhir `GET /analytics/periods`, dibandingkan
  dengan tanggal lokal browser) menampilkan "Amplop ini tidak membawa sisa ke periode berikutnya. Yang tidak terpakai
  di-reset {tgl} ({n} hari lagi)." (`{tgl}` = "{hari} {Jan Feb Mar Apr Mei Jun Jul Agu Sep Okt Nov Des}"; di hari
  terakhir: "(hari ini)"). Hanya web: alokasi tidak pernah lewat bot.

## Pemulihan

- **Riwayat basi** (recompute gagal setelah tanggal tersimpan, penyesuaian 9, atau kunci snapshot dicurigai): operator
  menjalankan skrip `--apply` (semua household), atau owner/admin rumah itu memanggil `POST /snapshots/recompute`.
  Keduanya membangun ulang seluruh rantai oldest-first dari aktivitas pertama household (`periods` hanya batas bawah).
  `POST /snapshots/run?year=&month=&force=true` BUKAN alat pemulihan: ia hanya menulis periode tertutup, dan hanya satu
  mata rantai, sehingga periode sesudahnya tetap membawa rollover lama.
- **Snapshot sebelum migrasi data**: cadangan `monthly_snapshots` dari langkah 5 checklist `AGENTS.md` dikembalikan dengan
  TRUNCATE + `pg_restore --data-only` dalam satu transaksi (perintahnya di checklist itu).
- **Rollback kode lalu deploy ulang**: perubahan `users.payday_day` yang dibuat kode lama di antaranya akan dikembalikan
  `heal` ke tanggal household. Bila yang diinginkan nilai user, jalankan `UPDATE households SET payday_day = NULL` sebelum
  restart: backfill `lifespan` menurunkannya lagi dari owner.

## Catatan untuk rencana ruang usaha (R2/R4/R5)

Tahap R2, R4, dan R5 didefinisikan di `docs/plugin/03-workflow.md` (Fase 2 · Ruang usaha): R2 resolver `ruang_aktif`,
R4 membuat dan berpindah ruang, R5 undangan, peran, dan batasan ruang usaha. Tiap butir di bawah diberi tahap tempat
ia harus dikerjakan.

Plugin R1 sudah di `main` (`households.type`, satu user boleh di beberapa household), dan fase ini sudah mengikutinya:
`mirrors_users` membatasi cermin ke ruang keluarga, `membership` hanya ruang keluarga, `set_household_payday` dan `heal`
tidak menyentuh `users.payday_day` untuk ruang usaha, dan job harian serta `/snapshots/run` sudah benar per household.
Plugin R2 (#166) juga sudah di `main`, dan fase ini digabung di atasnya (penyesuaian 23):

- **R2 — kueri keanggotaan per `user_id` saja: selesai.** Resolver `app/services/ruang.py` menggantikannya di join web,
  `POST /household/invite`, `GET /household/`, `/household/members`, `/household/leaderboard`, `cmd_join`, dan
  `cmd_invite`. `membership` di modul siklus kini diteruskan ke `ruang.keanggotaan_keluarga`, tanpa kueri sendiri;
  `POST /snapshots/recompute` memakai ruang tulis R2 dan menghitung izinnya untuk household itu; profil tetap ruang
  keluarga.
- **Terbuka (sesudah R2, sebelum ruang usaha bisa dibuka di R4) — call site masih membaca `user.payday_day`.** R2
  meneruskan `household_id` ruang aktif ke services, tetapi jendela periode (ringkasan amplop, analitik, export) masih
  dihitung dari `user.payday_day`, cermin ruang KELUARGA, juga saat header membuka ruang lain. Bacalah
  `households.payday_day` ruang aktif (`household_payday`); sesudahnya cermin `users.payday_day` bisa dipensiunkan.
  Hari ini laten: belum ada klien yang mengirim header dan belum ada ruang usaha.

Yang masih harus dikerjakan rencana ruang usaha:

- **R4 — pembuatan ruang usaha harus mengisi `households.payday_day` secara eksplisit.** NULL diturunkan dari anggota
  (`household_payday`, `current_payday`, `pick_payday`) memakai `users.payday_day` mereka, yaitu siklus ruang KELUARGA
  mereka, bukan siklus usaha.
- **R4 — mengubah tanggal ruang usaha** butuh pintu masuk sendiri: `PUT /user/profile` (dan `payday_context` tanpa
  `household_id`) hanya menjangkau ruang keluarga. `POST /snapshots/recompute` mengikuti ruang tulis R2 (sampai R3 ruang
  keluarga, sesudahnya ruang yang ditulis) dengan izin untuk household itu. `set_household_payday` dan
  `recompute_history` sudah bekerja untuk ruang usaha (tanpa cermin ke user), tetapi izin (`can_change_payday`)
  diputuskan pemanggil.
- **R5 — bergabung ke ruang usaha.** Hari ini join web dan `cmd_join` menolak undangan ke household selain ruang keluarga
  sebelum mengubah apa pun (Plugin R2), dan pindah ruang keluarga hanya menghapus keanggotaan ruang keluarga lama, bukan
  keanggotaan ruang usaha. Jalur undangan ruang usaha di R5 tidak boleh memanggil `adopt_household_payday` (fungsinya
  tidak memeriksa tipe; pakai `household_payday`) dan tidak boleh menghapus keanggotaan ruang keluarga user. Judul dan
  pesan notifikasi perubahan siklus ("Siklus anggaran rumah berubah", "Tanggal gajian {rumah} kini tanggal …") juga
  terkirim untuk ruang usaha, karena `set_household_payday` memberi tahu semua anggota ruang itu; ganti kata "rumah" per
  tipe.

## Batasan yang diketahui

- **Kunci hanya dalam proses.** Skrip migrasi berjalan di proses lain, jadi tidak diserialkan dengan API maupun job
  harian: jalankan di jam sepi (lihat "Skrip migrasi data").
- **`heal` membandingkan dengan objek household yang dibaca lebih awal** (job: tahap pertama; skrip: saat survei). Bila owner
  meng-commit perubahan tanggal di antaranya, cermin anggota bisa dikembalikan ke tanggal lama sampai job berikutnya;
  `households.payday_day` sendiri tidak terpengaruh.
- **Job tidak mengisolasi kegagalan per household**: exception di satu household menghentikan sisanya hari itu (dicatat
  APScheduler); job besoknya mengejar (`CATCH_UP_PERIODS`).
- **Error per amplop** di dalam recompute tetap menghitung periodenya sebagai ter-recompute (`recomputed`, kalimat "dihitung
  ulang"); yang menandainya hanya log `jatahku.household_cycle` ("punya error"), daftar `errors` di respons route, dan
  untuk skrip `--apply` jumlah "E error" di baris terakhir beserta kode keluar 1.
- **Recompute dibatasi 120 periode** (`rollover.MAX_RECOMPUTE_PERIODS`, 10 tahun): riwayat yang lebih panjang hanya
  dihitung ulang 120 periode terakhirnya, dengan warning di log `jatahku.rollover`.
- **Mengubah tanggal di tengah periode** memindahkan pemasukan dan transaksi ke jendela baru (riwayat dihitung ulang).
  Untuk amplop non-rollover, alokasi yang kini jatuh di periode yang sudah tertutup tidak terbawa ke periode berjalan:
  gajian 25 → 1 pada 10 Nov memindahkan alokasi 25 Okt ke periode Oktober yang sudah tutup, dan sisanya di-reset.
  Peringatan amplop non-rollover di Alokasi adalah mitigasi yang dipilih.
- **`services/merge.py`** memindahkan amplop dan keanggotaan antar-household tanpa mengadopsi tanggal gajian dan tanpa
  recompute: `heal` menyamakan cermin anggota esok harinya (job 00:05), dan riwayat dihitung ulang lewat
  `POST /snapshots/recompute` (owner/admin rumah itu) atau skrip `--apply`.

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
  `test_periods_to_cover.py`, `test_siklus_household_script.py`. Frontend: `paydayLock.test.js`, `nonRolloverWarning.test.js`.
  Perintah: `DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python3 -m unittest
  discover -s app/tests -t .` dan `cd frontend && node --test src/lib/*.test.js src/native/*.test.js`.
