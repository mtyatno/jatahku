# Siklus anggaran per household — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Satu household = satu siklus anggaran: `households.payday_day` menjadi sumber kebenaran yang ditentukan owner, `users.payday_day` menjadi cerminnya, snapshot dihitung per household dengan satu jendela dan menyimpan alokasi + pengeluaran periode, sebagai fondasi laporan berkala.

**Architecture:** Satu service baru `app/services/household_cycle.py` adalah satu-satunya penulis payday (dikunci tes). Route profil, join (web + bot), snapshot, job harian, dan skrip migrasi memanggil service itu. Recompute riwayat diserialkan per household (`asyncio.Lock`) dan selalu membaca payday terbaru. Skema bertambah lewat DDL idempoten di `lifespan` + satu revisi alembic. Frontend hanya menampilkan: kunci payday di Settings dan peringatan amplop non-rollover di Alokasi.

**Tech Stack:** FastAPI, SQLAlchemy async (Postgres di produksi; tes memakai `db` tiruan dari `app/tests/fakes.py`), python-telegram-bot, APScheduler, React 18 + Vite, `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-31-siklus-household-design.md` (Project doc `claude/siklus-household-desain.md`). Baca bagian "Penyesuaian saat menyusun rencana implementasi" dan bagian 10 dulu.

## Global Constraints

- Branch `feat/siklus-household` dari `main` terbaru; satu PR berlabel `migrasi`. Ada sesi pengembangan lain yang berjalan paralel: perubahan di `models.py`, `main.py`, `AGENTS.md` hanya **menambah** baris; revisi alembic dibuat di Task 13 dari `main` segar (`alembic heads` harus tetap satu).
- Git: jangan `git add -A`; stage file satu per satu; jangan commit `frontend/dist/` (setelah build: `git checkout -- frontend/dist`). File di `docs/superpowers/` di-gitignore: tambahkan dengan `git add -f`.
- Akhir setiap pesan commit:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_017DL2c6KwEzKSaXsjUN4PBR
  ```
- API hanya bertambah (AGENTS.md, Aplikasi mobile #2): field/endpoint lama tidak dihapus atau diubah artinya. Satu-satunya perilaku baru yang menolak: 403 di `PUT /user/profile` dan `POST /snapshots/recompute` untuk member household >1 anggota. Cek: `python3 -m app.scripts.openapi_cek` → "Tidak ada perubahan API yang memutus".
- Penulis tunggal payday: atribut `payday_day` (user maupun household) hanya di-assign di `app/services/household_cycle.py`; SQL `SET payday_day` hanya di `app/services/household_cycle_schema.py`.
- Enum vs string (AGENTS.md): bandingkan peran dengan `str(getattr(role, "value", role))`, jangan `role == "owner"` langsung.
- Konstanta: `RECOMPUTE_PERIODS_ON_CHANGE = 12` (household_cycle), `CATCH_UP_PERIODS = 3` (scheduler, tidak berubah), `periods` endpoint recompute default 6 maks 36 (tidak berubah), debounce simpan payday 600 ms (frontend).
- Logger service: `logging.getLogger("jatahku.household_cycle")`.
- Teks (Bahasa Indonesia, persis):
  - 403 profil: `"Tanggal gajian mengikuti rumah tangga ({nama rumah}, tanggal {N}). Minta owner yang mengubahnya."`
  - 400 profil tanpa household: `"Belum punya household"`; 400 rentang (sudah ada): `"payday_day harus antara 1 dan 31"`.
  - 403 recompute: `"Hanya owner atau admin rumah tangga yang bisa menghitung ulang riwayat."`
  - 400 join tanpa kode: `"Kode invite wajib diisi"`.
  - Judul notifikasi: `"Siklus anggaran rumah berubah"`. Pesan (owner mengubah): `"Tanggal gajian {nama rumah} kini tanggal {N} (diubah {nama owner}). Riwayat {periode} periode terakhir dihitung ulang."`. Pesan (skrip migrasi): `"Siklus anggaranmu kini mengikuti {nama rumah}: tanggal {N}. Riwayat {periode} periode terakhir dihitung ulang."`
  - Join (web flash dan baris bot): `"Siklus anggaranmu sekarang mengikuti rumah ini: tanggal {N}."`; flash web lengkap: `"Berhasil bergabung ke {nama rumah}! Siklus anggaranmu sekarang mengikuti rumah ini: tanggal {N}."`
  - Settings terkunci: `"Mengikuti siklus rumah tangga: tanggal {N} (diatur {nama owner})."` (tanpa nama owner: `"Mengikuti siklus rumah tangga: tanggal {N}."`). Konfirmasi: `"Mengubah tanggal gajian berlaku untuk semua anggota {nama rumah}, dan 12 periode terakhir dihitung ulang. Lanjutkan?"`
  - Alokasi: `"Amplop ini tidak membawa sisa ke periode berikutnya. Yang tidak terpakai di-reset {tgl} ({n} hari lagi)."`; bila `n == 0`: `"… di-reset {tgl} (hari ini)."`. `{tgl}` = `"{hari} {Bln}"` dengan bulan `Jan Feb Mar Apr Mei Jun Jul Agu Sep Okt Nov Des`.
- Tes backend tanpa Postgres (CI tidak punya): fungsi murni + `db_with(...)` / `FakeResult` dari `app/tests/fakes.py`, `patch.object(modul, ...)` untuk IO.
- Perintah tes: backend satu file `DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python3 -m unittest app.tests.<modul> -v`; semua `… python3 -m unittest discover -s app/tests -t .`; frontend `cd frontend && node --test src/lib/<file>.test.js`; build `cd frontend && npm run build`.

## Review Focus

1. **Payday diubah beruntun** (mengetik "2" lalu "25", atau owner dan admin bersamaan) → recompute satu household tidak pernah tumpang-tindih, dan yang terakhir selalu memakai payday terbaru. Dipin di Task 5 (`test_recompute_history_serialises_and_reads_latest_payday`).
2. **User tanpa keanggotaan household** (data lama/rusak) → `GET /user/profile` tetap 200 dengan nilai bawaan, `PUT` payday → 400, `recompute` → `{"recomputed": 0, "periods": []}`. Dipin di Task 6 (`test_profile_without_household_defaults`, `test_put_payday_without_household_400`) dan Task 8 (`test_recompute_without_household`).
3. **Nama rumah/owner berisi karakter HTML** (`<`, `&`) di notifikasi Telegram (parse mode HTML) → tidak memutus pengiriman: service tidak mengirim `telegram_html` sendiri, `kirim` meng-escape. Dipin di Task 5 (`test_notifies_members_except_actor` memeriksa tidak ada `telegram_html`).
4. **Telegram/lonceng gagal saat notifikasi** → perubahan payday dan recompute tetap terjadi. Dipin di Task 5 (`test_notification_failure_keeps_change`).
5. **Household yatim tanpa anggota** (tertinggal saat user join household lain) → dilewati job dan skrip, tidak dibuat snapshot/notifikasi. Dipin di Task 9 (`test_job_only_households_with_members`) dan Task 10 (`test_survey_skips_households_without_members`).

---

## Peta file

| File | Tanggung jawab |
|---|---|
| `app/core/period.py` | + `get_period_for_month` |
| `app/services/household_cycle_schema.py` (baru) | `HOUSEHOLD_CYCLE_DDL`: ALTER aditif + backfill `households.payday_day` (dipakai `main.py` dan alembic) |
| `app/services/household_cycle.py` (baru) | Satu-satunya penulis payday: resolver, izin, konteks, adopsi, heal, ubah payday, recompute serial, notifikasi |
| `app/services/rollover.py` | + `SnapshotValues`, `snapshot_values`, `recompute_household`; simpan `allocated_amount`/`spent_amount` |
| `app/models/models.py` | + `Household.payday_day`, `MonthlySnapshot.allocated_amount`, `MonthlySnapshot.spent_amount` |
| `app/main.py` | jalankan `HOUSEHOLD_CYCLE_DDL` di blok Postgres `lifespan` |
| `app/api/routes/user_settings.py` | profil: field baru, PUT payday lewat service |
| `app/api/routes/household.py` | `GET /household/` + `payday_day`; join: kode dari query atau body, adopsi payday |
| `app/bot/household_cmd.py` | `cmd_join`: adopsi payday + baris pesan |
| `app/api/routes/snapshots.py` | `recompute`: izin + `recompute_history`; `run`: per household |
| `app/api/routes/export.py` | `_resolve_period` memakai `get_period_for_month` |
| `app/services/scheduler.py` | `household_runs` (murni) + job per household |
| `app/scripts/siklus_household.py` (baru) | migrasi data sekali jalan (`--dry-run`/`--apply`) |
| `frontend/src/lib/paydayLock.js` (baru) | keputusan kunci/konfirmasi payday, teks join |
| `frontend/src/lib/nonRolloverWarning.js` (baru) | teks peringatan amplop non-rollover |
| `frontend/src/pages/Settings.jsx`, `frontend/src/pages/Allocate.jsx` | memakai dua helper di atas |
| `alembic/versions/<rev>_siklus_household.py` (baru, Task 13) | DDL yang sama, idempoten, + downgrade |
| `docs/siklus-household.md` (baru), `AGENTS.md`, `CLAUDE.md` | dokumentasi + checklist deploy |

Tes baru: `app/tests/test_period_for_month.py`, `test_household_cycle_schema.py`, `test_rollover_snapshot_values.py`, `test_household_cycle.py`, `test_household_cycle_change.py`, `test_profile_payday.py`, `test_household_cycle_sole_writer.py`, `test_household_join_payday.py`, `test_snapshots_household.py`, `test_scheduler_household_runs.py`, `test_siklus_household_script.py`; `frontend/src/lib/paydayLock.test.js`, `nonRolloverWarning.test.js`.

---

### Task 1: `get_period_for_month`

**Files:**
- Modify: `app/core/period.py` (setelah `get_budget_period`)
- Modify: `app/api/routes/export.py` (`_resolve_period`, cabang `year`+`month`)
- Test: `app/tests/test_period_for_month.py`

**Interfaces:**
- Produces: `get_period_for_month(payday_day: int, year: int, month: int) -> tuple[date, date]` = `get_budget_period(payday_day, _safe_date(year, month, payday_day))`.

- [ ] **Step 1: Tulis tes yang gagal**

```python
class PeriodForMonthTests(unittest.TestCase):
    def test_payday_1_is_calendar_month(self):
        self.assertEqual(get_period_for_month(1, 2026, 2), (date(2026, 2, 1), date(2026, 2, 28)))
    def test_payday_25(self):
        self.assertEqual(get_period_for_month(25, 2026, 1), (date(2026, 1, 25), date(2026, 2, 24)))
    def test_payday_31_across_february_2026(self):
        self.assertEqual(get_period_for_month(31, 2026, 1), (date(2026, 1, 31), date(2026, 2, 27)))
        self.assertEqual(get_period_for_month(31, 2026, 2), (date(2026, 2, 28), date(2026, 3, 30)))
        self.assertEqual(get_period_for_month(31, 2026, 3), (date(2026, 3, 31), date(2026, 4, 29)))
    def test_leap_year(self):
        self.assertEqual(get_period_for_month(30, 2028, 2), (date(2028, 2, 29), date(2028, 3, 29)))
    def test_december_rolls_into_next_year(self):
        self.assertEqual(get_period_for_month(25, 2026, 12), (date(2026, 12, 25), date(2027, 1, 24)))
    def test_export_resolve_period_uses_same_windows(self):
        for p in (1, 15, 25, 28, 29, 30, 31):
            for y in (2026, 2028):
                for m in range(1, 13):
                    user = SimpleNamespace(id=None, payday_day=p)
                    self.assertEqual(_resolve_period(user, year=y, month=m), get_period_for_month(p, y, m))
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `… -m unittest app.tests.test_period_for_month -v` → ImportError `get_period_for_month`.
- [ ] **Step 3: Implementasikan** fungsi di `period.py`; ganti dua baris cabang `y and m` di `export._resolve_period` dengan `return get_period_for_month(payday_day, y, m)` (hapus impor `_safe_date` bila tak terpakai).
- [ ] **Step 4: Jalankan** file tes ini + `app.tests.test_export` → PASS.
- [ ] **Step 5: Commit** — `git add app/core/period.py app/api/routes/export.py app/tests/test_period_for_month.py`; pesan `feat(periode): get_period_for_month (tahun, bulan) → periode payday`.

---

### Task 2: Skema — kolom baru, DDL idempoten, `lifespan`

**Files:**
- Create: `app/services/household_cycle_schema.py`
- Modify: `app/models/models.py` (`Household`, `MonthlySnapshot`)
- Modify: `app/main.py` (blok `if conn.dialect.name == "postgresql":`, setelah loop `KOTAK_DDL`)
- Test: `app/tests/test_household_cycle_schema.py`

**Interfaces:**
- Produces: `HOUSEHOLD_CYCLE_DDL: list[str]` — urutan: `ALTER TABLE households ADD COLUMN IF NOT EXISTS payday_day INTEGER`, `ALTER TABLE monthly_snapshots ADD COLUMN IF NOT EXISTS allocated_amount NUMERIC(15,2)`, `ALTER TABLE monthly_snapshots ADD COLUMN IF NOT EXISTS spent_amount NUMERIC(15,2)`, lalu backfill persis seperti spec bagian 1b (`DISTINCT ON`, owner → admin → member, `created_at`, `WHERE h.id = sub.household_id AND h.payday_day IS NULL`).
- Produces: `Household.payday_day: Mapped[int | None]` (nullable, tanpa default); `MonthlySnapshot.allocated_amount`, `MonthlySnapshot.spent_amount: Mapped[Decimal | None]` (`Numeric(15, 2)`, nullable, tanpa default).

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_household_payday_column_nullable_without_default`: `Household.__table__.c.payday_day.nullable is True` dan `.default is None` dan `.server_default is None`.
  - `test_snapshot_amount_columns`: dua kolom `nullable`, tipe `Numeric` dengan `precision == 15`, `scale == 2`.
  - `test_ddl_additive_and_idempotent`: setiap pernyataan `ALTER` memuat `ADD COLUMN IF NOT EXISTS`; tidak ada `DROP` di pernyataan mana pun; ada tepat satu `UPDATE households` dan memuat `h.payday_day IS NULL`.
  - `test_ddl_covers_every_new_column`: `payday_day`, `allocated_amount`, `spent_amount` masing-masing muncul di sebuah `ALTER`.
  - `test_backfill_orders_owner_admin_member_then_oldest`: teks backfill memuat `WHEN 'owner' THEN 0`, `WHEN 'admin' THEN 1` dan `hm.created_at` (mencerminkan `pick_payday` Task 4).
  - `test_lifespan_runs_household_cycle_ddl`: sumber `app/main.py` memuat `HOUSEHOLD_CYCLE_DDL`.
- [ ] **Step 2: Jalankan, pastikan gagal** (ImportError/AttributeError).
- [ ] **Step 3: Implementasikan** modul DDL, kolom model, dan loop `for stmt in HOUSEHOLD_CYCLE_DDL: await conn.execute(text(stmt))` di `lifespan` (pola `KOTAK_DDL`, `main.py:78-79`).
- [ ] **Step 4: Jalankan** file tes ini → PASS; jalankan seluruh suite backend → tetap hijau (model baru nullable).
- [ ] **Step 5: Commit** — pesan `feat(siklus): kolom households.payday_day + allocated/spent di monthly_snapshots (DDL idempoten)`.

---

### Task 3: `rollover` — nilai snapshot murni, simpan alokasi/pengeluaran, `recompute_household`

**Files:**
- Modify: `app/services/rollover.py`
- Test: `app/tests/test_rollover_snapshot_values.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class SnapshotValues: opening: Decimal; closing: Decimal; rollover: Decimal; allocated: Decimal; spent: Decimal`.
- Produces: `snapshot_values(prev_rollover: Decimal, allocated: Decimal, spent: Decimal, is_rollover: bool) -> SnapshotValues`.
- Produces: `async def recompute_household(household_id, payday_day: int, periods: int, today: date | None = None) -> list[dict]` — `get_closed_periods(payday_day, today or date.today(), periods)` oldest-first; tiap periode `await create_monthly_snapshots(ps, pe, force=True, household_ids=[household_id])`; kembalikan `[{"period": f"{ps} → {pe}", **hasil}, …]` (bentuk respons endpoint `recompute` hari ini). **Hanya** dipanggil lewat `household_cycle.recompute_history` (Task 5).
- `create_monthly_snapshots` memakai `snapshot_values` dan mengisi `allocated_amount=v.allocated`, `spent_amount=v.spent` di `MonthlySnapshot` baru. Perilaku lain tidak berubah.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_identity_opening_minus_allocated_is_rollover_in`: untuk kombinasi `prev ∈ {0, 150000, -50000}`, `alloc ∈ {0, 500000}`, `spent ∈ {0, 400000, 700000}`, `is_rollover ∈ {True, False}`: `v.opening - v.allocated == prev`, `v.closing == v.opening - v.spent`.
  - `test_rollover_carries_closing`: `snapshot_values(D(100000), D(500000), D(400000), True)` → `closing == rollover == D(200000)`.
  - `test_non_rollover_resets_surplus`: sama dengan `False` → `closing == D(200000)`, `rollover == D(0)`.
  - `test_non_rollover_resets_deficit`: `snapshot_values(D(0), D(500000), D(700000), False)` → `closing == D(-200000)`, `rollover == D(0)`.
  - `test_create_monthly_snapshots_stores_allocated_and_spent`: patch `rollover.AsyncSessionLocal` dengan context manager async yang menghasilkan `db_with(FakeResult(rows=[household]), FakeResult(rows=[env]), FakeResult(None), FakeResult(D(100000)), FakeResult(D(400000)), FakeResult(D(500000)))` (urutan kueri: household, amplop, snapshot ada?, rollover sebelumnya, spent, allocated); `env.is_rollover=True`. Snapshot yang di-`db.add`: `allocated_amount == D(500000)`, `spent_amount == D(400000)`, `opening_balance == D(600000)`, `closing_balance == D(200000)`, `rollover_amount == D(200000)`.
  - `test_recompute_household_oldest_first_force_single_household`: patch `rollover.create_monthly_snapshots` (`AsyncMock` → `{"processed": 1, "snapshots_created": 1, "errors": []}`); `await recompute_household(hid, 25, 3, today=date(2026, 10, 31))` → dipanggil tiga kali dengan `(date(2026,7,25), date(2026,8,24))`, `(date(2026,8,25), date(2026,9,24))`, `(date(2026,9,25), date(2026,10,24))`, masing-masing `force=True, household_ids=[hid]`; hasil[0]`["period"] == "2026-07-25 → 2026-08-24"`.
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasikan.**
- [ ] **Step 4: Jalankan** file ini + `test_rollover_key_invariant`, `test_closed_periods`, `test_prediction_rollover` → PASS.
- [ ] **Step 5: Commit** — pesan `feat(rollover): snapshot_values murni, simpan alokasi/pengeluaran, recompute_household`.

---

### Task 4: `household_cycle` — baca, izin, konteks, adopsi, heal

**Files:**
- Create: `app/services/household_cycle.py`
- Test: `app/tests/test_household_cycle.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class MemberRow: user_id; name: str; role; created_at; payday_day: int`.
- Produces: `async def membership(db, user) -> HouseholdMember | None` — satu-satunya kueri keanggotaan di modul ini (titik ubah untuk `ruang_aktif`, spec bagian 10).
- Produces: `async def member_rows(db, household_id) -> list[MemberRow]` — satu kueri `select(HouseholdMember.role, HouseholdMember.created_at, User.id, User.name, User.payday_day).join(User, User.id == HouseholdMember.user_id).where(HouseholdMember.household_id == household_id)`.
- Produces: `def pick_payday(rows: Sequence[MemberRow]) -> int` (murni): peringkat owner 0, admin 1, lainnya 2, lalu `created_at` tertua; payday `None`/0 dianggap 1; tanpa baris → 1.
- Produces: `def can_change_payday(role, member_count: int) -> bool` — enum maupun string.
- Produces: `async def household_payday(db, household, rows: list[MemberRow] | None = None) -> int` — kembalikan `household.payday_day` bila terisi (tanpa kueri); bila `None`: `rows` atau `member_rows(...)`, `pick_payday`, tulis ke `household.payday_day`, `await db.flush()`.
- Produces: `@dataclass class PaydayContext: household; role; payday_day: int; member_count: int; can_change: bool; owner_name: str | None` dan `async def payday_context(db, user) -> PaydayContext | None`. Urutan kueri persis: `membership` → `select(Household).where(Household.id == m.household_id)` → `member_rows`; payday lewat `household_payday(db, household, rows)` (tanpa kueri tambahan). `owner_name` = nama baris ber-peran owner, `None` bila owner itu `user` sendiri atau tidak ada owner.
- Produces: `async def adopt_household_payday(db, user, household) -> int` — `user.payday_day = await household_payday(db, household)`; tidak commit.
- Produces: `async def heal(db, household) -> list[User]` — household dengan `payday_day is None` → `[]` tanpa kueri. Selain itu muat `User` anggota (`select(User).join(HouseholdMember, …).where(HouseholdMember.household_id == household.id)`), samakan yang berbeda, `logger.warning("payday anggota %s menyimpang (%s → %s)", user.id, lama, baru)` per user, `commit` hanya bila ada yang diubah; kembalikan user yang diubah.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_pick_payday_prefers_owner_then_admin_then_oldest`: baris `[member(2026-01-01, 5), admin(2026-02-01, 10), owner(2026-03-01, 25)]` → 25; tanpa owner `[member(2026-01-01, 5), admin(2026-02-01, 10)]` → 10; dua member → yang `created_at` tertua.
  - `test_pick_payday_without_members_is_1`.
  - `test_can_change_payday_matrix`: owner/admin → True untuk 1 dan 3 anggota; member → True untuk 1, False untuk 2; sama untuk `HouseholdRole.member` dan `"member"`.
  - `test_household_payday_stored_value_no_query`: `household.payday_day = 25`, `db_with()` → 25, `db.execute` tidak dipanggil.
  - `test_household_payday_fills_null_from_owner`: `db_with(FakeResult(rows=[(HouseholdRole.member, t1, uid1, "Budi", 1), (HouseholdRole.owner, t2, uid2, "Ani", 25)]))` → 25; `household.payday_day == 25`; `db.flush` di-await.
  - `test_payday_context_member_of_two`: `db_with(FakeResult(member_membership), FakeResult(household_payday_25), FakeResult(rows=[owner Ani 25, member Budi 25]))` → `can_change False`, `member_count 2`, `owner_name "Ani"`, `payday_day 25`.
  - `test_payday_context_owner_has_no_owner_name`: user = owner → `owner_name is None`, `can_change True`.
  - `test_payday_context_without_membership_is_none`: `db_with(FakeResult(None))` → `None`.
  - `test_adopt_sets_user_payday_without_commit`: user payday 1, household payday 25 → kembali 25, `user.payday_day == 25`, `db.commit` tidak di-await.
  - `test_heal_fixes_diverged_members_and_warns`: household 25, anggota `[u1 25, u2 1]` → kembali `[u2]`, `u2.payday_day == 25`, `db.commit` di-await, `assertLogs("jatahku.household_cycle", "WARNING")` memuat `menyimpang`.
  - `test_heal_noop_when_aligned`: → `[]`, `db.commit` tidak di-await.
  - `test_heal_skips_household_without_payday`: `household.payday_day = None` → `[]`, `db.execute` tidak dipanggil.
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasikan.**
- [ ] **Step 4: Jalankan** → PASS.
- [ ] **Step 5: Commit** — pesan `feat(siklus): household_cycle — resolver, izin, konteks, adopsi, heal`.

---

### Task 5: `household_cycle` — ubah payday, recompute serial, notifikasi

**Files:**
- Modify: `app/services/household_cycle.py`
- Test: `app/tests/test_household_cycle_change.py`

**Interfaces:**
- Consumes: Task 3 `rollover.recompute_household`; Task 4 `household_payday`, `member_rows`.
- Produces: `RECOMPUTE_PERIODS_ON_CHANGE = 12`.
- Produces: `async def recompute_history(household_id, periods: int) -> list[dict]` — `async with _lock_for(household_id):` lalu `payday = await _current_payday(household_id)` lalu `return await rollover.recompute_household(household_id, payday, periods)`. `_lock_for` = `asyncio.Lock` per household dalam dict modul. `async def _current_payday(household_id) -> int` membuka `AsyncSessionLocal()` sendiri, memuat household, `household_payday(...)` (mengisi NULL), `commit`.
- Produces: `async def notify_payday_changed(users, *, household_name: str, day: int, changed_by: str | None, periods: int) -> int` — per user `await notification_service.kirim(user, NotificationType.system, "Siklus anggaran rumah berubah", pesan, link="/settings")` (**tanpa** `telegram_html`); pesan sesuai Global Constraints (`changed_by` terisi → pesan owner; `None` → pesan skrip). Setiap kirim di dalam `try/except Exception` → `logger.error`; kembalikan jumlah yang berhasil.
- Produces: `async def set_household_payday(db, household, day: int, *, actor) -> dict` — langkah persis spec bagian 2: `ValueError` bila di luar 1–31; no-op `{"changed": False}` bila sama; assign household + setiap `User` anggota; `commit`; `advisor_cache.invalidate(household.id)`; `recompute_history(household.id, RECOMPUTE_PERIODS_ON_CHANGE)`; `notify_payday_changed([u for u in anggota if u.id != actor.id], household_name=household.name, day=day, changed_by=actor.name, periods=12)`; kembalikan `{"changed": True, "members": len(anggota), "recomputed": len(hasil)}`.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_rejects_out_of_range`: hari 0 dan 32 → `ValueError`, tanpa kueri.
  - `test_same_day_is_noop`: household 25, set 25 → `{"changed": False}`; `recompute_history`, `kirim`, `db.commit` tidak dipanggil.
  - `test_change_syncs_all_members_and_recomputes_12`: household "Rumah Budi" payday 1, anggota `[budi(actor) 1, ani 1]` (`FakeResult(rows=[budi, ani])` untuk `scalars().all()`); patch `household_cycle.recompute_history` (`AsyncMock(return_value=[{}] * 12)`), `household_cycle.advisor_cache.invalidate`, `household_cycle.notification_service.kirim` → `household.payday_day == 25`, `budi.payday_day == ani.payday_day == 25`, `db.commit` di-await, `invalidate` di-await dengan `household.id`, `recompute_history` di-await dengan `(household.id, 12)`, hasil `{"changed": True, "members": 2, "recomputed": 12}`.
  - `test_notifies_members_except_actor`: skenario di atas → `kirim` di-await **sekali**, argumen `(ani, NotificationType.system, "Siklus anggaran rumah berubah", "Tanggal gajian Rumah Budi kini tanggal 25 (diubah Budi). Riwayat 12 periode terakhir dihitung ulang.")`, `link="/settings"`, dan `"telegram_html" not in call.kwargs`.
  - `test_notification_failure_keeps_change`: `kirim` `side_effect=RuntimeError` → hasil tetap `changed True`, `recompute_history` tetap di-await, `assertLogs(..., "ERROR")`.
  - `test_recompute_history_uses_latest_payday`: patch `_current_payday` (`AsyncMock(return_value=25)`) dan `household_cycle.rollover.recompute_household` → di-await dengan `(hid, 25, 12)`.
  - `test_recompute_history_serialises_and_reads_latest_payday`: `_current_payday` `side_effect=[2, 25]`; `recompute_household` palsu mencatat `("start", payday)`, `await asyncio.sleep(0.01)`, `("end", payday)`; jalankan dua `recompute_history(hid, 12)` dengan `asyncio.gather` → log persis `[("start", 2), ("end", 2), ("start", 25), ("end", 25)]`.
  - `test_notify_payday_changed_script_message`: `changed_by=None`, `periods=12`, rumah "Rumah Ani", day 25 → pesan `"Siklus anggaranmu kini mengikuti Rumah Ani: tanggal 25. Riwayat 12 periode terakhir dihitung ulang."`.
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasikan.**
- [ ] **Step 4: Jalankan** `test_household_cycle` + `test_household_cycle_change` → PASS.
- [ ] **Step 5: Commit** — pesan `feat(siklus): set_household_payday, recompute serial per household, notifikasi anggota`.

---

### Task 6: Profil — field baru, PUT payday lewat service, penulis tunggal

**Files:**
- Modify: `app/api/routes/user_settings.py` (`get_profile` ±81-147, `update_profile` ±150-178)
- Test: `app/tests/test_profile_payday.py`, `app/tests/test_household_cycle_sole_writer.py`

**Interfaces:**
- Consumes: Task 4 `payday_context`, `PaydayContext`; Task 5 `set_household_payday`. Impor di level modul `user_settings` (supaya tes bisa `patch.object(user_settings, "payday_context")`).
- `GET /user/profile` menambah `household_payday_day`, `payday_locked`, `payday_owner_name`, `household_name`, `household_member_count` (nilai bawaan tanpa household: spec bagian 3).
- `PUT /user/profile`: bila `req.payday_day is not None`, **sebelum** mengubah apa pun: konteks `None` → 400 `"Belum punya household"`; di luar 1–31 → 400 `"payday_day harus antara 1 dan 31"`; `not ctx.can_change` → 403 (teks Global Constraints, `{nama rumah}` = `ctx.household.name`, `{N}` = `ctx.payday_day`). Lalu field lain seperti sekarang. Lalu: ada payday → `await set_household_payday(db, ctx.household, req.payday_day, actor=user)` (service yang commit, termasuk field lain); tanpa payday → `await db.commit()`. Respons tetap `{"status": "updated"}`.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_member_of_two_gets_403_and_nothing_saved`: ctx `can_change=False` (rumah "Rumah Ani", payday 25); `update_profile(UpdateProfile(name="Baru", payday_day=10), user=user, db=db)` → `HTTPException` 403 dengan detail `"Tanggal gajian mengikuti rumah tangga (Rumah Ani, tanggal 25). Minta owner yang mengubahnya."`; `user.name` tidak berubah; `db.commit` dan `set_household_payday` tidak di-await.
  - `test_owner_change_goes_through_service`: ctx `can_change=True` → `set_household_payday` di-await dengan `(db, ctx.household, 10, actor=user)`; `user.name == "Baru"`.
  - `test_put_payday_without_household_400`: ctx `None` → 400 `"Belum punya household"`.
  - `test_put_payday_out_of_range_400`: 32 → 400 `"payday_day harus antara 1 dan 31"`, `payday_context` boleh dipanggil, tidak ada perubahan tersimpan.
  - `test_other_fields_without_payday_skip_service`: `UpdateProfile(name="X")` → `payday_context` dan `set_household_payday` tidak dipanggil, `db.commit` di-await.
  - `test_profile_includes_household_cycle_fields`: patch `payday_context` (rumah "Rumah Ani", payday 25, 2 anggota, `can_change False`, owner "Ani"); tiga kueri hitung lama dijawab `FakeResult(0)` → respons memuat `household_payday_day 25`, `payday_locked True`, `payday_owner_name "Ani"`, `household_name "Rumah Ani"`, `household_member_count 2`, dan `payday_day` tetap ada.
  - `test_profile_without_household_defaults`: ctx `None`, `user.payday_day = 7` → `household_payday_day 7`, `payday_locked False`, `payday_owner_name None`, `household_name None`, `household_member_count 1`.
  - `test_household_cycle_sole_writer` (file sendiri): pindai `app/**/*.py` selain `app/tests/`; regex `r"\.payday_day\s*=(?!=)"` hanya boleh cocok di `app/services/household_cycle.py`; `r"(?i)\bset\s+payday_day\b"` hanya di `app/services/household_cycle_schema.py`. Pesan gagal menyebut file dan baris.
- [ ] **Step 2: Jalankan, pastikan gagal** (`test_household_cycle_sole_writer` gagal di `user_settings.py:171`).
- [ ] **Step 3: Implementasikan.**
- [ ] **Step 4: Jalankan** dua file ini → PASS; `python3 -m app.scripts.openapi_cek` → tidak ada yang memutus.
- [ ] **Step 5: Commit** — pesan `feat(siklus): profil membawa siklus rumah, PUT payday lewat household_cycle (403 untuk member)`.

---

### Task 7: Join (web + bot) dan `GET /household/`

**Files:**
- Modify: `app/api/routes/household.py` (`HouseholdResponse`, `get_household`, `join_household`)
- Modify: `app/bot/household_cmd.py` (`cmd_join`)
- Test: `app/tests/test_household_join_payday.py`

**Interfaces:**
- Consumes: Task 4 `adopt_household_payday`, `household_payday` (impor level modul di kedua file).
- `HouseholdResponse` + `payday_day: int` (dari `household_payday`).
- `join_household(code: str | None = Query(None), body: JoinRequest | None = Body(None), …)` dengan `class JoinRequest(BaseModel): code: str`; kode = query, kalau kosong body; keduanya kosong → 400 `"Kode invite wajib diisi"`; `strip().upper()`. Setelah `db.add(new_member)`: muat `Household`, `payday = await adopt_household_payday(db, user, household)`, **lalu** `commit`. Respons `{"status": "joined", "household_name": …, "payday_day": payday}`.
- `cmd_join`: sama — muat household dan `adopt_household_payday` sebelum `commit`; pesan sukses menambah baris `"Siklus anggaranmu sekarang mengikuti rumah ini: tanggal {N}."` sebelum baris `/status`.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_join_accepts_code_in_json_body`: `TestClient` atas `FastAPI()` + `household.router` (prefix `/household`), override `get_current_user`/`get_db` (pola reproduksi 422 di spec), patch `household._redis` (redis palsu: `get` → `str(hid).encode()`, `delete`, `close` `AsyncMock`) dan `household.adopt_household_payday` (`AsyncMock(return_value=25)`); `POST /household/join` dengan `json={"code": "abc12def"}` → 200, `json() == {"status": "joined", "household_name": "Rumah Ani", "payday_day": 25}`; redis `get` dipanggil dengan `"invite:ABC12DEF"`.
  - `test_join_still_accepts_query_code`: `POST /household/join?code=ABC12DEF` → 200.
  - `test_join_without_code_400`: tanpa query dan body → 400 detail `"Kode invite wajib diisi"`.
  - `test_join_adopts_before_commit`: rekam urutan panggilan (`adopt` dan `db.commit` dilampirkan ke satu `MagicMock` manajer) → `adopt` sebelum `commit` pertama.
  - `test_get_household_includes_payday_day`: patch `household.household_payday` → 25; respons `payday_day == 25`.
  - `test_cmd_join_adopts_payday_and_mentions_it`: patch `household_cmd.AsyncSessionLocal`, `household_cmd.get_or_create_user`, `household_cmd.adopt_household_payday` (25), redis (`aioredis.from_url`); `update.message.reply_text` di-await dengan teks yang memuat `"Siklus anggaranmu sekarang mengikuti rumah ini: tanggal 25."`; `adopt` sebelum `commit`.
- [ ] **Step 2: Jalankan, pastikan gagal** (tes body → 422).
- [ ] **Step 3: Implementasikan.**
- [ ] **Step 4: Jalankan** → PASS; `openapi_cek` → tidak ada yang memutus (parameter `code` menjadi opsional + body opsional = aditif).
- [ ] **Step 5: Commit** — pesan `fix(household): join web menerima kode di body (422 sebelumnya); anggota baru mengikuti siklus rumah`.

---

### Task 8: Snapshot — `recompute` berizin, `run` per household

**Files:**
- Modify: `app/api/routes/snapshots.py` (`run_monthly_snapshot`, `recompute_snapshots`)
- Test: `app/tests/test_snapshots_household.py`

**Interfaces:**
- Consumes: Task 1 `get_period_for_month`; Task 4 `payday_context`, `household_payday`; Task 5 `recompute_history` (impor level modul).
- `recompute_snapshots(periods, user, db)`: ctx `None` → `{"recomputed": 0, "periods": []}`; `not ctx.can_change` → 403 (teks Global Constraints); selain itu `out = await recompute_history(ctx.household.id, periods)` → `{"recomputed": len(out), "periods": out}`.
- `run_monthly_snapshot(year, month, force, user, db: AsyncSession = Depends(get_db))`: household yang punya anggota (`select(Household).where(Household.id.in_(select(HouseholdMember.household_id)))`); per household `payday = await household_payday(db, h)`, `ps, pe = get_period_for_month(payday, y, m)`, `r = await create_monthly_snapshots(ps, pe, force=force, household_ids=[h.id])`; `await db.commit()` di akhir. Respons `{"households": [{"household_id": str(h.id), "period": f"{ps} → {pe}", **r}, …], "processed": Σ, "snapshots_created": Σ, "errors": [gabungan]}`. Tidak ada pemakai frontend (sudah dicek).

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_recompute_member_of_two_403`: ctx `can_change False` → 403 detail persis; `recompute_history` tidak di-await.
  - `test_recompute_owner_uses_household_history`: ctx `can_change True` → `recompute_history` di-await dengan `(ctx.household.id, 6)`; respons `recomputed == len(out)`.
  - `test_recompute_without_household`: ctx `None` → `{"recomputed": 0, "periods": []}`.
  - `test_run_uses_each_household_payday`: `db_with(FakeResult(rows=[h1, h2]))`; `household_payday` `side_effect=[1, 25]`; `create_monthly_snapshots` `AsyncMock(return_value={"processed": 2, "snapshots_created": 2, "errors": []})`; `year=2026, month=9, force=False` → dipanggil dengan `(date(2026,9,1), date(2026,9,30), force=False, household_ids=[h1.id])` dan `(date(2026,9,25), date(2026,10,24), force=False, household_ids=[h2.id])`; respons `processed == 4`, `snapshots_created == 4`, `households[1]["period"] == "2026-09-25 → 2026-10-24"`; `db.commit` di-await.
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasikan.**
- [ ] **Step 4: Jalankan** → PASS; `openapi_cek` → tidak ada yang memutus.
- [ ] **Step 5: Commit** — pesan `fix(snapshot): recompute hanya owner/admin dengan payday rumah; run admin per household`.

---

### Task 8b: Kompatibilitas dengan Plugin R1 (ruang keluarga vs ruang usaha)

Added to this plan after Plugin R1 (#161) landed on main during implementation and the branch was rebased onto it. Spec authority: section "## 10. Kompatibilitas dengan ruang usaha" of `docs/superpowers/specs/2026-10-31-siklus-household-design.md` — "Saat R1 tayang, `set_household_payday` dan `heal` hanya mencerminkan ke `users.payday_day` untuk household `rumah_tangga`, dan `adopt_household_payday` hanya dipanggil saat bergabung ke ruang keluarga." R1 is now live.

What R1 added (already on the branch): `households.type` VARCHAR(20) NOT NULL DEFAULT 'rumah_tangga' (`Household.type`, constants `HouseholdType.RUMAH_TANGGA = "rumah_tangga"`, `HouseholdType.USAHA = "usaha"` in `app/models/models.py`), unique `(user_id, household_id)` on `household_members` — one user may now belong to several households, at most once each. Today every household is `rumah_tangga` (creating a business space comes later), so these changes must not alter any behaviour for existing data.

**Files:**
- Modify: `app/services/household_cycle.py`
- Modify: `app/api/routes/household.py` (`join_household`), `app/bot/household_cmd.py` (`cmd_join`)
- Test: `app/tests/test_household_cycle_r1.py` (new); update existing assertions in `app/tests/test_household_cycle.py`, `app/tests/test_household_cycle_change.py`, `app/tests/test_household_join_payday.py` only where the changed query/behaviour requires it.

**Interfaces:**
- `membership(db, user)` returns the user's membership in their **ruang keluarga**: `select(HouseholdMember).join(Household, Household.id == HouseholdMember.household_id).where(HouseholdMember.user_id == user.id, Household.type == HouseholdType.RUMAH_TANGGA)`; `scalar_one_or_none()`. (A user has at most one family household; business-space memberships must not make this raise or return the business space.) `payday_context` keeps using it, so profile/recompute act on the family household.
- `def mirrors_users(household) -> bool` (pure): `str(getattr(household, "type", None) or HouseholdType.RUMAH_TANGGA) == HouseholdType.RUMAH_TANGGA` (a household object without `type` — older tests' stubs — counts as family).
- `set_household_payday(db, household, day, *, actor)`: unchanged, except member `users.payday_day` are assigned only when `mirrors_users(household)`; `households.payday_day`, commit, cache invalidation, recompute and notifications are unchanged for both types. Return `"members"` still counts the household's members.
- `heal(db, household)`: when `not mirrors_users(household)` → return `[]` without any query (a business space never changes users' mirrors).
- `join_household` (web) and `cmd_join` (bot): call `adopt_household_payday` only when `mirrors_users(household)`; for a business space keep the join itself and respond with `payday_day` = `await household_payday(db, household)` (web JSON) and omit the "Siklus anggaranmu …" line (bot). (Joining a business space via these invite routes is not possible yet; this keeps the rule correct when it becomes possible.)

- [ ] **Step 1: Tulis tes yang gagal** (`app/tests/test_household_cycle_r1.py`)
  - `test_membership_selects_family_household_only`: compiled SQL of the membership query contains a join to `households` and a `households.type` condition bound to `rumah_tangga` (assert via the statement's compiled params, e.g. `stmt.compile(dialect=postgresql.dialect()).params` contains the value `"rumah_tangga"`).
  - `test_mirrors_users`: `rumah_tangga` → True; `usaha` → False; object without `type` → True; `type=None` → True.
  - `test_set_payday_on_business_space_does_not_touch_users`: household `type="usaha"`, payday 1 → set 25: `household.payday_day == 25`, both member users keep payday 1, commit awaited, `recompute_history` awaited with `(household.id, 12)`.
  - `test_heal_skips_business_space`: `type="usaha"`, payday 25 → `[]`, `db.execute` not called, `db.commit` not awaited.
  - `test_web_join_business_space_does_not_adopt`: TestClient join (pattern of `app/tests/test_household_join_payday.py`) into a household stub with `type="usaha"` → 200, `adopt_household_payday` not awaited, `household_payday` awaited, response `payday_day` = its value, user payday unchanged.
  - `test_bot_join_business_space_does_not_adopt`: same for `cmd_join`; reply has no "Siklus anggaranmu" line.
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasikan.**
- [ ] **Step 4: Jalankan** the new file + `test_household_cycle`, `test_household_cycle_change`, `test_household_join_payday`, `test_profile_payday`, `test_snapshots_household`, `test_ruang_model` → PASS; `python3 -m app.scripts.openapi_cek` → no breaking change; full backend suite once.
- [ ] **Step 5: Commit** — pesan `feat(siklus): siklus hanya dicerminkan ke user untuk ruang keluarga (kompatibel Plugin R1)`.

---

### Task 9: Job snapshot harian per household

**Files:**
- Modify: `app/services/scheduler.py` (`payday_snapshot_job`; tambah `household_runs`)
- Test: `app/tests/test_scheduler_household_runs.py`

**Interfaces:**
- Consumes: Task 4 `household_payday`, `heal`; `rollover.create_monthly_snapshots`; `period.get_closed_periods`.
- Produces: `def household_runs(rows: list[tuple[uuid.UUID, int]], today: date, catch_up: int) -> list[tuple[uuid.UUID, int, list[tuple[date, date]]]]` (murni, urutan input dipertahankan, periode oldest-first).
- `payday_snapshot_job()`: satu sesi `AsyncSessionLocal()`: household yang punya anggota (kueri sama dengan Task 8); per household `payday = await household_payday(db, h)`, `await heal(db, h)`; `await db.commit()`; tutup sesi; lalu untuk setiap `(hid, payday, periods)` dari `household_runs(…, date.today(), CATCH_UP_PERIODS)`: `create_monthly_snapshots(ps, pe, household_ids=[hid])` (tanpa `force`), log seperti sekarang dengan `household=%s payday=%s`.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_household_runs_one_window_per_household`: `household_runs([(h1, 1), (h2, 25)], date(2026, 10, 31), 3)` → `[(h1, 1, [(2026-07-01, 2026-07-31), (2026-08-01, 2026-08-31), (2026-09-01, 2026-09-30)]), (h2, 25, [(2026-07-25, 2026-08-24), (2026-08-25, 2026-09-24), (2026-09-25, 2026-10-24)])]`.
  - `test_job_heals_and_snapshots_per_household`: patch `scheduler`-side `AsyncSessionLocal` (context manager → `db_with(FakeResult(rows=[h1, h2]))`), `household_cycle.household_payday` (`side_effect=[1, 25]`), `household_cycle.heal` (`AsyncMock(return_value=[])`), `rollover.create_monthly_snapshots`, dan `date` (`fixed_date(date(2026, 10, 31))`) → `heal` di-await dua kali; `create_monthly_snapshots` di-await 6 kali, setiap panggilan `household_ids` berisi tepat satu id, h1 hanya dengan periode payday 1 dan h2 hanya payday 25.
  - `test_job_only_households_with_members`: SQL kueri household (pakai `executed_sql(db)`) memuat `household_members`.
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasikan** (impor tetap di dalam fungsi, pola modul ini; patch di tes mengikuti tempat impor).
- [ ] **Step 4: Jalankan** → PASS.
- [ ] **Step 5: Commit** — pesan `fix(scheduler): snapshot harian per household dengan satu jendela; heal payday anggota`.

---

### Task 10: Skrip migrasi data `siklus_household`

**Files:**
- Create: `app/scripts/siklus_household.py`
- Test: `app/tests/test_siklus_household_script.py`

**Interfaces:**
- Consumes: Task 4 `member_rows`, `pick_payday`, `household_payday`, `heal`; Task 5 `recompute_history`, `notify_payday_changed`.
- Produces: `@dataclass class HouseholdSurvey: household; members: list[MemberRow]; target_payday: int; mixed: bool`.
- Produces: `async def survey(db) -> list[HouseholdSurvey]` — household yang punya anggota; `target_payday = household.payday_day or pick_payday(members)`; `mixed = len({m.payday_day for m in members}) > 1`. Tidak menulis apa pun.
- Produces: `def format_survey(surveys) -> str` — satu baris per household: id, nama, jumlah anggota, payday anggota, target, `CAMPURAN` bila mixed; baris ringkas akhir `"{n} household, {k} campuran"`.
- Produces: `async def apply(db, surveys, periods: int) -> dict` — per household: `household_payday`, `changed = await heal(db, h)`, `out = await recompute_history(h.id, periods)`, bila `changed`: `notify_payday_changed(changed, household_name=h.name, day=payday, changed_by=None, periods=periods)`; kembalikan `{"households": n, "mixed": k, "snapshots": Σ snapshots_created, "notified": Σ}`.
- Produces: `def main(argv=None) -> int` — `argparse`: `--apply` (tanpa itu = dry-run), `--periods` (default 12); `python3 -m app.scripts.siklus_household`; pakai `AsyncSessionLocal` dan `asyncio.run`; cetak `format_survey` lalu (bila `--apply`) ringkasan `apply`.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_survey_marks_mixed`: anggota payday 1 dan 25 → `mixed True`, `target_payday` = payday household (atau owner bila NULL).
  - `test_survey_skips_households_without_members`: kueri household memuat `household_members` (via `executed_sql`).
  - `test_dry_run_writes_nothing`: `main([])` dengan sesi palsu → `apply` tidak dipanggil, `db.commit` tidak di-await.
  - `test_apply_heals_recomputes_and_notifies_changed_only`: dua household; `heal` mengembalikan `[budi]` untuk yang pertama dan `[]` untuk yang kedua → `recompute_history` di-await untuk keduanya dengan `periods=12`; `notify_payday_changed` di-await sekali dengan `[budi]`, `changed_by=None`.
  - `test_apply_twice_is_idempotent`: panggilan kedua (`heal` → `[]`) → `notify_payday_changed` tidak di-await.
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasikan** (pola `app/scripts/kotak_corpus.py`).
- [ ] **Step 4: Jalankan** → PASS.
- [ ] **Step 5: Commit** — pesan `feat(siklus): skrip migrasi siklus_household (--dry-run / --apply)`.

---

### Task 11: Settings — kunci payday, konfirmasi owner, pesan join

**Files:**
- Create: `frontend/src/lib/paydayLock.js`, `frontend/src/lib/paydayLock.test.js`
- Modify: `frontend/src/pages/Settings.jsx` (kartu "📅 Tanggal Gajian" ±790-810, `savePaydayDay` ±445, `joinHousehold` ±495)

**Interfaces:**
- Consumes: field profil Task 6; `payday_day` respons join Task 7.
- Produces: `paydayLockState(profile) -> { locked: boolean, note: string | null, needsConfirm: boolean, confirmText: string | null }` — `locked = !!profile.payday_locked`; `note` teks terkunci (dengan/tanpa nama owner) bila `locked`; `needsConfirm = !locked && (profile.household_member_count ?? 1) > 1`; `confirmText` teks konfirmasi dengan `household_name` bila `needsConfirm`. `N` = `profile.household_payday_day ?? profile.payday_day`.
- Produces: `joinSuccessMessage(householdName, paydayDay) -> string` — dengan `paydayDay` → flash lengkap; tanpa → `"Berhasil bergabung ke {nama}!"` (perilaku lama).
- Settings: terkunci → teks `note` menggantikan input (tidak pernah mengirim `payday_day`); `needsConfirm` → input + tombol **Simpan** yang membuka dialog in-app (pola modal `showReset`, `Settings.jsx:371/976`) berisi `confirmText`, tombol Batal/Lanjutkan; sendirian → simpan saat berubah dengan debounce 600 ms. Respons PUT tidak `ok` → `flashErr(detail)`. Setelah simpan/join → `load()`.

- [ ] **Step 1: Tulis tes yang gagal** (`node:test`): `locked member shows owner note` (`{payday_locked: true, household_payday_day: 25, payday_owner_name: "Ani"}` → `note === "Mengikuti siklus rumah tangga: tanggal 25 (diatur Ani)."`, `needsConfirm false`); `locked without owner name`; `owner of two needs confirm` (`{payday_locked: false, household_member_count: 2, household_name: "Rumah Ani"}` → `confirmText === "Mengubah tanggal gajian berlaku untuk semua anggota Rumah Ani, dan 12 periode terakhir dihitung ulang. Lanjutkan?"`); `solo saves directly` (`household_member_count: 1` → `needsConfirm false`, `locked false`); `old profile without new fields is unlocked solo`; `joinSuccessMessage with and without payday`.
- [ ] **Step 2: Jalankan, pastikan gagal** — `cd frontend && node --test src/lib/paydayLock.test.js`.
- [ ] **Step 3: Implementasikan** helper, lalu sambungkan ke `Settings.jsx`.
- [ ] **Step 4: Jalankan** tes helper → PASS; `node --test src/lib/*.test.js src/native/*.test.js` → hijau; `npm run build` → sukses; `git checkout -- frontend/dist`.
- [ ] **Step 5: Commit** — pesan `feat(settings): tanggal gajian mengikuti rumah tangga (kunci, konfirmasi owner, pesan join)`.

---

### Task 12: Alokasi — peringatan amplop non-rollover

**Files:**
- Create: `frontend/src/lib/nonRolloverWarning.js`, `frontend/src/lib/nonRolloverWarning.test.js`
- Modify: `frontend/src/pages/Allocate.jsx` (baris amplop di form, ±411-438)

**Interfaces:**
- Produces: `nonRolloverWarning(env, periodEnd, today, amount) -> string | null` — `periodEnd` `"YYYY-MM-DD"`, `today` `"YYYY-MM-DD"` atau `Date` (pakai tanggal lokal); hitung selisih hari sebagai tanggal kalender (UTC dari komponen, tanpa pergeseran zona); `null` bila `env.is_rollover !== false`, `!(Number(amount) > 0)`, `!periodEnd`, `n < 0`, atau `n > 7`; selain itu teks Global Constraints.
- Allocate: di bawah baris "🔄 Min" amplop, tampilkan teks bila tidak `null`, dengan `periodEnd = periods[periods.length - 1]?.period_end` dan `amount = allocations[env.id]`; gaya `text-xs text-amber-600`.

- [ ] **Step 1: Tulis tes yang gagal**: `rollover envelope never warns`; `non-rollover 3 days before end` (`{is_rollover: false}`, `"2026-11-24"`, `"2026-11-21"`, 100000 → `"Amplop ini tidak membawa sisa ke periode berikutnya. Yang tidak terpakai di-reset 24 Nov (3 hari lagi)."`); `on the last day says hari ini`; `8 days before end is silent`; `zero amount is silent`; `missing is_rollover field is silent`; `month names` (`"2026-08-31"` → `"31 Agu"`).
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasikan** helper lalu sambungkan ke `Allocate.jsx`.
- [ ] **Step 4: Jalankan** tes helper → PASS; seluruh tes frontend + `npm run build` → hijau; `git checkout -- frontend/dist`.
- [ ] **Step 5: Commit** — pesan `feat(alokasi): peringatan amplop non-rollover menjelang akhir periode`.

---

### Task 13: Alembic, dokumentasi, verifikasi akhir

**Files:**
- Create: `alembic/versions/<rev>_siklus_household.py` (rev = 12 hex acak, `down_revision` = `alembic heads` saat itu)
- Create: `docs/siklus-household.md`
- Modify: `AGENTS.md` (bagian baru "Deploy Checklist — Siklus anggaran per household (<rev>)" sebelum "## Aplikasi mobile"), `CLAUDE.md` ("Key Decisions", satu baris)
- Modify: `docs/superpowers/specs/2026-10-31-siklus-household-design.md` (Status), Project doc `claude/siklus-household-desain.md`
- Test: tidak ada file baru; verifikasi seluruh suite

**Interfaces:**
- Consumes: Task 2 `HOUSEHOLD_CYCLE_DDL`.
- Revisi: `upgrade()` menjalankan setiap pernyataan `HOUSEHOLD_CYCLE_DDL` (`op.execute`), idempoten; `downgrade()` `ALTER TABLE … DROP COLUMN IF EXISTS` untuk tiga kolom (tanpa `DROP TYPE`).

- [ ] **Step 1: Segarkan branch** — `git fetch origin main && git rebase origin/main`; selesaikan konflik (pertahankan perubahan kedua sisi); jalankan ulang seluruh suite backend.
- [ ] **Step 2: Buat revisi** dari head saat itu; `alembic heads` → tepat satu (revisi baru).
- [ ] **Step 3: Dokumentasi** — `docs/siklus-household.md` (perilaku final: sumber kebenaran, penulis tunggal, izin, recompute serial, job, skrip, kompatibilitas ruang usaha; pola `docs/kotak-struk.md`); checklist `AGENTS.md` dari spec bagian 9 dengan nomor revisi, perintah `sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.siklus_household` (`--dry-run` dulu, lalu `--apply`), dan cek pemilik tabel `households`/`monthly_snapshots` (query pemilik tabel di checklist Kotak Struk); baris `CLAUDE.md`: `- Siklus anggaran milik household: households.payday_day (owner menentukan), users.payday_day = cermin; penulis tunggal services/household_cycle.py`.
- [ ] **Step 4: Verifikasi** — seluruh suite backend → OK; `python3 -m app.scripts.openapi_cek` → tidak ada yang memutus; `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build` → hijau; `git checkout -- frontend/dist`; `git status` bersih kecuali file tugas ini.
- [ ] **Step 5: Commit** — stage revisi, `docs/siklus-household.md`, `AGENTS.md`, `CLAUDE.md`, spec (`git add -f`); pesan `docs(siklus): revisi alembic, checklist deploy, dokumentasi`. Perbarui Project doc spec (`project_write`) dengan status terbaru.
