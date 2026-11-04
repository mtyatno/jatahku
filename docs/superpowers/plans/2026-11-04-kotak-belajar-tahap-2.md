# Kotak Struk: belajar lintas user tahap 2 — donasi contoh, aturan logo, arah uang — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tahap 2 spec belajar lintas user (§10, keputusan pemilik §12.4): (1) **donasi contoh** — user yang setuju (opt-in di Settings) menyumbang baris OCR tersamar dari bukti yang ia koreksi; pemilik meninjau, mengganti nama, menyetujui di Admin, lalu mengunduh entri korpus `reviewed: true`; (2) **aturan `logo`** — bukti `tidak_dikenali` bertanya "Aplikasi apa ini?", jawaban menjadi suara, aturan yang disetujui memberi aplikasi itu kunci dan penerbit; (3) **arah uang** — "Bukan pengeluaran" memilih alasan (top-up / uang masuk / rekening sendiri), suaranya menjadi aturan `arah` yang hanya menambah saran "bukan pengeluaran?", termasuk top-up ShopeePay "Kirim Ke GOPAY TOPU-…".

**Architecture:** Satu migrasi (`c9e4a7f2b5d8`): kolom `receipt_scans.sample_lines` (lewat `KOTAK_DDL`), tabel `proof_sample_consents` dan `proof_samples`. Worker menangkap baris tersamar (`samaran.mask_line` + nama samaran) hanya untuk user yang setuju dan hanya bila saklar `features.kotak_donasi` menyala; titik koreksi yang sudah ada (`record.mark_recorded`, `record.skip_item`, bot "Nominal salah", jawaban aplikasi) memindahkannya ke `proof_samples` (`donasi.donate`), selain itu dihapus bersama kerangka. Aturan `logo`/`arah` memakai tabel `proof_rule_votes`/`proof_rules` tahap 1 (ambang 2 user, persetujuan pemilik, cache 5 menit). Aturan `logo` hanya dibaca `UnknownReader` (penerbit + kunci label belajar); aturan `arah` hanya dibaca `registry.read_document` sesudah `apply_flow`, hanya `keluar` → saran. Status, blokir, cek, dedup, perutean, dan `looks_like_proof` tidak pernah membaca aturan.

**Tech Stack:** FastAPI, SQLAlchemy async (Postgres; SQLite + aiosqlite di tes), Alembic, python-telegram-bot (handler yang sama untuk chat web), React 18 + Vite, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-01-kotak-belajar-lintas-user-design.md` (mengikat; §2 baris `logo`/`arah`, §10 Tahap 2, §12.4). **Pre-flight (wajib dibaca tiap implementer):** `.superpowers/sdd/2026-10-26-bagikan-ke-jatahku/a16-preflight.md` — baris kode yang dirujuk, konflik K1–K17, celah G1–G12. Rencana ini mengikuti rekomendasinya; bila pemilik/pengendali memutuskan lain, ubah task terkait sebelum dikirim. Rencana tahap 1 (format, pola, invarian yang tetap berlaku): `docs/superpowers/plans/2026-11-01-kotak-belajar.md`.

**Dasar:** branch `feat/kotak-belajar-2` @ 7faa202 (= origin/main; tahap 1 PR #180 tayang, saklar `receipt_inbox` menyala untuk semua, `share_target` #183). Baseline di 7faa202: **2761 tes, OK, 1 dilewati** (`test_real_corpus_meets_release_gate`: 15 sampel nyata `reviewed: false`; menjadi 0 dilewati bila PR sampel tinjauan pemilik masuk main lebih dulu), 359 dtk; `openapi_cek --dasar 7faa202` exit 0; `kotak_corpus eval` 10 sampel lulus exit 0; salinan korpus semua `reviewed: true` 25 sampel lulus, satu-satunya gagal `real-shopeepay-topup-01` (flow `top_up` terbaca `keluar`); `kotak_sapuan cek` 493 daftar 0 beda; frontend 679 lulus. Head alembic `e7b3d5a9c1f4`.

## Global Constraints

- Git: jangan `git add -A`; stage per path; jangan commit `frontend/dist/` (sesudah build: `git checkout -- frontend/dist`). Setiap commit diakhiri baris atribusi sesi yang diberikan pengendali.
- **Satu PR berlabel `migrasi`**, branch `feat/kotak-belajar-2`, **satu revisi alembic `c9e4a7f2b5d8`** (`down_revision = 'e7b3d5a9c1f4'`), dibuat di M1a; task lain tidak menyentuh `alembic/` atau model kecuali disebut. Bila main mendapat migrasi lain sebelum merge: rebase, `down_revision` disesuaikan, tes head diperbarui (satu head).
- **API hanya bertambah** (AGENTS.md Aplikasi mobile #2): `python3 -m app.scripts.openapi_cek --dasar 7faa202` exit 0 di setiap task backend. Endpoint baru memakai `response_model`. Field baru opsional (`SkipIn.alasan`, `flags.ask_app`, `flags.app_logo`); arti field lama tidak berubah.
- **Struk tidak pernah tercatat diam-diam atau dua kali** (Aplikasi mobile #11): donasi dan suara tidak membuat transaksi, tidak mengubah status item, tidak mengubah `check_recordable`/`claim_for_recording`/dedup; galatnya ditelan (SAVEPOINT) dan dicatat di log tanpa isi bukti.
- **Tanpa aturan = perilaku hari ini.** Tidak ada perubahan pembacaan tanpa aturan yang disetujui: `kotak_sapuan cek` **0 beda** di setiap task yang menyentuh pembaca/worker/kerangka, dan `test_empty_rules_change_nothing` (tahap 1) tetap hijau. Kalibrasi pembaca (mis. L6 m-7) bukan bagian tahap 2 (K16).
- **Aturan tidak pernah melonggarkan** blokir gagal/pending, cek, dedup (spec §1.3). `logo`: hanya `doc.issuer` dan kunci label belajar di `UnknownReader` (K7). `arah`: hanya `keluar` → `top_up|masuk|antar_rekening_sendiri` pada QRIS/transfer berprofil, sesudah `apply_flow`, saklar menyala (K10); hasilnya hanya `flags.skip_suggestion` ("Tetap catat" selalu ada kecuali `blocked`).
- **Privasi:**
  - Tabel aturan tetap hanya struktur: nilai `logo` ∈ 12 kunci profil ∪ {`baru`} (K6); kunci `logo:<kata>` lolos penyaring kandidat ketat (K8); token `arah` hanya kata kosakata (K9). Tidak ada nama, nomor, nominal, atau teks bebas.
  - Baris donasi hanya untuk user yang setuju, hanya saat `features.kotak_donasi` menyala (K1, G1), hanya jenis di G6; tersamar `mask_line`; kata nama yang dikenal (pihak lawan, pengirim, merchant terbaca, user) diganti nama samaran (K5); tidak ada deret ≥ 6 digit (diuji); tidak pernah dikirim ke klien selain Admin; dihapus seperti `layout` bila bukan koreksi; `proof_samples` berumur `SAMPLE_TTL` (G2); hapus akun, gabung akun, dan menarik persetujuan menghapus semuanya (G4).
  - Suara `label_*`/`arah` untuk kunci `logo:` hanya sesudah aturan `logo` kunci itu disetujui (K8). Tab Suara Admin menyamarkan kunci logo dan token arah (K15).
- Konstanta baru di `app/services/kotak_struk/config.py`: `SAMPLE_MAX_LINES = 80`, `SAMPLE_LINE_MAX = 200`, `SAMPLE_TTL = timedelta(days=30)`, `SAMPLE_TYPES = LAYOUT_TYPES`, `APP_NEW = "baru"`, `ARAH_FLOWS = ("top_up", "masuk", "antar_rekening_sendiri")`, `KEY_MAX = 60` (pindah dari `belajar`, nilai sama).
- Jenis aturan baru: `logo` (kunci `logo:<kata>`, nilai kunci profil | `baru`), `arah` (kunci `{app}|judul:<kata>` atau `{app}|ke:<kata>`, nilai flow). Transisi status, ambang `RULE_MIN_USERS = 2`, rekonsiliasi, `forget_user`: sama dengan tahap 1. Tambahan G8: menyetujui nilai kedua untuk kunci `logo`/`arah` yang sudah punya nilai `disetujui` → 409.
- Tes pembaca, `kotak_corpus`, dan sapuan berjalan **tanpa** aturan; hanya tes khusus yang menyuntik `ParseContext(rules=…)`.
- `app/services/` tidak menanyakan keanggotaan household sendiri (`test_ruang_pagar.py`). Route tulis baru dicatat di `test_ruang_pagar.test_setiap_route_tulis_punya_sumber_ruang` (K13).
- Teks UI, pesan bot, dan docstring Bahasa Indonesia.
- **Cek tiap task backend** (laporkan angka, bandingkan dengan baseline 2761/0 gagal/1 dilewati):
  1. `cd /home/claude/jatahku && DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python3 -m unittest discover -s app/tests -t .`
  2. `python3 -m app.scripts.openapi_cek --dasar 7faa202` → exit 0.
  3. `python3 -m app.scripts.kotak_corpus eval` → exit 0; task yang menyentuh pembaca juga `eval --corpus <salinan scratch dengan semua "reviewed": true>` (hasil harus sama dengan baseline: satu gagal `real-shopeepay-topup-01`).
  4. Task yang menyentuh pembaca/worker/kerangka/registry: `python3 -m app.scripts.kotak_sapuan cek` → **0 beda**. Satu-satunya `tulis` di tahap 2 ada di M0 (entri `known_l6e` baru; entri lama tidak berubah).
- **Cek tiap task frontend:** `cd /home/claude/jatahku/frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`, lalu `git checkout -- frontend/dist`. Logika di modul murni `src/lib/`; JSX hanya merender.
- **Cek bot:** task yang menyentuh `receipt_cmd.py` juga `python3 -m unittest app.tests.test_kotak_bot app.tests.test_web_chat -v` (callback chat web lewat `bot_callbacks()`).
- Postgres tidak tersedia di sandbox: migrasi dicek di CI (workflow "Migrasi"); bila ada Postgres kosong, `DATABASE_URL=postgresql+asyncpg://… JWT_SECRET=x .github/scripts/cek-migrasi.sh origin/main`.

## Review Focus

1. **Tanpa persetujuan tidak ada baris yang disimpan** — user tanpa persetujuan, atau saklar `kotak_donasi` mati: `sample_lines` NULL dan `proof_samples` kosong di semua jalur; menarik persetujuan menghapus semuanya. Dipin `test_donation_requires_consent_and_flag` (M1b) dan `test_withdraw_deletes_samples` (M1a).
2. **Sampel tanpa nomor dan tanpa nama yang dikenal** — tidak ada `\d{6,}` dan tidak ada kata nama pihak lawan/pengirim/merchant/user di `sample_lines`/`proof_samples.lines`, untuk semua daftar sapuan bertanda `proof`/`probe`/`failed`/`pending`; persetujuan Admin dengan baris yang masih bernomor ditolak. Dipin `test_samples_hold_no_long_digits_or_known_names` (M1b), `test_approve_remasks_and_refuses_numbers` (M1d).
3. **Donasi dan suara tidak pernah memengaruhi pencatatan** — satu transaksi per item, galat donasi/suara → tetap 201/`tercatat`/`dilewati`. Dipin `test_donation_never_affects_recording` (M1c), `test_skip_votes_never_fail_the_skip` (M3a).
4. **Aturan logo/arah tidak pernah melewati blokir** — semua daftar `failed`/`pending` sapuan dengan aturan `logo` dan `arah` jahat untuk setiap kunci: `status`, `{code: level}` cek, `check_recordable`, `ref_hash`, `doc_type`, perutean sama. Dipin `test_logo_rules_never_change_status_or_routing` (M2b), `test_arah_rules_never_bypass_blocks` (M3b).
5. **Arah hanya saran** — aturan `arah` yang disetujui: item tetap `siap`, `flags.skip_suggestion` terisi, Simpan/`t_`/"Tetap catat" tetap mencatat satu kali, tidak ada lewati otomatis; hanya `keluar` yang berubah. Dipin `test_arah_rule_never_records_or_skips` dan `test_arah_only_from_keluar` (M3b).
6. **Kunci logo bukan nama orang/merchant** — kandidat dua kata tanpa kata logo/penyedia ditolak; suara logo ditolak bila katanya ada di keterangan/pihak lawan/merchant/pengirim/nama user; suara label untuk kunci logo hanya sesudah aturan logo disetujui; Suara Admin menyamarkannya. Dipin `test_logo_key_never_from_person_or_merchant_name` (M2a).
7. **API hanya bertambah dan migrasi idempoten** — `openapi_cek --dasar 7faa202` exit 0; `test_migration_is_idempotent` (berkas baru) dan workflow "Migrasi" hijau; satu head.
8. **Tanpa aturan = perilaku hari ini** — `kotak_sapuan cek` 0 beda dan `test_empty_rules_change_nothing` hijau sesudah `LOGO_KEYS = True` dan token arah di kerangka.

---

## Peta file

**Baru (backend):** `app/services/kotak_struk/samaran.py` (`mask_line`, `needs_review`, `pseudonymise`; dipindah dari `kotak_corpus`), `app/services/kotak_struk/donasi.py` (persetujuan, tangkap, donasi, tinjauan, retensi, `forget_user`), `alembic/versions/c9e4a7f2b5d8_kotak_belajar_2.py`.
**Tes baru:** `app/tests/test_kotak_donasi.py`, `app/tests/test_kotak_donasi_admin.py`, `app/tests/test_kotak_logo.py`, `app/tests/test_kotak_arah.py`.
**Diubah (backend):** `app/models/models.py`, `app/services/kotak_struk/{config,schema,worker,maintenance,record,belajar,kerangka,registry,view}.py`, `readers/{profiles,unknown}.py`, `app/services/scheduler.py`, `app/services/account_deletion.py`, `app/services/merge.py`, `app/api/routes/{kotak_struk,admin_kotak,user_settings}.py`, `app/scripts/kotak_corpus.py`, `app/bot/receipt_cmd.py`, `app/bot/handlers.py` (pola callback), tes yang ada (`test_kotak_schema`, `test_kotak_corpus`, `test_kotak_kerangka`, `test_kotak_belajar`, `test_kotak_aturan_pembaca`, `test_kotak_admin_aturan`, `test_kotak_worker`, `test_kotak_maintenance`, `test_kotak_bot`, `test_web_chat`, `test_account_deletion`, `test_ruang_pagar`, `test_kotak_sapuan` fixture).
**Frontend:** baru `src/lib/proofSamples.js` (+ test), `src/lib/kotakDonasi.js` (+ test), `src/components/ProofSamplesSection.jsx`; diubah `src/lib/api.js`, `src/lib/proofFormat.js` (+ test), `src/lib/proofRules.js` (+ test), `src/components/ProofCard.jsx`, `src/pages/Settings.jsx`, `src/pages/Admin.jsx`.
**Dokumen:** `docs/kotak-struk.md`, `AGENTS.md`, `docs/mobile/PROGRESS.md` (baris A68 bila paragraf privasi baru), spec §10 catatan "as-built".

---

# Tahap 2 — `feat/kotak-belajar-2` (satu PR, label `migrasi`)

Urutan pengerjaan: M0 → M1a → M1b → M1c → M1d → M1e → M2a → M2b → M2c → M3a → M3b → M3c → M3d → M4 → M5. M2a–M3d tidak bergantung pada M1b–M1e kecuali kait donasi (M2a/M3a memanggil `donasi.donate` bila sudah ada; bila pengendali menjalankan M2/M3 lebih dulu, kait itu ditambahkan di M1c).

### Task M0: Sisa tahap 1 (tanpa perubahan pembacaan)

Pre-flight §1. Empat butir kecil, satu commit masing-masing; L6 m-7 **tidak** (K16), o-1 di M4.

**Files:**
- Modify: `app/services/kotak_struk/kerangka.py` (`_words` → publik `words`, alias `_words` tetap; `_CURATED` + "kepada", "atas"), `app/api/routes/admin_kotak.py` (impor `words`; `_no_control_chars` juga menolak kategori `Cf`), `app/tests/fixtures/kotak/sweep_lines.json` (+ bentuk L6 m-2 bertanda `store`/`known_l6e`), `app/tests/test_kotak_sapuan.py` (tag `known_l6e` dikenali dengan alasan tertulis)
- Test: `app/tests/test_kotak_kerangka.py`, `app/tests/test_kotak_belajar.py`, `app/tests/test_kotak_admin_aturan.py`, `app/tests/test_kotak_sapuan.py`

**Interfaces:**
- `kerangka.words(text) -> list[str]` (= `_words` sekarang). `PublicReaderNamesTests` (tahap 1) mencakupnya.
- `RuleDecisionIn.note`: karakter `Cf` (U+200B, U+202E, U+FEFF) → 422 "Catatan tidak boleh memuat karakter kontrol".
- `LABEL_WORDS` memuat "kepada", "atas": label "Kepada" kini masuk kerangka dan bisa menjadi suara `label_pihak` ("kepada" sudah di `belajar.PARTY_WORDS`); "Atas Nama" masuk kerangka tetapi tidak memberi suara (`_party_label`: "nama" lemah, "atas" bukan kata penerima) — keduanya dipin tes.
- Sapuan: bentuk m-2 dari `task-L6-review.md:195-203` ("BCA / TOKO MAJU / KOPI 15.000 / ROTI 10.000 / TOTAL 25.000", "KANTIN / BNI / …", "gopay / Pesanan / 2 items / Total", EDC "BRI / … / SALE / KOPI / TOTAL") ditambahkan dengan tag `known_l6e` (bukan `store`) dan `note` yang menyebut harga privasi L6e; `cek` mencetak beda HANYA untuk entri baru, lalu `tulis` **sekali** untuk menambahkannya (satu-satunya `tulis` di tahap 2; entri lama tidak boleh berubah).

- [ ] **Step 1: Write the failing test** — `test_words_is_public_and_same_as_private`, `test_note_with_format_chars_is_422`, `test_kepada_label_votes_label_pihak_and_atas_nama_alone_does_not`, `test_layout_holds_no_pii` (tahap 1) tetap hijau dengan kosakata baru, `test_known_l6e_shapes_pinned` (entri `known_l6e` ada dan hasilnya = snapshot).
- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_kerangka app.tests.test_kotak_belajar app.tests.test_kotak_admin_aturan app.tests.test_kotak_sapuan -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend; `kotak_sapuan cek` sebelum `tulis` hanya menyebut id `known_l6e` baru (laporkan outputnya), sesudah `tulis` 0 beda.
- [ ] **Step 5: Commit** (empat commit, stage per path):

```bash
git commit -m "refactor(kotak): kerangka.words publik untuk peringatan Admin"
git commit -m "fix(admin): catatan aturan menolak karakter format tak terlihat"
git commit -m "feat(kotak): label Kepada dan Atas Nama masuk kosakata kerangka"
git commit -m "test(kotak): sapuan memin bentuk struk kecil berlogo (harga privasi L6e)"
```

---

### Task M1a: Migrasi, model, saklar, persetujuan donasi

Spec §10 Tahap 2 butir 1; pre-flight §2, K1, K12, G1, G4.

**Files:**
- Create: `alembic/versions/c9e4a7f2b5d8_kotak_belajar_2.py`, `app/services/kotak_struk/donasi.py` (bagian persetujuan)
- Modify: `app/models/models.py` (sesudah `ProofRule` ±693: `ProofSampleConsent`, `ProofSample`; `ReceiptScan` sesudah `layout` ±633: `sample_lines`), `app/services/kotak_struk/schema.py` (`_COLUMNS` + `("sample_lines", "JSONB")`), `app/services/kotak_struk/config.py` (konstanta Global Constraints), `app/api/routes/user_settings.py` (`GET/PUT /user/kotak-donasi`), `app/services/account_deletion.py` (loop 213-215), `app/services/merge.py` (dekat 284)
- Test: `app/tests/test_kotak_donasi.py`, perluas `app/tests/test_kotak_schema.py` (K12), `app/tests/test_account_deletion.py`

**Interfaces:**
- Models:
  - `ReceiptScan.sample_lines: Mapped[list | None] = mapped_column(JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True)` — tidak pernah di `view.item_detail`.
  - `ProofSampleConsent` (`proof_sample_consents`): `user_id` PK FK users `ondelete="CASCADE"`, `consented_at` server_default now.
  - `ProofSample` (`proof_samples`): `id Uuid PK`, `user_id` FK users CASCADE (index), `item_id Uuid NULL` (tanpa FK), `rule_key String(60) NULL`, `doc_type String(30)`, `trigger String(20)` (`nominal|tanggal|tidak_dikenali|arah|aplikasi|nominal_bot`), `lines JSON`, `user_name String(60) NULL` (nama samaran user), `truth JSON NULL` (`{total, date, flow, app}`), `today Date`, `status String(12)` (`menunggu|disetujui|ditolak`), `created_at`, `decided_at NULL`, `decided_by` FK users SET NULL, `note String(200) NULL`; `UniqueConstraint("item_id", name="uq_proof_sample_item")`, `Index("ix_proof_samples_status")`.
- Migrasi `c9e4a7f2b5d8` (`down_revision = 'e7b3d5a9c1f4'`): `upgrade()` = setiap `KOTAK_DDL` + `create_table(..., if_not_exists=True)` kedua tabel + indeks `if_not_exists`; `downgrade()` = drop indeks/tabel `if_exists` + `ALTER TABLE receipt_scans DROP COLUMN IF EXISTS sample_lines`. Docstring idempoten (lifespan `KOTAK_DDL` + `create_all` membuat hal yang sama, tanpa jendela 500).
- `donasi.py` (bagian M1a):
  - `async def donation_available(db) -> bool` — `feature_enabled(db, "kotak_donasi", "web")`.
  - `async def consented(db, user_id) -> bool`.
  - `async def set_consent(db, user_id, on: bool, *, now) -> datetime | None` — on: upsert baris (idempoten, `consented_at` pertama tetap); off: hapus baris, `forget_user` (di bawah). Tidak meng-commit.
  - `async def forget_user(db, user_id) -> None` — hapus `proof_samples` user, `ProofSampleConsent`, dan `UPDATE receipt_scans SET sample_lines = NULL WHERE user_id = …`.
- API (`/user`, login wajib, `response_model`):
  - `GET /user/kotak-donasi` → `KotakDonasiOut {available: bool, consented: bool, consented_at: datetime | None}`.
  - `PUT /user/kotak-donasi` body `KotakDonasiIn {consented: bool}` (field lain 422) → `KotakDonasiOut`; saklar mati dan `consented: true` → 409 "Donasi contoh belum dibuka"; `false` selalu boleh (menarik persetujuan). Commit di route.
- `delete_account`: `donasi.forget_user(db, uid)` sebelum loop + `ProofSampleConsent`, `ProofSample` di loop; `ProofSample.decided_by == uid` → NULL. `merge_users`: `donasi.forget_user(db, source_user_id)` di samping `belajar.forget_user` (G4: persetujuan tidak diwariskan).
- `test_kotak_schema`: `test_single_head_after_plugin_h1` diganti `test_single_head_after_kotak_belajar` (head `["c9e4a7f2b5d8"]`, anak `e7b3d5a9c1f4` hanya berkas baru); `test_migration_is_idempotent` dan `test_migration_tables_match_the_models` untuk berkas baru; `test_every_new_column_has_ddl` mencakup `sample_lines`.

- [ ] **Step 1: Write the failing test**

```python
async def test_consent_roundtrip_and_flag(self):
    self.flag(kotak_donasi=False)
    r = await self.client.get("/user/kotak-donasi")
    self.assertEqual(r.json(), {"available": False, "consented": False, "consented_at": None})
    self.assertEqual((await self.client.put("/user/kotak-donasi", json={"consented": True})).status_code, 409)
    self.flag(kotak_donasi=True)
    r = await self.client.put("/user/kotak-donasi", json={"consented": True})
    self.assertTrue(r.json()["consented"])

async def test_withdraw_deletes_samples(self): ...          # Review Focus 1: consent off → proof_samples user 0, sample_lines NULL, baris user lain utuh
async def test_put_rejects_extra_fields(self): ...
async def test_delete_account_forgets_donation(self): ...
async def test_merge_users_drops_source_donation(self): ...
def test_single_head_after_kotak_belajar(self): ...
def test_migration_is_idempotent(self): ...                  # berkas c9e4a7f2b5d8: down_revision 'e7b3d5a9c1f4'; op.execute dari KOTAK_DDL; create_* if_not_exists
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_donasi app.tests.test_kotak_schema app.tests.test_account_deletion -v`.
- [ ] **Step 3: Implement.** Cek `alembic check` lokal tidak mungkin tanpa Postgres; pastikan kolom/indeks/FK migrasi sama persis dengan model (CI "Migrasi").
- [ ] **Step 4: Run to pass** + cek backend.
- [ ] **Step 5: Commit**

```bash
git add alembic/versions/c9e4a7f2b5d8_kotak_belajar_2.py app/models/models.py app/services/kotak_struk/schema.py app/services/kotak_struk/config.py app/services/kotak_struk/donasi.py app/api/routes/user_settings.py app/services/account_deletion.py app/services/merge.py app/tests/test_kotak_donasi.py app/tests/test_kotak_schema.py app/tests/test_account_deletion.py
git commit -m "feat(kotak): tabel donasi contoh, persetujuan opt-in, dan saklar kotak_donasi"
```

---

### Task M1b: Baris tersamar di worker (hanya user yang setuju)

Pre-flight §2 "Where the text exists", K2, K5, G6.

**Files:**
- Create: `app/services/kotak_struk/samaran.py`
- Modify: `app/scripts/kotak_corpus.py` (impor dan ekspor ulang `mask_line`, `needs_review`, `MIN_RUN_DIGITS` dari `samaran`; isi 71-262 dipindah, perilaku sama), `app/services/kotak_struk/worker.py` (`process_item` 362-376 dan 399; `_outcome` 225-282), `app/services/kotak_struk/maintenance.py` (`expire_items` 46-56, `purge_layouts` 59-71: juga `sample_lines=null()`)
- Test: perluas `app/tests/test_kotak_donasi.py`, `app/tests/test_kotak_worker.py`, `app/tests/test_kotak_maintenance.py`; `app/tests/test_kotak_corpus.py` tidak diubah (bukti perpindahan tanpa beda)

**Interfaces:**
- `samaran.mask_line(line) -> str`, `samaran.needs_review(line) -> bool` — salinan persis dari `kotak_corpus` (modul murni, tanpa `os.environ`).
- `samaran.PSEUDONYMS = {"user": "ANDI PRATAMA", "pihak": "BUDI SANTOSO", "pengirim": "SITI AMINAH", "merchant": "TOKO CONTOH"}` (huruf besar/kecil mengikuti kata asli; nama lebih panjang dari daftar memakai kata terakhir berulang).
- `samaran.pseudonymise(lines, names: dict[str, str | None]) -> tuple[list[str], str | None]` — setiap kata (`normalize_name`, ≥ 2 huruf) dari nama yang dikenal diganti kata samaran peran itu, di setiap baris, utuh kata (bukan potongan kata lain); mengembalikan `(baris, nama samaran user atau None)`.
- `donasi.sample_lines(lines, doc, secrets, *, user_name) -> list[str] | None` — None bila `doc.doc_type not in SAMPLE_TYPES` dan teksnya tidak `looks_like_proof`; selain itu `clean_lines` → `mask_line` → `pseudonymise` (nama: `doc.counterparty.name`, `pc.read_sender_name`, `pc.read_name(body, profile, "merchant")`, `user_name`) → baris yang masih memuat nilai `secrets` (ref, rekening, NMID tidak di baris NMID) atau `\d{6,}` dibuang → paling banyak `SAMPLE_MAX_LINES` × `SAMPLE_LINE_MAX`. Dibangun dari teks dan hasil baca SEBELUM dokumen disamarkan (sama dengan `_layout`).
- Worker: di sesi pertama `process_item` (362-376) `donate = await donasi.donation_available(db) and await donasi.consented(db, user_id)`; `_outcome(res, text, user_name=…, sample=donate)` menambah `columns["sample_lines"]` (galat → None + peringatan "baris donasi Kotak Struk tidak dibuat (<jenis galat>)"; item tetap `siap`). Tanpa persetujuan: kunci `sample_lines` = None, tidak ada kueri tambahan saat saklar mati selain `feature_enabled`.
- Pembersihan: `expire_items` dan `purge_layouts` juga mengosongkan `sample_lines` (item selesai 24 jam sejak dibaca, dan saat kedaluwarsa). Item yang dikoreksi memindahkannya lebih dulu (M1c).

- [ ] **Step 1: Write the failing test**

```python
async def test_donation_requires_consent_and_flag(self):      # Review Focus 1
    for flag, consent in ((False, True), (True, False), (False, False)):
        item = await self.process(GOPAY_LINES, flag=flag, consent=consent)
        self.assertIsNone(item.sample_lines)
    item = await self.process(GOPAY_LINES, flag=True, consent=True)
    self.assertTrue(item.sample_lines)
    self.assertNotIn("sample_lines", json.dumps(await item_detail(self.db, item, self.user)))

def test_samples_hold_no_long_digits_or_known_names(self):   # Review Focus 2: semua daftar sapuan proof/probe/failed/pending
    for case in sweep_cases(("proof", "probe", "failed", "pending")):
        lines = sample_lines(case.lines, case.doc, case.secrets, user_name=case.user_name) or []
        dumped = "\n".join(lines)
        self.assertNotRegex(dumped, r"\d{6,}")
        for word in known_name_words(case):
            self.assertNotIn(word, normalize_name(dumped).split())

def test_mask_line_moved_without_change(self): ...           # samaran.mask_line is kotak_corpus.mask_line; MaskLineTests hijau
def test_store_receipt_has_no_sample(self): ...
async def test_purge_and_expire_clear_sample_lines(self): ...
async def test_sample_error_keeps_item_siap(self): ...
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_donasi app.tests.test_kotak_worker app.tests.test_kotak_maintenance app.tests.test_kotak_corpus -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend; `kotak_sapuan cek` 0 beda; `eval` sama.
- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/samaran.py app/scripts/kotak_corpus.py app/services/kotak_struk/donasi.py app/services/kotak_struk/worker.py app/services/kotak_struk/maintenance.py app/tests/test_kotak_donasi.py app/tests/test_kotak_worker.py app/tests/test_kotak_maintenance.py
git commit -m "feat(kotak): baris bukti tersamar untuk donasi contoh, hanya dari user yang setuju"
```

---

### Task M1c: Koreksi memindahkan baris ke antrean tinjauan

Pre-flight §2 "Trigger points", K3, G2, G7.

**Files:**
- Modify: `app/services/kotak_struk/donasi.py` (`donate`, `purge_samples`), `app/services/kotak_struk/record.py` (`mark_recorded` 237-267 sesudah `_learn_correction`; `skip_item` 139-160 antara UPDATE dan commit; muat kolom yang dibutuhkan), `app/bot/receipt_cmd.py` (`note_fix_amount` 1061-…, sesudah suara), `app/services/kotak_struk/maintenance.py` (`purge_samples`), `app/services/scheduler.py` (`kotak_maintenance` langkah 5, sesi dan `try` sendiri)
- Test: perluas `app/tests/test_kotak_donasi.py`, `app/tests/test_kotak_transactions.py`, `app/tests/test_kotak_bot.py`, `app/tests/test_kotak_maintenance.py`

**Interfaces:**
- `donasi.correction_trigger(item, final: belajar.Final | None, *, skip_reason=None, alasan=None, app=None, typed_amount=None) -> str | None` — murni: `nominal` (nominal tercatat ≠ total terbaca, atau total tidak terbaca), `tanggal` (tanggal tercatat ≠ tanggal bukti WIB dan ≠ hari ini), `tidak_dikenali` (item `tidak_dikenali` tercatat atau dilewati `bukan_pengeluaran`), `arah` (`skip_reason == "bukan_pengeluaran"` dan `alasan` ≠ `document.flow`, juga tanpa alasan bila flow `keluar`), `aplikasi` (jawaban M2), `nominal_bot` ("Nominal salah"); `batal`/`duplikat` → None.
- `async def donate(db, item, trigger: str | None, *, truth: dict, now) -> bool` — `trigger` None atau `item.sample_lines` kosong → kosongkan `sample_lines` (bila ada) dan False. Selain itu sisip `ProofSample(status="menunggu", lines=item.sample_lines, rule_key=(item.layout or {}).get("key"), doc_type, trigger, user_name=<samaran user bila ada>, truth, today=processed_at WIB)` dengan `on_conflict_do_nothing` (`uq_proof_sample_item`), lalu `item.sample_lines = None`. SAVEPOINT sendiri; tidak meng-commit; galat → log + False. Persetujuan dicek LAGI di sini (ditarik sesudah dibaca → tidak disimpan).
- `mark_recorded`: sesudah `_learn_correction`, `donate(db, item, correction_trigger(item, final), truth={total, date, flow: doc flow, app: None})`; nilai `final` dari `Transaction` yang sama (refaktor kecil: `_learn_correction` mengembalikan `Final | None`). Sekali per transaksi (cabang id baru).
- `skip_item(db, item_id, user_id, reason, *, alasan=None)`: alasan baru diterima di sini sekarang (dipakai M3a); sesudah UPDATE berhasil: `donate(..., correction_trigger(item, None, skip_reason=reason, alasan=alasan), truth={flow: alasan})`; `batal`/`duplikat` mengosongkan `sample_lines`. Satu `db.commit()` yang sudah ada.
- `note_fix_amount`: sesudah `learn_from_correction`, `donate(..., "nominal_bot", truth={total: amount})` di commit yang sama.
- `maintenance.purge_samples(db, *, now) -> int` — hapus `menunggu` dengan `created_at < now - SAMPLE_TTL` dan `disetujui` dengan `decided_at < now - SAMPLE_TTL`; commit sendiri. Log "n sampel donasi dihapus".

- [ ] **Step 1: Write the failing test**

```python
async def test_corrected_amount_moves_lines_to_queue(self):
    item = await self.siap_item(GOPAY_LINES, consent=True)        # total terbaca 10.000
    await self.post_txn(item, amount=12500)                         # koreksi
    sample = await self.only_sample()
    self.assertEqual((sample.trigger, sample.status, sample.truth["total"]), ("nominal", "menunggu", 12500))
    self.assertIsNone((await self.reload(item)).sample_lines)

async def test_correct_read_or_batal_donates_nothing(self): ...
async def test_tidak_dikenali_confirmation_donates(self): ...
async def test_donation_never_affects_recording(self):        # Review Focus 3: donate dipatch melempar → 201, 1 transaksi, item tercatat; kirim ulang client_ref → tetap 1 sampel
async def test_bot_fix_amount_donates_once(self): ...
async def test_consent_withdrawn_after_capture_stores_nothing(self): ...
async def test_purge_samples_ttl(self): ...
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_donasi app.tests.test_kotak_transactions app.tests.test_kotak_bot app.tests.test_kotak_maintenance -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend.
- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/donasi.py app/services/kotak_struk/record.py app/bot/receipt_cmd.py app/services/kotak_struk/maintenance.py app/services/scheduler.py app/tests/test_kotak_donasi.py app/tests/test_kotak_transactions.py app/tests/test_kotak_bot.py app/tests/test_kotak_maintenance.py
git commit -m "feat(kotak): koreksi bukti dari user yang setuju masuk antrean tinjauan sampel"
```

---

### Task M1d: API Admin tinjauan sampel dan entri korpus

Pre-flight §2 "Admin review → corpus", K4, K5, K17.

**Files:**
- Modify: `app/api/routes/admin_kotak.py`, `app/services/kotak_struk/donasi.py` (tinjauan), `app/scripts/kotak_corpus.py` (`add --dari-donasi`)
- Test: `app/tests/test_kotak_donasi_admin.py`, perluas `app/tests/test_kotak_corpus.py`

**Interfaces (semua `Depends(require_admin)`, `response_model`):**
- `GET /admin/kotak/samples?status=menunggu|disetujui|ditolak|semua` (bawaan `menunggu`) → `ProofSamplesResponse {counts: {menunggu, disetujui, ditolak}, samples: [ProofSampleOut]}`; `ProofSampleOut {id, doc_type, rule_key, app_label, trigger, lines: [{text, periksa: bool}], user_name, truth, reading: {doc_type, issuer, total, paid_at, counterparty, status, flow}, today, status, created_at, decided_at, decided_by_name, note}`; `reading` = pembaca SEKARANG pada baris itu (tanpa aturan, `kotak_corpus.sample_context` pola); `periksa` = `samaran.needs_review`. Tidak pernah memuat `user_id`/`item_id`.
- `POST /admin/kotak/samples/{id}/setujui` body `SampleApproveIn {lines: list[str] (1..SAMPLE_MAX_LINES, tiap ≤ SAMPLE_LINE_MAX), user_name: str | None (≤ 60), note: str | None (≤ 200, tanpa Cc/Cf), from_status: Literal["menunggu","ditolak"] | None}` (field lain 422) → `ProofSampleOut`. Server menerapkan `mask_line` lagi pada setiap baris; masih ada `\d{6,}` → 422 "Masih ada nomor panjang di baris N"; transisi: setujui ← menunggu|ditolak (409 selain itu); 404 "Sampel tidak ditemukan".
- `POST /admin/kotak/samples/{id}/tolak` body `{note, from_status}` → baris dihapus (G2: tidak ada isi yang disimpan), jawab 200 `{deleted: true}`.
- `DELETE /admin/kotak/samples/{id}` → 204 (sesudah entri disalin ke korpus).
- `GET /admin/kotak/samples/{id}/korpus` (hanya `disetujui`; selain itu 409) → `CorpusEntryOut {entry: {id: "donasi-<doc_type>-<8 hex>", real: true, reviewed: true, today, user_name?, lines, expect}, truth, gated_diff: [field]}`; `expect` = `kotak_corpus.expect_from` pada baris yang disetujui; `gated_diff` = field total/tanggal/status yang berbeda dari `truth`.
- `kotak_corpus add --dari-donasi <berkas.json> [--id ID] [--tahan] [--corpus PATH]` — membaca `entry` (atau `{entry, …}` utuh dari endpoint), memvalidasi (`_sample_problem`, id unik, awalan `indomaret-` ditolak, `needs_review` dicetak sebagai PERIKSA), menghitung ulang `expect` dengan pembaca saat ini, mencetak beda dengan `truth`; ada beda gated → exit 3 kecuali `--tahan` (ditulis `reviewed: false`, pola A14) — K17. Tanpa beda: ditulis `reviewed: true`.

- [ ] **Step 1: Write the failing test** — daftar per status dan `counts`; tanpa `user_id`/`item_id` di respons; `periksa` untuk baris "Ref …5678 …1234"; `test_approve_remasks_and_refuses_numbers` (Review Focus 2: baris editan "Ke 1234567890" disamarkan menjadi "…7890"; "1234 5678 9012" juga; deret yang lolos `mask_line` → 422); transisi/409/404; non-admin 403; tolak menghapus baris; `korpus` hanya untuk `disetujui`, entri lolos `load_corpus`; CLI: `--dari-donasi` menulis `reviewed: true` bila tanpa beda, exit 3 bila beda gated, `--tahan` menulis `reviewed: false`, berkas korpus asli tidak berubah saat gagal.
- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_donasi_admin app.tests.test_kotak_corpus -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend (`openapi_cek`: hanya path baru).
- [ ] **Step 5: Commit**

```bash
git add app/api/routes/admin_kotak.py app/services/kotak_struk/donasi.py app/scripts/kotak_corpus.py app/tests/test_kotak_donasi_admin.py app/tests/test_kotak_corpus.py
git commit -m "feat(admin): tinjauan sampel donasi dan entri korpus siap salin"
```

---

### Task M1e: Settings (opt-in) dan Admin "Donasi contoh"

Pre-flight §2 "User API + Settings", G3.

**Files:**
- Create: `frontend/src/lib/kotakDonasi.js` (+ `.test.js`), `frontend/src/lib/proofSamples.js` (+ `.test.js`), `frontend/src/components/ProofSamplesSection.jsx`
- Modify: `frontend/src/lib/api.js` (blok Kotak ±581-690: `kotakDonasi()`, `setKotakDonasi(on)`, `adminProofSamples(status)`, `adminProofSampleAction(id, action, body)`, `adminProofSampleEntry(id)`, `adminDeleteProofSample(id)`; `null`/`{ok:false}` bila gagal, pola `kotakSkip`), `frontend/src/pages/Settings.jsx` (kartu baru sesudah tips 808-813), `frontend/src/pages/Admin.jsx` (`ReceiptScanCard` 1414-…, di bawah `ProofRulesSection` 1488)

**Interfaces:**
- `kotakDonasi.js`: `CONSENT_TEXT` (draf, disetujui pemilik sebelum merge — G3): judul "Bantu Jatahku membaca bukti dari bank-mu"; isi "Bila diaktifkan, saat kamu mengoreksi hasil baca bukti bayar, teks bukti itu (nomor rekening, referensi, dan HP sudah disamarkan; nama yang kami kenali diganti nama samaran) dikirim ke pengelola Jatahku untuk ditinjau. Pengelola mengganti nama yang tersisa, lalu memakainya sebagai contoh agar pembacaan bukti dari aplikasi yang sama lebih tepat. Contoh yang belum dipakai dihapus dalam 30 hari. Gambar bukti tidak pernah dikirim. Kamu bisa mematikannya kapan saja; contoh yang belum dipakai ikut dihapus."; `consentView(resp)` → `{show: available || consented, on, label, since}` atau null; `toggleOutcome(res)`.
- Settings: kartu tampil bila `available` atau sudah `consented` (supaya tetap bisa ditarik walau saklar mati); toggle `role="switch"`, `aria-checked`, teks persetujuan penuh terlihat sebelum menyalakan.
- `proofSamples.js`: `SAMPLE_TABS` (Menunggu/Disetujui/Ditolak), `sampleRows(resp, tab)`, `periksaCount(row)`, `editableLines(row)` (teks per baris), `approveBody(row, lines, userName, note)` (memotong ke batas server, menolak baris kosong), `entryFileName(entry)` (`<id>.json`), `actionOutcome(action, res)` → `{kind: ok|conflict|invalid|error, text}`; data rusak → null tanpa melempar.
- `ProofSamplesSection.jsx`: daftar menunggu: aplikasi, pemicu, "Hasil baca" vs "Koreksi user" (`reading` vs `truth`), baris dalam `<textarea>` yang bisa diedit (baris PERIKSA ditandai), kolom nama samaran user, Setujui/Tolak; tab Disetujui: "Unduh entri korpus" (Blob `application/json`, via `native.files` bila ada pola unduh di proyek, selain itu tautan `download`), "Hapus sesudah disalin". Langkah manusia tertulis di bawah tombol: "Simpan berkas, lalu jalankan `python -m app.scripts.kotak_corpus add --dari-donasi <berkas>` di checkout lokal dan buka PR."

- [ ] **Step 1: Write the failing test** (`node --test src/lib/kotakDonasi.test.js src/lib/proofSamples.test.js`): kartu tidak tampil bila tidak tersedia dan belum setuju; tampil untuk menarik; `approveBody` tidak pernah mengirim field selain `lines/user_name/note/from_status`; baris PERIKSA dihitung; hasil 409/422 → teks server; data rusak → null.
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** — cek frontend lengkap; `git checkout -- frontend/dist`.
- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/kotakDonasi.js frontend/src/lib/kotakDonasi.test.js frontend/src/lib/proofSamples.js frontend/src/lib/proofSamples.test.js frontend/src/components/ProofSamplesSection.jsx frontend/src/lib/api.js frontend/src/pages/Settings.jsx frontend/src/pages/Admin.jsx
git commit -m "feat(web): persetujuan donasi contoh di Settings dan tinjauan sampel di Admin"
```

---

### Task M2a: Kunci logo, suara `logo`, dan "Aplikasi apa ini?" (server)

Spec §2 baris `logo`; pre-flight §3, K6, K8, G9, G10; L1 review I-1 opsi B.

**Files:**
- Modify: `app/services/kotak_struk/kerangka.py` (`LOGO_KEYS = True`; `rule_key` 168-192 kandidat ketat; `build_layout` 319-344 tetap hanya `tidak_dikenali` untuk kunci logo; `logo_word(key)`), `app/services/kotak_struk/belajar.py` (`KIND_LOGO`, `KINDS`, `_valid_key`, `votes_for(..., logo_approved=…)`, `learn_app_choice`, `approved_logo_keys`), `app/services/kotak_struk/view.py` (`_flags` 55-76: `ask_app`, `app_logo`), `app/api/routes/kotak_struk.py` (`POST /{item_id}/aplikasi`), `app/services/kotak_struk/record.py` (`_learn_correction`: teruskan kunci logo yang disetujui), `app/tests/test_ruang_pagar.py` (`tanpa` + rute baru, K13)
- Test: `app/tests/test_kotak_logo.py`, perluas `app/tests/test_kotak_kerangka.py`, `app/tests/test_kotak_belajar.py`, `app/tests/test_kotak_api.py` (atau berkas tes API Kotak yang ada)

**Interfaces:**
- `kerangka.rule_key`: kandidat logo = 1 kata huruf (≥ 3 huruf), atau 2 kata bila salah satunya di `LOGO_WORDS` ∪ `MONEY_PROVIDERS`; aturan lain tahap 1 tetap (bukan status/label/`LABEL_WORDS`/forbidden, hanya sesudah baris bilah status). `logo_word(key) -> str | None` (`"logo:newpay"` → `"newpay"`).
- `profiles.learned_profile(lines, profile, rules, *, allow_logo: bool = False)` — kunci `logo:` hanya bila `allow_logo` (dipakai `UnknownReader` saja; QRIS/transfer tanpa profil tidak pernah berkunci logo saat membaca).
- `belajar`:
  - `KIND_LOGO = "logo"`; `KINDS` tetap tiga jenis label untuk `approved_rules` label; `ALL_KINDS = (*KINDS, KIND_LOGO, KIND_ARAH)` untuk Admin/rekonsiliasi (KIND_ARAH di M3a).
  - `_valid_key(key, *, logo_ok: bool)` — kunci profil, atau `logo:<kata>` sah (format kandidat, ≤ `KEY_MAX`) hanya bila `logo_ok`.
  - `votes_for(layout, document, merchant, final, *, approved_logo: frozenset[str] = frozenset())` — kunci `logo:` hanya bila ada di `approved_logo` (K8: suara label untuk aplikasi baru hanya sesudah aplikasinya disetujui).
  - `async def approved_logo_keys(db) -> frozenset[str]` — dari cache `approved_rules` (kunci yang punya aturan `logo` disetujui).
  - `async def learn_app_choice(db, item, choice: str, *, user_id, user_name: str | None) -> bool` — syarat: `item.doc_type == "tidak_dikenali"`, `item.layout.key` berawalan `logo:`, `choice` ∈ kunci profil ∪ {`APP_NEW`}, kata logo TIDAK ada di `normalize_name` dari keterangan transaksi tercatat (bila ada), `document.counterparty.name`, `item.merchant`, `user_name`; suara `Vote("logo", key, choice)` + `recount`; `channel_meta.app_choice = choice` (sekali per item). SAVEPOINT; tidak pernah melempar; tidak meng-commit; panggil `donasi.donate(..., "aplikasi", truth={app: choice})` bila M1c sudah ada.
- `view._flags` + `ask_app: bool` (item `siap`/`tercatat`, `tidak_dikenali`, kunci kerangka `logo:`, belum ada `app_choice`) dan `app_logo: str | None` (kata logo, huruf asli tidak disimpan → huruf besar). Bentuk lama tidak berubah.
- `POST /kotak-struk/{item_id}/aplikasi` body `AppChoiceIn {app: str (≤ 20)}` → `AppChoiceOut {app: str, ask_app: false}`; item tidak ada/milik user lain 404; tidak bisa ditanya (`ask_app` False, sudah dijawab) 409 "Aplikasi bukti ini tidak bisa dipilih"; nilai bukan pilihan 422. Commit di route.

- [ ] **Step 1: Write the failing test**

```python
def test_logo_key_never_from_person_or_merchant_name(self):   # Review Focus 6
    with_names = [["09:41", "Siti Aminah", "Kirim Uang Berhasil", "Nominal Rp50.000"],
                  ["10:57 LTE", "Wahyu Nugroho", "Rp50.000", "Berhasil"]]
    for lines in with_names:
        self.assertIsNone(rule_key(clean_lines(lines), None, forbidden_words=set()))
    self.assertEqual(rule_key(["NEWPAY", "Pembayaran Berhasil", "Total Rp50.000"], None, forbidden_words=set()),
                     "logo:newpay")
    # suara logo ditolak bila kata logo = nama user / pihak lawan / merchant / kata di keterangan
async def test_app_choice_votes_once_and_threshold(self): ...  # user A, B → aturan logo menunggu users=2
async def test_label_votes_for_logo_key_only_after_logo_approved(self): ...
async def test_ask_app_flags(self): ...                       # hanya tidak_dikenali berkunci logo, belum dijawab; app_logo = "NEWPAY"
async def test_aplikasi_route_errors(self): ...               # 404 / 409 / 422; tanpa_kelompok ruang tetap kosong
def test_qris_without_profile_never_gets_a_logo_read_key(self): ...
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_logo app.tests.test_kotak_kerangka app.tests.test_kotak_belajar app.tests.test_ruang_pagar -v`.
- [ ] **Step 3: Implement.** Tes tahap 1 yang memakai `patch.object(kerangka, "LOGO_KEYS", True)` disesuaikan dengan kandidat ketat (laporkan yang berubah).
- [ ] **Step 4: Run to pass** + cek backend; `kotak_sapuan cek` **0 beda** (kerangka berubah, pembacaan tidak); `test_layout_holds_no_pii` diperluas: kunci logo pada semua daftar sapuan tidak memuat kata nama (laporkan jumlah kerangka berkunci logo baru di sapuan).
- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/kerangka.py app/services/kotak_struk/readers/profiles.py app/services/kotak_struk/belajar.py app/services/kotak_struk/view.py app/api/routes/kotak_struk.py app/services/kotak_struk/record.py app/tests/test_kotak_logo.py app/tests/test_kotak_kerangka.py app/tests/test_kotak_belajar.py app/tests/test_ruang_pagar.py
git commit -m "feat(kotak): pilihan Aplikasi apa ini dan suara aturan logo untuk aplikasi tanpa profil"
```

---

### Task M2b: Pembaca memakai aturan `logo` yang disetujui

Spec §5 "`logo` menambah kata pengenal aplikasi"; pre-flight K7, G11.

**Files:**
- Modify: `app/services/kotak_struk/belajar.py` (`approved_rules` 429-455: jenis `logo` ikut dimuat), `readers/profiles.py` (`learned_logo(rules, lines) -> str | None`), `readers/unknown.py` (`_parse`/`_learned` 40-110), `app/services/kotak_struk/kerangka.py` (`_profile_of` 311-316 memakai `doc.issuer` dari aturan — sudah)
- Test: perluas `app/tests/test_kotak_logo.py`, `app/tests/test_kotak_aturan_pembaca.py`

**Interfaces:**
- `approved_rules(db)` → `{rule_key: {"label_total": [...], "label_pihak": [...], "label_tanggal": [...], "logo": [nilai]}}` (nilai `logo` urut pendukung; kunci lain tidak berubah).
- `profiles.learned_logo(rules, lines) -> str | None` — kunci `logo:<kandidat>` (`kerangka.rule_key` dengan `allow_logo`), nilai `logo` pertama yang sah (kunci profil atau `baru`); None tanpa aturan.
- `UnknownReader._parse`: bila `detect_issuer` None dan `learned_logo` memberi kunci profil P → `doc.issuer = P` dan label belajar dibaca dengan kunci P (`learned_for(rules, P)`); `baru` → `doc.issuer` tetap None, label belajar dengan kunci `logo:<kata>`. `apply_header_status`, `_app_receipt_total` tanpa aturan, refs, `doc_type`, keyakinan tanpa label aturan: sama persis. Profil P TIDAK pernah dipakai untuk status (`done_phrases`), pihak (`party_on_top`), atau label `ref`.
- `registry.read_document`, `looks_like_proof`, `detect_issuer`, QRIS/transfer: tidak berubah.

- [ ] **Step 1: Write the failing test**

```python
async def test_approved_logo_maps_unknown_app_to_profile_issuer(self):
    rules = {"logo:newpay": {"logo": ["bsi"]}}
    d = (await read(["NEWPAY", "Pembayaran Berhasil", "Total Rp50.000", "31 Okt 2026 10:00"],
                    ParseContext(today=TODAY, rules=rules))).parsed.doc
    self.assertEqual((d.doc_type, d.issuer), ("tidak_dikenali", "bsi"))

async def test_logo_rules_never_change_status_or_routing(self):   # Review Focus 4
    # setiap daftar sapuan (semua tag) dengan aturan logo jahat untuk kandidatnya (nilai tiap profil + baru) dan
    # label jahat ("status", baris gagal): reader, doc_type, status, {code: level}, ref_hash, flow, check_recordable sama
async def test_logo_baru_unlocks_learned_labels_for_logo_key(self): ...
async def test_empty_rules_change_nothing(self): ...             # tahap 1, tetap hijau dengan LOGO_KEYS
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_logo app.tests.test_kotak_aturan_pembaca -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend; `kotak_sapuan cek` 0 beda; `eval` salinan reviewed sama.
- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/belajar.py app/services/kotak_struk/readers/profiles.py app/services/kotak_struk/readers/unknown.py app/tests/test_kotak_logo.py app/tests/test_kotak_aturan_pembaca.py
git commit -m "feat(kotak): aturan logo yang disetujui memberi penerbit bukti tak dikenal"
```

---

### Task M2c: "Aplikasi apa ini?" di kartu bukti dan bot

Pre-flight §3 "Where the question is asked", G9, G10, G12.

**Files:**
- Modify: `frontend/src/lib/proofFormat.js` (+ `.test.js`), `frontend/src/lib/api.js` (`kotakChooseApp(id, app)`), `frontend/src/components/ProofCard.jsx`, `app/bot/receipt_cmd.py` (`_store_reply` 474-523, callback baru), `app/bot/handlers.py` (`bot_callbacks` 1870: `^k[nxdoa]_`)
- Test: `frontend/src/lib/proofFormat.test.js`, perluas `app/tests/test_kotak_bot.py`, `app/tests/test_web_chat.py`

**Interfaces:**
- `proofFormat.APP_CHOICES` = 12 kunci `ISSUER_LABEL` (urutan tabel) + `{key: 'baru', label: 'Lainnya'}`; `appQuestion(item)` → `{logo, choices}` atau null (`flags.ask_app` tidak true, item tidak `siap`/`tercatat`); `appChoiceOutcome(res)` → `{kind: ok|conflict|error, text}`. Tes backend `test_app_choices_match_profiles` membaca `proofFormat.js` dan membandingkan kunci dengan `PROFILES` (cegah kunci basi).
- `ProofCard`: di bawah badge, untuk `appQuestion` → "Logo di bukti: {logo}. Aplikasi apa ini?" + `<select>` + "Kirim"; sesudah ok → "Terima kasih, dicatat." (tidak membaca ulang item; pembacaan tidak berubah). Tidak memengaruhi Simpan/lewati.
- Bot: `_store_reply` untuk `tidak_dikenali` dengan `flags.ask_app` menambah baris "🏷️ Aplikasi apa ini?" (`ka_{item_id}`) di bawah baris kedua. `ka_{item_id}` → edit pesan: "Logo di bukti: {logo}. Aplikasi apa ini?" + 12 tombol (3 per baris, `ka_{item_id}_{i}`, i = indeks `PROFILES`) + "Lainnya" (`ka_{item_id}_n`) + "↩️ Kembali" (render ulang `_result_reply`). Jawaban → `belajar.learn_app_choice` + commit → pesan hasil dirender ulang tanpa tombol aplikasi (tombol amplop tetap). callback_data ≤ 64 (`ka_` + 36 + `_` + 2). Item milik user lain / sudah dijawab → "⚠️ Aplikasi bukti ini tidak bisa dipilih.".

- [ ] **Step 1: Write the failing test** — frontend: `appQuestion` null tanpa `ask_app`; pilihan 13; hasil 409 → teks server. Bot: tombol muncul hanya untuk `ask_app`; dua langkah; satu suara; tombol amplop tetap mencatat satu kali sesudah menjawab; chat web memakai pola yang sama (callback tercatat di pesan).
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** — cek frontend lengkap + cek bot + cek backend.
- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/proofFormat.js frontend/src/lib/proofFormat.test.js frontend/src/lib/api.js frontend/src/components/ProofCard.jsx app/bot/receipt_cmd.py app/bot/handlers.py app/tests/test_kotak_bot.py app/tests/test_web_chat.py
git commit -m "feat(kotak): tanya aplikasi bukti tak dikenal di kartu bukti, bot, dan chat web"
```

---

### Task M3a: Token arah di kerangka, alasan "Bukan pengeluaran", suara `arah` (server)

Spec §2 baris `arah`, §4.2 butir 4; pre-flight §4, K9, K11 (server), K14.

**Files:**
- Modify: `app/services/kotak_struk/kerangka.py` (`arah_tokens`, `build_layout` menambah `"arah"`), `app/services/kotak_struk/belajar.py` (`KIND_ARAH`, `votes_for_skip`, `learn_from_skip`), `app/services/kotak_struk/record.py` (`skip_item` 139-160: `alasan`, kait suara sesudah UPDATE, sebelum commit; `channel_meta.skip_alasan`), `app/api/routes/kotak_struk.py` (`SkipIn` 37-38 + `alasan`; route 142-151)
- Test: `app/tests/test_kotak_arah.py`, perluas `app/tests/test_kotak_kerangka.py`, `app/tests/test_kotak_belajar.py`

**Interfaces:**
- `kerangka.ARAH_PARTY_WORDS = MONEY_PROVIDERS ∪ penanda profil ∪ {top, up, topup, topu, isi, saldo, deposit, reload}`, `TOP_UP_WORDS = {top, up, topup, topu, isi, saldo, deposit, reload}`, `ARAH_GENERIC = {transfer, pembayaran, bayar, transaksi, payment, transaction, kirim, uang, ke, dari, qris, nominal, total, rekening}`.
- `kerangka.arah_tokens(lines, doc) -> list[str]` — murni, kosakata saja:
  - `judul:<kata>`: kata entri `judul` (baris judul 4 teratas, `TITLE_WORDS`) tanpa kata status (`classify_status`/`_TITLE_EXTRA` status), harus memuat ≥ 1 kata di luar `ARAH_GENERIC`; urutan asli, ≤ 6 kata.
  - `ke:<kata>`: kata terdepan `re.findall("[a-z]+", counterparty.name.lower())` selama ada di `ARAH_PARTY_WORDS`, ≤ 3, minimal 2 kata, ≥ 1 kata penyedia/penanda dan ≥ 1 kata `TOP_UP_WORDS` ("GOPAY TOPU-SXXXX Axxxxxxx" → `ke:gopay topu`; "Shopeepaysitxx Amixxxxx" → tidak ada).
  - Kerangka: `"arah": arah_tokens(...)` (daftar, boleh kosong) — kunci tambahan versi 1; kerangka lama tanpa `arah` = tanpa suara.
- `belajar.KIND_ARAH = "arah"`; `votes_for_skip(layout, document, alasan) -> list[Vote]` — murni: `alasan` ∈ `ARAH_FLOWS`, `alasan ≠ document.flow` (K14), kunci kerangka profil (logo hanya bila disetujui), `document.doc_type ∈ PROOF_TYPES`; satu suara per token: `Vote("arah", f"{key}|{token}", alasan)` bila panjang ≤ `KEY_MAX` (paling banyak 2: satu `judul:`, satu `ke:`).
- `async def learn_from_skip(db, item, alasan, *, user_id) -> int` — seperti `learn_from_correction` (SAVEPOINT, tidak melempar, tidak meng-commit).
- `record.skip_item(db, item_id, user_id, reason, *, alasan=None)` — `alasan` hanya bersama `bukan_pengeluaran` (selain itu `ValueError` di service; route 422); disimpan `channel_meta.skip_alasan`; sesudah UPDATE berhasil: `learn_from_skip` lalu `donasi.donate` (M1c) dalam commit yang sama; galat keduanya tidak pernah menggagalkan lewati.
- `SkipIn.alasan: Literal["top_up","masuk","antar_rekening_sendiri"] | None = None` (+ `model_validator`: alasan dengan reason lain → 422 "Alasan hanya untuk Bukan pengeluaran").

- [ ] **Step 1: Write the failing test**

```python
def test_shopeepay_gopay_topu_gives_ke_token(self):
    sample = corpus_sample("real-shopeepay-topup-01")
    doc = read_flag_on(sample).doc
    self.assertEqual(doc.flow, "keluar")
    self.assertIn("ke:gopay topu", arah_tokens(clean_lines(sample["lines"]), doc))

def test_person_with_provider_prefix_gives_no_token(self): ...  # real-gopay-topup-01, "Shopeepaysitxx Amixxxxx"
def test_status_only_title_gives_no_judul_token(self): ...      # "Transfer Berhasil" → tidak ada
async def test_skip_with_alasan_votes_arah_once(self):         # user A, B → aturan arah shopeepay|ke:gopay topu → top_up menunggu
async def test_agreeing_alasan_gives_no_vote(self): ...         # sint-topup top_up + alasan top_up → 0 suara
async def test_skip_votes_never_fail_the_skip(self): ...        # Review Focus 3: learn_from_skip melempar → 200, dilewati
async def test_skipin_alasan_validation(self): ...              # alasan + duplikat → 422; alasan saja tanpa reason → 422; tanpa alasan = perilaku lama
def test_votes_and_rules_hold_no_pii(self): ...                 # tahap 1, kini termasuk token arah
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_arah app.tests.test_kotak_kerangka app.tests.test_kotak_belajar -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend; `kotak_sapuan cek` 0 beda.
- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/kerangka.py app/services/kotak_struk/belajar.py app/services/kotak_struk/record.py app/api/routes/kotak_struk.py app/tests/test_kotak_arah.py app/tests/test_kotak_kerangka.py app/tests/test_kotak_belajar.py
git commit -m "feat(kotak): alasan Bukan pengeluaran menjadi suara arah uang"
```

---

### Task M3b: Pembaca memakai aturan `arah` yang disetujui (hanya saran)

Spec §5 "`arah`"; pre-flight K10; final review o-1.

**Files:**
- Modify: `app/services/kotak_struk/belajar.py` (`approved_rules`: jenis `arah`), `readers/profiles.py` (`learned_arah(rules, key, tokens) -> str | None`), `app/services/kotak_struk/registry.py` (`read_document` 101-121: sesudah `apply_flow` 117)
- Test: perluas `app/tests/test_kotak_arah.py`, `app/tests/test_kotak_aturan_pembaca.py`, `app/tests/test_kotak_transactions.py`

**Interfaces:**
- `approved_rules` menambah `{"{app}|{token}": {"arah": [flow]}}`.
- `registry.read_document`: bila `proofs_enabled`, `ctx.rules`, `doc.doc_type ∈ PROOF_TYPES`, `doc.issuer` (kunci profil), dan `doc.flow == "keluar"` sesudah `apply_flow`: `flow = learned_arah(ctx.rules, doc.issuer, kerangka.arah_tokens(clean_lines(lines), doc))`; flow ∈ `ARAH_FLOWS` → `doc.flow = flow`, `evidence += ["Arah uang dari aturan belajar"]`. Cek dan `common_checks` tetap dengan `plain`.
- Tidak berubah: status, blokir, cek, `ref_hash`, `soft_duplicate` (catatan o-1 di M4), `check_recordable`, `claim_for_recording`, bot/web tetap menawarkan "Tetap catat"/Simpan.

- [ ] **Step 1: Write the failing test**

```python
async def test_approved_arah_makes_shopeepay_topup_a_suggestion(self):
    rules = {"shopeepay|ke:gopay topu": {"arah": ["top_up"]}}
    res = await read_document(text(TOPUP_LINES), ParseContext(today=TODAY, rules=rules), proofs_enabled=True)
    self.assertEqual(res.parsed.doc.flow, "top_up")

async def test_arah_rule_never_records_or_skips(self):        # Review Focus 5: worker dengan aturan → item siap,
    # flags.skip_suggestion top_up, blocked None; POST /transactions dengan receipt_item_id → 201, 1 transaksi; status
    # tidak pernah dilewati otomatis; bot: "Oke, lewati" dan "Tetap catat" dua-duanya ada, "Tetap catat" mencatat sekali
async def test_arah_only_from_keluar(self): ...                # masuk / antar_rekening_sendiri / top_up / tidak_diketahui tetap
async def test_arah_rules_never_bypass_blocks(self): ...       # Review Focus 4: failed/pending sapuan + aturan arah tiap token
async def test_arah_needs_switch_and_profile_key(self): ...
async def test_corpus_eval_uses_no_rules(self): ...            # tahap 1: real-shopeepay-topup-01 tetap gagal di eval (tanpa aturan)
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_arah app.tests.test_kotak_aturan_pembaca app.tests.test_kotak_transactions -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend; `kotak_sapuan cek` 0 beda; `eval` salinan reviewed sama dengan baseline.
- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/belajar.py app/services/kotak_struk/readers/profiles.py app/services/kotak_struk/registry.py app/tests/test_kotak_arah.py app/tests/test_kotak_aturan_pembaca.py app/tests/test_kotak_transactions.py
git commit -m "feat(kotak): aturan arah yang disetujui menyarankan bukan pengeluaran, tidak pernah otomatis"
```

---

### Task M3c: Pilihan alasan di kartu bukti dan bot `kx_`

Pre-flight §4 "What reaches the server today", K11.

**Files:**
- Modify: `frontend/src/lib/proofFormat.js` (+ `.test.js`; `skipActions` 203-216, `SKIP_REASONS`, `skipReasonChoices(item)`), `frontend/src/lib/api.js` (`kotakSkip(id, reason, alasan)` 638-648: `alasan` hanya bila ada), `frontend/src/components/ProofCard.jsx` (`skip` 186-204, tombol 420-435), `app/bot/receipt_cmd.py` (`_second_row` 387-396, `_proof_reply` 554-559, `_kotak_action` 813-850)
- Test: `frontend/src/lib/proofFormat.test.js`, perluas `app/tests/test_kotak_bot.py`, `app/tests/test_web_chat.py`

**Interfaces:**
- `proofFormat.SKIP_REASONS = [{alasan: 'top_up', label: 'Top-up saldo sendiri'}, {alasan: 'masuk', label: 'Uang masuk'}, {alasan: 'antar_rekening_sendiri', label: 'Ke rekening sendiri'}, {alasan: null, label: 'Lainnya'}]`; `skipReasonChoices(item)` — saran (`flags.skip_suggestion`) di urutan pertama; kosong untuk item yang tidak bisa dilewati (`skipActions` kosong).
- `ProofCard`: "Bukan pengeluaran" membuka pilihan alasan (radio + "Lewati"); "Lainnya" = perilaku lama; Esc/Batal menutup; satu permintaan `kotakSkip(id, 'bukan_pengeluaran', alasan)`. "Sama, lewati" tidak berubah.
- Bot: "🚫 Bukan pengeluaran" `kx_{id}` → edit pesan "Kenapa bukan pengeluaran?" + `kx_{id}_t` / `kx_{id}_m` / `kx_{id}_s` / `kx_{id}_l` (Lainnya); "Oke, lewati" pada tawaran → `kx_{id}_y` (alasan = flow item, tanpa suara karena sama, satu ketukan). Akhiran tidak dikenal → seperti `kx_{id}`. `kd_` tidak berubah. Tombol `kx_{id}` dari pesan lama membuka pilihan (dicatat di docs).

- [ ] **Step 1: Write the failing test** — frontend: urutan saran; "Lainnya" mengirim tanpa `alasan`; payload tidak pernah memuat field lain. Bot: dua langkah, `_y` satu langkah, suara hanya bila alasan ≠ flow, `kx_` lama tetap bekerja, callback_data ≤ 64, chat web merekam tombol pesan yang diedit.
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** — cek frontend + cek bot + cek backend.
- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/proofFormat.js frontend/src/lib/proofFormat.test.js frontend/src/lib/api.js frontend/src/components/ProofCard.jsx app/bot/receipt_cmd.py app/tests/test_kotak_bot.py app/tests/test_web_chat.py
git commit -m "feat(kotak): pilih alasan Bukan pengeluaran di kartu bukti, bot, dan chat web"
```

---

### Task M3d: Admin untuk jenis `logo` dan `arah`

Pre-flight §3 "Admin", K15, G8.

**Files:**
- Modify: `app/api/routes/admin_kotak.py` (`EXAMPLE_VALUE`/`synthetic_example` 50-54, 125-128; `has_warning` 131; votes 215-227), `app/services/kotak_struk/belajar.py` (`decide`: G8), `frontend/src/lib/proofRules.js` (+ `.test.js`; `KIND_LABEL` 11, `ruleAppLabel` 62, `syntheticExample` 70, `voteRows`)
- Test: perluas `app/tests/test_kotak_admin_aturan.py`, `frontend/src/lib/proofRules.test.js`

**Interfaces:**
- Contoh sintetis: `logo` → `Logo "NEWPAY" → BSI Mobile` (nilai `baru` → `→ Aplikasi baru`); `arah` → `Judul "top up" → Top-up` atau `Penerima "GOPAY TOPU…" → Top-up` (kata kunci huruf besar + "…"; tanpa angka). Frontend membangun dari `kind`/`rule_key`/`value` sendiri (pola tahap 1).
- `KIND_LABEL` + `logo: 'Aplikasi'`, `arah: 'Arah uang'`; `ruleAppLabel` untuk `"{app}|…"` = label aplikasinya.
- `GET /admin/kotak/votes`: baris `logo` → `rule_key = "logo:*"`; `arah` → bagian sebelum "|" (K15). `GET /admin/kotak/rules` (≥ 2 user) tetap kunci penuh.
- `decide(setujui)` untuk `logo`/`arah` saat kunci yang sama sudah punya nilai lain `disetujui` → `RuleConflict("Kunci ini sudah punya aturan yang disetujui; cabut dulu")` (409).
- Peringatan `warning` untuk `logo` bila kata logo dua kata (periksa bukan nama orang).

- [ ] **Step 1: Write the failing test** — contoh tanpa angka; votes menyamarkan; G8 409; kind lama tidak berubah; frontend label dan contoh untuk kedua jenis, data rusak → tanpa melempar.
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** — cek backend + cek frontend.
- [ ] **Step 5: Commit**

```bash
git add app/api/routes/admin_kotak.py app/services/kotak_struk/belajar.py frontend/src/lib/proofRules.js frontend/src/lib/proofRules.test.js app/tests/test_kotak_admin_aturan.py
git commit -m "feat(admin): aturan aplikasi dan arah uang di Aturan belajar"
```

---

### Task M4: Dokumentasi, privasi, checklist deploy

**Files:**
- Modify: `docs/kotak-struk.md` — Status (tahap 2, revisi `c9e4a7f2b5d8`, saklar `kotak_donasi`); "Belajar lintas user" (jenis `logo` dan `arah`: kunci, nilai, ambang, pembaca; `LOGO_KEYS` dan penyaring kandidat; token arah; G8; Suara tersamar); bagian baru **"Donasi contoh"** (persetujuan, saklar, apa yang ditangkap dan kapan, nama samaran, pemicu K3, antrean Admin, retensi 30 hari, langkah manusia `add --dari-donasi` → PR, K17); "Kanal" (bot `ka_`, `kx_` dua langkah, `_y`); "Web dan PWA" (kartu: Aplikasi apa ini?, alasan; Settings donasi; Admin Donasi contoh); "API" (endpoint baru, `SkipIn.alasan`, `flags.ask_app/app_logo`); "Konstanta"; "Pemeliharaan" (langkah 5 `purge_samples`; `sample_lines` di langkah 1 dan 3); "Privasi dan masa simpan" (kolom `sample_lines`, `proof_samples`, paragraf baru untuk `privacy.html` siap tempel, baris DPIA baru); "Alat korpus" (`--dari-donasi`, `--tahan`, exit 3); "Batasan yang diketahui" (hapus butir "arah tahap 2"/"logo tahap 2"; tambah: logo hanya di pembaca tidak dikenali, arah hanya QRIS/transfer berprofil dari `keluar`, form Catat tanpa pilihan, tombol `kx_` lama, `soft_duplicate` memakai total/tanggal yang disesuaikan aturan (o-1)); "Tes".
- Modify: `AGENTS.md` — "Deploy Checklist — Kotak Struk belajar tahap 2 (c9e4a7f2b5d8)": tanpa paket/folder/`.env`; hak tabel `receipt_scans`/`users` (seperti e7b3d5a9c1f4); merge → `ls … | grep c9e4a7f2b5d8`; `alembic current` harus `e7b3d5a9c1f4`; `alembic upgrade head` sesudah deploy (penanda revisi; lifespan membuat kolom/tabel); ulang job deploy; verifikasi (`\d proof_samples`, `\d proof_sample_consents`, `\d receipt_scans | grep sample_lines`, `GET /admin/kotak/samples` → `counts`, `GET /user/kotak-donasi` → `available: false`); lalu **urutan saklar donasi**: pemilik memasang paragraf privasi (cek `curl … | grep -c "Donasi contoh"` → 1, ulangi sesudah deploy berikutnya) → `PUT /admin/settings/app_config` menambah `"kotak_donasi": {"web": true}` (gabung dengan isi lama, jangan menimpa `receipt_inbox`) → uji Settings dan satu koreksi dengan akun uji yang setuju → Admin Donasi contoh. Rollback: saklar `kotak_donasi` mati (tangkap berhenti; antrean tetap bisa ditinjau/dihapus).
- Modify: `docs/mobile/PROGRESS.md` (A68: paragraf donasi menunggu pemilik bila relevan); spec `docs/superpowers/specs/2026-11-01-kotak-belajar-lintas-user-design.md` §10 Tahap 2 — satu catatan "as-built" yang merujuk pre-flight K-keputusan (tanpa mengubah teks yang disetujui).

Teks `privacy.html` (draf, disetujui pemilik sebelum saklar `kotak_donasi`):

```html
<p><strong>Donasi contoh (opsional).</strong> Bila Anda mengaktifkan "Bantu Jatahku membaca bukti" di Pengaturan, saat Anda
mengoreksi hasil pembacaan bukti bayar, teks bukti itu dikirim ke pengelola Jatahku untuk ditinjau: nomor rekening, nomor
referensi, dan nomor HP sudah disamarkan, dan nama yang kami kenali diganti nama samaran. Pengelola mengganti nama yang
tersisa lalu memakainya sebagai contoh pengujian pembacaan. Contoh yang belum dipakai dihapus dalam 30 hari; contoh yang
dipakai hanya memuat teks yang sudah disamarkan. Gambar bukti tidak pernah dikirim. Anda bisa mematikannya kapan saja, dan
contoh yang belum dipakai ikut dihapus.</p>
```

- [ ] **Step 1:** Tulis; setiap klaim dicek terhadap kode di branch ini (nama fungsi, konstanta, endpoint, pesan, callback).
- [ ] **Step 2:** `grep -n "c9e4a7f2b5d8\|proof_samples\|kotak_donasi\|dari-donasi" AGENTS.md docs/kotak-struk.md` dan cek backend (tidak berubah); `git diff --check`.
- [ ] **Step 3: Commit**

```bash
git add docs/kotak-struk.md AGENTS.md docs/mobile/PROGRESS.md
git add -f docs/superpowers/specs/2026-11-01-kotak-belajar-lintas-user-design.md   # docs/superpowers/ ada di .gitignore
git commit -m "docs(kotak): tahap 2 belajar lintas user, donasi contoh, privasi, checklist c9e4a7f2b5d8"
```

---

### Task M5: Invarian ujung ke ujung dan verifikasi rilis

**Files:**
- Test: `app/tests/test_kotak_belajar.py` (kelas `EndToEndTahap2Tests`)

- [ ] **Step 1: Tes ujung ke ujung** (SQLite, worker palsu seperti `test_kotak_worker.py`):
  1. **Donasi:** saklar `kotak_donasi` menyala; user A setuju, user B tidak; keduanya membagikan bukti GoPay yang sama dan mengoreksi nominal → satu `proof_samples` (A), B tanpa `sample_lines`; Admin menyetujui dengan baris editan (nama diganti), `GET …/korpus` lolos `load_corpus`; A menarik persetujuan → antreannya kosong.
  2. **Logo:** dua user di rumah tangga berbeda membagikan bukti "NEWPAY" `tidak_dikenali`, menjawab "BSI" (web, bot) → aturan `logo` menunggu users=2; admin menyetujui; user ketiga → `doc.issuer = "bsi"`, status/cek/`ref_hash` sama dengan tanpa aturan; versi gagal bukti itu tetap diblokir.
  3. **Arah:** dua user melewati bukti ShopeePay `real-shopeepay-topup-01` dengan alasan `top_up` → aturan `shopeepay|ke:gopay topu` menunggu; disetujui; user ketiga → `flags.skip_suggestion == "top_up"`, item `siap`, Simpan mencatat satu transaksi; bot menawarkan "Oke, lewati"/"Tetap catat".
  4. Privasi: `layout`, `proof_rule_votes`, `proof_rules`, `proof_samples` tanpa `\d{6,}` dan tanpa kata nama sampel; `purge_layouts` 24 jam kemudian mengosongkan `layout` dan `sample_lines`; `purge_samples` 30 hari; hapus akun A → sampel, persetujuan, suara hilang, aturan dihitung ulang.
- [ ] **Step 2: Run** — tes ini, lalu semua cek backend (angka akhir vs baseline 2761/0/1), `openapi_cek --dasar 7faa202`, `kotak_corpus eval` dan `eval --real-only` (dilaporkan), `eval` salinan reviewed (sama dengan baseline), `kotak_sapuan cek` (0 beda), cek frontend, cek bot; `cek-migrasi.sh` bila Postgres tersedia.
- [ ] **Step 3: Commit**

```bash
git add app/tests/test_kotak_belajar.py
git commit -m "test(kotak): invarian ujung ke ujung belajar lintas user tahap 2"
```

- [ ] **Sesudah M5 (pengendali):** review akhir seluruh branch; PR `feat/kotak-belajar-2` label `migrasi` (deskripsi: ringkasan, checklist AGENTS c9e4a7f2b5d8, urutan saklar `kotak_donasi`, teks privasi untuk pemilik); merge hanya dengan izin pemilik; migrasi sesudah deploy ("Urutan merge PR bermigrasi"); saklar `kotak_donasi` dinyalakan pemilik sesudah `privacy.html` diperbarui.
