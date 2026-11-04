# Kotak Struk: belajar lintas user dan menyalakan saklar `receipt_inbox` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menyalakan `features.receipt_inbox` untuk semua user dengan aman: kerangka tata letak bukti disimpan sebentar, koreksi user menjadi suara, suara dari ≥ 2 user menjadi aturan yang menunggu persetujuan pemilik di Admin, pembaca memakai aturan yang disetujui, kosakata "dibatalkan/ditolak" diblokir, dan titik terbuka review akhir Bagian A (N2, N4, C2, C3, sisa N1) ditutup. Tahap 2 (PR kedua): donasi contoh, aturan logo, top-up/arah uang.

**Architecture:** Worker menyimpan kerangka aman (`receipt_scans.layout`: label tersamar, jenis nilai, nominal/tanggal, HMAC nama; tanpa nomor) untuk QRIS/transfer/tidak dikenali. `record.mark_recorded` (satu-satunya titik yang dilewati semua pencatatan pertama: web, batch, bot, kirim ulang) dan `record.skip_item` memanggil `belajar.learn_from_correction`, yang membandingkan hasil baca dengan transaksi yang tercatat dan menulis suara (`proof_rule_votes`, satu per user per aturan) lalu menghitung ulang `proof_rules` (≥ 2 user → `menunggu`). Admin menyetujui/menolak/mencabut. Worker memuat aturan `disetujui` (cache 5 menit) ke `ParseContext.rules`; pembaca QRIS/transfer/tidak dikenali mendahulukan label dari aturan. Status, arah uang, dan cek duplikat tidak pernah membaca aturan.

**Tech Stack:** FastAPI, SQLAlchemy async (Postgres; SQLite + aiosqlite di tes), Alembic, python-telegram-bot (handler yang sama untuk chat web), React 18 + Vite, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-01-kotak-belajar-lintas-user-design.md` (mengikat; keputusan pemilik §12). **Pre-flight (wajib dibaca tiap implementer):** `.superpowers/sdd/2026-10-26-bagikan-ke-jatahku/a15-preflight.md` — baris kode yang dirujuk, konflik K1–K10, celah G1–G10, dan input konkret §9.1. Rencana ini mengikuti rekomendasi pre-flight; bila pemilik/pengendali memutuskan lain, ubah task terkait sebelum dikirim.

**Dasar:** branch `feat/kotak-belajar` @ 0109ab3 (= origin/main 2125226 + commit spec). Baseline tes backend di 0109ab3: **2393 tes, 1 gagal, 1 dilewati** — gagal yang sudah ada: `test_fund_shift_integration…test_basic_quota_bot_fund_shift_finishes_started_input` (bergantung tanggal: struk "10 Okt" di luar bulan kuota sejak 1 Nov; tidak terkait Kotak Struk); dilewati: `test_real_corpus_meets_release_gate`. `kotak_corpus eval`: 10 sampel, lulus, exit 0 (15 sampel nyata `reviewed: false` dilewati).

## Global Constraints

- Git: jangan `git add -A`; stage per path; jangan commit `frontend/dist/` (sesudah build: `git checkout -- frontend/dist`). Setiap commit diakhiri baris atribusi sesi yang diberikan pengendali.
- Dua PR. **Tahap 1** (L0–L8): branch `feat/kotak-belajar`, satu PR berlabel `migrasi`, satu revisi alembic `e7b3d5a9c1f4` (`down_revision = '2d51b9031a6b'`). **Tahap 2** (M1–M3): branch `feat/kotak-belajar-2` dari main sesudah tahap 1 tayang dan saklar menyala; PR kedua, label `migrasi` (M1).
- **API hanya bertambah** (AGENTS.md Aplikasi mobile #2): `python3 -m app.scripts.openapi_cek --dasar 2125226` keluar 0 di setiap task backend. Endpoint baru memakai `response_model`.
- **Struk tidak pernah tercatat diam-diam atau dua kali** (Aplikasi mobile #11): belajar tidak membuat transaksi, tidak mengubah status item, tidak mengubah `check_recordable`/`claim_for_recording`/dedup; galat belajar ditelan dan dicatat di log.
- **Aturan tidak pernah melonggarkan** blokir status gagal/pending, cek arah uang, atau cek duplikat (spec §1.3). Aturan hanya mengubah dari label mana nilai dibaca, dan hanya di pembaca QRIS, transfer, dan tidak dikenali. Pembaca struk belanja tidak pernah memakai aturan; struk belanja tidak pernah menghasilkan kerangka atau suara.
- **Privasi (spec §8):** `layout`, `proof_rule_votes`, `proof_rules` tidak pernah memuat nama (hanya HMAC `merchants.hmac_hex`), nomor rekening/HP/referensi, deret ≥ 6 digit, atau teks bebas. Label: digit → `#`, ≤ 40 karakter, ≤ 5 kata, setiap kata di `LABEL_WORDS`, tanpa kata nama pihak lawan/pengirim/user (G2). Label yang memuat `#` tidak pernah menjadi suara. Kerangka dihapus 24 jam sejak dibaca untuk item selesai dan saat kedaluwarsa (K2).
- Ambang aturan: **2 user berbeda** (`RULE_MIN_USERS = 2`); rumah tangga dihitung dan ditampilkan, bukan ambang.
- Status aturan: `menunggu`, `disetujui`, `ditolak`, `dicabut`. Transisi (G5): setujui ← menunggu|ditolak|dicabut; tolak ← menunggu; cabut ← disetujui; selain itu 409. Suara baru memperbarui hitungan di status apa pun tanpa mengubah statusnya.
- Jenis aturan tahap 1: `label_total`, `label_pihak`, `label_tanggal`. `arah` dan `logo` di tahap 2 (K7; M2–M3). Kunci aturan (`rule_key`): kunci profil (`detect_issuer(...).key`) atau `logo:<kata>` (G4); tanpa kunci → tanpa kerangka dan tanpa suara.
- Konstanta baru di `app/services/kotak_struk/config.py`: `LAYOUT_MAX_LINES = 60`, `LAYOUT_LABEL_MAX = 40`, `LAYOUT_LABEL_WORDS = 5`, `LAYOUT_TTL = timedelta(hours=24)`, `RULE_MIN_USERS = 2`, `RULE_CACHE_S = 300`, `FIX_TTL_S = 300`, `LAYOUT_TYPES = {"qris", "transfer", "tidak_dikenali"}`.
- Tes pembaca, `kotak_corpus`, dan tes yang ada berjalan **tanpa** aturan (deterministik); hanya tes khusus yang menyuntik `ParseContext(rules=…)`.
- `app/services/` tidak menanyakan keanggotaan household sendiri (`test_ruang_pagar.py`): household suara = `item.household_id`.
- Teks UI, pesan bot, dan docstring Bahasa Indonesia.
- **Cek tiap task backend** (laporkan angka, bandingkan dengan baseline 2393/1 gagal/1 dilewati):
  1. `cd /home/claude/jatahku && DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python3 -m unittest discover -s app/tests -t .`
  2. `python3 -m app.scripts.openapi_cek --dasar 2125226` → exit 0.
  3. `python3 -m app.scripts.kotak_corpus eval` → exit 0; task yang menyentuh pembaca juga menjalankan `eval --corpus <salinan scratch corpus.json dengan semua "reviewed": true>` dan melaporkan sampel yang berubah (G8).
  4. Task yang menyentuh pembaca/status/worker: `python3 -m unittest app.tests.test_kotak_sapuan -v` (L0b) dan melaporkan setiap entri snapshot yang berubah.
- **Cek tiap task frontend:** `cd /home/claude/jatahku/frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`, lalu `git checkout -- frontend/dist`. Komponen JSX tidak bisa diuji di Node: logika di modul murni `src/lib/`.
- Postgres tidak tersedia di sandbox: cek migrasi di CI (workflow "Migrasi"); bila ada Postgres kosong, `DATABASE_URL=postgresql+asyncpg://… JWT_SECRET=x .github/scripts/cek-migrasi.sh origin/main`.

## Review Focus

1. **Tidak pernah tercatat dua kali atau diam-diam** — belajar di `mark_recorded` berjalan sekali per transaksi, tidak membuat transaksi, dan galatnya tidak membiarkan item `siap`. Dipin `test_learning_never_records_or_duplicates` (L2).
2. **Aturan tidak pernah melewati blokir** — semua bukti gagal/pending di set sapuan, dengan semua jenis aturan disuntik (termasuk aturan jahat berlabel "Status"/baris gagal), tetap `status_gagal`/`status_pending` yang sama; `check_recordable` tetap MSG_BLOCKED. Dipin `test_rules_never_bypass_status_blocks` (L3).
3. **Tanpa PII di kerangka dan tabel aturan** — tidak ada deret ≥ 6 digit, nama pihak lawan/pengirim/user, atau teks nama polos. Dipin `test_layout_holds_no_pii` (L1) dan `test_votes_and_rules_hold_no_pii` (L2), ujung ke ujung di L8.
4. **Struk belanja tidak berubah oleh sapuan** — setiap daftar bertanda `store` tetap `struk_belanja`/`berhasil`/tanpa cek/rincian dan merchant tersimpan, di kedua saklar. Dipin `test_store_receipts_unchanged_by_sweep` (L0b), dijalankan di L3, L5, L6a–e.
5. **API hanya bertambah dan migrasi idempoten** — `openapi_cek --dasar 2125226` exit 0; `test_migration_is_idempotent` (L1/L2) dan workflow "Migrasi" hijau.
6. **Tanpa aturan = perilaku hari ini** — `test_empty_rules_change_nothing` dan `test_corpus_eval_uses_no_rules` (L3).

---

## Peta file

**Baru (backend):** `app/services/kotak_struk/kerangka.py` (kerangka + `safe_label` + `rule_key`), `app/services/kotak_struk/belajar.py` (suara, aturan, `learn_from_correction`, cache, `forget_user`), `app/api/routes/admin_kotak.py`, `app/scripts/kotak_hari_pertama.py`, `app/scripts/kotak_sapuan.py`, `alembic/versions/e7b3d5a9c1f4_kotak_belajar.py`, `app/tests/fixtures/kotak/sweep_lines.json`, `app/tests/fixtures/kotak/sweep_snapshot.json`.
**Tes baru:** `app/tests/test_kotak_hari_pertama.py`, `test_kotak_sapuan.py`, `test_kotak_kerangka.py`, `test_kotak_belajar.py`, `test_kotak_aturan_pembaca.py`, `test_kotak_admin_aturan.py`.
**Diubah (backend):** `app/models/models.py`, `app/services/kotak_struk/{config,schema,worker,maintenance,record}.py`, `readers/{base,profiles,proof_common,qris,transfer,unknown}.py`, `registry.py`, `app/services/scheduler.py`, `app/services/account_deletion.py`, `app/services/merge.py`, `app/services/receipt_scan.py` (`accuracy_stats`), `app/bot/receipt_cmd.py`, `app/bot/handlers.py`, `app/main.py`.
**Frontend:** baru `src/lib/proofRules.js` (+ `proofRules.test.js`); diubah `src/lib/api.js`, `src/pages/Admin.jsx`.
**Dokumen:** `docs/kotak-struk.md`, `docs/scan-struk.md`, `AGENTS.md`, `docs/mobile/PROGRESS.md`, `docs/mobile/03-workflow.md`.

---

# Tahap 1 — `feat/kotak-belajar` (satu PR, label `migrasi`)

Urutan pengerjaan: L0 → L0b → L1 → L2 → L2b → L3 → L4a → L4b → L5 → L6a → L6b → L6c → L6d → L6e → L7 → L8.

### Task L0: Perintah sekali jalan "hari pertama"

Keputusan pemilik §12.3 (opsi B): item `siap` lama dari form Catat (`source = 'web_form'`) dilewati (`batal`) tepat sebelum saklar dinyalakan; item bot/chat/share tidak disentuh. Pre-flight "Day-1 one-off command", K8.

**Files:**
- Create: `app/scripts/kotak_hari_pertama.py`
- Test: `app/tests/test_kotak_hari_pertama.py`

**Interfaces:**
- Consumes: `record.skip_item(db, item_id, user_id, reason) -> bool` (`record.py:131-150`, UPDATE bersyarat `siap|gagal → dilewati`, commit sendiri).
- Produces:
  - `async def candidates(db, *, now, older_than: timedelta) -> list[tuple[uuid, uuid, str | None]]` — `(id, user_id, doc_type)` item `status == 'siap'`, `source == 'web_form'`, `created_at < now - older_than`, urut `created_at`.
  - `async def run(db, *, now, older_than, apply: bool) -> Summary` — `Summary(found: int, by_doc_type: dict[str, int], users: int, skipped: int, lost: int)`; `apply=False` tidak menulis apa pun; `apply=True` memanggil `skip_item(..., "batal")` per item (`lost` = False karena dicatat/dilewati bersamaan).
  - CLI: `python3 -m app.scripts.kotak_hari_pertama [--apply] [--lebih-lama-dari JAM]` (bawaan 24; 0 diizinkan; negatif ditolak argparse). Mencetak hanya angka (per `doc_type`, jumlah user), tanpa id, nama, atau nominal. Exit 0; galat database tidak ditangkap (traceback, exit 1). Docstring modul: cara pakai di VPS (`cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.kotak_hari_pertama`), dry-run dulu, dijalankan tepat sebelum saklar menyala, risiko antrean offline (simpanan form Catat yang masih di antrean HP untuk item yang dilewati akan ditolak saat sinkron, karena itu bawaan 24 jam).

- [ ] **Step 1: Write the failing test** (SQLite, pola `test_kotak_maintenance.py`):

```python
async def test_dry_run_counts_only_old_web_form_siap(self):
    old = await self.item(source="web_form", status="siap", created_at=NOW - timedelta(hours=30), doc_type="qris")
    await self.item(source="web_form", status="siap", created_at=NOW - timedelta(hours=2))          # terlalu baru
    await self.item(source="telegram", status="siap", created_at=NOW - timedelta(days=3))          # bot: tidak
    await self.item(source="pwa_share", status="siap", created_at=NOW - timedelta(days=3))
    await self.item(source="web_form", status="gagal", created_at=NOW - timedelta(days=3))         # bukan siap
    await self.item(source="web_form", status="tercatat", created_at=NOW - timedelta(days=3))
    s = await run(self.db, now=NOW, older_than=timedelta(hours=24), apply=False)
    self.assertEqual((s.found, s.by_doc_type, s.skipped), (1, {"qris": 1}, 0))
    self.assertEqual((await self.get(old.id)).status, "siap")

async def test_apply_skips_with_reason_batal_and_is_idempotent(self): ...   # status dilewati, channel_meta.skip_reason == "batal"; run kedua found == 0
async def test_zero_cutoff_takes_every_web_form_siap(self): ...
async def test_lost_race_is_counted_not_raised(self): ...   # skip_item dipatch mengembalikan False → lost == 1
def test_cli_rejects_negative_hours(self): ...
def test_output_has_no_ids_or_names(self): ...           # stdout tidak memuat str(item.id) atau nama user
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_hari_pertama -v` → FAIL (modul belum ada).
- [ ] **Step 3: Implement** (pola argparse/`asyncio.run`/`engine.dispose()` seperti `app/scripts/siklus_household.py`).
- [ ] **Step 4: Run to pass** — tes task + tiga cek backend Global Constraints.
- [ ] **Step 5: Commit**

```bash
git add app/scripts/kotak_hari_pertama.py app/tests/test_kotak_hari_pertama.py
git commit -m "feat(kotak): perintah sekali jalan melewati item siap lama form Catat sebelum saklar menyala"
```

---

### Task L0b: Snapshot sapuan pembaca (penjaga struk belanja dan blokir)

Satu alat dan satu fixture yang dipakai L3, L5, L6a–e untuk membuktikan "tidak ada struk belanja berubah, tidak ada blokir hilang" (spec §9.1). Dibuat dari pohon SEBELUM perubahan pembaca apa pun.

**Files:**
- Create: `app/scripts/kotak_sapuan.py`, `app/tests/fixtures/kotak/sweep_lines.json`, `app/tests/fixtures/kotak/sweep_snapshot.json`
- Test: `app/tests/test_kotak_sapuan.py`

**Interfaces:**
- `sweep_lines.json`: `[{"id": str, "tags": ["store"|"proof"|"failed"|"pending"|"probe"], "lines": [str], "user_name": str|null}]`. Isi minimal: semua sampel `corpus.json` (juga yang `reviewed: false`, id sama), 4 struk `receipt_ocr_lines.json` (`store`), daftar struk dari tes (`STORE_LINES`, `SUKSES_LINES`, `TITLED_STORES`, struk "TOKO MANDIRI JAYA"/"BAKSO MANDIRI"/"KANTIN BNI" `test_kotak_kalibrasi.py`, struk QRIS/EDC/PLU di `test_kotak_worker.py`) bertanda `store`, `ONE_MARKER_SLIPS` dan `N1_SLIPS`, semua input tabel §9.1 pre-flight (`probe`), dan bukti gagal/pending dari `test_kotak_readers.py`/`test_kotak_kalibrasi.py` (`failed`/`pending`). ≥ 120 daftar. Tanpa nomor/nama nyata (repo publik): salin dari tes yang sudah ada saja.
- `async def snapshot_entry(lines, *, proofs_enabled, user_name) -> dict` — `read_document` + `worker._outcome` dengan `ParseContext(today=date(2026, 11, 1), user_name=…)`: `{reader, doc_type, issuer, status, checks: {code: level}, total, paid_date, counterparty, unread_proof, lines: n, merchant}`.
- `async def build(path_lines) -> dict` — `{id: {"off": entry, "on": entry}}`.
- CLI: `python3 -m app.scripts.kotak_sapuan tulis` (menulis snapshot), `python3 -m app.scripts.kotak_sapuan cek` (mencetak beda per id/saklar/field; exit 1 bila ada beda).
- Tes:
  - `test_snapshot_matches` — `build()` == `sweep_snapshot.json` (perubahan yang disengaja = `tulis` ulang, dan laporan task mencantumkan output `cek` sebelum `tulis`).
  - `test_store_receipts_unchanged_by_sweep` — **independen dari snapshot**: setiap daftar bertanda `store`, kedua saklar: `doc_type == "struk_belanja"`, `status == "berhasil"`, `checks == {}`, `unread_proof is False`, `lines > 0`, `merchant` tidak kosong. Pengecualian tercatat (A14: struk dengan kaki "Transaksi gagal - struk ini tidak sah" = blokir; "Pembayaran pending …" = warn) diberi tag sendiri (`store_void`, `store_pending`), bukan `store`.
  - `test_failed_proofs_stay_blocked` — setiap `failed`: `status_gagal: block` di kedua saklar; setiap `pending`: `status_pending: warn` (atau block bila juga gagal).

- [ ] **Step 1: Write the failing test** (tiga tes di atas).
- [ ] **Step 2: Run to fail** — modul belum ada.
- [ ] **Step 3: Implement, lalu `tulis`.** Bila `test_store_receipts_unchanged_by_sweep` atau `test_failed_proofs_stay_blocked` gagal di pohon dasar untuk daftar tertentu, itu temuan: jangan diubah tagnya diam-diam; catat di laporan (kemungkinan bagian dari L6) dan beri tag `known_<item>` (mis. `known_c3`), lalu tes melewati tag itu dengan alasan tertulis di fixture.
- [ ] **Step 4: Run to pass** + cek backend (`eval` tidak berubah).
- [ ] **Step 5: Commit**

```bash
git add app/scripts/kotak_sapuan.py app/tests/fixtures/kotak/sweep_lines.json app/tests/fixtures/kotak/sweep_snapshot.json app/tests/test_kotak_sapuan.py
git commit -m "test(kotak): snapshot sapuan pembaca untuk struk belanja dan bukti gagal"
```

---

### Task L1: Kerangka tata letak di worker, kolom `layout`, migrasi, pembersihan

Spec §3a; pre-flight §3a, K1 (kolom, bukan `document.layout`), K2 (24 jam sejak dibaca, hanya item selesai), G1, G2, G4.

**Files:**
- Create: `app/services/kotak_struk/kerangka.py`, `alembic/versions/e7b3d5a9c1f4_kotak_belajar.py`
- Modify: `app/models/models.py` (`ReceiptScan`, sesudah `transaction_ids` ±baris 624: `layout: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)`)
- Modify: `app/services/kotak_struk/schema.py` (`_COLUMNS` + `("layout", "JSONB")`), `config.py` (konstanta Global Constraints)
- Modify: `app/services/kotak_struk/worker.py` (`_outcome` 188-240: kolom `layout`; `process_item` 342-353 meneruskan nama user)
- Modify: `app/services/kotak_struk/maintenance.py` (`expire_items` 39-49 juga `layout=None`; baru `purge_layouts`), `app/services/scheduler.py` (`kotak_maintenance` 324-347: langkah 3)
- Test: `app/tests/test_kotak_kerangka.py`, perluas `test_kotak_worker.py`, `test_kotak_maintenance.py`, `test_kotak_schema.py`

**Interfaces:**
- Produces (`kerangka.py`, fungsi murni kecuali disebut):
  - `LABEL_WORDS: frozenset[str]` — kata dari semua label `GENERIC_LABELS` dan `AppProfile.labels` + daftar kurasi (mis. jumlah, kirim, uang, bayar, pembayaran, total, nominal, transfer, ke, dari, tujuan, penerima, nama, merchant, toko, tanggal, waktu, selesai, transaksi, biaya, admin, layanan, saldo, terpakai, dibayar, debit, sumber, metode, jenis, keterangan, catatan, tagihan, harga, subtotal, amount, date, time, paid, payment, recipient, to, from, name).
  - `safe_label(text: str | None, *, forbidden_words: set[str]) -> str | None` — dinormalkan huruf kecil, spasi dirapatkan, titik dua/tanda baca ujung dibuang; `None` bila kosong, memuat digit (digit → `#` lalu ditolak untuk suara; disimpan di kerangka sebagai `#`), > `LAYOUT_LABEL_MAX` karakter, > `LAYOUT_LABEL_WORDS` kata, ada kata di luar `LABEL_WORDS`, atau ada kata di `forbidden_words`.
  - `rule_key(lines: list[str], profile: AppProfile | None, *, forbidden_words: set[str]) -> str | None` — `profile.key` bila ada; selain itu `logo:<kata>` dari baris pertama di antara 3 baris bersih pertama yang 1–2 kata, hanya huruf, ≥ 3 huruf, bukan label/kata status/kata di `LABEL_WORDS`, bukan kata di `forbidden_words` (huruf kecil, ≤ 40); selain itu `None` (G4).
  - `build_layout(lines: list[str], doc: DokumenBayar, secrets: Secrets, *, user_name: str | None) -> dict | None` — `None` bila `doc.doc_type not in LAYOUT_TYPES` atau `rule_key` None. Bentuk:
    `{"v": 1, "key": str, "lines": [ {"i": int, "label": str|None, "kind": "nominal", "amount": int} | {"i", "label", "kind": "tanggal", "date": "YYYY-MM-DD"} | {"i", "label", "kind": "nama", "h": hmac_hex(normalize_name(nilai))} | {"i", "label": None, "kind": "judul", "words": [str ≤ 6]} ]}`, paling banyak `LAYOUT_MAX_LINES` entri, urut `i` (indeks di `clean_lines(lines)`).
    Aturan baris: baris yang memuat nilai `secrets` (ref, rekening, NMID) atau deret ≥ `LONG_DIGITS` digit di luar nominal/tanggal (`split_long_numbers`) **tidak masuk sama sekali**. `nominal`: `amounts_in` pada sisa baris sesudah label; label = teks sebelum nominal, atau baris sebelumnya bila baris ini nominal saja. `tanggal`: `parse_datetime_id`, label = teks sebelum tanggal. `nama`: nilai berbentuk nama (1–6 kata, huruf/`.'&-`, tanpa digit, bukan kata status/label saja) sesudah label (sebaris, titik dua, atau label berdiri sendiri di baris sebelumnya), atau tanpa label. `judul`: hanya baris di 4 baris pertama yang memuat judul status (`proof_common._STATUS_TITLE`) atau kata top-up/uang masuk (`transfer._TOP_UP`, `_INCOMING`): kata huruf kecil tanpa digit, tanpa kata nama. `forbidden_words` = kata `normalize_name` dari `doc.counterparty.name`, nama pengirim bila terbaca, dan `user_name`.
- Kolom `receipt_scans.layout` (JSON/JSONB, nullable); tidak pernah masuk `view.item_detail`.
- `maintenance.purge_layouts(db, *, now) -> int` — satu UPDATE: `layout = NULL` untuk `status IN ('tercatat','dilewati','kedaluwarsa') AND layout IS NOT NULL AND (processed_at IS NULL OR processed_at < now - LAYOUT_TTL)`; commit sendiri. `expire_items` juga mengosongkan `layout`. `kotak_maintenance` langkah 3 dengan sesi dan `try` sendiri.
- Migrasi `e7b3d5a9c1f4` (L1 membuat berkasnya; L2 menambah tabel): `upgrade()` = setiap pernyataan `KOTAK_DDL` (idempoten, termasuk kolom baru); `downgrade()` = `ALTER TABLE receipt_scans DROP COLUMN IF EXISTS layout`. Docstring: idempoten, lifespan menjalankan DDL yang sama (tanpa jendela 500).

- [ ] **Step 1: Write the failing test**

```python
def test_layout_shape_for_transfer(self):
    lines = ["GoPay", "Transfer Berhasil", "Ditransfer ke", "BUDI SANTOSO", "Mandiri 1234567890",
             "Jumlah Kirim Uang", "Rp10.000", "Tanggal 31 Okt 2026", "No. Ref 123456789012"]
    lay = build_layout(lines, transfer_doc(name="BUDI SANTOSO", total=10000), Secrets(ref_values=["123456789012"],
                       account_number="1234567890"), user_name="Andi Pratama")
    kinds = {(e["kind"], e.get("label")) for e in lay["lines"]}
    self.assertIn(("nominal", "jumlah kirim uang"), kinds)
    self.assertIn(("tanggal", "tanggal"), kinds)
    self.assertIn(("nama", "ditransfer ke"), kinds)
    self.assertEqual(lay["key"], "gopay")

def test_layout_holds_no_pii(self):    # Review Focus 3; set slip dari sweep_lines.json bertanda proof/probe
    for case in proof_cases():
        dumped = json.dumps(build_layout(...))
        self.assertNotRegex(dumped, r"\d{6,}")
        for word in name_words(case):          # pihak lawan, pengirim, user_name dari sampel
            self.assertNotIn(word, dumped.lower())

def test_label_with_name_or_unknown_word_is_dropped(self): ...  # "Transfer ke BUDI SANTOSO Rp10.000" → label None
def test_store_receipt_has_no_layout(self): ...                  # struk_belanja → None
def test_logo_key_for_unknown_app_and_none_for_status_bar_or_name(self): ...
async def test_worker_stores_layout_column_not_in_document(self): ...   # process_item → item.layout ada; "layout" not in item.document; item_detail tanpa layout
async def test_purge_layouts_only_finished_and_older_than_24h(self): ...
async def test_expire_clears_layout(self): ...
def test_every_new_column_has_ddl(self): ...   # sudah ada; kini mencakup layout
def test_migration_is_idempotent(self): ...    # berkas e7b3d5a9c1f4: down_revision '2d51b9031a6b'; setiap op.execute dari KOTAK_DDL; create_* if_not_exists (sesudah L2)
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_kerangka app.tests.test_kotak_worker app.tests.test_kotak_maintenance app.tests.test_kotak_schema -v`.
- [ ] **Step 3: Implement.** Kerangka dibangun di `_outcome` dari `text.lines`, `res.parsed.doc`, `res.parsed.secrets` (sebelum dokumen disamarkan untuk `unread_proof`); galat di `build_layout` → `layout=None` + log peringatan (item tetap `siap`).
- [ ] **Step 4: Run to pass** + cek backend; `kotak_sapuan cek` tanpa beda (kerangka tidak mengubah hasil baca).
- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/kerangka.py app/services/kotak_struk/config.py app/services/kotak_struk/schema.py app/services/kotak_struk/worker.py app/services/kotak_struk/maintenance.py app/services/scheduler.py app/models/models.py alembic/versions/e7b3d5a9c1f4_kotak_belajar.py app/tests/test_kotak_kerangka.py app/tests/test_kotak_worker.py app/tests/test_kotak_maintenance.py app/tests/test_kotak_schema.py
git commit -m "feat(kotak): kerangka tata letak bukti tanpa data pribadi, dihapus 24 jam"
```

---

### Task L2: Suara dan aturan: tabel, `learn_from_correction`, ambang, hapus akun

Spec §3b, §4.1–4.3; pre-flight §3b, §4, §8, K3, K5, K6 (nilai suara), K9, G3, G7. Tahap 1 hanya `label_total`, `label_pihak`, `label_tanggal` (K7).

**Files:**
- Create: `app/services/kotak_struk/belajar.py`
- Modify: `app/models/models.py` (sesudah `ReceiptLearnVote` ±665: `ProofRuleVote`, `ProofRule`), `alembic/versions/e7b3d5a9c1f4_kotak_belajar.py` (dua tabel + indeks, `if_not_exists=True`; downgrade `drop_table(..., if_exists=True)`)
- Modify: `app/services/kotak_struk/record.py` (`mark_recorded` 200-221; `skip_item` 131-150 hanya kait kosong untuk M3, tanpa suara di tahap 1)
- Modify: `app/services/account_deletion.py` (`delete_account` 177-217), `app/services/merge.py` (`merge_users`, sebelum `delete(User)` ±280)
- Test: `app/tests/test_kotak_belajar.py`, perluas `test_kotak_transactions.py`, `test_kotak_bot.py`, `test_account_deletion.py`, `test_kotak_schema.py`

**Interfaces:**
- Models:
  - `ProofRuleVote` (`proof_rule_votes`): `kind String(20)`, `rule_key String(60)`, `value String(60)`, `user_id` FK users `ondelete="CASCADE"`, PK `(kind, rule_key, value, user_id)`; `household_id Uuid NULL` (tanpa FK, seperti `receipt_scans.household_id`); `created_at` server_default now.
  - `ProofRule` (`proof_rules`): `id Uuid PK`, `kind`, `rule_key`, `value`, `users Integer`, `households Integer`, `status String(12)`, `created_at`, `decided_at NULL`, `decided_by Uuid NULL` FK users `ondelete="SET NULL"`, `note String(200) NULL`; `UniqueConstraint("kind","rule_key","value", name="uq_proof_rule")`; `Index("ix_proof_rules_status")`.
- `belajar.py`:
  - `@dataclass Final(amount: int | None, txn_date: date | None, description: str | None, today: date)`.
  - `@dataclass Vote(kind: str, rule_key: str, value: str)`.
  - `def votes_for(layout: dict | None, document: dict | None, merchant: str | None, final: Final) -> list[Vote]` — murni; paling banyak satu suara per jenis:
    - `label_total`: `final.amount` ≠ total terbaca (juga bila total tidak terbaca); baris `nominal` dengan `amount == final.amount` dan label tidak `None` serta tanpa `#`; tepat satu label berbeda → suara; beberapa → yang diawali "total" bila tepat satu; selain itu tanpa suara (G3).
    - `label_pihak`: n-gram 1–6 kata dari `normalize_name(final.description)`; `hmac_hex` tiap n-gram dicocokkan dengan `h` baris `nama` berlabel; cocok dan nilai baris itu bukan nama yang terbaca (`hmac_hex(normalize_name(counterparty.name or merchant))` berbeda) → suara (K5).
    - `label_tanggal`: `final.txn_date` ≠ tanggal bukti (WIB dari `paid_at`) dan ≠ `final.today`, sama dengan `date` baris `tanggal` berlabel → suara (K9).
  - `async def record_votes(db, votes, *, user_id, household_id) -> None` — `pg_insert(ProofRuleVote).on_conflict_do_nothing()`; lalu `recount(db, kind, rule_key, value)`.
  - `async def recount(db, kind, rule_key, value) -> ProofRule | None` — `COUNT(*)`, `COUNT(DISTINCT household_id)`; baris aturan dibuat (`menunggu`) saat `users >= RULE_MIN_USERS`; baris yang ada hanya diperbarui hitungannya; tidak pernah dihapus.
  - `async def learn_from_correction(db, item: ReceiptScan, final: Final, *, user_id) -> int` — jumlah suara; tidak pernah melempar (galat → log + 0); tanpa commit sendiri (pemanggil yang commit); tidak menyentuh item atau transaksi. Tidak jalan bila `item.layout` kosong atau `item.doc_type not in LAYOUT_TYPES`.
  - `async def forget_user(db, user_id) -> None` — kunci aturan yang pernah dipilih user, hapus suaranya, `recount` tiap kunci (G7). Dipanggil `delete_account` (sebelum loop hapus 208-210) dan `merge_users` (sebelum user sumber dihapus).
- `record.mark_recorded`: sesudah `transaction_ids` ditambah id BARU (bukan jalur awal 210-211), untuk jenis selain struk belanja: muat `Transaction` (amount, transaction_date, description), `Final(..., today=date.today())`, lalu `learn_from_correction` di `db.begin_nested()` yang sama dengan `_learn`, galat ditelan; satu `db.commit()` yang sudah ada. Web (`after_recorded`), batch, bot (`handlers._receipt_feedback_saved` 435), dan `heal_recorded` semuanya lewat sini (K3).

- [ ] **Step 1: Write the failing test**

```python
def test_amount_correction_votes_label_of_matching_line(self):
    lay = {"v": 1, "key": "jago", "lines": [{"i": 3, "label": "nominal", "kind": "nominal", "amount": 10000},
                                           {"i": 5, "label": "total bayar", "kind": "nominal", "amount": 12500}]}
    votes = votes_for(lay, {"amounts": {"total": 10000}}, None, Final(12500, None, "Transfer ke X", TODAY))
    self.assertEqual(votes, [Vote("label_total", "jago", "total bayar")])

def test_typed_amount_not_printed_gives_no_vote(self): ...
def test_two_labels_same_amount_prefers_total_else_none(self): ...
def test_name_vote_only_when_printed_and_changed(self): ...      # nama panggilan yang tidak tercetak → tanpa suara
def test_date_vote_never_for_today_or_doc_date(self): ...
async def test_threshold_two_distinct_users(self): ...            # user A: suara saja, tanpa ProofRule; user B: ProofRule menunggu users=2
async def test_same_user_votes_once(self): ...
async def test_households_counted(self): ...
async def test_learning_never_records_or_duplicates(self):       # Review Focus 1
    # web POST /transactions dengan receipt_item_id dan nominal dikoreksi → 1 transaksi, 1 suara
    # kirim ulang client_ref (heal_recorded) → tetap 1 transaksi, 1 suara
    # learn_from_correction dipatch melempar → item tercatat, 1 transaksi, 0 suara, respons 201
async def test_bot_record_path_learns_through_mark_recorded(self): ...
async def test_no_learning_from_store_receipts(self): ...
async def test_votes_and_rules_hold_no_pii(self): ...            # Review Focus 3: tabel suara/aturan setelah koreksi pada slip sweep: tanpa \d{6,}, tanpa kata nama
async def test_delete_account_forgets_votes_and_recounts(self): ...   # users 2 → 1 (status tidak berubah)
async def test_merge_users_forgets_source_votes(self): ...
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_belajar app.tests.test_kotak_transactions app.tests.test_kotak_bot app.tests.test_account_deletion app.tests.test_kotak_schema -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend.
- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/belajar.py app/services/kotak_struk/record.py app/models/models.py alembic/versions/e7b3d5a9c1f4_kotak_belajar.py app/services/account_deletion.py app/services/merge.py app/tests/test_kotak_belajar.py app/tests/test_kotak_transactions.py app/tests/test_kotak_bot.py app/tests/test_account_deletion.py app/tests/test_kotak_schema.py
git commit -m "feat(kotak): suara koreksi lintas user dan aturan menunggu persetujuan"
```

---

### Task L2b: Bot "Nominal salah" menyumbang suara nominal

K4: `struk_fix_` melewati item dan user mengetik nominal sebagai pengeluaran baru yang tidak tertaut. Task ini hanya mencatat nominal ketikan itu sebagai koreksi; pencatatannya tetap persis seperti sekarang. Bisa dilepas tanpa memengaruhi task lain.

**Files:**
- Modify: `app/bot/receipt_cmd.py` (`handle_struk_callback` 937-971; konstanta kunci di dekat `NOTE_KEY`), `app/bot/handlers.py` (`handle_message` 1159-1162)
- Test: perluas `app/tests/test_kotak_bot.py`, `app/tests/test_web_chat.py`

**Interfaces:**
- `FIX_KEY = "kotak:fix:{}"` (tg user id), nilai `str(item_id)`, TTL `FIX_TTL_S`. Ditulis hanya oleh `struk_fix_` untuk item Kotak Struk selain struk belanja yang berhasil dilewati.
- `async def note_fix_amount(update, text) -> None` — `getdel` kunci; ada → `parse_amount(text)` (`handlers.py:92`); satu nominal → `belajar.learn_from_correction(db, item, Final(amount, None, None, today), user_id=…)` lalu commit; tidak pernah melempar dan **tidak pernah menahan teks dari NLP** (dipanggil sesudah `capture_note`, sebelum deteksi teks bukti; selalu lanjut). Item milik user lain / tidak ada / layout kosong → tanpa suara.

- [ ] **Step 1: Write the failing test** — `test_fix_then_typed_amount_votes_and_still_records_once` (ketik "bakso 12500" sesudah "Nominal salah" → satu transaksi NLP seperti biasa + satu suara `label_total`), `test_fix_key_expires_or_other_text_without_amount_no_vote`, `test_fix_never_blocks_nlp_when_redis_down`, `test_web_chat_same_path`.
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend.
- [ ] **Step 5: Commit**

```bash
git add app/bot/receipt_cmd.py app/bot/handlers.py app/tests/test_kotak_bot.py app/tests/test_web_chat.py
git commit -m "feat(kotak): nominal ketikan sesudah Nominal salah menjadi suara koreksi"
```

---

### Task L3: Pembaca memakai aturan yang disetujui

Spec §5; pre-flight §5, K6. Tanpa aturan = perilaku hari ini byte demi byte.

**Files:**
- Modify: `app/services/kotak_struk/readers/base.py` (`ParseContext` 45-57: `rules: dict = field(default_factory=dict)`)
- Modify: `app/services/kotak_struk/belajar.py` (`approved_rules`, cache, `invalidate_rules_cache`, `learned_for`)
- Modify: `readers/profiles.py` (`with_learned`), `readers/proof_common.py` (`read_amounts` 571-594, `read_paid_at` 641-661), `readers/qris.py` (parse 42-88), `readers/transfer.py` (parse 73-147), `readers/unknown.py` (`_parse` 40-73)
- Modify: `app/services/kotak_struk/worker.py` (`process_item` 327-351: muat aturan di sesi yang sama dengan `_load_learning`)
- Test: `app/tests/test_kotak_aturan_pembaca.py`

**Interfaces:**
- `belajar.approved_rules(db) -> dict[str, dict[str, list[str]]]` — `{rule_key: {"label_total": [...], "label_pihak": [...], "label_tanggal": [...]}}` dari `status == 'disetujui'`, urut `users` turun lalu `decided_at`; cache modul `RULE_CACHE_S` (monotonic); `invalidate_rules_cache()`.
- `belajar.learned_for(rules, key) -> Learned(total: list[str], party: list[str], date: list[str])`.
- `profiles.with_learned(profile, learned) -> AppProfile | None` — `profile` apa adanya bila `learned` kosong; selain itu salinan (`dataclasses.replace`; profil `None` → `AppProfile(key="", label="", markers=[])`) dengan `labels["merchant"]`/`["sender"]` = `learned.party` + label profil, dan `labels["paid_at"] = learned.date`. `doc.issuer` tetap dari profil asli.
- `proof_common.read_amounts(lines, profile, *, learned_total: list[str] = ())` — bila `learned_total` menemukan nominal (`_first_amount`), itu `total` dengan keyakinan `tinggi`; subtotal/biaya/pajak/diskon dibaca seperti biasa (cek `selisih_nominal` tetap jalan); selain itu logika sekarang.
- `proof_common.read_paid_at(lines, profile)` — langkah pertama baru: `labels_for(profile, "paid_at")` (kosong di GENERIC) → `find_value` → `parse_datetime_id`; tidak ketemu → logika sekarang.
- Pembaca QRIS/transfer: `key = kerangka.rule_key(lines, profile, forbidden_words=set())` → `learned_for(ctx.rules, key)` → `lp = with_learned(profile, learned)` untuk semua pembacaan label; nama dari aturan keyakinan `tinggi` (sudah).
- `UnknownReader._parse`: kunci dari `detect_issuer`/`rule_key`; bila `learned.total` menemukan nominal → total itu, keyakinan `tinggi`, sebelum `_app_receipt_total`. Pembaca struk belanja tidak berubah.
- Status (`read_proof_status`, `apply_header_status`, `_apply_labelled_failure`), `checks.apply_flow`, `checks.common_checks`, dan `dedup` tidak menerima aturan.

- [ ] **Step 1: Write the failing test**

```python
async def test_empty_rules_change_nothing(self):          # Review Focus 6: setiap daftar sweep_lines, kedua saklar, ctx rules={} == snapshot
async def test_corpus_eval_uses_no_rules(self): ...       # kotak_corpus membangun ParseContext tanpa rules (rules == {})
async def test_learned_total_label_reads_total_tinggi(self):
    lines = ["NEWPAY", "Transfer Berhasil", "Ke BUDI", "Jumlah Kirim Uang", "Rp12.500", "31 Okt 2026 10:00"]
    rules = {"logo:newpay": {"label_total": ["jumlah kirim uang"], "label_pihak": [], "label_tanggal": []}}
    d = (await read(lines, ParseContext(today=TODAY, rules=rules))).parsed.doc
    self.assertEqual((d.amounts.total, d.confidence["total"]), (12500, "tinggi"))
async def test_rule_label_first_profile_label_fallback(self): ...
async def test_learned_date_and_party_labels(self): ...
async def test_rules_never_bypass_status_blocks(self):    # Review Focus 2
    # setiap daftar failed/pending di sweep_lines + bentuk §9.1, aturan semua jenis untuk kuncinya, termasuk
    # label_total "status" dan label = teks baris gagal → status, {code: level} cek, dan check_recordable sama
async def test_rule_cache_expires_and_invalidates(self): ...
async def test_store_reader_ignores_rules(self): ...
```

- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_aturan_pembaca -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend + `kotak_sapuan cek` **tanpa beda** + `eval` salinan reviewed tanpa beda.
- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/readers/base.py app/services/kotak_struk/readers/profiles.py app/services/kotak_struk/readers/proof_common.py app/services/kotak_struk/readers/qris.py app/services/kotak_struk/readers/transfer.py app/services/kotak_struk/readers/unknown.py app/services/kotak_struk/belajar.py app/services/kotak_struk/worker.py app/tests/test_kotak_aturan_pembaca.py
git commit -m "feat(kotak): pembaca mendahulukan label dari aturan yang disetujui"
```

---

### Task L4a: API Admin aturan belajar

Spec §6; pre-flight §6, K10, G5, G6, G10.

**Files:**
- Create: `app/api/routes/admin_kotak.py`
- Modify: `app/main.py` (include router `prefix="/admin/kotak"`, `tags=["admin"]`, di samping `admin.router` ±152), `app/services/receipt_scan.py` (`accuracy_stats` 310: kunci tambahan `rules_pending`)
- Test: `app/tests/test_kotak_admin_aturan.py`

**Interfaces (semua `Depends(require_admin)`; non-admin 403 seperti rute admin lain):**
- `GET /admin/kotak/rules?status=menunggu|disetujui|ditolak|dicabut|semua` (bawaan `menunggu`) → `ProofRulesResponse {counts: {menunggu, disetujui, ditolak, dicabut}, rules: [ProofRuleOut]}`; `ProofRuleOut {id, kind, rule_key, value, users, households, status, created_at, decided_at, decided_by, decided_by_name, note}`; urut `users` turun, lalu `created_at`.
- `POST /admin/kotak/rules/{id}/setujui|tolak|cabut`, body `RuleDecisionIn {note: str | None (≤ 200)}` → `ProofRuleOut`; transisi G5, selain itu 409 "Aturan ini tidak bisa diubah ke status itu"; id tidak ada 404 "Aturan tidak ditemukan". Isi `decided_at`, `decided_by`, `note`; `invalidate_rules_cache()`.
- `GET /admin/kotak/votes` → `ProofVotesResponse {rows: [{rule_key, kind, users: int, values: int}]}` — per (kunci, jenis): jumlah user berbeda dan jumlah nilai label berbeda, untuk tab "Suara"; tanpa teks label (G6).
- `/admin/receipt-scans/stats` + `rules_pending: int`.

- [ ] **Step 1: Write the failing test** — daftar per status dan `counts`; transisi sah/409/404; cache dibatalkan (aturan disetujui terbaca `approved_rules` berikutnya tanpa menunggu 5 menit); non-admin 403; `votes` tanpa label; `rules_pending` di stats.
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend (`openapi_cek`: hanya penambahan path).
- [ ] **Step 5: Commit**

```bash
git add app/api/routes/admin_kotak.py app/main.py app/services/receipt_scan.py app/tests/test_kotak_admin_aturan.py
git commit -m "feat(admin): API aturan belajar Kotak Struk (daftar, setujui, tolak, cabut, suara)"
```

---

### Task L4b: UI Admin "Aturan belajar"

**Files:**
- Create: `frontend/src/lib/proofRules.js`, `frontend/src/lib/proofRules.test.js`
- Modify: `frontend/src/lib/api.js` (blok Kotak ±581-660: `adminProofRules(status)`, `adminProofRuleAction(id, action, note)`, `adminProofVotes()`; `null` bila gagal, pola `kotakPendingCount`), `frontend/src/pages/Admin.jsx` (`ReceiptScanCard` 1411-1482: bagian baru di bawah "Per penerbit")

**Interfaces (`proofRules.js`, murni):**
- `KIND_LABEL = {label_total: 'Label nominal', label_pihak: 'Label penerima', label_tanggal: 'Label tanggal'}`.
- `ruleAppLabel(ruleKey)` — `ISSUER_LABEL[key]` (dari `proofFormat.js`), `logo:x` → `Aplikasi baru: x`, selain itu kunci asli.
- `syntheticExample(rule)` — `label_total`: `"{Label} Rp##.###"`; `label_pihak`: `"{Label} NAMA PENERIMA"`; `label_tanggal`: `"{Label} ## Okt 2026"` (label huruf awal kapital); tidak pernah data user.
- `ruleActions(status)` — `menunggu` → `['setujui','tolak']`; `disetujui` → `['cabut']`; `ditolak`/`dicabut` → `['setujui']`.
- `ruleSummary(resp)` — `"{m} menunggu · {d} disetujui · {t} ditolak"` atau null; `ruleRows(resp)`; `voteRows(resp)`; `actionOutcome(res)` → `{kind: 'ok'|'conflict'|'error', text}`.
- UI: judul "Aturan belajar" dengan lencana `n menunggu` (dari `rules_pending` stats), tab "Menunggu" / "Semua" / "Suara"; baris: jenis, aplikasi, contoh sintetis, `users` user · `households` rumah tangga, tombol Setujui/Tolak/Cabut (catatan opsional, maks 200); 409 → teks server dan daftar dimuat ulang.

- [ ] **Step 1: Write the failing test** (`node --test src/lib/proofRules.test.js`): contoh sintetis tidak pernah memuat angka asli; aksi per status; label aplikasi; ringkasan; data rusak/null → null tanpa melempar.
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement** (JSX hanya merender hasil `proofRules.js`).
- [ ] **Step 4: Run to pass** — cek frontend lengkap; `git checkout -- frontend/dist`.
- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/proofRules.js frontend/src/lib/proofRules.test.js frontend/src/lib/api.js frontend/src/pages/Admin.jsx
git commit -m "feat(admin): bagian Aturan belajar di kartu Scan Struk"
```

---

### Task L5: Kosakata status "dibatalkan/ditolak" → gagal

Spec §7; pre-flight §7. Keputusan pemilik butir 3.

**Files:**
- Modify: `app/services/kotak_struk/readers/proof_common.py` (`_GAGAL` 666, `_STATUS_WORD` 708-709, `_STATUS_TITLE` 782-784, `payment_status_value`/`read_payment_status` 914-947, `read_status` 950-966, `read_labelled_failure` 980-997)
- Modify: `app/tests/fixtures/kotak/sweep_lines.json` (+ bentuk baru), `sweep_snapshot.json` (tulis ulang sesudah `cek`)
- Test: perluas `app/tests/test_kotak_kalibrasi.py` (kelas baru `CancelledVocabularyTests`)

**Interfaces / aturan:**
- `_CANCELLED = dibatalkan|ditolak|batal|rejected|cancelled|canceled|void` → `gagal`, hanya di: (a) judul status (`_STATUS_TITLE`: kata benda transaksi + kata itu: "Transfer Dibatalkan", "Pembayaran Ditolak", "Transaksi Batal", "Payment rejected"); (b) nilai label status pembayaran ("Status: Dibatalkan", "Status Transaksi Ditolak"); (c) baris berstatus saja di 4 baris pertama ("Dibatalkan", "Ditolak", "Rejected", "Cancelled") — **"Batal" dan "Void" tanpa kata benda tidak pernah** (tombol "Batal", baris "VOID" di struk). Baris badan pendek (`BODY_WORDS`) tidak membaca kata ini. Kaki bersyarat/tanya/bantuan tetap dilewati (`_CONDITIONAL`, `_HELP_PHRASE`). Negasi tidak berubah.
- `_NOT_DONE` tetap (kata-kata ini di posisi lain hanya mencegah `berhasil`).

- [ ] **Step 1: Write the failing test** — kedua saklar: `["GoPay","Transfer Dibatalkan","Ke BUDI","Nominal Rp50.000","26/10/2026 08:12"]` → `gagal` + `status_gagal: block`; `["GoPay","Ke BUDI","Nominal Rp50.000","Status: Ditolak",…]` → block; "Payment cancelled", "Transaksi Batal"; tidak memblokir: tombol "Batal" di bawah ("Menunggu pembayaran" … "Batal"), struk dengan baris "VOID 1 KOPI 15.000", kaki "Jika transaksi dibatalkan, dana kembali dalam 3 hari", "Barang yang sudah dibeli tidak dapat dibatalkan"; "Selesai" + "Dibatalkan" di mana pun tetap bukan berhasil.
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend + `kotak_sapuan cek`: beda hanya pada bentuk dibatalkan/ditolak yang disengaja; `test_store_receipts_unchanged_by_sweep` hijau; laporan mencantumkan output `cek`; lalu `tulis`.
- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/readers/proof_common.py app/tests/test_kotak_kalibrasi.py app/tests/fixtures/kotak/sweep_lines.json app/tests/fixtures/kotak/sweep_snapshot.json
git commit -m "feat(kotak): bukti dibatalkan atau ditolak diblokir seperti gagal"
```

---

### Task L6a–L6e: Menutup titik wajib review akhir Bagian A

Spec §9.1. Satu task per titik, masing-masing: input konkret dari pre-flight (tabel §9.1) sebagai tes yang gagal dulu, perbaikan kecil, sapuan (`kotak_sapuan cek` + `test_store_receipts_unchanged_by_sweep` + `test_failed_proofs_stay_blocked` + `eval` salinan reviewed), laporan beda, `tulis`. Semua tes baru di `app/tests/test_kotak_kalibrasi.py` (kelas per titik); `sweep_lines.json` mendapat inputnya.

#### L6a — N2 sisa: kata status di nama toko menutupi "Gagal" tunggal (saklar menyala)
- Input (pre-flight): `["QRIS","TOKO SUKSES MAKMUR","Rp25.000","26/10/2026 08:12","NMID ID1234567890","Gagal"]` → hari ini `qris.umum`/`berhasil`, bisa dicatat. Bentuk review asli ("Pembayaran Gagal") sudah tertutup (`test_kotak_kalibrasi.py:354-361`): pertahankan.
- Jalur: `read_status` (950-966) baris 961 — `_strongest(_status_lines(lines[:HEADER_LINES], HEADER_WORDS))` mengambil "TOKO SUKSES MAKMUR".
- Perbaikan: di judul, `berhasil` hanya dari judul status (`_is_status_title`), baris berstatus saja (setelah kata status dibuang ≤ 1 kata lain, mis. "Berhasil", "Pembayaran Sukses!"), atau nilai label status; baris berbentuk nama dengan kata status ("TOKO SUKSES MAKMUR") tidak menyumbang apa pun, sehingga badan (`_first(_status_lines(lines, BODY_WORDS))`) membaca "Gagal".
- Tes: input di atas → `gagal` + block (saklar menyala); QRIS "TOKO SUKSES MAKMUR" tanpa status lain → `tidak_diketahui` (bukan berhasil), tanpa blokir; judul "Pembayaran Berhasil" + kaki "Gagal? Hubungi kami" tetap berhasil; semua `store` tidak berubah.
- Files: `readers/proof_common.py`, tes, fixture sapuan. Commit: `fix(kotak): kata status di nama toko tidak lagi menutupi status gagal di badan`.

#### L6b — N4: blokir palsu oleh kaki bantuan/refund berbentuk judul
- Input: (a) `["BCA mobile","26/10/2026 14:22","Ke BUDI","Nominal Rp150.000","Total Rp150.000","Info transaksi pending/gagal: 14017"]`; (b) `[…, "Status Berhasil", "Transaksi gagal akan dikembalikan"]`; (c) `["DANA","Kirim Uang Berhasil","Ke SITI","Nominal Rp50.000","Total Rp50.000","Pembayaran gagal akan di-refund otomatis"]` → hari ini block di kedua saklar (palsu).
- Jalur: `apply_header_status` (`struk_belanja.py:62-76`) → `read_body_failure_title` (868-887) → `_status_lines` → `_HELP_PHRASE` (720-723).
- Perbaikan: `_HELP_PHRASE` + kata awal `info|informasi`; kalimat judul gagal yang diikuti `akan (dikembalikan|di-?refund|diproses)` = kalimat informasi, bukan status; di `read_body_failure_title`, nilai label status pembayaran `berhasil` (`read_payment_status`) dan baris berstatus saja di judul menentukan lebih dulu, seperti `read_status` di jalur bukti.
- Tes: (a)–(c) tidak diblokir di kedua saklar; tetap diblokir: "Transaksi Gagal" sungguhan di badan, "Transaksi gagal, dana dikembalikan ke saldo kamu" (sudah terjadi, bukan "akan"), dan semua `failed` di sapuan. Bentuk berlabel "Info: Transaksi Gagal" (label Info lalu judul gagal) diputuskan implementer, dipin dengan tes, dan dilaporkan (rekomendasi: tetap gagal, karena tidak ada kata jenis transaksi sesudah "Info" yang menjadikannya frasa bantuan).
- Commit: `fix(kotak): kaki info dan refund tidak lagi memblokir bukti berhasil`.

#### L6c — C2: judul tanpa kata benda transaksi ("Kirim Uang Berhasil")
- Input: `["DANA","Kirim Uang Berhasil","Ke SITI 0812 3456 7890","Nominal Rp50.000","Total Rp50.000","26/10/2026 08:12"]` → hari ini `struk_belanja`, tidak tampak bukti, `ocr_lines` 24 jam memuat nomor HP, merchant "Dana" — di kedua saklar.
- Jalur: `_STATUS_TITLE` (782-784); `registry.looks_like_proof` (57-78).
- Perbaikan: kata benda `kirim\s+uang|kirim\s+dana|transfer\s+dana` di `_STATUS_TITLE` (tidak "bayar": terlalu umum di struk; tidak mengubah penanda pembaca transfer, A14 r3 m3).
- Tes: input → tampak bukti, tanpa `ocr_lines`, `lines == []`, tanpa merchant/baris peta, total tetap; faktur "Silakan kirim uang ke rekening BCA …" tetap bukan bukti; semua `store` tidak berubah.
- Commit: `fix(kotak): judul Kirim Uang Berhasil dikenali sebagai bukti bayar`.

#### L6d — C3: struk 1–2 barang dibayar QRIS
- Input: `["TOKO SUKSES MAKMUR","KOPI 15.000","TOTAL 15.000","QRIS 15.000"]`, `["TOKO MAJU","KOPI 15.000","ROTI 10.000","TOTAL 25.000","QRIS 25.000","NMID ID1020304050607"]` → hari ini saklar mati: struk tanpa rincian/merchant; **saklar menyala: `qris.umum`**.
- Jalur: `QrisReader.detect` (`qris.py:27-40`, penjaga struk pada baris mentah 32-34); `looks_like_store_receipt` (1108-1129).
- Perbaikan: penjaga struk di detektor bukti (QRIS dan transfer) memakai baris yang dinormalkan seperti `registry.looks_like_proof` (77); pola struk juga terpenuhi oleh ≥ 1 baris barang tanpa kuantitas sebelum baris TOTAL **dan** baris cara bayar sesudahnya bernominal sama dengan total, asal tidak ada label bukti (Merchant/Penerima/NMID berlabel/Nominal) di atas TOTAL.
- Tes: kedua input → `struk_belanja`, rincian dan merchant tersimpan, kedua saklar; QRIS asli di korpus (sintetis + 15 nyata di salinan reviewed) tetap `qris`; GoPay QRIS Indomaret tetap `qris`.
- Commit: `fix(kotak): struk kecil berbayar QRIS tetap struk belanja`.

#### L6e — Sisa N1 (+ M7): slip satu penanda tanpa judul status
- Input: `["BCA mobile","26/10/2026 14:22","Ke BUDI 1234 5678 9012","Nominal Rp150.000","Total Rp150.000"]` + (tanpa status | `"BERHASIL"` | `"Status : Berhasil"` | `"Pengaduan transaksi gagal: 14017 Gagal"`) → hari ini di kedua saklar `struk_belanja`, `document.lines` 2 baris dari digit rekening, merchant "Bca Mobile" + baris peta, `ocr_lines`. M7: `evidence` struk mengutip `Non-tunai "DEBIT BCA 1234567890 Rp150.000"`.
- Jalur: `registry.looks_like_proof` (57-78), `is_app_receipt` (`proof_common.py:340-…`), `worker._plain_evidence` (182-185).
- Perbaikan: `looks_like_proof` juga benar bila baris logo aplikasi (`logo_profile`) ada di 2 baris pertama dan teks tidak berpola struk (baris dinormalkan) — tanpa syarat label sumber; kutipan `evidence` struk belanja disamarkan (`mask_digits` untuk deret ≥ 6 digit) di `_outcome` untuk semua jenis.
- Tes: keempat bentuk di kedua saklar → tanpa rincian, merchant, baris peta, `ocr_lines`; total/status/cek tetap; rekonstruksi per field (pola `test_kotak_worker.py` ONE_MARKER_SLIPS) tidak menemukan `123456789012`; struk dengan "BCA" di nama toko (`TOKO MANDIRI JAYA`, `KANTIN BNI`) tetap struk; `evidence` struk tanpa deret ≥ 6 digit.
- Commit: `fix(kotak): slip aplikasi satu penanda tanpa judul tidak menyimpan nomor`.

Untuk setiap L6x:
- [ ] **Step 1: Write the failing test** (input di atas, kedua saklar).
- [ ] **Step 2: Run to fail** — `python3 -m unittest app.tests.test_kotak_kalibrasi app.tests.test_kotak_sapuan -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass** + cek backend + `kotak_sapuan cek` (laporkan setiap beda; hanya input titik ini yang boleh berubah) + `eval` salinan reviewed; lalu `tulis`.
- [ ] **Step 5: Commit** (stage per path: `app/services/kotak_struk/readers/proof_common.py`, file pembaca/registry/worker yang disentuh, `app/tests/test_kotak_kalibrasi.py`, `app/tests/fixtures/kotak/sweep_lines.json`, `app/tests/fixtures/kotak/sweep_snapshot.json`).

---

### Task L7: Dokumentasi, privasi, checklist deploy

Spec §8, §9, §10 L7.

**Files:**
- Modify: `docs/kotak-struk.md` — Status (A14 tayang 31 Okt, PR #135; tahap 1 ini; saklar menyala untuk semua sesudah urutan); bagian baru **"Belajar lintas user"** (kerangka: kolom `layout`, isi, umur 24 jam sejak dibaca dan hanya item selesai; suara di `mark_recorded`/`skip_item`; jenis aturan tahap 1; ambang 2 user; persetujuan Admin; cache 5 menit; pembaca: urutan label aturan → profil → umum, keyakinan `tinggi`, tidak pernah status/arah/duplikat; Bot "Nominal salah"; hapus akun/gabung akun); "Cek silang" (+ kosakata §7 dan posisi yang dihitung); "Saklar fitur" + "Menyalakan saklar" (gerbang §7c diganti: urutan baru = merge + migrasi → `privacy.html` + DPIA oleh pemilik → `kotak_hari_pertama` dry-run lalu `--apply` → saklar ON → uji HP tanpa share → PR `share_target` → uji share; `eval --real-only` tetap dijalankan dan dilaporkan, bukan gerbang; pemantauan 2 minggu: `% dikoreksi`, aturan menunggu, laporan user; saklar bisa dimatikan); "Alat korpus dan gerbang rilis" (gerbang tidak lagi syarat); "Pemeliharaan" (langkah 3 `purge_layouts`); "Privasi dan masa simpan" (kerangka, tabel aturan, teks paragraf `privacy.html` dari spec §8 untuk dipasang pemilik di server, baris DPIA: data label + hitungan, dasar kepentingan sah, retensi selama aturan dipakai); "Batasan yang diketahui" (perbarui N2/N4/C2/C3/N1 yang tertutup; sisa; nama/tanggal hanya dari form Catat; arah di tahap 2; label di luar `LABEL_WORDS` tidak dipelajari; item yang dibaca jalur struk tidak belajar); "API" (endpoint Admin); "Tes".
- Modify: `docs/scan-struk.md` "Belajar dari koreksi" — satu kalimat + tautan ke bagian baru.
- Modify: `AGENTS.md` — "Deploy Checklist — Kotak Struk belajar lintas user (e7b3d5a9c1f4)": tanpa paket/folder/`.env` baru; hak tabel `receipt_scans` (pemilik `jatahku`, query di checklist Kotak Struk); merge → `ls … | grep e7b3d5a9c1f4`; `alembic current` harus `2d51b9031a6b` sebelum upgrade; `alembic upgrade head` → `e7b3d5a9c1f4`; restart; ulang job deploy; verifikasi (`\d proof_rules`, `\d proof_rule_votes`, `\d receipt_scans | grep layout`, `GET /admin/kotak/rules` → `counts`); lalu urutan saklar di `docs/kotak-struk.md` (jangan disalin). Perbarui langkah 7 checklist Bagian A ("saklar tetap mati sampai gerbang korpus") dan butir 4 checklist Bagian B → rujuk urutan baru.
- Modify: `docs/mobile/PROGRESS.md` (A28 → selesai dengan gerbang yang diganti keputusan pemilik 1 Nov 2026; A68 tetap `berjalan` sampai pemilik memasang `privacy.html`), `docs/mobile/03-workflow.md` (baris A28 dan catatan FS-1).

- [ ] **Step 1:** Tulis; setiap klaim dicek terhadap kode di branch ini (nama fungsi, konstanta, endpoint, pesan).
- [ ] **Step 2:** `grep -n "e7b3d5a9c1f4\|proof_rules\|kotak_hari_pertama" AGENTS.md docs/kotak-struk.md` dan cek backend (tidak berubah).
- [ ] **Step 3: Commit**

```bash
git add docs/kotak-struk.md docs/scan-struk.md AGENTS.md docs/mobile/PROGRESS.md docs/mobile/03-workflow.md
git commit -m "docs(kotak): belajar lintas user, gerbang baru, privasi, checklist deploy e7b3d5a9c1f4"
```

---

### Task L8: Invarian ujung ke ujung dan verifikasi rilis

**Files:**
- Test: `app/tests/test_kotak_belajar.py` (kelas `EndToEndInvariantTests`)

- [ ] **Step 1: Tes ujung ke ujung** (SQLite, worker palsu seperti `test_kotak_worker.py`): dua user di rumah tangga berbeda membagikan bukti aplikasi tak dikenal yang sama (teks), worker menyimpan kerangka, masing-masing mengoreksi nominal lewat `POST /transactions` dengan `receipt_item_id` → aturan `menunggu` users=2 households=2; admin menyetujui (`POST /admin/kotak/rules/{id}/setujui`); user ketiga membagikan bukti yang sama → total dari aturan, `tinggi`, dan bot tidak bertanya nominal (`needs_amount_check` False); versi gagal bukti itu tetap diblokir; `layout`/suara/aturan tanpa PII; tiap user satu transaksi; `purge_layouts` 24 jam kemudian mengosongkan kerangka; hapus akun user pertama → users=1, aturan tetap `disetujui`.
- [ ] **Step 2: Run** — tes ini, lalu semua cek backend (laporkan angka akhir vs baseline 2393/1/1), `openapi_cek --dasar 2125226`, `kotak_corpus eval` dan `eval --real-only` (dilaporkan, bukan gerbang), `kotak_sapuan cek` (tanpa beda), cek frontend.
- [ ] **Step 3: Commit**

```bash
git add app/tests/test_kotak_belajar.py
git commit -m "test(kotak): invarian ujung ke ujung belajar lintas user"
```

- [ ] **Sesudah L8 (pengendali):** review akhir seluruh branch; PR `feat/kotak-belajar` label `migrasi` (deskripsi: ringkasan, checklist AGENTS, urutan saklar); merge hanya dengan izin pemilik; migrasi sesudah deploy ("Urutan merge PR bermigrasi"); langkah spec §9.5 bersama pemilik.

---

# Tahap 2 — `feat/kotak-belajar-2` (PR kedua, label `migrasi`, sesudah saklar menyala)

Keputusan pemilik §12.4: dikerjakan langsung sesudah tahap 1 tayang. Pre-flight sebelum tahap 2 wajib diulang (main bergerak); di bawah ini rencana kasar per task, rinciannya ditulis ulang di pre-flight tahap 2.

### Task M1: Donasi contoh (opt-in) untuk korpus

**Catatan desain (celah spec):** teks OCR tidak pernah disimpan, jadi baris tersamar harus diambil **di worker** untuk user yang sudah setuju, bukan saat koreksi.
**Files:** migrasi baru (tabel `proof_sample_consents(user_id PK FK CASCADE, consented_at)` dan `proof_samples(id, rule_key, lines JSON, doc_type, status menunggu|disetujui|ditolak, created_at, decided_at, decided_by)`; kolom `receipt_scans.sample_lines` JSON lewat `KOTAK_DDL`, dihapus seperti `layout`), `worker.py` (`mask_line` dari `kotak_corpus` untuk user yang setuju), `belajar.learn_from_correction` (koreksi yang menghasilkan suara memindahkan `sample_lines` ke `proof_samples`), API user `GET/PUT /user/kotak-donasi` (additive), API Admin `GET /admin/kotak/samples`, `POST …/{id}/setujui|tolak` dengan baris yang sudah diganti nama oleh pemilik, `kotak_corpus add --dari-donasi <id>` (`reviewed: true` hanya oleh pemilik), Settings (toggle + teks persetujuan), paragraf privasi tambahan, hapus akun.
**Invarian:** tanpa persetujuan tidak ada baris yang disimpan; `PERIKSA` (`needs_review`) ditampilkan di Admin; tidak ada nomor ≥ 6 digit di `proof_samples` (tes); donasi tidak memengaruhi pencatatan.

### Task M2: Aturan `logo` untuk aplikasi tanpa profil

**Files:** `ProofCard`/`proofFormat.js` (pilihan "Aplikasi apa ini?" pada bukti `tidak_dikenali`: 12 profil + "Lainnya"), `SkipIn`/`savePayload` atau endpoint baru `POST /kotak-struk/{id}/aplikasi` (additive), `belajar.votes_for` (`logo`: kunci `logo:<kata>`, nilai = kunci profil atau nama baru tersanitasi), `profiles.detect_issuer` (penanda tambahan dari `ctx.rules`), Admin (jenis baru di `proofRules.js`).
**Invarian:** penanda dari aturan tidak pernah mengubah status/blokir; nama aplikasi baru melewati `safe_label`-gaya kosakata atau persetujuan teks oleh pemilik.

### Task M3: Arah uang (`arah`) dan top-up e-wallet sendiri

**Files:** `routes/kotak_struk.py` `SkipIn` + `alasan: Literal["top_up","masuk","antar_rekening_sendiri"] | None = None` (additive), `record.skip_item` meneruskan alasan ke `learn_from_correction` (suara `arah`: kunci `{rule_key}|{kata judul}`, nilai flow), `ProofCard`/`proofFormat.skipActions` (pilihan alasan setelah "Bukan pengeluaran"), bot `kx_` langkah kedua (tombol tiga alasan, didaftarkan di `bot_callbacks()`), `registry.read_document` (aturan `arah` disetujui → `flow` sebelum `checks.apply_flow`; hanya `skip_suggestion`, tidak pernah mencatat/melewati otomatis), bentuk "Kirim Ke GOPAY TOPU-…" ShopeePay → `top_up` dari aturan.
**Invarian:** aturan `arah` hanya menambah peringatan "bukan pengeluaran?"; "Tetap catat" selalu tersedia kecuali `blocked`; tes `test_arah_rule_never_records_or_skips`.

Untuk M1–M3: langkah tes-dulu → gagal → implementasi → lulus → commit, cek backend/frontend yang sama dengan tahap 1 (`openapi_cek --dasar <commit main saat tahap 2 mulai>`), checklist deploy baru di `AGENTS.md`, dan `docs/kotak-struk.md` diperbarui di task dokumen penutup tahap 2.
