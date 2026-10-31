# Siklus anggaran per household — desain

**Tanggal:** 31 Okt 2026
**Status:** desain disetujui pemilik produk di chat, bagian 1–9 (31 Okt 2026). Belum diimplementasikan.
**Klasifikasi:** arsitektural. Mengubah invarian yang dibaca ±25 call site (snapshot, rollover, advisor, analitik, langganan, struk), menyentuh web dan bot, dan butuh migrasi skema + data.
**Spec lanjutan:** laporan berkala (bulanan, kuartalan, tahunan) ditulis sebagai spec terpisah **setelah** fase ini tayang. Spec ini adalah fondasinya.

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
7. **Owner mengubah payday → 12 periode tertutup terakhir household dihitung ulang otomatis**, supaya riwayat semua anggota konsisten dengan jendela baru.
8. Saat **bergabung** tidak ada yang dihitung ulang: amplop dan transaksi lama anggota tinggal di household lamanya.

## Tujuan

Setelah fase ini, untuk household mana pun berlaku: semua anggota memakai satu `payday_day`, setiap `(amplop, tahun, bulan)` di `monthly_snapshots` dihitung dengan jendela household itu, dan snapshot menyimpan alokasi dan pengeluaran periode, sehingga spec laporan bisa membaca `rollover_in`, `allocated`, `spent`, `closing`, `rollover_out` per periode tanpa menghitung ulang riwayat.

**Kriteria sukses**
1. Household campuran di produksi (kalau ada) setelah `--apply`: semua anggota payday sama, snapshot 12 periode terakhir dihitung ulang, dashboard anggota yang payday-nya berubah menampilkan sisa yang cocok dengan buku besar (tanpa transaksi terhitung ganda).
2. Member household >1 anggota tidak bisa mengubah payday (403) dan tidak bisa `recompute` (403); UI menampilkannya read-only tanpa pernah memicu 403.
3. Owner mengubah payday: semua anggota berubah dalam satu transaksi, 12 periode dihitung ulang, anggota lain menerima notifikasi (lonceng web + Telegram).
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
- Revisi alembic baru (label PR `migrasi`), isinya DDL dan backfill yang sama dengan `if_not_exists` / `IF NOT EXISTS`, jadi aman dijalankan sebelum atau sesudah deploy. **Dibuat paling akhir** dari `main` segar karena ada sesi pengembangan lain; `alembic heads` harus tetap satu (`a7c4e2b9d1f3` saat spec ini ditulis).
- `HouseholdRole` disimpan sebagai `SAEnum` → nilai di DB `'owner'|'admin'|'member'` (cek saat implementasi dengan `\dT+ householdrole`; sesuaikan `CASE` bila label enum berbeda).

### 1c. Tabel yang butuh hak ALTER
`households` dan `monthly_snapshots` harus dimiliki user DB aplikasi (`jatahku`), seperti dicek di checklist Kotak Struk. Kalau `monthly_snapshots` milik `postgres`, startup pertama gagal; jalankan DDL sebagai `postgres` dulu (checklist bagian 9).

## 2. Service `app/services/household_cycle.py` — satu-satunya penulis payday

Semua fungsi menerima `db: AsyncSession` dan **tidak** `commit` sendiri kecuali disebut; pemanggil yang commit (pola repo).

- `async def household_payday(db, household) -> int`: kembalikan `household.payday_day`; bila NULL, turunkan dari anggota dengan urutan owner → admin → anggota tertua (`HouseholdMember.created_at`) → 1, tulis ke `household.payday_day`, `flush`, kembalikan.
- `def can_change_payday(membership, member_count: int) -> bool`: `role in (owner, admin)` → True; `member` → True hanya bila `member_count == 1`; selain itu False.
- `async def set_household_payday(db, household_id, day: int, *, actor) -> dict`:
  1. validasi `1 <= day <= 31` (`ValueError` → 400 di route);
  2. muat household; bila `day == household_payday(...)` → no-op, kembalikan `{"changed": False}` (tanpa recompute, tanpa notifikasi);
  3. `household.payday_day = day`; `UPDATE users SET payday_day = :day WHERE id IN (SELECT user_id FROM household_members WHERE household_id = :hid)`; `commit`;
  4. `advisor_cache.invalidate(hid)`;
  5. `await rollover.recompute_household(hid, day, periods=RECOMPUTE_PERIODS_ON_CHANGE)` dengan `RECOMPUTE_PERIODS_ON_CHANGE = 12`;
  6. notifikasi ke setiap anggota **selain actor** lewat `notification_service.kirim(user, NotificationType.system, title, message, link="/settings", telegram_html=…)`. Judul `"Siklus anggaran rumah berubah"`, pesan `"Tanggal gajian {nama rumah} kini tanggal {day} (diubah {actor.name}). Riwayat 12 periode terakhir dihitung ulang."`. Gagal kirim dicatat, tidak membatalkan perubahan;
  7. kembalikan `{"changed": True, "members": n, "recomputed": k}`.
- `async def adopt_household_payday(db, user, household) -> int`: `user.payday_day = await household_payday(db, household)`; kembalikan nilainya. Dipanggil join web dan bot **sebelum** commit keanggotaan baru, dalam transaksi yang sama.
- `async def heal(db, household) -> list[uuid]`: untuk household dengan `payday_day` terisi, samakan `users.payday_day` anggota yang berbeda, `commit`, catat `logger.warning("payday anggota %s menyimpang (%s → %s)")`, kembalikan id yang diperbaiki. Dipanggil job harian (bagian 4). Tidak memanggil recompute: penyimpangan hanya mungkin terjadi lewat jalur yang lupa memakai service ini, dan job yang sama menghitung snapshot dengan payday household.
- **Penulis tunggal, dikunci tes:** atribut `payday_day` hanya boleh di-assign di `app/services/household_cycle.py` (dan deklarasi kolom di `app/models/models.py`, backfill DDL di `app/main.py`). `user_settings.py:171` (`user.payday_day = req.payday_day`) diganti pemanggilan service; skrip migrasi (bagian 7) memakai service. Tes `test_household_cycle_sole_writer` memindai `app/**/*.py` (kecuali `app/tests`) dengan regex `\.payday_day\s*=(?!=)` (assignment atribut; argumen kata kunci `payday_day=` tidak ikut) dan `(?i)\bset\s+payday_day` (SQL), dan gagal bila ada file di luar daftar itu.
- `household_payday` boleh dipanggil dari handler GET (mengisi NULL saat dibaca); bila sesi GET tidak di-commit, nilainya tetap benar di respons dan job harian yang menyimpannya.

## 3. API (aditif; satu 403 baru)

- `GET /user/profile` +
  `household_payday_day` (int), `payday_locked` (bool: `not can_change_payday(...)`), `payday_owner_name` (nama owner, `null` bila pemanggil owner-nya). `payday_day` yang sudah ada tetap dikembalikan (= cermin).
- `PUT /user/profile` dengan `payday_day`: cek izin dilakukan **paling awal**, sebelum perubahan apa pun: bila `can_change_payday` → lanjut memproses field lain lalu `set_household_payday`; bila tidak → `403` detail `"Tanggal gajian mengikuti rumah tangga ({nama rumah}, tanggal {N}). Minta owner yang mengubahnya."` tanpa menyimpan apa pun. Tanpa keanggotaan household (seharusnya tidak terjadi) → `400 "Belum punya household"`, seperti `incomes.py`. UI tidak pernah mengirim `payday_day` saat terkunci.
- `GET /household/` (`HouseholdResponse`) + `payday_day`.
- `POST /household/join` response + `payday_day`. **Verifikasi saat implementasi:** route menerima `code` sebagai query (`code: str`) sedangkan `Settings.jsx:498` mengirim body JSON `{code}`. Kalau ini 422 di produksi, terima keduanya (query atau body) tanpa mengubah arti.
- `POST /snapshots/recompute`: hanya `can_change_payday` (owner/admin; member hanya bila sendirian) → selain itu 403; periode dari `household_payday`, bukan `user.payday_day`. Parameter `periods` tetap (default 6, maks 36).
- `POST /snapshots/run` (admin): untuk tiap household, `period = get_period_for_month(household_payday, year, month)` lalu `create_monthly_snapshots(..., household_ids=[hid], force=force)`. Respons: ringkasan per household.
- Semua perubahan lolos `python -m app.scripts.openapi_cek`.

## 4. Job snapshot & rollover

### 4a. `payday_snapshot_job` (`scheduler.py`)
Iterasi **household**, bukan grup user:
```
for household in households:
    payday = await household_payday(db, household)   # mengisi NULL
    await heal(db, household)
    for ps, pe in get_closed_periods(payday, today, CATCH_UP_PERIODS):
        await create_monthly_snapshots(ps, pe, household_ids=[household.id])
```
`CATCH_UP_PERIODS = 3` dan jadwal (00:05) tidak berubah. Loop IO dipisah dari fungsi murni `household_runs(rows, today, catch_up) -> list[(hid, payday, [(ps, pe)])]` yang menerima `(household_id, payday)` dan diuji tanpa DB.

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
`get_closed_periods(payday, today, periods)` oldest-first, tiap periode `create_monthly_snapshots(ps, pe, force=True, household_ids=[hid])`. Dipakai endpoint `recompute`, `set_household_payday`, dan skrip migrasi (bagian 7). Deterministik, aman diulang.

## 5. `app/core/period.py`

- Tambah `get_period_for_month(payday_day, year, month) -> tuple[date, date]` = `get_budget_period(payday_day, _safe_date(year, month, payday_day))`.
- `export._resolve_period` (cabang `year`+`month`) dan `snapshots.run` memakainya; perilaku identik (dikunci tes kesetaraan).
- `get_report_period` **tidak** dibuat di fase ini (belum ada pemakai); masuk spec laporan.

## 6. Web & bot

### 6a. Settings (`frontend/src/pages/Settings.jsx`, kartu "📅 Tanggal Gajian")
- Bila `payday_locked`: input diganti teks read-only `"Mengikuti siklus rumah tangga: tanggal {N} (diatur {payday_owner_name})."` dan `payday_day` tidak pernah dikirim.
- Bila boleh mengubah dan `member_count > 1`: input tidak lagi menyimpan saat diketik; ada tombol Simpan yang membuka dialog konfirmasi in-app (pola dialog reset data di halaman yang sama, bukan `window.confirm`): `"Mengubah tanggal gajian berlaku untuk semua anggota {nama rumah}, dan 12 periode terakhir dihitung ulang. Lanjutkan?"`. Household sendirian: perilaku sekarang (simpan langsung saat berubah).
- Logika keputusan di `lib/paydayLock.js` (`paydayLockState(profile, household) -> {locked, note, needsConfirm}`) supaya bisa diuji `node --test`.

### 6b. Join
- Web (`Settings.jsx` `joinHousehold`): flash `"Berhasil bergabung ke {rumah}! Siklus anggaranmu sekarang mengikuti rumah ini: tanggal {payday_day}."`, lalu `load()` memuat profil baru.
- Bot `cmd_join` (`household_cmd.py`, juga dipakai chat web lewat registry handler yang sama): panggil `adopt_household_payday` sebelum commit; pesan sukses ditambah baris `"Siklus anggaranmu sekarang mengikuti rumah ini: tanggal {N}."`.

### 6c. Alokasi (`frontend/src/pages/Allocate.jsx`)
Banner inline di baris amplop tujuan bila `!env.is_rollover` **dan** sisa hari periode berjalan ≤ 7 **dan** nilai alokasi > 0:
`"Amplop ini tidak membawa sisa ke periode berikutnya. Yang tidak terpakai di-reset {period_end} ({n} hari lagi)."`
Data sudah ada di halaman: `is_rollover` dari `/envelopes/summary`, `period_end` periode berjalan dari `/analytics/periods`. Logika di `lib/nonRolloverWarning.js` (`nonRolloverWarning(env, periodEnd, today, amount) -> string | null`), diuji `node --test`. Hanya web: alokasi tidak pernah terjadi lewat bot.

### 6d. Notifikasi
Lewat `notification_service.kirim` dengan `NotificationType.system` (tanpa enum DB baru, tanpa email): lonceng web + Telegram bila tertaut, `link="/settings"`. Teks di bagian 2.

## 7. Migrasi data sekali jalan: `app/scripts/siklus_household.py`

Dijalankan admin di VPS setelah deploy (pola `app/scripts/kotak_corpus.py`, `argparse`, `python -m`):
- `--dry-run` (default): per household cetak id, nama, jumlah anggota, payday tiap anggota, payday household yang akan dipakai, dan tanda **campuran** bila `COUNT(DISTINCT users.payday_day) > 1`. Tidak menulis apa pun.
- `--apply [--periods 12]`: untuk tiap household: `household_payday` (mengisi NULL), `heal` (menyamakan anggota), `recompute_household(hid, payday, periods)` untuk **semua** household (mengisi `allocated_amount`/`spent_amount`; household non-campuran menghasilkan angka identik), lalu notifikasi (bagian 6d, tanpa `actor`) ke anggota yang payday-nya berubah, dengan pesan `"Siklus anggaranmu kini mengikuti {rumah}: tanggal {N}. Riwayat {periods} periode terakhir dihitung ulang."`.
- Idempoten: menjalankan `--apply` dua kali menghasilkan DB yang sama dan tidak mengirim notifikasi kedua (tidak ada anggota yang berubah lagi).
- Keluaran akhir: jumlah household, jumlah campuran, jumlah snapshot ditulis, anggota yang diberi tahu.

## 8. Pengujian (semua tanpa Postgres; fungsi murni + `db` tiruan seperti `test_export.py`)

| Area | Tes |
|---|---|
| `period.py` | `get_period_for_month` untuk payday 1, 25, 31 (Jan 31–Feb 27, Feb 28–Mar 30, Mar 31–Apr 29 di 2026); setara dengan `_resolve_period(year, month)` lama. |
| `household_cycle` | `can_change_payday` (owner, admin, member sendirian, member berdua); `household_payday` mengisi NULL dari owner → admin → tertua; `set_household_payday` menulis household + semua anggota, no-op bila sama, memanggil `recompute_household(…, 12)` dan `advisor_cache.invalidate`, notifikasi ke anggota selain actor; `adopt_household_payday`; `heal` memperbaiki dan mencatat warning; `test_household_cycle_sole_writer`. |
| `rollover` | `snapshot_values`: `opening − allocated == prev_rollover`; rollover vs non-rollover; closing negatif → rollover 0; `create_monthly_snapshots` menyimpan dua kolom baru (mock session). |
| `scheduler` | `household_runs` menghasilkan tepat satu jendela per household untuk household campuran (payday 1 dan 25), 3 periode tertutup. |
| rute | `PUT /user/profile`: owner → service dipanggil; member → 403 dan field lain tetap tersimpan; `GET /user/profile` field baru; `recompute` 403 untuk member, memakai payday household; `snapshots/run` per household; `household/join` web mengadopsi payday dan response berisi `payday_day`. |
| bot | `cmd_join` memanggil `adopt_household_payday` dan pesannya menyebut tanggal. |
| skrip | `--dry-run` tidak menulis; `--apply` memanggil heal + recompute per household dan notifikasi hanya untuk yang berubah; idempoten pada panggilan kedua. |
| frontend | `paydayLockState`, `nonRolloverWarning` (`node --test`); `npm run build`. |
| API | `python -m app.scripts.openapi_cek` → tidak ada yang memutus. |

Semua tes ditulis lebih dulu (TDD), per tugas di rencana implementasi.

## 9. Deploy & rollout (checklist di `AGENTS.md`, label PR `migrasi`)

1. Sebelum merge: cek pemilik `households` dan `monthly_snapshots` (query pemilik tabel di checklist Kotak Struk); bila bukan `jatahku`, siapkan menjalankan DDL sebagai `postgres`.
2. Merge → deploy. Restart pertama menjalankan DDL + backfill di `lifespan`; API tetap 200 (kolom nullable, model menerima NULL). Run deploy boleh berakhir "Deploy GAGAL" karena `alembic current ≠ heads`.
3. `alembic upgrade head` (urutan "merge PR bermigrasi" di `AGENTS.md`), `alembic current` = revisi baru, restart, re-run job deploy yang gagal.
4. `python -m app.scripts.siklus_household --dry-run` → baca daftar campuran; lalu `--apply`.
5. Verifikasi: `GET /user/profile` dua anggota satu household → `household_payday_day` sama; esok harinya `journalctl -u jatahku | grep menyimpang` kosong; bila ada household campuran, dashboard anggota yang berubah dicek sisa amplopnya masuk akal.
6. Dokumentasi: `docs/siklus-household.md` (perilaku final, seperti `docs/kotak-struk.md`), satu baris di `CLAUDE.md` "Key Decisions" ("Siklus anggaran milik household: `households.payday_day`, `users.payday_day` cermin; penulis tunggal `services/household_cycle.py`").

## Di luar cakupan

- Desain laporan berkala (PDF, email berpassword, halaman analitik, notifikasi rilis) — spec berikutnya. Yang bisa diasumsikan spec itu dari fase ini: satu jendela per household, `get_period_for_month`, snapshot berisi `allocated_amount`/`spent_amount`, `recompute_household`.
- `get_report_period` / agregasi N periode.
- Mengubah tanggal "hari ini" job (`date.today()` server) ke zona waktu user.
- Endpoint keluar/keluarkan anggota household (belum ada); household lama yang yatim saat join (perilaku lama).
- Perbaikan `payday_day` lewat admin panel (admin hanya membaca).

## Risiko & mitigasi

- **Jendela nilai salah saat migrasi.** Dihindari dengan kolom NULL + backfill dalam DDL startup, sebelum job pertama berjalan.
- **Jalur baru lupa memakai service** → invarian bocor. Mitigasi: tes penulis tunggal + `heal` harian; akibat terburuk satu hari penyimpangan, bukan rantai rollover rusak.
- **Owner mengganti payday berulang** memicu recompute 12 periode tiap kali. Skala sekarang (29 user) hitungan detik; bila nanti membesar, pindahkan ke tugas latar (`asyncio.create_task`) dengan kunci per household. Dua recompute bersamaan: penulis terakhir menang, hasilnya tetap deterministik.
- **Riwayat anggota berubah** saat payday household berubah atau saat migrasi: itu memang konsekuensi keputusan #7, dan dikomunikasikan lewat notifikasi.
- **Konflik dengan sesi pengembangan lain:** perubahan dijaga lokal; `models.py`, `main.py` hanya baris aditif; `AGENTS.md` hanya tambah satu bagian; revisi alembic dibuat terakhir; rebase sebelum PR.

## Dampak ke rencana lain

- **Mobile (AGENTS.md "API hanya bertambah"):** semua field/endpoint lama tetap; satu 403 baru di `PUT /user/profile` hanya untuk kombinasi yang UI tidak pernah kirim. Dicatat di `docs/mobile` paritas bila aplikasi sudah terpasang saat fase ini tayang.
- **AI Advisor v2:** tidak ada perubahan angka; `advisor_cache.invalidate(hid)` dipanggil saat payday berubah.
- **Kotak Struk:** `document_date_kind` memakai `user.payday_day` (cermin) — tidak berubah.
