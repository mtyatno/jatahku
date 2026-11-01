# Laporan berkala tahap 1 (inti) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Laporan bulanan beku per user terbit otomatis di hari gajian, bisa dibaca di halaman desktop, layar ringkas HP,
dan diunduh sebagai PDF ber-AES-256 dengan kata sandi laporan yang diatur user; lonceng + Telegram memberi tahu.

**Architecture:** Paket baru `app/services/laporan/` dengan pola advisor: `muat.py` (satu-satunya yang membaca DB untuk
isi laporan) → `hitung.py` + `susun.py` (fungsi murni, tanpa DB) → `data` JSON beku di tabel `reports`. `job.py`
(cron tiap jam menit 30, di dalam `household_lock`) menerbitkan dan memberi tahu; `pdf.py` membuat PDF dari `data`
saat diminta; `rahasia.py` mengenkripsi kata sandi dengan Fernet. Route `app/api/routes/laporan.py`, halaman React
`/laporan` dan `/laporan/:id`.

**Tech Stack:** FastAPI, SQLAlchemy async (Postgres di produksi; tes memakai `app/tests/fakes.py` dan SQLite
`aiosqlite`), APScheduler, fpdf2 2.8.9, cryptography 50.0.2 (Fernet), pypdfium2 (sudah ada, untuk tes), React 18 +
recharts, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-01-laporan-berkala-design.md` (Project doc `claude/laporan-berkala-desain.md`).
Rencana ini = tahap 1 bagian 11 spec. Tahap 2 (email) dan 3 (kuartalan/tahunan) mendapat rencana sendiri setelah tahap
1 tayang.

## Global Constraints

- Branch `feat/laporan-berkala` dari `main` terbaru; satu PR berlabel `migrasi`. Sesi lain berjalan paralel: perubahan
  di `models.py`, `main.py`, `AGENTS.md`, `scheduler.py` hanya **menambah**; revisi alembic dibuat terakhir (Task 11)
  dari `main` segar, `alembic heads` harus tetap satu.
- Git: jangan `git add -A`; stage file satu per satu; jangan commit `frontend/dist/` (setelah build:
  `git checkout -- frontend/dist`); file di `docs/superpowers/` di-gitignore → `git add -f`.
- Akhir setiap pesan commit:
  ```
  Co-Authored-By: <nama model sendiri> <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_017DL2c6KwEzKSaXsjUN4PBR
  ```
- API hanya bertambah; `python3 -m app.scripts.openapi_cek` → "Tidak ada perubahan API yang memutus".
- Kontrak visibilitas (`AGENTS.md` "Household Visibility Contract"): deskripsi transaksi hanya lewat
  `visibility.masked_description(viewer_id, txn)`; agregat menghitung semua transaksi.
- Pagar R2 (`app/tests/test_ruang_pagar.py`): file baru tidak boleh memuat teks `HouseholdMember.user_id ==`; route
  non-GET baru harus masuk kelompok yang dikenal (tahap 1 hanya `PUT /user/laporan-pengaturan`, lolos lewat awalan
  `/user/`).
- Tanpa rumus angka advisor baru (aturan "satu sumber angka"): angka per amplop dari `monthly_snapshots`; amplop tanpa
  snapshot lewat `rollover.calculate_envelope_balance` + `get_previous_rollover` + `snapshot_values`.
- Paket: `fpdf2==2.8.9`, `cryptography==50.0.2` di `requirements.txt`.
- Konstanta: `JENDELA_TERBIT_HARI = 7`, `AMBANG_HAMPIR_HABIS = Decimal("0.7")`, `MAKS_PDF_SERENTAK = 2`, job menit 30,
  batas unduh PDF `10/minute`, batas simpan kata sandi `5/hour`, kata sandi 6–64 karakter, daftar laporan `limit`
  bawaan 24 maks 100, mutasi web 50 baris per langkah.
- Logger: `logging.getLogger("jatahku.laporan")`.
- Teks (Bahasa Indonesia, persis):
  - Notifikasi: judul `"{judul} siap"`, pesan `"Lihat bagaimana periode kemarin berjalan."`, tautan
    `/laporan/{id}`; Telegram: `"<b>{judul} siap</b>\nLihat bagaimana periode kemarin berjalan.\n<a href=\"{APP_URL}/laporan/{id}\">Buka laporan</a>"` (judul di-`html.escape`).
  - 404: `"Laporan tidak ditemukan"`. 409: `{"detail": "Atur kata sandi laporan dulu untuk mengunduh PDF.", "kode": "kata_sandi_belum_diatur"}`.
    503: `{"detail": "Kata sandi laporan belum bisa dipakai di server. Coba lagi nanti.", "kode": "kunci_belum_diatur"}`.
  - Judul bagian (halaman dan PDF): `Ringkasan`, `Amplop`, `Dibanding periode lalu`, `Pola harian`,
    `5 pengeluaran terbesar`, `Langganan`, `Sorotan`, `Lampiran: mutasi`.
  - Status: `aman`→`Aman`, `hampir_habis`→`Hampir habis`, `lewat_batas`→`Lewat batas`, `tabungan`→`Tabungan`,
    `kosong`→`Kosong`.
  - Banner: `"Atur kata sandi laporan untuk mengunduh PDF."` (tautan `/settings#laporan`). Kosong:
    `"Belum ada laporan. Laporan pertama terbit di hari gajian setelah periode berjalan tutup."`
  - Tombol: `Unduh PDF`; top bar ekspor manual: `Ekspor` / `Ekspor {periode}`.
  - Pengaturan: judul kartu `📄 Laporan`; status `"Kata sandi laporan sudah diatur."` / `"Belum ada kata sandi laporan."`;
    tombol `Atur kata sandi` / `Ganti kata sandi`; sukses `"Kata sandi laporan disimpan"`.
  - Footer PDF: `"Halaman {n} dari {nb}"` dan `"Dibuat otomatis oleh Jatahku"`; header memuat `"Angka per {tgl}"`.
- Tes backend tanpa Postgres: fungsi murni, `db_with(...)`/`FakeResult`/`fixed_date` dari `app/tests/fakes.py`, atau
  SQLite (`sqlite+aiosqlite://`, `StaticPool`, `PRAGMA foreign_keys=ON`, `Base.metadata.create_all` — pola
  `app/tests/test_account_deletion.py:66-105`).
- Perintah tes: `DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python3 -m unittest app.tests.<modul> -v`;
  semua `… python3 -m unittest discover -s app/tests -t .` (satu kegagalan lama yang diterima:
  `test_fund_shift_integration…test_basic_quota_bot_fund_shift_finishes_started_input`, gagal tiap tanggal 1);
  frontend `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`.

## Keputusan rencana (penyesuaian terhadap spec; disinkronkan ke spec di Task 11)

1. **Batas frekuensi** memakai slowapi dengan kunci per user `transactions.transcribe_key_func` (hash header
   Authorization, di memori, satu proses) — pola `/transactions/transcribe`; bukan penghitung Redis baru.
2. **Langganan terbayar** = transaksi di jendela laporan yang deskripsinya diawali penanda `BILL_MARKER` (`"🔄 "`,
   `app/services/advisor/snapshot.py:28`, dibuat tombol Bayar), bukan `compute_bills` (membaca `next_run` saat ini).
3. **Tahap 1 membiarkan `email_status` NULL**; tahap 2 hanya mengisi status untuk laporan yang terbit setelah tahap 2
   tayang, jadi tidak ada email tertunda untuk laporan lama.
4. **FK:** `reports.user_id` `ON DELETE CASCADE`, `reports.household_id` `ON DELETE SET NULL` (laporan mantan anggota
   tetap ada saat household dihapus), `report_settings.user_id` `CASCADE`; ditambah penanganan eksplisit di hapus/gabung
   akun.
5. **`data.email`** (ringkasan tanpa nominal) sudah dihitung di tahap 1, beku bersama laporan.
6. **Prasyarat snapshot** = ada ≥ 1 snapshot kunci periode itu di antara amplop household; job snapshot menulis satu
   household di bawah `household_lock` yang sama.
7. **Kata sandi tersimpan yang tidak terbaca** (kunci diganti) diperlakukan seperti belum diatur (409) dan dicatat warning.

## Review Focus

1. Amplop pribadi anggota lain atau deskripsi privatnya muncul di laporan user lain → tes lingkup dan penyamaran di
   Task 4, tes IDOR di Task 7.
2. Emoji atau karakter di luar font (nama amplop, penanda `🔄`, panah) di PDF → tes `teks_pdf` dan render di Task 6.
3. Ratusan transaksi dalam satu periode → tes PDF multi-halaman dan waktu render di Task 6; mutasi web bertahap di
   Task 10.
4. Tanggal gajian 29–31, Februari, dan pergantian tahun (judul, nama file, periode berikutnya) → tes Task 2 dan Task 4.
5. `REPORT_SECRET_KEY` kosong, tidak valid, atau diganti → tes Task 1 dan Task 7 (503, 409 untuk token tak terbaca).

## Struktur berkas

| Berkas | Tanggung jawab |
|---|---|
| `app/services/laporan/__init__.py` | paket kosong |
| `app/services/laporan/schema.py` | `LAPORAN_DDL` (kolom `users.email_verified_at`) |
| `app/services/laporan/rahasia.py` | Fernet: enkripsi/dekripsi kata sandi, cek kunci saat startup |
| `app/services/laporan/hitung.py` | fungsi murni: judul, nama file, status, lewat batas, beruntun, persen, uang, sorotan |
| `app/services/laporan/susun.py` | dataclass bahan + `susun_bulanan` → `data` v1 (murni) |
| `app/services/laporan/muat.py` | satu-satunya pembaca DB untuk isi laporan → `BahanLaporan` |
| `app/services/pemasukan.py` | filter pemasukan bersama (dipakai analitik dan laporan) |
| `app/services/laporan/job.py` | penerbitan per household, notifikasi |
| `app/services/laporan/pdf.py` + `app/assets/fonts/` | PDF dari `data`, AES-256 |
| `app/api/routes/laporan.py` | `/laporan`, `/laporan/{id}`, `/laporan/{id}/pdf`, `/user/laporan-pengaturan` |
| `frontend/src/lib/laporanView.js` | helper murni halaman + alur unduh |
| `frontend/src/hooks/useMediaQuery.js` | hook bersama (dipindah dari `Envelopes.jsx`) |
| `frontend/src/pages/Laporan.jsx`, `LaporanDetail.jsx`, `frontend/src/components/laporan/*`, `components/LaporanSettings.jsx` | UI |

---

### Task 1: Model, skema, dan kunci rahasia

**Files:**
- Modify: `app/models/models.py` (User + dua kelas baru di akhir file), `app/core/config.py` (sebelum `model_config`),
  `app/main.py` (lifespan: setelah loop `HOUSEHOLD_CYCLE_DDL`, dan setelah `email_service.check_configured()`),
  `requirements.txt`
- Create: `app/services/laporan/__init__.py`, `app/services/laporan/schema.py`, `app/services/laporan/rahasia.py`
- Test: `app/tests/test_laporan_model.py`, `app/tests/test_laporan_rahasia.py`

**Interfaces:**
- Produces:
  - `User.email_verified_at: Mapped[datetime | None]` (`DateTime(timezone=True)`, nullable).
  - `Report` (`__tablename__ = "reports"`): `id` UUID PK; `user_id` FK `users.id` `ondelete="CASCADE"`;
    `household_id` FK `households.id` `ondelete="SET NULL"`, nullable; `jenis: String(16)`; `periode_mulai`,
    `periode_akhir: Date`; `payday_day: Integer`; `data`: `JSON().with_variant(JSONB(), "postgresql")`; `terbit_at`
    `DateTime(tz)` `server_default=func.now()`; `notified_at`, `email_terakhir_at`, `email_terkirim_at` `DateTime(tz)`
    nullable; `email_status: String(16)` nullable; `email_alasan: String(32)` nullable; `email_percobaan: Integer`
    `default=0, server_default="0"`. `__table_args__`: `UniqueConstraint("user_id", "jenis", "periode_mulai",
    name="uq_reports_user_jenis_periode")`, `Index("ix_reports_email_antrean", "email_status", "email_terakhir_at")`.
  - `ReportSettings` (`"report_settings"`): `user_id` UUID PK + FK `users.id` `ondelete="CASCADE"`;
    `kata_sandi_enc: Text` nullable; `email_on`, `kuartalan_on`, `tahunan_on: Boolean` `default=True,
    server_default=text("true")`; `updated_at` `DateTime(tz)` `server_default=func.now(), onupdate=func.now()`.
  - `JENIS_BULANAN = "bulanan"` (konstanta di `models.py` dekat kelas `Report`).
  - `schema.LAPORAN_DDL: list[str] = ["ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP WITH TIME ZONE"]` (modul tanpa import).
  - `config.Settings.REPORT_SECRET_KEY: str = ""` (komentar: kunci Fernet, hanya dari `/opt/jatahku/.env`).
  - `rahasia.KunciLaporanTidakAda(RuntimeError)`; `rahasia.kunci_tersedia() -> bool`; `rahasia.enkripsi(kata_sandi: str) -> str`;
    `rahasia.dekripsi(token: str) -> str` (kunci tidak ada → `KunciLaporanTidakAda`; token tak terbaca → `ValueError`);
    `rahasia.check_configured() -> bool` (kosong/tidak valid → `logger.warning("REPORT_SECRET_KEY kosong atau tidak valid: kata sandi dan PDF laporan nonaktif")`, return False).

- [ ] **Step 1: Tulis tes yang gagal**

```python
# test_laporan_model.py
def test_reports_table_contract(self):
    t = Report.__table__
    self.assertIn("uq_reports_user_jenis_periode", {c.name for c in t.constraints})
    self.assertIn("ix_reports_email_antrean", {i.name for i in t.indexes})
    self.assertEqual(next(iter(t.c.household_id.foreign_keys)).ondelete, "SET NULL")
    self.assertEqual(next(iter(t.c.user_id.foreign_keys)).ondelete, "CASCADE")
    self.assertTrue(t.c.email_status.nullable)
def test_report_settings_defaults(self): ...  # server_default true untuk tiga toggle; kata_sandi_enc nullable
def test_users_email_verified_at_column_and_ddl(self):
    self.assertTrue(User.__table__.c.email_verified_at.nullable)
    self.assertTrue(all("IF NOT EXISTS" in s for s in LAPORAN_DDL))
def test_lifespan_runs_laporan_ddl_and_key_check(self):
    src = inspect.getsource(main.lifespan)
    self.assertIn("for stmt in LAPORAN_DDL", src); self.assertIn("rahasia.check_configured()", src)
# test_laporan_rahasia.py (patch rahasia.get_settings → SimpleNamespace(REPORT_SECRET_KEY=Fernet.generate_key().decode()))
def test_roundtrip(self):
    token = enkripsi("rahasia-é1")
    self.assertEqual(dekripsi(token), "rahasia-é1")
    self.assertNotIn("rahasia", token)
def test_missing_key(self): ...  # REPORT_SECRET_KEY="" → kunci_tersedia() False; enkripsi/dekripsi → KunciLaporanTidakAda
def test_invalid_key(self): ...  # "bukan-kunci" → kunci_tersedia() False
def test_token_from_other_key_is_value_error(self): ...
def test_check_configured_warns_without_secret(self): ...  # assertLogs("jatahku.laporan","WARNING"); kata sandi tidak pernah ada di log
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `… -m unittest app.tests.test_laporan_model app.tests.test_laporan_rahasia -v` → ImportError.
- [ ] **Step 3: Implementasikan** semua yang ada di Interfaces; `requirements.txt` + `fpdf2==2.8.9` dan `cryptography==50.0.2`; `pip install --break-system-packages fpdf2==2.8.9 cryptography==50.0.2` lokal.
- [ ] **Step 4: Jalankan tes Task 1 + `app.tests.test_ruang_model`** → PASS.
- [ ] **Step 5: Commit** — `feat(laporan): tabel reports, report_settings, email_verified_at, kunci Fernet`.

### Task 2: Perhitungan murni

**Files:** Create `app/services/laporan/hitung.py`; Test `app/tests/test_laporan_hitung.py`

**Interfaces:**
- Produces (semua murni): `BULAN` (nama lengkap, indeks 1–12: Januari … Desember), `BLN` (Jan Feb Mar Apr Mei Jun Jul
  Agu Sep Okt Nov Des); `adalah_bulan_kalender(ps: date, pe: date) -> bool`; `judul_bulanan(ps, pe) -> str`;
  `nama_file_pdf(jenis: str, ps: date, pe: date) -> str`; `AMBANG_HAMPIR_HABIS`; `status_amplop(tujuan: str, awal:
  Decimal, terpakai: Decimal, akhir: Decimal) -> str`; `pernah_lewat_batas(rollover_masuk: Decimal, alokasi_per_hari:
  dict[date, Decimal], belanja_per_hari: dict[date, Decimal], ps: date, pe: date) -> bool`;
  `beruntun_terpanjang(tanggal: Iterable[date]) -> int`; `persen(bagian: Decimal, total: Decimal) -> int | None`
  (ROUND_HALF_UP, None bila total ≤ 0); `persen_perubahan(sekarang: Decimal, lalu: Decimal | None) -> int | None`;
  `rata_rata(nilai: list[Decimal | None]) -> Decimal | None`; `uang(x: Decimal) -> str` (2 desimal, ROUND_HALF_UP);
  `teks_sorotan(beruntun: int, amplop_aman: int, hari_mencatat: int) -> str`.

Aturan yang tidak ditentukan tanda tangan:
- `status_amplop` berurutan: `tujuan` ∈ {`saving`, `sinking_fund`} → `tabungan`; `akhir < 0` → `lewat_batas`;
  `awal <= 0` → `kosong`; `terpakai >= AMBANG_HAMPIR_HABIS * awal` → `hampir_habis`; selain itu `aman`.
- `pernah_lewat_batas`: saldo = `rollover_masuk`; tiap hari dari `ps` sampai `pe` tambah alokasi hari itu, kurangi
  belanja hari itu; True bila saldo akhir hari mana pun < 0.
- `teks_sorotan`: `beruntun >= 7` → `"Mencatat {beruntun} hari berturut-turut"`; elif `amplop_aman >= 1` →
  `"{amplop_aman} amplop tidak pernah lewat batas"`; elif `hari_mencatat >= 1` → `"Mencatat di {hari_mencatat} hari"`;
  else `"Siap untuk periode berikutnya"`.
- Judul: bulan kalender → `"Laporan {BULAN[m]} {y}"`; tahun sama → `"Laporan {d1} {BLN} – {d2} {BLN} {y}"`; beda tahun →
  `"Laporan {d1} {BLN} {y1} – {d2} {BLN} {y2}"` (en dash U+2013). Nama file: kalender → `jatahku-laporan-YYYY-MM.pdf`,
  selain itu `jatahku-laporan-YYYY-MM-DD.pdf` (tanggal awal); jenis selain `bulanan` → `ValueError` (tahap 3 menambah).

- [ ] **Step 1: Tulis tes yang gagal**

```python
def test_judul(self):
    self.assertEqual(judul_bulanan(date(2026,10,1), date(2026,10,31)), "Laporan Oktober 2026")
    self.assertEqual(judul_bulanan(date(2026,9,25), date(2026,10,24)), "Laporan 25 Sep – 24 Okt 2026")
    self.assertEqual(judul_bulanan(date(2026,12,25), date(2027,1,24)), "Laporan 25 Des 2026 – 24 Jan 2027")
    self.assertEqual(judul_bulanan(date(2026,1,31), date(2026,2,27)), "Laporan 31 Jan – 27 Feb 2026")
def test_nama_file(self):
    self.assertEqual(nama_file_pdf("bulanan", date(2026,10,1), date(2026,10,31)), "jatahku-laporan-2026-10.pdf")
    self.assertEqual(nama_file_pdf("bulanan", date(2026,9,25), date(2026,10,24)), "jatahku-laporan-2026-09-25.pdf")
def test_status_amplop(self):  # subTest tiap baris
    for args, exp in [(("saving", D(100), D(200), D(-100)), "tabungan"), (("expense", D(100), D(150), D(-50)), "lewat_batas"),
                      (("expense", D(0), D(0), D(0)), "kosong"), (("expense", D(100), D(70), D(30)), "hampir_habis"),
                      (("expense", D(100), D(69), D(31)), "aman")]: ...
def test_pernah_lewat_batas(self):  # belanja 120 pada 3 Okt, alokasi 100 pada 1 Okt dan 50 pada 5 Okt → True; tanpa belanja 120 → False;
    ...                             # alokasi dan belanja di hari yang sama (100/100) → False
def test_beruntun(self):
    self.assertEqual(beruntun_terpanjang([]), 0)
    self.assertEqual(beruntun_terpanjang([d(1), d(2), d(3), d(5), d(6)]), 3)  # d(n) = date(2026, 10, n)
def test_persen_dan_uang(self):
    self.assertEqual(persen(D("1"), D("3")), 33)
    self.assertIsNone(persen(D(5), D(0)))
    self.assertEqual(persen_perubahan(D(88), D(100)), -12)
    self.assertIsNone(persen_perubahan(D(5), None))
    self.assertEqual(uang(D("1.005")), "1.01")
def test_teks_sorotan(self):
    self.assertEqual(teks_sorotan(7, 0, 9), "Mencatat 7 hari berturut-turut")
    self.assertEqual(teks_sorotan(6, 2, 9), "2 amplop tidak pernah lewat batas")
    self.assertEqual(teks_sorotan(0, 0, 3), "Mencatat di 3 hari")
    self.assertEqual(teks_sorotan(0, 0, 0), "Siap untuk periode berikutnya")
```

- [ ] **Step 2: Jalankan, pastikan gagal.** - [ ] **Step 3: Implementasikan.** - [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** — `feat(laporan): perhitungan murni (judul, status, lewat batas, sorotan)`.

### Task 3: Penyusun `data` v1 (murni)

**Files:** Create `app/services/laporan/susun.py`; Test `app/tests/test_laporan_susun.py`

**Interfaces:**
- Consumes: Task 2.
- Produces dataclass beku: `AmplopPeriode(id: str, nama: str, emoji: str, pribadi: bool, tujuan: str, awal: Decimal,
  alokasi: Decimal, terpakai: Decimal, akhir: Decimal, rollover: Decimal, ditutup: bool, alokasi_per_hari: dict[date,
  Decimal], terpakai_lalu: list[Decimal | None])` (3 periode sebelumnya, terlama dulu); `TransaksiPeriode(id: str,
  amplop_id: str, tanggal: date, jumlah: Decimal, keterangan: str, pencatat: str, milik_penerima: bool, penyesuaian:
  bool, tagihan: bool)` (keterangan sudah tersamar); `PemasukanPeriode(tanggal: date, jumlah: Decimal, keterangan:
  str)`; `TagihanBerikut(tanggal: date, nama: str, amplop_id: str, jumlah: Decimal)`; `TargetTabungan(nama: str,
  amplop_id: str, target: Decimal)`; `BahanLaporan(penerima_nama: str, rumah_nama: str, periode_mulai: date,
  periode_akhir: date, payday: int, angka_per: date, amplop: list[AmplopPeriode], transaksi: list[TransaksiPeriode],
  pemasukan: list[PemasukanPeriode], tagihan_berikut: list[TagihanBerikut], target: list[TargetTabungan],
  streak_saat_ini: int)`.
- `ada_aktivitas(bahan: BahanLaporan) -> bool` (ada alokasi > 0 atau ada transaksi).
- `susun_bulanan(bahan: BahanLaporan) -> dict` dengan kunci **persis** (uang = `uang(...)`, tanggal ISO):
  `versi` (1), `jenis` ("bulanan"), `judul`, `periode {mulai, akhir, gajian}`, `angka_per`, `penerima {nama, rumah}`,
  `ringkasan {pemasukan, dialokasikan, terpakai, sisa, dibawa, persen_terpakai}`,
  `amplop[] {id, nama, emoji, jenis ("bersama"|"pribadi"), tujuan, awal, alokasi, terpakai, akhir, rollover, status, pernah_lewat_batas, ditutup}`,
  `banding {terpakai_lalu, terpakai_rata3, persen_perubahan, amplop[] {id, terpakai_lalu, terpakai_rata3}}`,
  `harian[] {tanggal, terpakai}` (setiap hari di jendela, termasuk nol), `hari_terboros {tanggal, terpakai} | null`,
  `terbesar[] {tanggal, amplop, keterangan, jumlah, pencatat}`,
  `langganan {terbayar[] {tanggal, nama, amplop, jumlah}, jatuh_tempo[] {tanggal, nama, amplop, jumlah}}`,
  `sorotan {hari_mencatat, beruntun_terpanjang, streak_saat_ini, amplop_aman[], target[] {nama, target, terkumpul, persen}}`,
  `mutasi[] {tanggal, arah ("masuk"|"keluar"), amplop, keterangan, jumlah, pencatat, penyesuaian}`,
  `email {persen_terpakai, amplop_aman, amplop_lewat_batas, tren_persen, sorotan}`.

Definisi: `dibawa` = Σ rollover; `sisa` = Σ akhir; `persen_terpakai` = `persen(Σ terpakai, Σ awal)`; banding total dari
penjumlahan per periode (periode tanpa satu pun angka = None); `terbesar` = 5 transaksi bukan penyesuaian, jumlah
terbesar dulu; `terbayar` = transaksi `tagihan` (nama = keterangan tanpa awalan `"🔄 "`); `hari_mencatat` dan
`beruntun` dari transaksi `milik_penerima` bukan penyesuaian; `amplop_aman` = nama amplop berstatus selain
`tabungan`/`kosong` dan `pernah_lewat_batas` False; target `terkumpul` = `akhir` amplopnya, `persen` = `persen(terkumpul,
target)`; `mutasi` = pemasukan (`arah` masuk, `amplop` null, `pencatat` = penerima) + transaksi, urut tanggal lalu urutan
masuk; `email.amplop_aman`/`amplop_lewat_batas` = jumlah status `aman`/`lewat_batas`; `email.tren_persen` =
`banding.persen_perubahan`; `email.sorotan` = `teks_sorotan(...)`. `rollover_masuk` untuk `pernah_lewat_batas` =
`awal - alokasi`.

- [ ] **Step 1: Tulis tes yang gagal** — pabrik bahan kecil `bahan(**ubah)` di tes; kasus:
  `test_ringkasan_sama_dengan_jumlah_baris`, `test_mutasi_keluar_per_amplop_sama_dengan_terpakai` (bahan konsisten),
  `test_harian_mencakup_setiap_hari` (`len == (pe-ps).days+1`, hari tanpa transaksi `"0.00"`), `test_terbesar_lima_tanpa_penyesuaian`,
  `test_langganan_terbayar_tanpa_penanda` (`nama == "Netflix"` dari `"🔄 Netflix"`), `test_sorotan_hanya_catatan_penerima`,
  `test_banding_dan_tren` (lalu 100, sekarang 88 → `persen_perubahan == -12`), `test_email_tanpa_nominal`
  (`json.dumps(data["email"])` tidak memuat satu pun nilai uang dari `data`), `test_bisa_diserialkan_json`,
  `test_ada_aktivitas_false_untuk_bahan_kosong`, `test_jenis_bersama_pribadi`.
- [ ] **Step 2–4:** gagal → implementasi → PASS.
- [ ] **Step 5: Commit** — `feat(laporan): penyusun data laporan bulanan`.

### Task 4: Pemuat data dan filter pemasukan bersama

**Files:**
- Create: `app/services/pemasukan.py`, `app/services/laporan/muat.py`
- Modify: `app/api/routes/analytics.py` (`_income_totals` memakai filter bersama; SQL tidak berubah)
- Test: `app/tests/test_laporan_muat.py` (SQLite), jalankan juga `test_adjustment_reporting`, `test_prediction_rollover`,
  `test_income_type_safe_daily`

**Interfaces:**
- Produces: `pemasukan.filter_pemasukan_user(household_id, user_id, period_start: date, period_end: date) -> list` (lima
  kondisi `_income_totals` sekarang: household, user, ≥ awal, ≤ akhir, `balance_check_id IS NULL`);
  `muat.muat_bahan(db, user, household, period_start: date, period_end: date, payday: int, angka_per: date) -> BahanLaporan`.

Isi `muat_bahan` (urutan kueri bebas; semantik wajib):
- Lingkup: `Envelope.household_id == household.id` dan (`owner_id IS NULL` atau `owner_id == user.id`).
- Baris amplop: amplop lingkup yang punya snapshot kunci `(ps.year, ps.month)` (`allocated_amount`/`spent_amount` NULL
  → hitung dengan `calculate_envelope_balance`); ditambah amplop lingkup `is_active == False` tanpa snapshot yang punya
  transaksi atau alokasi di jendela → `snapshot_values(get_previous_rollover(...), bal["allocated"], bal["spent"],
  env.is_rollover)`, `ditutup=True`. Amplop aktif tanpa snapshot (dibuat setelah periode) tidak ikut.
- `terpakai_lalu`: `spent_amount` snapshot kunci `get_closed_periods(payday, period_start, 3)` per amplop (None bila
  tidak ada).
- `alokasi_per_hari`: `Allocation` ⋈ `Income` per (amplop, `income_date`) di jendela.
- Transaksi: amplop baris, `is_deleted == False`, tanggal di jendela; `keterangan = masked_description(user.id, txn)`;
  `pencatat` = nama user pencatat; `penyesuaian = txn.balance_check_id is not None`; `tagihan =
  txn.description.startswith(BILL_MARKER)`.
- Pemasukan: `select(Income).where(*filter_pemasukan_user(...), Income.amount > 0)`.
- `tagihan_berikut`: `RecurringTransaction` aktif di amplop lingkup dengan `next_run` di
  `get_budget_period(payday, period_end + 1 hari)`.
- Target: `Goal` milik amplop baris. Streak: `UserStreak.current_streak` (0 bila tidak ada).

- [ ] **Step 1: Tulis tes yang gagal** — fixture SQLite: household H, owner A, member B; amplop S (bersama), PA
  (pribadi A), PB (pribadi B), C (bersama, `is_active=False`, tanpa snapshot, transaksi di jendela); jendela
  1–31 Okt 2026 (payday 1), snapshot Okt untuk S/PA/PB dan Jul–Sep untuk S.
  - `test_lingkup_tanpa_amplop_pribadi_anggota_lain`: `{a.id for a in bahan.amplop} == {S, PA, C}` untuk A.
  - `test_deskripsi_privat_anggota_lain_tersamar`: transaksi privat B di S → `"Transaksi privat"`; privat milik A
    terbaca.
  - `test_amplop_ditutup_dihitung_seperti_snapshot`: angka C = `snapshot_values(...)`.
  - `test_terpakai_lalu_urut_terlama_dulu` (Jul, Agu, Sep).
  - `test_pemasukan_hanya_milik_penerima_tanpa_penyesuaian_dan_transfer`.
  - `test_penanda_tagihan_dan_penyesuaian`, `test_tagihan_berikut_hanya_periode_berikutnya` (juga payday 31: jendela 31
    Jan–27 Feb → berikutnya 28 Feb–30 Mar), `test_target_dan_streak`.
  - `test_filter_pemasukan_sama_dengan_income_totals`: SQL `_income_totals` sebelum dan sesudah sama (bandingkan
    string kompilasi postgresql).
- [ ] **Step 2–4:** gagal → implementasi → PASS (termasuk tiga modul analitik di atas dan `app.tests.test_ruang_pagar`).
- [ ] **Step 5: Commit** — `feat(laporan): pemuat bahan laporan; filter pemasukan bersama`.

### Task 5: Job penerbitan dan notifikasi

**Files:**
- Create: `app/services/laporan/job.py`
- Modify: `app/services/scheduler.py` (`start_scheduler`: job baru, tambah saja)
- Test: `app/tests/test_laporan_job.py` (unit dengan `db_with`/`fixed_date` + satu tes ujung-ke-ujung SQLite)

**Interfaces:**
- Consumes: `household_lock`, `current_payday`, `member_rows` (`household_cycle`), `get_closed_periods`, Task 3–4.
- Produces: `JENDELA_TERBIT_HARI = 7`; `penerima_layak(user, period_end: date) -> bool` (email tidak berawalan
  `deleted_`/`banned_`, `created_at.date() <= period_end`); `notifikasi_laporan(judul: str, report_id, app_url: str) ->
  tuple[str, str, str, str]` (judul notifikasi, pesan, link, telegram_html — teks di Global Constraints);
  `async terbitkan_household(household_id, today: date) -> list[uuid.UUID]`; `async kirim_notifikasi_laporan(report_id)
  -> None`; `async laporan_job(today: date | None = None) -> dict` (`{"terbit": int, "gagal": int}`).

Alur `terbitkan_household` (seluruhnya di dalam `async with household_lock(household_id)`, sesi sendiri
`AsyncSessionLocal`): `current_payday` → None berhenti; `[(ps, pe)] = get_closed_periods(payday, today, 1)`;
`(today - pe).days > JENDELA_TERBIT_HARI` berhenti; tidak ada snapshot kunci `(ps.year, ps.month)` untuk amplop household
→ berhenti; anggota dari `member_rows` → `User` yang `penerima_layak` dan belum punya `Report` (`jenis` bulanan,
`periode_mulai` ps); `muat_bahan` → `ada_aktivitas` False lewati → `Report(user_id, household_id, jenis, ps, pe, payday,
data=susun_bulanan(bahan))`; satu commit. `laporan_job`: household `type == HouseholdType.RUMAH_TANGGA` yang punya
anggota; per household `try/except` → `logger.exception`, `gagal += 1`; setelah kunci dilepas
`kirim_notifikasi_laporan` per id (memanggil `notification_service.kirim(user, NotificationType.system, judul, pesan,
link=..., telegram_html=...)`, lalu `notified_at`). Registrasi: `scheduler.add_job(laporan_job, trigger="cron",
minute=30, id="laporan", replace_existing=True, max_instances=1)`.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_terbit_satu_per_anggota_dan_idempoten` (run kedua: 0 baru).
  - `test_jendela_tujuh_hari` (pe + 7 hari → terbit; pe + 8 → tidak).
  - `test_tanpa_snapshot_tidak_terbit_lalu_terbit`.
  - `test_ruang_usaha_tidak_diproses` (SQL pemilihan household memuat filter `type`).
  - `test_penerima_tidak_layak` (akun dibuat setelah pe; `deleted_…`/`banned_…`).
  - `test_tanpa_aktivitas_dilewati`.
  - `test_gagal_satu_household_tidak_menghentikan_lain`.
  - `test_kunci_household_dipegang_saat_membangun` (pola tes kunci di `test_scheduler_household_runs.py`, id household
    baru per tes).
  - `test_notifikasi_isi_dan_notified_at` (`kirim` dipanggil dengan `NotificationType.system`, judul `"{judul} siap"`,
    `link="/laporan/{id}"`, `telegram_html` memuat `"{APP_URL}/laporan/{id}"` dan judul ter-escape).
  - `test_registrasi_scheduler` (`id="laporan"`, `minute=30`, `max_instances=1`).
  - `test_ujung_ke_ujung_sqlite`: household payday 1 dengan snapshot Okt, `laporan_job(date(2026,11,1))` → satu
    `Report` per anggota, `data["judul"] == "Laporan Oktober 2026"`, angka sama dengan `susun_bulanan(muat_bahan(...))`.
- [ ] **Step 2–4:** gagal → implementasi → PASS (+ `app.tests.test_kotak_maintenance`, `test_scheduler_household_runs`).
- [ ] **Step 5: Commit** — `feat(laporan): job penerbitan tiap jam dan notifikasi`.

### Task 6: PDF ber-AES-256

**Files:**
- Create: `app/services/laporan/pdf.py`; `app/assets/fonts/NotoSans-Regular.ttf`, `NotoSans-Bold.ttf`, `OFL.txt`
- Test: `app/tests/test_laporan_pdf.py`

**Interfaces:**
- Consumes: `data` v1 (Task 3).
- Produces: `teks_pdf(s: str) -> str` (buang karakter yang tidak ada di cmap font Regular — dibaca sekali lewat
  `fontTools.ttLib.TTFont(...)["cmap"].getBestCmap()`; fontTools ikut fpdf2); `rupiah(nilai: str) -> str`
  (`"1234567.00"` → `"Rp1.234.567"`, negatif `"-Rp12.000"`); `render_pdf(data: dict, kata_sandi: str) -> bytes`;
  `MAKS_PDF_SERENTAK = 2`; `async buat_pdf(data: dict, kata_sandi: str) -> bytes` (`asyncio.Semaphore` modul +
  `asyncio.to_thread(render_pdf, ...)`).

Font (unduh lewat `raw.githubusercontent.com`, cocokkan sha256 sebelum commit):
`https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts/NotoSans/full/ttf/NotoSans-Regular.ttf`
(sha256 `f5f552c8c5edb61fe6efb824baf4d4de47b1a8689ab4925ff43f7bd6a4ebece5`), `…/NotoSans-Bold.ttf`
(`3a08a47daa00cade516425c15c57615aef2fd418ec9811a7b9f465088f92cc05`), lisensi
`https://raw.githubusercontent.com/notofonts/latin-greek-cyrillic/main/OFL.txt`.

PDF: A4 tegak, margin 15 mm; header (Jatahku, judul, periode, penerima + rumah, `"Angka per {tgl}"`); bagian 1–7 dengan
judul di Global Constraints; grafik batang harian dari `rect` fpdf2; lampiran mutasi sebagai tabel dengan judul kolom
berulang tiap halaman; footer dua teks di Global Constraints. Semua teks lewat `teks_pdf`. Enkripsi
`set_encryption(owner_password=secrets.token_urlsafe(24), user_password=kata_sandi,
encryption_method=EncryptionMethod.AES_256, permissions=<cetak + salin>)`. Tidak menulis ke disk.

- [ ] **Step 1: Tulis tes yang gagal** (buka dengan `pypdfium2.PdfDocument(io.BytesIO(pdf), password=...)`)
  - `test_terbuka_dengan_kata_sandi_dan_memuat_isi` (teks halaman 1 memuat judul, `"Ringkasan"`, nama amplop).
  - `test_tanpa_atau_salah_kata_sandi_gagal` (`PdfiumError`).
  - `test_kata_sandi_non_ascii` (`"kopi-é123"`).
  - `test_emoji_dan_penanda_dibuang` (nama `"🍔 Makan"`, keterangan `"🔄 Netflix →"` → tidak error; teks tanpa `🍔`).
  - `test_mutasi_panjang_multi_halaman` (300 baris → ≥ 3 halaman, render < 5 detik, judul kolom muncul di halaman
    terakhir).
  - `test_rupiah` (`"1234567.00"` → `"Rp1.234.567"`, `"-12000.00"` → `"-Rp12.000"`, `"0.00"` → `"Rp0"`).
  - `test_buat_pdf_lewat_thread_dan_semaphore` (patch `asyncio.to_thread`; semaphore bernilai `MAKS_PDF_SERENTAK`).
  - `test_font_cocok_sha256`.
- [ ] **Step 2–4:** gagal → implementasi → PASS.
- [ ] **Step 5: Commit** — `feat(laporan): PDF laporan ber-AES-256 dengan font Noto Sans`.

### Task 7: API laporan dan pengaturan

**Files:**
- Create: `app/api/routes/laporan.py`
- Modify: `app/main.py` (import + `app.include_router(laporan.router, prefix="/laporan", tags=["laporan"])`,
  `app.include_router(laporan.pengaturan_router, prefix="/user", tags=["laporan"])`)
- Test: `app/tests/test_laporan_api.py` (SQLite + TestClient, override `get_db` dan `get_current_user`)

**Interfaces:**
- Consumes: `Report`, `ReportSettings` (Task 1), `rahasia` (Task 1), `hitung.nama_file_pdf`, `pdf.buat_pdf`,
  `transactions.transcribe_key_func`.
- Produces (respons persis):
  - `GET /laporan?limit=24&offset=0` → `[{id, jenis, judul, periode_mulai, periode_akhir, terbit_at, nama_file}]`
    milik pemanggil, `terbit_at` lalu `periode_mulai` menurun; `limit` 1–100.
  - `GET /laporan/{report_id}` → objek di atas + `data`; bukan milik/tidak ada → 404 `"Laporan tidak ditemukan"`.
  - `GET /laporan/{report_id}/pdf` → `application/pdf`, `Content-Disposition: attachment; filename="{nama_file}"`;
    404 sama; kunci tidak tersedia → 503; tanpa `report_settings`/`kata_sandi_enc`, atau token tak terbaca (warning
    log) → 409 (badan JSON di Global Constraints); `@limiter.limit("10/minute", key_func=transcribe_key_func)`.
  - `GET /user/laporan-pengaturan` → `{kata_sandi_diatur, email, email_terverifikasi, email_on, kuartalan_on,
    tahunan_on, pro}` (tanpa baris → bawaan; `pro = user.plan == "pro"`; `email_terverifikasi =
    user.email_verified_at is not None`).
  - `PUT /user/laporan-pengaturan` body `{"kata_sandi": str}` (6–64, pydantic `Field`) → bentuk GET; kunci tidak ada →
    503; `@limiter.limit("5/hour", key_func=transcribe_key_func)`.
  - Respons tidak pernah memuat kata sandi atau `kata_sandi_enc`.

- [ ] **Step 1: Tulis tes yang gagal** — `test_daftar_hanya_milik_sendiri_terurut`, `test_detail_milik_orang_lain_404`
  (anggota satu household pun), `test_pdf_tanpa_kata_sandi_409_dengan_kode`, `test_pdf_tanpa_kunci_503`,
  `test_pdf_token_tak_terbaca_409`, `test_pdf_berhasil` (`%PDF` di awal, tidak terbuka tanpa kata sandi, nama file di
  header), `test_put_kata_sandi_pendek_422`, `test_put_menyimpan_terenkripsi` (`kata_sandi_enc != kata sandi`,
  `dekripsi` mengembalikannya, teks respons tidak memuat kata sandi), `test_get_pengaturan_bawaan_dan_pro`,
  `test_batas_frekuensi_pdf` (limiter aktif, panggilan ke-11 → 429).
- [ ] **Step 2–4:** gagal → implementasi → PASS (+ `test_ruang_pagar`, `test_ruang_gerbang`, `python3 -m app.scripts.openapi_cek`).
- [ ] **Step 5: Commit** — `feat(laporan): API laporan, unduh PDF, dan pengaturan kata sandi`.

### Task 8: Hapus akun dan gabung akun

**Files:** Modify `app/services/account_deletion.py`, `app/services/merge.py`; Test `app/tests/test_laporan_akun.py`
(SQLite dengan `PRAGMA foreign_keys=ON`)

**Interfaces:**
- `account_deletion`: `Report` dan `ReportSettings` masuk daftar tingkat user (baris 208-210); `_delete_household`
  menjalankan `update(Report).where(Report.household_id == hid).values(household_id=None)` sebelum `delete(Household)`.
- `merge_users`: laporan sumber dipindah ke target kecuali yang bentrok `(jenis, periode_mulai)` dengan milik target
  (yang bentrok dihapus); `household_id` laporan yang menunjuk household yang dibuang → household yang dipertahankan;
  `report_settings` sumber dipindah bila target belum punya, selain itu dihapus.

- [ ] **Step 1: Tulis tes yang gagal** — `test_hapus_akun_menghapus_laporan_dan_pengaturan`,
  `test_hapus_household_menyisakan_laporan_mantan_anggota_dengan_household_null`, `test_gabung_memindahkan_laporan`,
  `test_gabung_laporan_bentrok_milik_sumber_dihapus`, `test_gabung_pengaturan`.
- [ ] **Step 2–4:** gagal → implementasi → PASS (+ `app.tests.test_account_deletion`, modul tes merge yang ada).
- [ ] **Step 5: Commit** — `feat(laporan): laporan ikut hapus akun dan gabung akun`.

### Task 9: Frontend — helper, API, hook bersama, "Ekspor"

**Files:**
- Create: `frontend/src/lib/laporanView.js`, `frontend/src/lib/laporanView.test.js`, `frontend/src/hooks/useMediaQuery.js`
- Modify: `frontend/src/lib/api.js`, `frontend/src/pages/Envelopes.jsx` (pakai hook bersama), `frontend/src/lib/exportPeriod.js`
  + `exportPeriod.test.js` (`getExportButtonLabel`), `frontend/src/components/ExportButtons.jsx` (aria-label, title,
  teks tombol)

**Interfaces:**
- `api.getLaporanList({limit, offset})`, `api.getLaporan(id)`, `api.unduhLaporanPdf(id)` (mengembalikan `Response`
  mentah), `api.getLaporanPengaturan()`, `api.simpanLaporanPengaturan(body)` — pola metode lain di `api.js`.
- `useMediaQuery(query) -> boolean` (isi persis versi `Envelopes.jsx:681-691`).
- `laporanView.js`: `BREAKPOINT_DESKTOP = '(min-width: 1024px)'`; `tampilanLaporan(isDesktop) -> 'lengkap' | 'ringkas'`;
  `labelStatus(status) -> { label, kelas }` (label di Global Constraints); `angkaUtama(data) -> [{ label, nilai }]`
  (Terpakai, Sisa, Dibawa ke periode berikut, Anggaran terpakai %); `trenTeks(persen) -> string`
  (`-12` → `"Pengeluaran turun 12% dibanding periode lalu"`, `5` → `"Pengeluaran naik 5% dibanding periode lalu"`,
  `0` → `"Pengeluaran sama dengan periode lalu"`, `null` → `""`); `bannerLaporan(pengaturan) -> { teks, tautan } | null`;
  `async unduhPdf({ api, native, laporan, mintaKataSandi }) -> 'tersimpan' | 'dibatalkan'` (200 →
  `native.files.save(blob, laporan.nama_file)`; 409 `kode` `kata_sandi_belum_diatur` → `await mintaKataSandi()` true →
  ulangi sekali; false → `'dibatalkan'`; status lain → `throw new Error(detail)`).
- `getExportButtonLabel` → `"Ekspor"` / `"Ekspor {periode}"`.

- [ ] **Step 1: Tulis tes yang gagal** (`node:test`, impor ber-`.js`): semua fungsi di atas, termasuk tiga alur
  `unduhPdf` dengan `api`/`native` palsu; `exportPeriod.test.js` diperbarui ke "Ekspor".
- [ ] **Step 2–4:** gagal → implementasi → `node --test src/lib/*.test.js src/native/*.test.js` PASS.
- [ ] **Step 5: Commit** — `feat(laporan): helper tampilan laporan, API klien, hook useMediaQuery; tombol Ekspor`.

### Task 10: Frontend — halaman, layar ringkas, pengaturan

**Files:**
- Create: `frontend/src/pages/Laporan.jsx`, `frontend/src/pages/LaporanDetail.jsx`,
  `frontend/src/components/laporan/{LaporanLengkap,LaporanRingkas,UnduhPdfButton,KataSandiForm}.jsx`,
  `frontend/src/components/LaporanSettings.jsx`
- Modify: `frontend/src/App.jsx` (`/laporan`, `/laporan/:id` di dalam `<Layout />`), `frontend/src/components/Layout.jsx`
  (`sidebarItems` + `{ to: '/laporan', label: 'Laporan', icon: 'file' }` setelah Analitik), `frontend/src/pages/Settings.jsx`
  (kartu `📄 Laporan` dengan `id="laporan"` di antara Notifikasi dan Plan & Usage)

**Interfaces:** Consumes Task 9. Perilaku:
- `Laporan.jsx`: daftar dari `getLaporanList` (judul, periode, tanggal terbit) → `/laporan/:id`; kosong → teks di
  Global Constraints.
- `LaporanDetail.jsx`: `getLaporan(id)` + `getLaporanPengaturan()`; `tampilanLaporan(useMediaQuery(BREAKPOINT_DESKTOP))`
  → `LaporanLengkap` atau `LaporanRingkas`; 404 → `"Laporan tidak ditemukan"`; `bannerLaporan` di atas keduanya.
- `LaporanLengkap`: bagian 1–8 dengan judul di Global Constraints; grafik harian `BarChart` recharts seperti
  `Analytics.jsx:398-407`; mutasi 50 baris + tombol `Tampilkan lebih banyak` (+50); hanya memformat `data`
  (`formatCurrency`).
- `LaporanRingkas`: judul, periode, `angkaUtama`, `data.email.sorotan`, `trenTeks`, `UnduhPdfButton` lebar penuh.
- `UnduhPdfButton`: `unduhPdf(...)`; `mintaKataSandi` membuka dialog berisi `KataSandiForm` dan resolve true setelah
  tersimpan; galat ditampilkan di bawah tombol.
- `KataSandiForm`: `input type="password"` (minLength 6, maxLength 64), simpan lewat `simpanLaporanPengaturan`,
  galat dari `detail`.
- `LaporanSettings`: status kata sandi + `KataSandiForm` (tombol `Atur kata sandi`/`Ganti kata sandi`), flash sukses.

- [ ] **Step 1: Implementasikan** komponen di atas (tanpa tes komponen; logika ada di Task 9).
- [ ] **Step 2: Verifikasi** — `npm run build` lulus; tangkapan layar Playwright (sudah terpasang) dengan API dimock:
  `/laporan/<id>` di 1280 px (laporan lengkap) dan 390 px (layar ringkas), `/laporan` kosong, dialog kata sandi; simpan
  di scratchpad dan sebut di laporan tugas; `git checkout -- frontend/dist`.
- [ ] **Step 3: Commit** — `feat(laporan): halaman laporan, layar ringkas HP, pengaturan kata sandi`.

### Task 11: Migrasi, dokumen, verifikasi akhir

**Files:**
- Create: `alembic/versions/<rev>_laporan_berkala.py`, `docs/laporan-berkala.md`
- Modify: `AGENTS.md` (checklist baru setelah checklist deploy terakhir), `CLAUDE.md` (Key Decisions),
  `docs/superpowers/specs/2026-11-01-laporan-berkala-design.md` (status + "Penyesuaian saat menyusun rencana" = tujuh
  keputusan rencana di atas; `git add -f`)

**Interfaces:**
- Revisi: `down_revision` = satu-satunya head setelah `git fetch origin main` (sekarang `2d51b9031a6b`; bila main
  bergerak, rebase dulu); `upgrade()`: `op.create_table("reports", …, if_not_exists=True)` dan `report_settings`
  dengan nama constraint/index persis Task 1, lalu `for stmt in LAPORAN_DDL: op.execute(sa.text(stmt))`;
  `downgrade()`: `drop_index`/`drop_table` `if_exists=True` + `ALTER TABLE users DROP COLUMN IF EXISTS email_verified_at`.
- `docs/laporan-berkala.md`: perilaku final tahap 1 (penerbitan, isi, PDF dan kata sandi, API, keamanan, batasan,
  pemulihan: jalankan `laporan_job` manual dari shell bila perlu).
- AGENTS.md `## Deploy Checklist — Laporan berkala tahap 1 (<rev>)`: **sebelum merge** — `sudo -u jatahku
  /opt/jatahku/venv/bin/pip install fpdf2==2.8.9 cryptography==50.0.2`; buat kunci
  `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` → `REPORT_SECRET_KEY=…`
  di `/opt/jatahku/.env`; pemilik tabel `users` (query checklist Kotak Struk, `bisa_alter = t`). **Setelah merge** —
  "Urutan merge PR bermigrasi" (`alembic current` = parent revisi → `upgrade head` → restart → re-run job deploy);
  log restart tanpa peringatan `REPORT_SECRET_KEY`; atur kata sandi di Pengaturan → Laporan; hari gajian berikutnya
  ±07:30 WIB: `journalctl -u jatahku | grep -i laporan` dan `/laporan` berisi laporan.
- CLAUDE.md: `- Laporan berkala: laporan beku per user di tabel reports (job tiap jam :30), PDF fpdf2 AES-256 dibuat saat diminta dengan kata sandi laporan terenkripsi (REPORT_SECRET_KEY di .env); tidak ada file laporan di disk`.

- [ ] **Step 1:** `git fetch origin main`; rebase bila perlu; tulis revisi; `alembic heads` → satu head baru.
- [ ] **Step 2:** Jalankan `.github/scripts/cek-migrasi.sh origin/main` di PostgreSQL 16 sementara (cluster
  `/var/lib/postgresql/16/main`, role/db sementara, hapus lagi setelahnya) → lulus.
- [ ] **Step 3:** Tulis dokumen, checklist, baris CLAUDE.md, sinkron spec + Project doc.
- [ ] **Step 4:** Verifikasi penuh: suite backend (hanya kegagalan lama yang diterima), `openapi_cek`, `node --test`,
  `npm run build` lalu `git checkout -- frontend/dist`, `git status` bersih.
- [ ] **Step 5: Commit** — `docs(laporan): revisi alembic, checklist deploy, dokumentasi tahap 1`.
