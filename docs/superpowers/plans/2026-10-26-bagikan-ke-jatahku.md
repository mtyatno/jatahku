# Bagikan ke Jatahku (bukti bayar QRIS & transfer) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** User membagikan bukti bayar QRIS/transfer (gambar, PDF, atau teks) ke bot Telegram atau ke PWA Jatahku (menu Bagikan di Android). Jatahku membaca bukti itu, menyarankan amplop dari peta merchant rumah tangga, dan mencatat setelah user mengonfirmasi (satu ketukan). Kuota scan dihapus untuk semua input.

**Architecture:** Semua kanal membuat item di Kotak Struk (tabel `receipt_scans` yang diperluas). Worker asyncio di dalam proses API mengklaim item, mengekstrak teks (RapidOCR / `pypdfium2` / teks), memilih pembaca dari registri (struk belanja, QRIS, transfer, tidak dikenali), lalu menyimpan "Dokumen Bayar" berversi. Kabar selesai lewat Redis pub/sub dengan cadangan cek DB. Pencatatan memakai jalur yang sudah ada (callback `t_…` di bot, `POST /transactions` di web) dengan field baru `receipt_item_id`; setelah tercatat, peta merchant per rumah tangga belajar.

**Tech Stack:** FastAPI, SQLAlchemy async (Postgres; SQLite + aiosqlite di tes integrasi), Redis, python-telegram-bot, RapidOCR, `pypdfium2==5.13.0` (baru), React 18 + Vite + service worker `injectManifest`, `node --test`.

**Spec:** Project doc `claude/bagikan-ke-jatahku-desain.md` (salinan lokal: `docs/superpowers/specs/2026-10-26-bagikan-ke-jatahku-design.md`; folder `docs/superpowers/` di-gitignore repo).

## Global Constraints

- Git: jangan `git add -A`; stage file satu per satu; jangan commit `frontend/dist/` (setelah build: `git checkout -- frontend/dist`).
- Dua branch, dua PR: **Bagian A** `feat/bagikan-ke-jatahku-server` (label `migrasi`), **Bagian B** `feat/bagikan-ke-jatahku-web`. Bagian B dimulai setelah PR Bagian A di-merge **dan** rencana kamera (`claude/foto-struk-kamera-rencana.md`) sudah di-merge.
- API hanya bertambah (AGENTS.md, Aplikasi mobile #2). Field/endpoint lama tidak dihapus atau diubah artinya. `GET /transactions/scan-receipt/quota` tetap `{limit, used, remaining}`; respons `scan-receipt` lama tetap ada, hanya ditambah field. Cek lokal: `python -m app.scripts.openapi_cek`.
- Struk tidak pernah tercatat diam-diam atau dua kali (Aplikasi mobile #11): selalu konfirmasi user; `upload_id`, hash file, `ref_hash`, `client_ref` mencegah ganda; transfer gagal tidak bisa dicatat.
- Kontrak visibilitas rumah tangga: saran hanya ke amplop `purpose == "expense"`, aktif, dan `owner_id IS NULL OR owner_id == user.id`.
- Perbedaan platform hanya di `frontend/src/native/` (Aplikasi mobile #1).
- Nomor rekening tidak pernah disimpan utuh; RRN/nomor referensi hanya sebagai HMAC + versi tersamar. HMAC memakai `settings.KOTAK_HMAC_KEY`.
- Saklar fitur: `features.receipt_inbox` di `/app/config` (sudah ada, default `False`, AppSetting `app_config`). Server: pembaca `qris`/`transfer` aktif hanya bila `feature_enabled(db, "receipt_inbox", "web")`. Klien: banner, halaman `/bagikan`, dan tombol PDF tampil hanya bila `useAppConfig().features.receipt_inbox`. Penghapusan kuota scan **tidak** bergantung pada saklar ini.
- Konstanta (`app/services/kotak_struk/config.py`, nilai persis dari spec):
  `WAIT_BOT_S = 10`, `WAIT_FORM_S = 45`, `STALE_PROCESSING = timedelta(minutes=5)`, `MAX_ATTEMPTS = 3`, `ITEM_EXPIRY = timedelta(days=7)`, `RATE_PER_HOUR = 30`, `MAX_FILES_PER_SHARE = 10`, `MAX_PENDING = 20`, `IMAGE_MAX_BYTES = 8 * 1024 * 1024`, `PDF_MAX_BYTES = 10 * 1024 * 1024`, `PDF_MAX_PAGES = 5`, `PDF_TIMEOUT_S = 15`, `NOTE_TTL_S = 300`, `SOFT_DUP_WINDOW = timedelta(hours=3)`, `CONFIDENT_SHARE = Fraction(2, 3)`, `OLD_PROOF_DAYS = 60`, `TEXT_MAX_CHARS = 4000`, `ORPHAN_FILE_AGE = timedelta(hours=1)`, `READER_THRESHOLD = 0.5`.
- Status item: `diterima`, `diproses`, `siap`, `gagal`, `tercatat`, `dilewati`, `kedaluwarsa`. `doc_type`: `struk_belanja`, `qris`, `transfer`, `tidak_dikenali`. `source`: `telegram`, `web_chat`, `web_form`, `pwa_share` (nanti `web_upload`, `android`, `ios`, `email`).
- Teks UI dan pesan bot Bahasa Indonesia, persis seperti di plan ini.
- Tes backend (sama dengan CI): `DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python -m unittest discover -s app/tests -t .`. Tes frontend: `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`.

## Review Focus

1. **Bukti yang sama dibagikan dua kali dengan cepat** (ketuk Bagikan dua kali, Telegram mengirim ulang) sebelum yang pertama selesai → satu item; share kedua mengembalikan item yang sama. Dipin di Task A6 (`test_same_open_file_returns_existing_item`).
2. **Foto struk belanja biasa tetap berperilaku seperti sekarang** (termasuk struk yang mencantumkan "Non Tunai (QRIS)") → dikenali `struk_belanja`, pesan bot struk lama tanpa baris kuota. Dipin di Task A5 (`test_store_receipt_with_qris_word_stays_struk_belanja`) dan Task A11.
3. **Ketikan biasa tidak dibajak sebagai bukti** ("kopi 35k", daftar multi-baris "kopi 20k\nroti 15k", pesan berisi "berhasil") → tetap ke NLP. Dipin di Task A11 (`test_plain_text_is_not_proof`).
4. **API restart/deploy saat item diproses** → item dipulihkan dan selesai; file belum dihapus sebelum diproses. Dipin di Task A7 (`test_stale_item_recovered_then_processed`).
5. **Amplop di peta merchant dihapus, nonaktif, atau milik pribadi anggota lain** → tidak pernah disarankan; saran jatuh ke sinyal berikutnya. Dipin di Task A8 (`test_hidden_or_inactive_envelopes_never_suggested`).

---

## Peta file

**Backend baru** — `app/services/kotak_struk/`:

| File | Tanggung jawab |
|---|---|
| `config.py` | Konstanta, status, sumber, jenis dokumen |
| `schema.py` | `KOTAK_DDL`: ALTER/INDEX aditif (dipakai `main.py` dan berkas alembic) |
| `document.py` | Dataclass Dokumen Bayar + JSON + adaptor respons `scan-receipt` |
| `merchants.py` | Kunci merchant, HMAC, nama tampilan, keterangan, teks belajar; upsert `household_merchants` |
| `extract.py`, `pdf_child.py` | Teks dari gambar/PDF/teks; PDF di proses terpisah |
| `readers/base.py`, `labels.py`, `profiles.py`, `struk_belanja.py`, `qris.py`, `transfer.py`, `unknown.py` | Pembaca dokumen |
| `registry.py` | Memilih pembaca |
| `checks.py` | Cek silang + arah uang |
| `dedup.py` | Duplikat (upload_id, file, ref, lunak) |
| `intake.py` | Membuat item dari kanal |
| `worker.py`, `waiter.py` | Pemrosesan dan menunggu hasil |
| `suggest.py`, `record.py` | Saran amplop, pencatatan + belajar |
| `view.py` | Detail item untuk API dan bot |
| `maintenance.py` | Kedaluwarsa dan file yatim |

**Backend lain:** `app/api/routes/kotak_struk.py` (baru), `app/scripts/kotak_corpus.py` (baru), `app/models/models.py`, `app/main.py`, `app/core/config.py`, `app/services/app_config.py`, `app/services/receipt_scan.py`, `app/api/routes/transactions.py`, `app/services/expense_rules.py`, `app/services/txn_nlp.py`, `app/bot/receipt_cmd.py`, `app/bot/handlers.py`, `app/services/scheduler.py`, `app/services/account_deletion.py`, `requirements.txt`, `alembic/versions/a7c4e2b9d1f3_kotak_struk.py` (baru).

**Frontend baru:** `src/lib/shareInbox.js`, `src/lib/proofFormat.js` (+ tes), `src/components/ProofCard.jsx`, `src/components/PendingProofsBanner.jsx`, `src/pages/Bagikan.jsx`.
**Frontend diubah:** `public/manifest.json`, `src/sw.js`, `src/App.jsx`, `src/lib/api.js`, `src/lib/receiptScan.js`, `src/lib/receiptProgress.js`, `src/native/index.js`, `src/native/web.js`, `src/hooks/useReceiptScan.js`, `src/components/ReceiptInput.jsx`, `src/components/MultiAddTransaction.jsx`, `src/components/Layout.jsx`, `src/pages/Settings.jsx`.

---

# Bagian A — Server dan bot (`feat/bagikan-ke-jatahku-server`)

Bagian A berdiri sendiri: setelah merge dan saklar dinyalakan, bukti bayar bisa dibagikan ke bot Telegram dan chat bot web.

### Task A1: Skema, konstanta, dan konfigurasi

**Files:**
- Create: `app/services/kotak_struk/__init__.py` (kosong), `app/services/kotak_struk/config.py`, `app/services/kotak_struk/schema.py`
- Create: `alembic/versions/a7c4e2b9d1f3_kotak_struk.py`
- Modify: `app/models/models.py` (`ReceiptScan` ±baris 535; model baru setelah `ReceiptLearnVote`)
- Modify: `app/main.py` (`lifespan`, setelah ALTER `income_type` ±baris 71)
- Modify: `app/core/config.py` (`Settings`)
- Test: `app/tests/test_kotak_schema.py`

**Interfaces:**
- Produces:
  - `config.py`: semua konstanta di Global Constraints, plus `ST_DITERIMA, ST_DIPROSES, ST_SIAP, ST_GAGAL, ST_TERCATAT, ST_DILEWATI, ST_KEDALUWARSA`, `OPEN_STATUSES = {ST_DITERIMA, ST_DIPROSES, ST_SIAP}`, `PROOF_TYPES = {"qris", "transfer"}`, `SOURCES = {"telegram", "web_chat", "web_form", "pwa_share"}`.
  - `ReceiptScan` kolom baru (semua nullable kecuali `attempts`): `source String(20)`, `status String(16) index`, `doc_type String(30)`, `household_id Uuid index`, `upload_id String(64)`, `file_sha256 String(64) index`, `content_type String(60)`, `pages Integer`, `file_path String(255)`, `ref_hash String(64) index`, `counterparty_key String(80) index`, `paid_at DateTime(tz)`, `document JSON().with_variant(JSONB(), "postgresql")`, `parser String(40)`, `attempts Integer default 0 server_default "0"`, `error String(200)`, `channel_meta JSON/JSONB`, `processed_at DateTime(tz)`, `expires_at DateTime(tz)`, `transaction_ids JSON/JSONB`.
  - `HouseholdMerchant` (`household_merchants`): `id Uuid PK`, `household_id FK households.id ondelete CASCADE`, `counterparty_key String(80)`, `raw_name String(100)`, `display_name String(60) null`, `city String(60) null`, `last_seen_at`, `created_at`; `UniqueConstraint("household_id", "counterparty_key", name="uq_hh_merchant")`.
  - `MerchantEnvelopeMap` (`merchant_envelope_map`): `id Uuid PK`, `merchant_id FK household_merchants.id ondelete CASCADE`, `envelope_id FK envelopes.id ondelete CASCADE`, `count Integer default 1`, `last_user_id FK users.id ondelete SET NULL null`, `last_used_at`; `UniqueConstraint("merchant_id", "envelope_id", name="uq_merchant_env")`.
  - `schema.KOTAK_DDL: list[str]` — satu `ALTER TABLE receipt_scans ADD COLUMN IF NOT EXISTS …` per kolom baru (tipe Postgres; JSON → `JSONB`; `attempts INTEGER NOT NULL DEFAULT 0`), plus `CREATE INDEX IF NOT EXISTS` untuk kolom ber-index dan `CREATE UNIQUE INDEX IF NOT EXISTS uq_receipt_scans_upload ON receipt_scans (user_id, upload_id) WHERE upload_id IS NOT NULL`.
  - `Settings.KOTAK_HMAC_KEY: str = ""`, `Settings.KOTAK_DIR: str = "/var/lib/jatahku/kotak"`. `RECEIPT_SCAN_LIMIT_BASIC` **tetap** di `Settings` (komentar "tidak dipakai lagi sejak Kotak Struk") supaya `.env` lama tidak membuat startup gagal.

- [ ] **Step 1: Write the failing test**

```python
"""Skema Kotak Struk (SQLite in-memory). Run: python -m unittest app.tests.test_kotak_schema -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import importlib.util, unittest
from datetime import timedelta
from fractions import Fraction
from sqlalchemy.exc import IntegrityError
from app.core.database import Base
from app.models.models import Household, HouseholdMerchant, ReceiptScan, User
from app.services.kotak_struk import config as K
from app.services.kotak_struk.schema import KOTAK_DDL

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
NEW_COLS = ["source", "status", "doc_type", "household_id", "upload_id", "file_sha256", "content_type",
            "pages", "file_path", "ref_hash", "counterparty_key", "paid_at", "document", "parser",
            "attempts", "error", "channel_meta", "processed_at", "expires_at", "transaction_ids"]

class ConstantsTests(unittest.TestCase):
    def test_constants_match_spec(self):
        self.assertEqual((K.WAIT_BOT_S, K.WAIT_FORM_S, K.MAX_ATTEMPTS, K.RATE_PER_HOUR), (10, 45, 3, 30))
        self.assertEqual((K.MAX_FILES_PER_SHARE, K.MAX_PENDING, K.PDF_MAX_PAGES, K.PDF_TIMEOUT_S), (10, 20, 5, 15))
        self.assertEqual(K.ITEM_EXPIRY, timedelta(days=7))
        self.assertEqual(K.SOFT_DUP_WINDOW, timedelta(hours=3))
        self.assertEqual(K.CONFIDENT_SHARE, Fraction(2, 3))

    def test_every_new_column_has_ddl(self):
        ddl = "\n".join(KOTAK_DDL)
        for col in NEW_COLS:
            with self.subTest(col):
                self.assertIn(f"ADD COLUMN IF NOT EXISTS {col} ", ddl)
                self.assertIn(col, ReceiptScan.__table__.c)
        self.assertIn("WHERE upload_id IS NOT NULL", ddl)

@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class SchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def test_json_columns_roundtrip(self):
        async with self.Session() as db:
            u = User(name="A"); db.add(u); await db.flush()
            s = ReceiptScan(user_id=u.id, status=K.ST_SIAP, document={"schema": 1, "lines": []},
                            transaction_ids=["x"], channel_meta={"chat_id": 1})
            db.add(s); await db.commit()
            got = await db.get(ReceiptScan, s.id)
            self.assertEqual((got.document["schema"], got.transaction_ids, got.attempts), (1, ["x"], 0))

    async def test_household_merchant_unique_per_key(self):
        async with self.Session() as db:
            hh = Household(name="R"); db.add(hh); await db.flush()
            db.add_all([HouseholdMerchant(household_id=hh.id, counterparty_key="nmid:ID1", raw_name="A"),
                        HouseholdMerchant(household_id=hh.id, counterparty_key="nmid:ID1", raw_name="B")])
            with self.assertRaises(IntegrityError):
                await db.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_schema -v`
Expected: FAIL — `ModuleNotFoundError: app.services.kotak_struk`.

- [ ] **Step 3: Implement**

`config.py`, `schema.py`, kolom dan model baru, dua field `Settings`. Di `lifespan`, setelah blok ALTER yang ada (masih di dalam `if conn.dialect.name == "postgresql":`): `for stmt in KOTAK_DDL: await conn.execute(text(stmt))`. Berkas alembic `a7c4e2b9d1f3` (down_revision = head saat ini, cek `alembic heads`) menjalankan `op.execute(stmt)` untuk tiap `KOTAK_DDL` dan `CREATE TABLE IF NOT EXISTS` untuk dua tabel baru via `op.create_table(..., if_not_exists=True)`; `downgrade()` = `pass` dengan komentar "aditif; tidak di-rollback".

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_schema -v`
Expected: PASS (4 tes).

- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/__init__.py app/services/kotak_struk/config.py app/services/kotak_struk/schema.py app/models/models.py app/main.py app/core/config.py alembic/versions/a7c4e2b9d1f3_kotak_struk.py app/tests/test_kotak_schema.py
git commit -m "feat(kotak): skema Kotak Struk, peta merchant, konstanta"
```

---

### Task A2: Dokumen Bayar, kunci merchant, keterangan

**Files:**
- Create: `app/services/kotak_struk/document.py`, `app/services/kotak_struk/merchants.py` (fungsi murni saja di task ini)
- Test: `app/tests/test_kotak_document.py`

**Interfaces:**
- Produces (`document.py`):
  - `@dataclass Counterparty(name: str | None = None, city: str | None = None, id_kind: str | None = None, id_masked: str | None = None, bank: str | None = None)`
  - `@dataclass Amounts(subtotal: int | None = None, fee: int = 0, tax: int = 0, discount: int = 0, total: int | None = None)`
  - `@dataclass Line(kind: str, name: str, amount: int, qty: float | None = None, unit_price: int | None = None, flag: str = "ok", note: str | None = None, suggestion: int | None = None)`
  - `@dataclass Ref(kind: str, masked: str)`
  - `@dataclass DokumenBayar(doc_type: str, issuer: str | None = None, status: str = "tidak_diketahui", flow: str = "tidak_diketahui", method: str = "lainnya", paid_at: datetime | None = None, counterparty: Counterparty = field(default_factory=Counterparty), amounts: Amounts = field(default_factory=Amounts), lines: list[Line] = field(default_factory=list), refs: list[Ref] = field(default_factory=list), note: str | None = None, confidence: dict[str, str] = field(default_factory=dict), evidence: list[str] = field(default_factory=list), checks: list[dict] = field(default_factory=list), schema: int = 1)` dengan `to_json() -> dict` (datetime ISO) dan `@classmethod from_json(d: dict) -> DokumenBayar` (field tak dikenal diabaikan, supaya versi lama/baru bisa dibaca).
- Produces (`merchants.py`, murni):
  - `normalize_name(s: str | None) -> str` — huruf kecil, buang tanda baca, rapatkan spasi.
  - `hmac_hex(value: str) -> str` — HMAC-SHA256 hex dengan kunci `settings.KOTAK_HMAC_KEY`; bila kosong, kunci = `sha256(("kotak:" + JWT_SECRET).encode()).digest()` dan log peringatan sekali.
  - `counterparty_key(cp: Counterparty, *, nmid: str | None = None, account_number: str | None = None, bank_code: str | None = None) -> str | None` — `nmid:<NMID upper>` › `rek:<hmac(bank_code + ":" + digits)>` (hanya bila `account_number` punya ≥8 digit) › `nama:<norm name>|<norm city atau bank>` › `None` bila tanpa nama; dipotong 80 karakter.
  - `display_name(raw: str | None) -> str` — huruf besar semua → kapital awal; kata di `ACRONYMS = {"PT","CV","UD","TB","SPBU","BRI","BCA","BNI","BSI","BTN","QRIS","RS","RSUD"}` tetap besar; teks campuran dibiarkan.
  - `compose_description(doc: DokumenBayar, *, display: str | None, note: str | None) -> str` — lihat tes; `doc_type` selain `qris`/`transfer`: `{display}` atau `Bukti bayar` bila tanpa nama (dengan catatan: `{note} ({display})`); ≤500 karakter.
  - `learnable_text(description: str, names: list[str]) -> str` — hapus (case-insensitive) setiap nama di `names`, frasa `(qris)`, `transfer ke`, tanda kurung kosong, rapatkan spasi.
  - `mask_digits(s: str, keep: int = 4) -> str` — `"…" + 4 digit terakhir` dari deret digit (boleh berspasi/strip).

- [ ] **Step 1: Write the failing test**

```python
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import unittest
from datetime import datetime, timezone, timedelta
from app.services.kotak_struk.document import Amounts, Counterparty, DokumenBayar, Ref
from app.services.kotak_struk import merchants as M

WIB = timezone(timedelta(hours=7))

def qris(name="SITI AMINAH", city="BANDUNG"):
    return DokumenBayar(doc_type="qris", method="qris", status="berhasil", flow="keluar",
                        paid_at=datetime(2026, 10, 26, 8, 12, tzinfo=WIB),
                        counterparty=Counterparty(name=name, city=city), amounts=Amounts(total=25000),
                        refs=[Ref("rrn", "…8812")])

class DocumentTests(unittest.TestCase):
    def test_json_roundtrip_and_unknown_fields_ignored(self):
        d = qris().to_json()
        self.assertEqual(d["paid_at"], "2026-10-26T08:12:00+07:00")
        d["future_field"] = 1
        back = DokumenBayar.from_json(d)
        self.assertEqual((back.counterparty.name, back.amounts.total, back.refs[0].masked), ("SITI AMINAH", 25000, "…8812"))

class MerchantKeyTests(unittest.TestCase):
    def test_nmid_beats_name(self):
        self.assertEqual(M.counterparty_key(Counterparty("SITI"), nmid="id1024358806544"), "nmid:ID1024358806544")

    def test_name_and_city_normalized(self):
        self.assertEqual(M.counterparty_key(Counterparty("Siti  Aminah.", "Bandung")), "nama:siti aminah|bandung")

    def test_full_account_uses_hmac_never_raw_digits(self):
        k = M.counterparty_key(Counterparty("BUDI"), account_number="0123 0100 1234 567", bank_code="BRI")
        self.assertTrue(k.startswith("rek:")); self.assertNotIn("1234567", k)
        self.assertEqual(k, M.counterparty_key(Counterparty("BUDI S"), account_number="012301001234567", bank_code="BRI"))

    def test_masked_account_falls_back_to_name_and_bank(self):
        self.assertEqual(M.counterparty_key(Counterparty("BUDI", bank="BRI"), account_number="****4567"), "nama:budi|bri")

    def test_no_name_no_key(self):
        self.assertIsNone(M.counterparty_key(Counterparty(None)))

class DescriptionTests(unittest.TestCase):
    def test_display_name(self):
        self.assertEqual(M.display_name("SITI AMINAH"), "Siti Aminah")
        self.assertEqual(M.display_name("SPBU PERTAMINA 34.401"), "SPBU Pertamina 34.401")
        self.assertEqual(M.display_name("Kopi Kenangan"), "Kopi Kenangan")

    def test_compose(self):
        self.assertEqual(M.compose_description(qris(), display="Siti Aminah", note=None), "Siti Aminah (QRIS)")
        self.assertEqual(M.compose_description(qris(), display="Siti Aminah", note="bakso 2, es teh"), "bakso 2, es teh (Siti Aminah)")
        t = DokumenBayar(doc_type="transfer", counterparty=Counterparty("BUDI SANTOSO"))
        self.assertEqual(M.compose_description(t, display="Budi Santoso", note=None), "Transfer ke Budi Santoso")

    def test_learnable_text_drops_merchant_names(self):
        self.assertEqual(M.learnable_text("bakso 2, es teh (Siti Aminah)", ["SITI AMINAH", "Warung Bu Siti"]), "bakso 2, es teh")
        self.assertEqual(M.learnable_text("Siti Aminah (QRIS)", ["SITI AMINAH"]), "")
        self.assertEqual(M.learnable_text("Transfer ke Budi Santoso", ["BUDI SANTOSO"]), "")

    def test_mask_digits(self):
        self.assertEqual(M.mask_digits("612345678812"), "…8812")
        self.assertEqual(M.mask_digits("0123 0100 1234 567"), "…4567")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_document -v`
Expected: FAIL — `ModuleNotFoundError: …kotak_struk.document`.

- [ ] **Step 3: Implement `document.py` dan fungsi murni `merchants.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_document -v`
Expected: PASS (10 tes).

- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/document.py app/services/kotak_struk/merchants.py app/tests/test_kotak_document.py
git commit -m "feat(kotak): Dokumen Bayar, kunci merchant, keterangan transaksi"
```

---

### Task A3: Ekstraksi teks (gambar, PDF, teks)

**Files:**
- Create: `app/services/kotak_struk/extract.py`, `app/services/kotak_struk/pdf_child.py`
- Modify: `requirements.txt` (tambah `pypdfium2==5.13.0`)
- Test: `app/tests/test_kotak_extract.py`

**Interfaces:**
- Produces:
  - `@dataclass TextDoc(lines: list[str], kind: str, pages: int = 1)` — `kind` ∈ `image`, `pdf_text`, `pdf_ocr`, `text`.
  - `class ExtractError(Exception)` dengan atribut `user_message: str`; subkelas: `PdfLocked` ("PDF terkunci kata sandi"), `PdfTooManyPages` ("PDF lebih dari 5 halaman"), `PdfUnreadable` ("PDF tidak bisa dibaca"), `ExtractUnavailable` ("Baca bukti sedang tidak bisa. Catat manual dulu."), `ImageUnreadable` ("Gambar tidak bisa dibaca. Coba kirim ulang.").
  - `sniff_type(data: bytes) -> str | None` — magic bytes: `\xff\xd8\xff` → `image/jpeg`, `\x89PNG` → `image/png`, `RIFF....WEBP` → `image/webp`, `%PDF-` → `application/pdf`; lainnya `None`.
  - `async def extract_text(data: bytes, content_type: str, *, ocr=None, pdf_runner=None) -> TextDoc` — `ocr` default `receipt_ocr.read_receipt_lines` (dipanggil dengan `owner=None`), `pdf_runner` default `run_pdf_isolated`. `text/plain` → baris non-kosong (strip), `kind="text"`. PDF: baris teks dari halaman bertekst; halaman tanpa teks (PNG dari child) di-OCR; `kind="pdf_ocr"` bila ada halaman yang di-OCR, selain itu `pdf_text`. `OcrUnavailable` → `ExtractUnavailable`; `OcrFailed` → `ImageUnreadable`.
  - `pdf_child.extract_pdf(data: bytes, max_pages: int, dpi: int = 200) -> tuple[list[str], list[bytes], int]` — fungsi top-level (bisa di-pickle untuk spawn): baris teks gabungan semua halaman (split `\r\n`/`\n`), PNG halaman tanpa teks, jumlah halaman. `PdfiumError` berisi "password" → `PdfLocked`; error lain → `PdfUnreadable`; `len(pdf) > max_pages` → `PdfTooManyPages`. Di child: `resource.setrlimit(RLIMIT_AS, 768 MB)` dalam `try` (diabaikan bila tidak didukung).
  - `async def run_pdf_isolated(data: bytes, *, timeout_s: int = PDF_TIMEOUT_S, max_pages: int = PDF_MAX_PAGES, fn=extract_pdf) -> tuple[list[str], list[bytes], int]` — `concurrent.futures.ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))` per panggilan, `asyncio.wait_for(loop.run_in_executor(...), timeout_s)`; timeout → matikan proses pool (`executor.shutdown(wait=False, cancel_futures=True)` + terminate proses) lalu `PdfUnreadable`. `ImportError` pypdfium2 → `ExtractUnavailable`.

- [ ] **Step 1: Write the failing test**

```python
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import time, unittest
from unittest.mock import AsyncMock
from app.services.receipt_ocr import OcrResult
from app.services.kotak_struk import extract as X
from app.services.kotak_struk.pdf_child import extract_pdf

def minimal_pdf(lines):
    """PDF satu halaman berteks Helvetica (tanpa pustaka luar)."""
    content = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out.encode())); out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out.encode())
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    return (out + f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()

def slow(data, max_pages, dpi=200):
    time.sleep(5)

class SniffTests(unittest.TestCase):
    def test_magic_bytes(self):
        self.assertEqual(X.sniff_type(b"\xff\xd8\xff\xe0xx"), "image/jpeg")
        self.assertEqual(X.sniff_type(b"\x89PNG\r\n\x1a\n"), "image/png")
        self.assertEqual(X.sniff_type(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertEqual(X.sniff_type(minimal_pdf(["a"])), "application/pdf")
        self.assertIsNone(X.sniff_type(b"<html>"))

class PdfTests(unittest.TestCase):
    def test_text_layer_read_without_ocr(self):
        lines, images, pages = extract_pdf(minimal_pdf(["Transfer Berhasil", "Nominal Rp150.000"]), max_pages=5)
        self.assertEqual((lines, images, pages), (["Transfer Berhasil", "Nominal Rp150.000"], [], 1))

    def test_garbage_pdf_is_unreadable(self):
        with self.assertRaises(X.PdfUnreadable):
            extract_pdf(b"%PDF-1.4 rusak", max_pages=5)

class ExtractTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_text(self):
        doc = await X.extract_text("Transfer berhasil\n\n  Rp150.000 \n".encode(), "text/plain")
        self.assertEqual((doc.lines, doc.kind), (["Transfer berhasil", "Rp150.000"], "text"))

    async def test_image_uses_ocr_without_owner(self):
        ocr = AsyncMock(return_value=OcrResult(lines=["QRIS", "Rp 25.000"], score=0.9, seconds=1))
        doc = await X.extract_text(b"\xff\xd8\xffimg", "image/jpeg", ocr=ocr)
        self.assertEqual((doc.lines, doc.kind), (["QRIS", "Rp 25.000"], "image"))
        self.assertIsNone(ocr.call_args.kwargs.get("owner"))

    async def test_scanned_pdf_pages_are_ocred(self):
        runner = AsyncMock(return_value=([], [b"png1"], 1))
        ocr = AsyncMock(return_value=OcrResult(lines=["Total Rp 99.000"], score=0.9, seconds=1))
        doc = await X.extract_text(minimal_pdf(["x"]), "application/pdf", ocr=ocr, pdf_runner=runner)
        self.assertEqual((doc.lines, doc.kind, doc.pages), (["Total Rp 99.000"], "pdf_ocr", 1))

    async def test_pdf_timeout_is_unreadable(self):
        with self.assertRaises(X.PdfUnreadable):
            await X.run_pdf_isolated(minimal_pdf(["a"]), timeout_s=1, fn=slow)

    async def test_error_messages_for_user(self):
        self.assertEqual(X.PdfLocked().user_message, "PDF terkunci kata sandi")
        self.assertEqual(X.PdfTooManyPages().user_message, "PDF lebih dari 5 halaman")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pip install pypdfium2==5.13.0 && python -m unittest app.tests.test_kotak_extract -v`
Expected: FAIL — `ModuleNotFoundError: …kotak_struk.extract`.

- [ ] **Step 3: Implement `extract.py` dan `pdf_child.py`; tambah `pypdfium2==5.13.0` ke `requirements.txt`**

Render halaman: `page.render(scale=dpi / 72).to_pil()` → PNG bytes via `io.BytesIO` (Pillow sudah ada). Halaman dianggap bertekst bila `get_textpage().get_text_range().strip()` tidak kosong.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_extract -v`
Expected: PASS (9 tes; tes timeout ±1 detik).

- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/extract.py app/services/kotak_struk/pdf_child.py requirements.txt app/tests/test_kotak_extract.py
git commit -m "feat(kotak): ekstraksi teks gambar, PDF (proses terpisah), dan teks"
```

---

### Task A4: Fondasi pembaca, struk belanja, tidak dikenali, registri

**Files:**
- Create: `app/services/kotak_struk/readers/__init__.py`, `readers/base.py`, `readers/labels.py`, `readers/struk_belanja.py`, `readers/unknown.py`, `app/services/kotak_struk/registry.py`
- Test: `app/tests/test_kotak_registry.py`

**Interfaces:**
- Consumes: A2 (`DokumenBayar`, `Line`, `Amounts`, `Counterparty`), A3 (`TextDoc`).
- Produces:
  - `base.py`: `@dataclass Secrets(ref_values: list[str] = [], account_number: str | None = None, bank_code: str | None = None, nmid: str | None = None)`; `@dataclass Parsed(doc: DokumenBayar, secrets: Secrets = field(default_factory=Secrets), extra: dict = field(default_factory=dict))` (`extra` untuk struk belanja: `total_label`, `merchant_key`, `confidence_source`, `reconciliation`, `adjustments`, `engine`); `@dataclass Check(code: str, level: str, message: str)` dengan `as_dict()`; `@dataclass ParseContext(today: date, user_name: str | None = None, merchant_aliases: dict = {}, merchant_profiles: dict = {}, image: bytes | None = None, content_type: str | None = None, user_id: Any = None, plan: str = "basic", llm: Callable | None = None)`; `class DocReader(Protocol)`: `doc_type: str`, `name: str`, `detect(doc: TextDoc) -> float`, `async parse(doc: TextDoc, ctx: ParseContext) -> Parsed`, `checks(parsed: Parsed, ctx: ParseContext) -> list[Check]`.
  - `labels.py`: `find_value(lines: list[str], synonyms: list[str]) -> str | None` (label di awal baris, case-insensitive, diikuti `:`/spasi; nilai = sisa baris, atau baris berikutnya bila sisa kosong); `find_amount(lines, synonyms) -> int | None` (pakai `receipt_parser.amounts_in` pada nilai; ambil angka pertama); `parse_datetime_id(text: str) -> datetime | None` (zona `Asia/Jakarta`; format: `26 Okt 2026 08:12:33 WIB`, `26 Oktober 2026, 08.12`, `26/10/2026 08:12`, `26-10-2026`, `2026-10-26 08:12:33`, `Oct 26, 2026 08:12 AM`; nama bulan Indonesia & Inggris, singkat & panjang; jam opsional → 00:00); `find_datetime(lines) -> datetime | None` (baris pertama yang terbaca); `count_markers(lines, words: list[str]) -> int` (jumlah kata unik yang muncul sebagai kata utuh, case-insensitive).
  - `StrukBelanjaReader` (`doc_type="struk_belanja"`, `name="struk_belanja"`): `detect` = 0.9 bila ada baris label total kuat (TOTAL, GRAND TOTAL, TOTAL BELANJA, TOTAL BAYAR) **dan** ≥2 baris barang/angka, 0.6 bila hanya salah satu, selain itu 0.2. `parse` memanggil `parse_receipt(lines, merchant_aliases=…, merchant_profiles=…)` lalu, bila keyakinan `rendah`/`gagal` dan `ctx.llm` + `ctx.image` ada, fallback LLM persis seperti `scan_receipt` lama (termasuk reset `flag == "cek"` dan `reconcile` ulang). Pemetaan: `items` → `Line(kind="item", …)`, `adjustments` → `Line(kind="discount"|"tax", …)`, `merchant` → `counterparty.name`, `total` → `amounts.total`, `date` → `paid_at` (00:00 WIB), `confidence["total"] = confidence`, `method="lainnya"`, `flow="keluar"`, `status="berhasil"`.
  - `UnknownReader` (`doc_type="tidak_dikenali"`, `name="tidak_dikenali"`): `detect` selalu 0.0 (hanya dipakai sebagai cadangan); `parse` mengambil nominal terbesar dari baris yang memuat `Rp`/`IDR`, `confidence["total"]="rendah"` bila ada, tanpa nominal bila tidak ada.
  - `registry.py`: `def readers_for(proofs_enabled: bool) -> list[DocReader]` (struk belanja selalu; QRIS & transfer hanya bila `proofs_enabled` — kelas dari Task A5 didaftarkan lewat `register_proof_reader(reader)`); `@dataclass ReadResult(parsed: Parsed, checks: list[Check], reader: str)`; `async def read_document(doc: TextDoc, ctx: ParseContext, *, proofs_enabled: bool) -> ReadResult` — skor tertinggi ≥ `READER_THRESHOLD`; seri → urutan daftar (bukti bayar sebelum struk belanja); tak ada → `UnknownReader`. `checks` = `reader.checks(...)` + `checks.common_checks(...)` (Task A5; sampai A5 selesai, `common_checks` belum ada — registri memanggilnya lewat import di dalam fungsi, dan task ini menambah stub `checks.py` berisi `def common_checks(parsed, ctx) -> list[Check]: return []` dan `def apply_flow(parsed, ctx) -> None: pass` yang diisi A5).

- [ ] **Step 1: Write the failing test**

```python
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import json, unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from app.services.kotak_struk.extract import TextDoc
from app.services.kotak_struk.readers import labels as L
from app.services.kotak_struk.readers.base import ParseContext
from app.services.kotak_struk.registry import read_document

FIX = json.loads((Path(__file__).parent / "fixtures" / "receipt_ocr_lines.json").read_text())
CTX = ParseContext(today=date(2026, 10, 15))

class LabelTests(unittest.TestCase):
    def test_value_same_line_or_next_line(self):
        lines = ["Merchant", "SITI AMINAH", "Nominal: Rp 25.000"]
        self.assertEqual(L.find_value(lines, ["merchant"]), "SITI AMINAH")
        self.assertEqual(L.find_amount(lines, ["nominal", "jumlah"]), 25000)

    def test_datetime_formats(self):
        for text, expect in [("26 Okt 2026 08:12:33 WIB", (2026, 10, 26, 8, 12)),
                             ("26 Oktober 2026, 08.12", (2026, 10, 26, 8, 12)),
                             ("26/10/2026 08:12", (2026, 10, 26, 8, 12)),
                             ("Oct 26, 2026 08:12 PM", (2026, 10, 26, 20, 12)),
                             ("2026-10-26", (2026, 10, 26, 0, 0))]:
            with self.subTest(text):
                d = L.parse_datetime_id(text)
                self.assertEqual((d.year, d.month, d.day, d.hour, d.minute), expect)
                self.assertEqual(d.utcoffset().total_seconds(), 7 * 3600)

class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_receipts_read_by_struk_belanja_same_as_before(self):
        for rec in FIX["receipts"][:3]:
            with self.subTest(rec["id"]):
                res = await read_document(TextDoc(lines=rec["lines"], kind="image"), CTX, proofs_enabled=True)
                self.assertEqual((res.reader, res.parsed.doc.doc_type), ("struk_belanja", "struk_belanja"))
                self.assertEqual(res.parsed.doc.amounts.total, rec["expect"]["total"])
                self.assertEqual(res.parsed.doc.counterparty.name, rec["expect"]["merchant"])
                self.assertTrue(all(l.kind == "item" for l in res.parsed.doc.lines if l.kind == "item"))

    async def test_unreadable_goes_to_unknown_with_largest_rp(self):
        res = await read_document(TextDoc(lines=["foto buram", "Rp 12.000", "Rp 2.000"], kind="image"), CTX, proofs_enabled=True)
        self.assertEqual((res.reader, res.parsed.doc.amounts.total, res.parsed.doc.confidence["total"]), ("tidak_dikenali", 12000, "rendah"))

    async def test_llm_fallback_kept_for_low_confidence_receipt(self):
        llm = AsyncMock(return_value={"merchant": "Toko A", "date": None, "total": 12000})
        ctx = ParseContext(today=date(2026, 10, 15), image=b"img", content_type="image/jpeg", llm=llm)
        res = await read_document(TextDoc(lines=["TOKO", "TOTAL 10.000", "x"], kind="image"), ctx, proofs_enabled=False)
        self.assertEqual((res.parsed.doc.amounts.total, res.parsed.extra["engine"]), (12000, "llm"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_registry -v`
Expected: FAIL — modul belum ada.

- [ ] **Step 3: Implement modul-modul di atas (termasuk stub `checks.py`)**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_registry app.tests.test_receipt_scan -v`
Expected: PASS (5 tes baru; tes lama tetap lulus).

- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/readers/__init__.py app/services/kotak_struk/readers/base.py app/services/kotak_struk/readers/labels.py app/services/kotak_struk/readers/struk_belanja.py app/services/kotak_struk/readers/unknown.py app/services/kotak_struk/registry.py app/services/kotak_struk/checks.py app/tests/test_kotak_registry.py
git commit -m "feat(kotak): registri pembaca, pembaca struk belanja dan tidak dikenali"
```

---

### Task A5: Pembaca QRIS & transfer, profil aplikasi, cek silang

**Files:**
- Create: `app/services/kotak_struk/readers/profiles.py`, `readers/qris.py`, `readers/transfer.py`
- Modify: `app/services/kotak_struk/checks.py` (isi stub), `app/services/kotak_struk/registry.py` (daftarkan dua pembaca)
- Create: `app/tests/fixtures/kotak/corpus.json`
- Test: `app/tests/test_kotak_readers.py`

**Interfaces:**
- Consumes: A4 (`DocReader`, `Parsed`, `Secrets`, `Check`, `labels.*`, `register_proof_reader`).
- Produces:
  - `profiles.py`: `@dataclass AppProfile(key: str, label: str, markers: list[str], labels: dict[str, list[str]] = {})`; `GENERIC_LABELS: dict[str, list[str]]` dengan kunci `amount` (`nominal`, `jumlah`, `jumlah pembayaran`, `total bayar`, `total pembayaran`, `total`, `amount`), `fee` (`biaya admin`, `biaya`, `admin`, `fee`), `merchant` (`merchant`, `nama merchant`, `penerima`, `tujuan`, `ke`), `city` (`lokasi`, `kota`), `ref` (`no. referensi`, `no referensi`, `referensi`, `no. ref`, `ref`, `rrn`, `reference no`, `id transaksi`, `no. transaksi`), `nmid` (`nmid`), `account` (`rekening tujuan`, `no. rekening`, `rekening`), `bank` (`bank tujuan`, `bank`), `note` (`berita`, `keterangan`, `catatan`); `PROFILES: list[AppProfile]` awal: `bca_mobile` (markers `["bca", "m-bca", "mybca"]`), `livin` (`["livin", "mandiri"]`), `brimo` (`["brimo", "bri"]`), `bni` (`["wondr", "bni"]`), `bsi` (`["bsi", "byond"]`), `jago` (`["jago"]`), `seabank` (`["seabank"]`), `blu` (`["blu"]`), `gopay` (`["gopay"]`), `ovo` (`["ovo"]`), `dana` (`["dana"]`), `shopeepay` (`["shopeepay"]`) — label khusus diisi Task A14 dari korpus nyata; `detect_issuer(lines) -> AppProfile | None` (marker terbanyak; seri → urutan daftar); `labels_for(profile: AppProfile | None, field: str) -> list[str]` (label profil dulu, lalu generik).
  - `QrisReader` (`doc_type="qris"`, `name="qris.umum"`): `detect` = 0.95 bila `count_markers(["qris","nmid","merchant pan","terminal id","acquirer","penerbit"]) >= 2`, 0.7 bila hanya "QRIS" + ada label merchant/nominal, selain itu 0.0; **0.0 bila baris memuat pola struk belanja** (`KEMBALI`, `TUNAI`, atau ≥3 baris barang `NAMA … ANGKA` sebelum baris total). `parse`: `method="qris"`, penerbit dari `detect_issuer`, `status` (`berhasil` bila "berhasil"/"sukses"/"successful"; `gagal` bila "gagal"/"failed"; `pending` bila "diproses"/"pending"), nominal, merchant, kota, waktu, ref (secrets.ref_values + `Ref("rrn"|"ref", mask_digits)`), NMID (secrets.nmid + `id_masked`), `flow="keluar"`, `confidence` per field (`tinggi` bila label kuat ditemukan, `sedang` bila dari pola cadangan).
  - `TransferReader` (`doc_type="transfer"`, `name="transfer.umum"`): `detect` = 0.9 bila `count_markers(["transfer","rekening tujuan","bank tujuan","bi-fast","berita","penerima"]) >= 2`; top-up (`top up`, `isi saldo`) dan uang masuk (`dana masuk`, `uang masuk`, `terima dana`, `dari`) juga dikenali reader ini (skor 0.85) dengan `flow` `top_up`/`masuk`. `parse`: `method="transfer"`, nominal → `amounts.subtotal`, biaya → `amounts.fee`, total → `amounts.total` (bila tidak ada total: `subtotal + fee`), penerima, bank, rekening (secrets.account_number/bank_code + `id_kind="rekening"`, `id_masked`), berita → `note`, ref, waktu, status.
  - `checks.py`: `common_checks(parsed, ctx) -> list[Check]` — kode: `selisih_nominal` (warn, "Nominal + biaya tidak sama dengan total"; turunkan `confidence["total"]` ke `sedang`), `status_gagal` (block, "Transaksi gagal, tidak bisa dicatat"), `status_pending` (warn, "Transaksi masih diproses bank"), `tanggal_depan` (warn, "Tanggal di bukti ada di masa depan"; `confidence["paid_at"]="rendah"`), `bukti_lama` (warn, "Bukti ini lebih dari 60 hari lalu"). `apply_flow(parsed, ctx) -> None` — transfer `keluar` dengan nama penerima ternormalisasi sama dengan `ctx.user_name`, atau ≥2 kata nama user ada di nama penerima → `flow="antar_rekening_sendiri"`.

- [ ] **Step 1: Buat fixture korpus sintetis**

`app/tests/fixtures/kotak/corpus.json` (format dipakai juga oleh Task A13):

```json
{"samples": [
  {"id": "sint-qris-1", "real": false, "lines": ["Pembayaran Berhasil", "QRIS", "Rp 25.000", "Merchant", "SITI AMINAH", "Lokasi BANDUNG", "NMID ID1024358806544", "Tanggal 26 Okt 2026 08:12:33 WIB", "No. Referensi 612345678812"],
   "expect": {"doc_type": "qris", "total": 25000, "paid_at": "2026-10-26T08:12:33+07:00", "counterparty": "SITI AMINAH", "status": "berhasil", "flow": "keluar"}},
  {"id": "sint-qris-2", "real": false, "lines": ["Transaksi Sukses", "Bayar QRIS", "Nama Merchant: WARUNG BAKSO PAK DI", "Kota: SEMARANG", "Jumlah Pembayaran Rp15.000", "26/10/2026 19:05", "RRN 000151856123", "Terminal ID A01"],
   "expect": {"doc_type": "qris", "total": 15000, "paid_at": "2026-10-26T19:05:00+07:00", "counterparty": "WARUNG BAKSO PAK DI", "status": "berhasil", "flow": "keluar"}},
  {"id": "sint-transfer-1", "real": false, "lines": ["Transfer Berhasil", "26 Okt 2026, 09:30 WIB", "Penerima", "BUDI SANTOSO", "Bank Tujuan BRI", "Rekening Tujuan 0123 0100 1234 567", "Nominal Rp150.000", "Biaya Admin Rp2.500", "Total Rp152.500", "Berita bayar arisan", "No. Ref 2026102612345678", "BI-FAST"],
   "expect": {"doc_type": "transfer", "total": 152500, "paid_at": "2026-10-26T09:30:00+07:00", "counterparty": "BUDI SANTOSO", "status": "berhasil", "flow": "keluar"}},
  {"id": "sint-transfer-gagal", "real": false, "lines": ["Transfer Gagal", "26 Okt 2026 10:00", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp50.000"],
   "expect": {"doc_type": "transfer", "total": 50000, "paid_at": "2026-10-26T10:00:00+07:00", "counterparty": "ANDI", "status": "gagal", "flow": "keluar"}},
  {"id": "sint-topup", "real": false, "lines": ["Top Up Berhasil", "GoPay", "Nominal Rp100.000", "26/10/2026 10:15", "ID Transaksi A1B2C3D4"],
   "expect": {"doc_type": "transfer", "total": 100000, "paid_at": "2026-10-26T10:15:00+07:00", "counterparty": null, "status": "berhasil", "flow": "top_up"}},
  {"id": "sint-masuk", "real": false, "lines": ["Dana Masuk", "Dari RINA", "Nominal Rp500.000", "26 Okt 2026 11:00", "Berita gaji"],
   "expect": {"doc_type": "transfer", "total": 500000, "paid_at": "2026-10-26T11:00:00+07:00", "counterparty": "RINA", "status": "berhasil", "flow": "masuk"}}
]}
```

- [ ] **Step 2: Write the failing test**

```python
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import json, unittest
from datetime import date
from pathlib import Path
from app.services.kotak_struk.extract import TextDoc
from app.services.kotak_struk.readers.base import ParseContext
from app.services.kotak_struk.registry import read_document

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "corpus.json").read_text())["samples"]
CTX = ParseContext(today=date(2026, 10, 26), user_name="Rina Wulandari")

async def read(lines, ctx=CTX, enabled=True):
    return await read_document(TextDoc(lines=lines, kind="image"), ctx, proofs_enabled=enabled)

class SyntheticCorpusTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_sample_matches_expectation(self):
        for s in CORPUS:
            with self.subTest(s["id"]):
                d = (await read(s["lines"])).parsed.doc
                e = s["expect"]
                self.assertEqual((d.doc_type, d.amounts.total, d.status, d.flow), (e["doc_type"], e["total"], e["status"], e["flow"]))
                self.assertEqual(d.paid_at.isoformat(), e["paid_at"])
                self.assertEqual(d.counterparty.name, e["counterparty"])

    async def test_secrets_never_in_document(self):
        res = await read(CORPUS[2]["lines"])
        blob = json.dumps(res.parsed.doc.to_json())
        self.assertNotIn("012301001234567", blob.replace(" ", ""))
        self.assertNotIn("2026102612345678", blob)
        self.assertEqual(res.parsed.secrets.ref_values, ["2026102612345678"])
        self.assertEqual((res.parsed.doc.amounts.subtotal, res.parsed.doc.amounts.fee), (150000, 2500))

    async def test_nmid_kept_as_secret_and_masked(self):
        res = await read(CORPUS[0]["lines"])
        self.assertEqual(res.parsed.secrets.nmid, "ID1024358806544")
        self.assertEqual(res.parsed.doc.counterparty.id_kind, "nmid")

class ClassificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_receipt_with_qris_word_stays_struk_belanja(self):
        res = await read(["ALFAMART", "14-10-2026 08:15", "ROTI 1 15.000", "SUSU 2 30.400", "Total Belanja 45.400", "Non Tunai (QRIS) 45.400"])
        self.assertEqual(res.reader, "struk_belanja")

    async def test_proof_readers_off_when_flag_disabled(self):
        res = await read(CORPUS[0]["lines"], enabled=False)
        self.assertNotIn(res.reader, ("qris.umum", "transfer.umum"))

class CheckTests(unittest.IsolatedAsyncioTestCase):
    def codes(self, res):
        return {c.code: c.level for c in res.checks}

    async def test_failed_transfer_blocked(self):
        self.assertEqual(self.codes(await read(CORPUS[3]["lines"]))["status_gagal"], "block")

    async def test_fee_mismatch_warns_and_lowers_confidence(self):
        lines = [l if not l.startswith("Total") else "Total Rp160.000" for l in CORPUS[2]["lines"]]
        res = await read(lines)
        self.assertEqual(self.codes(res)["selisih_nominal"], "warn")
        self.assertEqual(res.parsed.doc.confidence["total"], "sedang")

    async def test_pending_future_and_old_dates(self):
        self.assertIn("status_pending", self.codes(await read(["Transfer Diproses", "Penerima ANDI", "Nominal Rp1.000", "26/10/2026 10:00"])))
        self.assertIn("tanggal_depan", self.codes(await read(["Transfer Berhasil", "Penerima ANDI", "Nominal Rp1.000", "26/12/2026 10:00"])))
        self.assertIn("bukti_lama", self.codes(await read(["Transfer Berhasil", "Penerima ANDI", "Nominal Rp1.000", "01/08/2026 10:00"])))

    async def test_transfer_to_own_name_flagged(self):
        res = await read(["Transfer Berhasil", "Penerima RINA WULANDARI", "Bank Tujuan BCA", "Nominal Rp1.000.000", "26/10/2026 10:00"])
        self.assertEqual(res.parsed.doc.flow, "antar_rekening_sendiri")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_readers -v`
Expected: FAIL — `qris.umum` belum terdaftar (sampel dikenali `tidak_dikenali`).

- [ ] **Step 4: Implement `profiles.py`, `qris.py`, `transfer.py`, isi `checks.py`, daftarkan pembaca di `registry.py`**

Urutan prioritas seri di registri: `qris.umum`, `transfer.umum`, `struk_belanja`. Nominal QRIS tanpa label: angka `Rp` pertama setelah baris "QRIS"/status (`confidence["total"]="sedang"`).

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_readers app.tests.test_kotak_registry -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/kotak_struk/readers/profiles.py app/services/kotak_struk/readers/qris.py app/services/kotak_struk/readers/transfer.py app/services/kotak_struk/checks.py app/services/kotak_struk/registry.py app/tests/fixtures/kotak/corpus.json app/tests/test_kotak_readers.py
git commit -m "feat(kotak): pembaca QRIS dan transfer, profil aplikasi, cek silang"
```

---

### Task A6: Intake dan duplikat lapis 1–3

**Files:**
- Create: `app/services/kotak_struk/intake.py`, `app/services/kotak_struk/dedup.py`
- Test: `app/tests/test_kotak_intake.py`

**Interfaces:**
- Consumes: A1 (model, konstanta), A3 (`sniff_type`).
- Produces:
  - `@dataclass IntakeRequest(user: User, source: str, upload_id: str | None = None, data: bytes | None = None, content_type: str | None = None, text: str | None = None, channel_meta: dict | None = None)`
  - `class IntakeRejected(Exception)` dengan `status_code: int`, `detail: str`.
  - `async def create_item(db, req: IntakeRequest, *, redis=None, kotak_dir: str | None = None, now: datetime | None = None) -> tuple[ReceiptScan, bool]` — `redis=None` → klien dari `settings.REDIS_URL` dibuat dan ditutup di dalam fungsi; `kotak_dir=None` → `settings.KOTAK_DIR`. Urutan: (1) tepat salah satu `data`/`text`, selain itu 422 "Kirim satu file atau teks"; (2) `source in SOURCES` (422); (3) `upload_id` sudah ada untuk user → `(item, False)`; (4) teks: >`TEXT_MAX_CHARS` → 413 "Teks terlalu panjang"; file: `sniff_type` None → 415 "Kirim foto (JPG/PNG/WebP), PDF, atau teks"; gambar >`IMAGE_MAX_BYTES` → 413 "Foto terlalu besar (maks 8 MB)"; PDF >`PDF_MAX_BYTES` → 413 "PDF terlalu besar (maks 10 MB)"; (5) `file_sha256` (teks: sha256 dari teks ternormalisasi `"\n".join(baris strip non-kosong)`) sama dengan item user berstatus `OPEN_STATUSES` → `(item, False)`; (6) batas per jam Redis `kotak:rate:{user_id}` (`INCR`, `EXPIRE 3600` pada nilai 1) > `RATE_PER_HOUR` → 429 "Terlalu banyak bukti. Coba lagi sebentar." (Redis error → lewati); (7) item user berstatus `diterima`/`diproses` ≥ `MAX_PENDING` → 429 "Masih ada bukti yang sedang dibaca. Tunggu sebentar."; (8) buat `ReceiptScan(status=ST_DITERIMA, source, upload_id, household_id, file_sha256, content_type, channel_meta, engine="rapidocr", confidence="gagal")`, flush, tulis file ke `kotak_dir/<id>` (mode 0600; teks sebagai UTF-8, `content_type="text/plain"`), isi `file_path`, commit; (9) `worker.wake()` bila modul worker sudah diimpor (import di dalam fungsi, abaikan `ImportError`). Mengembalikan `(item, True)`.
  - `dedup.py`: `async def find_by_upload(db, user_id, upload_id) -> ReceiptScan | None`; `async def find_open_by_file(db, user_id, sha) -> ReceiptScan | None`; `async def recorded_duplicate(db, household_id, *, file_sha: str | None, ref_hash: str | None, exclude_id) -> dict | None` → `{"kind": "file"|"ref", "item_id": str, "recorded": True}` untuk item `tercatat` di rumah tangga; `async def pending_ref_duplicate(db, household_id, ref_hash, exclude_id) -> dict | None` → `{"kind": "ref", "item_id", "recorded": False, "by": <nama user pemilik>}` untuk item rumah tangga milik user lain berstatus `siap`. (Lapis lunak di Task A9.)

- [ ] **Step 1: Write the failing test**

Kelas tes SQLite seperti `test_fund_shift_integration` (salin `FakeRedis` minimal dengan `incr`/`expire`), satu user + rumah tangga, `kotak_dir` = `tempfile.mkdtemp()`.

```python
    async def test_creates_item_and_file(self):
        item, created = await create_item(self.db, IntakeRequest(self.user, "telegram", data=JPG), redis=self.redis, kotak_dir=self.dir)
        self.assertTrue(created)
        self.assertEqual((item.status, item.source, item.household_id, item.content_type), ("diterima", "telegram", self.hh.id, "image/jpeg"))
        self.assertEqual(Path(item.file_path).read_bytes(), JPG)
        self.assertEqual(oct(Path(item.file_path).stat().st_mode & 0o777), "0o600")

    async def test_upload_id_is_idempotent(self):
        a, _ = await create_item(self.db, IntakeRequest(self.user, "pwa_share", upload_id="u1", data=JPG), redis=self.redis, kotak_dir=self.dir)
        b, created = await create_item(self.db, IntakeRequest(self.user, "pwa_share", upload_id="u1", data=PNG), redis=self.redis, kotak_dir=self.dir)
        self.assertEqual((b.id, created), (a.id, False))

    async def test_same_open_file_returns_existing_item(self):
        a, _ = await create_item(self.db, IntakeRequest(self.user, "telegram", data=JPG), redis=self.redis, kotak_dir=self.dir)
        b, created = await create_item(self.db, IntakeRequest(self.user, "telegram", data=JPG), redis=self.redis, kotak_dir=self.dir)
        self.assertEqual((b.id, created), (a.id, False))

    async def test_rejections(self):
        cases = [(IntakeRequest(self.user, "telegram"), 422),
                 (IntakeRequest(self.user, "telegram", data=b"<html>"), 415),
                 (IntakeRequest(self.user, "telegram", data=b"\xff\xd8\xff" + b"0" * (8 * 1024 * 1024)), 413),
                 (IntakeRequest(self.user, "telegram", text="x" * 4001), 413),
                 (IntakeRequest(self.user, "lain", text="Transfer berhasil"), 422)]
        for req, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(IntakeRejected) as cm:
                    await create_item(self.db, req, redis=self.redis, kotak_dir=self.dir)
                self.assertEqual(cm.exception.status_code, code)

    async def test_rate_and_pending_limits(self):
        self.redis.counts[f"kotak:rate:{self.user.id}"] = 30
        with self.assertRaises(IntakeRejected) as cm:
            await create_item(self.db, IntakeRequest(self.user, "telegram", text="baru 1"), redis=self.redis, kotak_dir=self.dir)
        self.assertEqual(cm.exception.status_code, 429)
        self.redis.counts.clear()
        for i in range(20):
            await create_item(self.db, IntakeRequest(self.user, "telegram", text=f"bukti {i}"), redis=self.redis, kotak_dir=self.dir)
        with self.assertRaises(IntakeRejected):
            await create_item(self.db, IntakeRequest(self.user, "telegram", text="bukti 21"), redis=self.redis, kotak_dir=self.dir)

    async def test_recorded_and_pending_ref_duplicates(self):
        other = await self.add_member("Dewi")
        rec = ReceiptScan(user_id=other.id, household_id=self.hh.id, status="tercatat", ref_hash="h1", file_sha256="f1")
        pend = ReceiptScan(user_id=other.id, household_id=self.hh.id, status="siap", ref_hash="h2")
        self.db.add_all([rec, pend]); await self.db.commit()
        self.assertEqual((await recorded_duplicate(self.db, self.hh.id, file_sha=None, ref_hash="h1", exclude_id=None))["kind"], "ref")
        self.assertEqual((await recorded_duplicate(self.db, self.hh.id, file_sha="f1", ref_hash=None, exclude_id=None))["kind"], "file")
        self.assertEqual((await pending_ref_duplicate(self.db, self.hh.id, "h2", None))["by"], "Dewi")
```

(`JPG = b"\xff\xd8\xff\xe0jpeg"`, `PNG = b"\x89PNG\r\n\x1a\nxx"`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_intake -v`
Expected: FAIL — modul belum ada.

- [ ] **Step 3: Implement `intake.py` dan `dedup.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_intake -v`
Expected: PASS (6 tes).

- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/intake.py app/services/kotak_struk/dedup.py app/tests/test_kotak_intake.py
git commit -m "feat(kotak): intake item, idempotensi, batas, duplikat file/ref"
```

---

### Task A7: Worker dan penunggu

**Files:**
- Create: `app/services/kotak_struk/worker.py`, `app/services/kotak_struk/waiter.py`
- Modify: `app/services/kotak_struk/merchants.py` (tambah `upsert_household_merchant`)
- Modify: `app/services/app_config.py` (tambah `feature_enabled`)
- Modify: `app/main.py` (`lifespan`: jalankan/hentikan worker)
- Test: `app/tests/test_kotak_worker.py`

**Interfaces:**
- Consumes: A3 (`extract_text`, `ExtractError`), A4/A5 (`read_document`, `ParseContext`), A2 (`counterparty_key`, `hmac_hex`), A6 (item).
- Produces:
  - `app_config.feature_enabled(db, name: str, platform: str = "web") -> bool` (async) — baca AppSetting `app_config` → `parse_overrides` → `_features_for(platform, overrides["features"])[name]`; error DB → nilai bawaan `FEATURES`.
  - `merchants.upsert_household_merchant(db, household_id, key: str, raw_name: str | None, city: str | None, *, now) -> HouseholdMerchant` (async) — buat atau perbarui `raw_name`, `city`, `last_seen_at`.
  - `worker.claim_next(db) -> UUID | None` — id `diterima` tertua; `UPDATE receipt_scans SET status='diproses', attempts=attempts+1, processed_at=now WHERE id=:id AND status='diterima'`; rowcount 1 → id, selain itu `None` (aman di Postgres dan SQLite).
  - `worker.recover_stale(db, *, now) -> int` — `diproses` dengan `processed_at < now - STALE_PROCESSING`: `attempts >= MAX_ATTEMPTS` → `gagal` (`error="Bukti tidak bisa dibaca. Coba kirim ulang."`, hapus file), selain itu → `diterima`.
  - `worker.process_item(item_id, *, session_factory=None, extract=None, now=None, proofs_enabled: bool | None = None) -> str` (async) — mengembalikan status akhir; `proofs_enabled=None` → `feature_enabled(db, "receipt_inbox", "web")`. Alur di spec bagian 1 & 2: baca file → `extract_text` → `ParseContext` (`user_name`, alias/profil dari `receipt_scan._load_learning`, `image`/`content_type`/`user_id`/`plan`/`llm=try_llm_fallback` untuk gambar) → `read_document(proofs_enabled=await feature_enabled(db, "receipt_inbox", "web"))` → `apply_flow` sudah di registri → isi kolom: `doc_type`, `document` (dengan `checks`), `parser`, `engine` (`extra["engine"]` atau `rapidocr`), `merchant` (= nama pihak), `merchant_key` (`extra["merchant_key"]`, struk belanja saja), `parsed_total`, `parsed_date`, `confidence` (`confidence["total"]` atau `gagal`), `total_label`, `ocr_lines` (JSON baris), `counterparty_key`, `ref_hash` (`hmac_hex` ref pertama), `paid_at`, `status=siap`, `expires_at=now+ITEM_EXPIRY`; `upsert_household_merchant` bila ada `counterparty_key`; hapus file + `file_path=None`; commit; `publish_done(item_id, status)`; bila `channel_meta.get("notify")` → `await app.bot.receipt_cmd.send_ready_message(item_id)` (import di dalam fungsi; error di-log). `ExtractError` → `gagal` + `error=e.user_message`, hapus file, publish. Error lain → log, kembalikan `diterima` bila `attempts < MAX_ATTEMPTS` selain itu `gagal`.
  - `worker.run_worker(stop: asyncio.Event, *, session_factory=None, poll_s: float = 2.0)` — loop: `recover_stale` tiap 60 dtk, `claim_next` → `process_item`; tanpa item → tunggu `wake()`/`poll_s`. `worker.wake() -> None` — set `asyncio.Event` modul.
  - `waiter.publish_done(item_id, status) -> None` (async) — `PUBLISH kotak:done:{id} status`; error diabaikan.
  - `waiter.wait_for_item(item_id, timeout_s: float, *, session_factory=None, poll_s: float = 0.5, redis_factory=None) -> ReceiptScan | None` (async) — cek DB dulu (status bukan `diterima`/`diproses` → kembalikan); subscribe Redis `kotak:done:{id}`; Redis gagal → poll DB tiap `poll_s`; habis waktu → item terakhir dari DB.
  - `main.py` `lifespan`: `kotak_stop = asyncio.Event(); kotak_task = asyncio.create_task(run_worker(kotak_stop))` setelah `start_scheduler()`; saat shutdown `kotak_stop.set(); await asyncio.wait_for(kotak_task, 10)` dalam `try`.

- [ ] **Step 1: Write the failing test**

SQLite + `async_sessionmaker` (`session_factory`), user + rumah tangga, item dibuat via `create_item` dengan teks/gambar, `extract` palsu.

```python
    async def test_process_qris_to_siap(self):
        item = await self.item(text="ignored")
        status = await process_item(item.id, session_factory=self.Session, extract=fake_extract(CORPUS[0]["lines"]),
                                    now=NOW, proofs_enabled=True)
        self.assertEqual(status, "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.parser, int(got.parsed_total), got.merchant), ("qris", "qris.umum", 25000, "SITI AMINAH"))
        self.assertEqual(got.counterparty_key, "nmid:ID1024358806544")
        self.assertEqual(got.ref_hash, hmac_hex("612345678812"))
        self.assertEqual(got.paid_at.isoformat()[:16], "2026-10-26T08:12")
        self.assertIsNone(got.file_path); self.assertEqual(os.listdir(self.dir), [])
        self.assertEqual(got.expires_at, NOW + timedelta(days=7))
        self.assertEqual((await self.merchant("nmid:ID1024358806544")).raw_name, "SITI AMINAH")

    async def test_extract_error_marks_gagal_with_message(self):
        item = await self.item(text="x")
        status = await process_item(item.id, session_factory=self.Session, extract=AsyncMock(side_effect=PdfLocked()), now=NOW)
        got = await self.get(item.id)
        self.assertEqual((status, got.error, got.file_path), ("gagal", "PDF terkunci kata sandi", None))

    async def test_claim_is_exclusive(self):
        item = await self.item(text="x")
        async with self.Session() as db:
            self.assertEqual(await claim_next(db), item.id)
            self.assertIsNone(await claim_next(db))

    async def test_stale_item_recovered_then_processed(self):
        item = await self.item(text="x")
        async with self.Session() as db:
            await claim_next(db)
        async with self.Session() as db:
            self.assertEqual(await recover_stale(db, now=NOW + timedelta(minutes=6)), 1)
        self.assertEqual((await self.get(item.id)).status, "diterima")
        self.assertTrue(Path((await self.get(item.id)).file_path).exists())
        async with self.Session() as db:
            self.assertEqual(await claim_next(db), item.id)

    async def test_third_stale_attempt_gives_up(self):
        item = await self.item(text="x")
        await self.set(item.id, status="diproses", attempts=3, processed_at=NOW - timedelta(minutes=10))
        async with self.Session() as db:
            await recover_stale(db, now=NOW)
        got = await self.get(item.id)
        self.assertEqual((got.status, got.error, got.file_path), ("gagal", "Bukti tidak bisa dibaca. Coba kirim ulang.", None))

    async def test_wait_returns_final_item_and_falls_back_to_db_poll(self):
        item = await self.item(text="x")
        await self.set(item.id, status="siap")
        got = await wait_for_item(item.id, 1, session_factory=self.Session, redis_factory=broken_redis)
        self.assertEqual(got.status, "siap")
        item2 = await self.item(text="y")
        got2 = await wait_for_item(item2.id, 0.3, session_factory=self.Session, redis_factory=broken_redis, poll_s=0.1)
        self.assertEqual(got2.status, "diterima")
```

`broken_redis` = factory yang melempar `ConnectionError`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_worker -v`
Expected: FAIL — modul belum ada.

- [ ] **Step 3: Implement `worker.py`, `waiter.py`, `upsert_household_merchant`, `feature_enabled`; pasang worker di `lifespan`**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_worker -v`
Expected: PASS (6 tes).

- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/worker.py app/services/kotak_struk/waiter.py app/services/kotak_struk/merchants.py app/services/app_config.py app/main.py app/tests/test_kotak_worker.py
git commit -m "feat(kotak): worker dalam proses API, pemulihan item macet, penunggu hasil"
```

---

### Task A8: Saran amplop dan pembelajaran

**Files:**
- Create: `app/services/kotak_struk/suggest.py`, `app/services/kotak_struk/record.py`
- Modify: `app/services/expense_rules.py` (`after_expense_recorded`)
- Modify: `app/services/txn_nlp.py` (`CATEGORY_KEYWORDS`)
- Modify: `app/services/kotak_struk/merchants.py` (tambah `merchant_for_item`, `set_display_name`)
- Test: `app/tests/test_kotak_suggest.py`

**Interfaces:**
- Consumes: A1 (model), A2 (`display_name`, `learnable_text`), A7 (item siap).
- Produces:
  - `merchants.merchant_for_item(db, item) -> HouseholdMerchant | None` (async) — via `(item.household_id, item.counterparty_key)`.
  - `merchants.set_display_name(db, merchant_id, household_id, name: str) -> HouseholdMerchant | None` (async) — bersihkan seperti `receipt_scan.clean_merchant_name` (huruf/angka/spasi/`&'.-`), potong 60; kosong → `None` (hapus nama panggilan); merchant di rumah tangga lain → `None`.
  - `suggest.visible_expense_envelopes(db, household_id, user_id) -> list[Envelope]` (async) — aktif, `purpose == "expense"`, `owner_id IS NULL OR owner_id == user_id`.
  - `suggest.suggest_for_item(db, item, user, *, note: str | None = None) -> dict` (async) → `{"envelope_id": str|None, "envelope_name": str|None, "confident": bool, "source": "note"|"merchant"|"keyword"|"none"}`. Urutan spec 4a: (1) `note` → `find_best_envelope(note, hid, db, user.id)`; (2) peta merchant: baris `merchant_envelope_map` merchant itu yang amplopnya ada di daftar terlihat; pilih `count` terbesar, seri → `last_used_at` terbaru; `confident = Fraction(top.count, sum(counts terlihat)) >= CONFIDENT_SHARE`; (3) `find_best_envelope(display_name or raw_name)` (`source="keyword"`, `confident` dari fungsi itu); (4) `none`.
  - `record.NotRecordable(Exception)` dengan `detail: str`.
  - `record.check_recordable(db, item_id, user) -> ReceiptScan` (async) — item milik user (selain itu `NotRecordable("Bukti tidak ditemukan")`); struk belanja: status `siap`/`tercatat` boleh; selain itu status harus `siap` (`tercatat` → "Bukti ini sudah tercatat"; lainnya → "Bukti ini belum siap dicatat"); check `level == "block"` → "Transaksi gagal, tidak bisa dicatat"; `dedup.recorded_duplicate` ada → "Bukti ini sudah tercatat".
  - `record.learn_text_for_item(db, item_id, description: str) -> str | None` (async) — `None` untuk struk belanja / item tak ada; selain itu `learnable_text(description, [raw_name, display_name, counterparty.name])`.
  - `record.mark_recorded(db, item_id, *, user_id, transaction_id, envelope_id) -> bool` (async) — tambahkan id ke `transaction_ids`, `status=tercatat`, `ocr_lines=None` tetap dibiarkan untuk struk belanja (feedback lama yang menghapus); bila item bukti dan ada merchant: `count += 1` (buat baris bila belum ada), `last_user_id`, `last_used_at`. Mengembalikan `False` bila item tidak ada. Commit sendiri.
  - `after_expense_recorded(db, user, envelope_id, description: str, learn_text: str | None = None)` — `learn_text is None` → belajar dari `description` (perilaku lama); string → belajar dari string itu; kosong → tidak belajar kata kunci (streak tetap).
  - `CATEGORY_KEYWORDS`: tambah ke `makan`: `bakso`, `soto`, `martabak`, `seblak`; ke `transport`: `spbu`, `pertamina`, `shell`, `bengkel`; kategori baru `kesehatan`: `apotek`, `apotik`, `klinik`, `kimia farma`, `k24`. (`warung` sengaja tidak ditambahkan: warung kelontong bukan makan.)

- [ ] **Step 1: Write the failing test**

SQLite: rumah tangga dengan user A (pemilik) dan B; amplop `Makan` (bersama), `Jajan` (bersama), `Pribadi B` (owner B), `Lama` (bersama, `is_active=False`), `Tabungan` (purpose `saving`). Item QRIS siap milik A dengan merchant `nmid:ID1`.

```python
    async def test_note_wins(self):
        s = await suggest_for_item(self.db, self.item, self.a, note="beli soto")
        self.assertEqual((s["envelope_name"], s["source"]), ("Makan", "note"))

    async def test_merchant_majority_is_confident(self):
        await self.map(self.env["Makan"], 2); await self.map(self.env["Jajan"], 1)
        s = await suggest_for_item(self.db, self.item, self.a)
        self.assertEqual((s["envelope_name"], s["confident"], s["source"]), ("Makan", True, "merchant"))

    async def test_split_history_not_confident_and_tie_uses_latest(self):
        await self.map(self.env["Makan"], 1, used=T1); await self.map(self.env["Jajan"], 1, used=T2)
        s = await suggest_for_item(self.db, self.item, self.a)
        self.assertEqual((s["envelope_name"], s["confident"]), ("Jajan", False))

    async def test_hidden_or_inactive_envelopes_never_suggested(self):
        await self.map(self.env["Pribadi B"], 5); await self.map(self.env["Lama"], 5); await self.map(self.env["Tabungan"], 5)
        s = await suggest_for_item(self.db, self.item, self.a)
        self.assertNotIn(s["envelope_name"], ("Pribadi B", "Lama", "Tabungan"))

    async def test_keyword_fallback_from_merchant_name(self):
        item = await self.qris_item("WARUNG BAKSO PAK DI", key="nama:warung bakso pak di|")
        s = await suggest_for_item(self.db, item, self.a)
        self.assertEqual((s["envelope_name"], s["source"]), ("Makan", "keyword"))

    async def test_mark_recorded_learns_household_map(self):
        ok = await mark_recorded(self.db, self.item.id, user_id=self.b.id, transaction_id=uuid4(), envelope_id=self.env["Makan"].id)
        self.assertTrue(ok)
        row = await self.map_row(self.env["Makan"])
        self.assertEqual((row.count, row.last_user_id), (1, self.b.id))
        self.assertEqual((await self.get(self.item.id)).status, "tercatat")
        s = await suggest_for_item(self.db, self.item, self.a)   # anggota lain langsung dapat saran yakin
        self.assertEqual((s["envelope_name"], s["confident"]), ("Makan", True))

    async def test_learn_text_excludes_merchant_names(self):
        self.assertEqual(await learn_text_for_item(self.db, self.item.id, "bakso 2, es teh (Siti Aminah)"), "bakso 2, es teh")
        self.assertEqual(await learn_text_for_item(self.db, self.item.id, "Siti Aminah (QRIS)"), "")

    async def test_recordable_rules(self):
        await check_recordable(self.db, self.item.id, self.a)
        with self.assertRaises(NotRecordable):
            await check_recordable(self.db, self.item.id, self.b)            # bukan pemilik
        await mark_recorded(self.db, self.item.id, user_id=self.a.id, transaction_id=uuid4(), envelope_id=self.env["Makan"].id)
        with self.assertRaises(NotRecordable) as cm:
            await check_recordable(self.db, self.item.id, self.a)
        self.assertEqual(cm.exception.detail, "Bukti ini sudah tercatat")
        store = await self.store_item(status="tercatat")
        await check_recordable(self.db, store.id, self.a)                    # struk belanja: banyak transaksi

    async def test_after_expense_recorded_learn_text(self):
        with patch("app.services.txn_nlp.save_learned_keywords", new=AsyncMock()) as save, \
             patch("app.services.streak.record_activity", new=AsyncMock()):
            await after_expense_recorded(self.db, self.a, self.env["Makan"].id, "Siti Aminah (QRIS)", learn_text="")
            save.assert_not_awaited()
            await after_expense_recorded(self.db, self.a, self.env["Makan"].id, "x (Siti)", learn_text="bakso")
            self.assertEqual(save.await_args.args[1], "bakso")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_suggest -v`
Expected: FAIL — modul belum ada.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_suggest app.tests.test_txn_nlp -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/suggest.py app/services/kotak_struk/record.py app/services/kotak_struk/merchants.py app/services/expense_rules.py app/services/txn_nlp.py app/tests/test_kotak_suggest.py
git commit -m "feat(kotak): saran amplop dari peta merchant rumah tangga dan pembelajarannya"
```

---

### Task A9: Detail item dan API Kotak Struk

**Files:**
- Create: `app/services/kotak_struk/view.py`, `app/api/routes/kotak_struk.py`
- Modify: `app/services/kotak_struk/dedup.py` (tambah `soft_duplicate`)
- Modify: `app/main.py` (`app.include_router(kotak_struk.router, prefix="/kotak-struk", tags=["kotak-struk"])`)
- Test: `app/tests/test_kotak_api.py`

**Interfaces:**
- Consumes: A6 (`create_item`, `IntakeRequest`, `IntakeRejected`), A7 (`wait_for_item`), A8 (`suggest_for_item`, `set_display_name`, `merchant_for_item`), A2 (`compose_description`, `display_name`).
- Produces:
  - `dedup.soft_duplicate(db, household_id, *, amount: int, paid_at: datetime) -> dict | None` (async) — transaksi tidak terhapus di amplop rumah tangga dengan `amount == amount`, `transaction_date == paid_at.date()`, `created_at` dalam ±`SOFT_DUP_WINDOW` dari `paid_at` → `{"kind": "soft", "transaction": {"id", "description", "amount", "created_at", "envelope_name"}}`. Hanya transaksi yang terlihat user (kontrak visibilitas: deskripsi transaksi privat anggota lain disamarkan dengan `visibility.masked_description`).
  - `view.item_detail(db, item, user, *, note: str | None = None) -> dict` (async) — bentuk persis spec 5d (`id`, `status`, `doc_type`, `source`, `created_at`, `paid_at`, `document`, `merchant {id, name, display_name}`, `suggestion`, `description_preview`, `flags {duplicate_of, skip_suggestion, blocked, warnings}`, `error`). `flags.duplicate_of`: `recorded_duplicate` › `pending_ref_duplicate` › `soft_duplicate` (lunak hanya untuk item `siap`). `flags.blocked`: `"transaksi_gagal"` (check block), `"sudah_tercatat"` (duplikat tercatat, atau item bukti `tercatat`), selain itu `None`. `flags.skip_suggestion` = `flow` bila ∈ {`top_up`, `masuk`, `antar_rekening_sendiri`}. `flags.warnings` = pesan check `warn` + "Bukti ini juga dibagikan {by}" untuk duplikat ref belum tercatat. Untuk status `diterima`/`diproses`/`gagal`: `document`, `merchant`, `suggestion`, `description_preview` = `None`.
  - Router (`get_current_user`, `get_db`):
    - `POST /` multipart `file: UploadFile | None`, `text: str | None` (Form), `source: str` (Form), `upload_id: str | None` (Form, ≤64), `wait: int = 0` (Form, 0–45) → `create_item` (Redis dari `settings.REDIS_URL`), lalu `wait_for_item` bila `wait > 0`; 201 bila item baru, 200 bila sudah ada; `IntakeRejected` → `HTTPException(status_code, detail)`. Isi `file` dibaca maksimal `PDF_MAX_BYTES + 1` byte.
    - `GET /?status=siap` → `{"items": [item_detail …]}` milik user, `created_at` menurun, maks 50.
    - `GET /{item_id}` → `item_detail` (bukan milik user → 404 "Bukti tidak ditemukan").
    - `POST /{item_id}/saran` body `{"note": str | None}` (≤200) → `{"suggestion", "description_preview"}`.
    - `POST /{item_id}/lewati` body `{"reason": "bukan_pengeluaran" | "duplikat" | "batal"}` → status `dilewati` (hanya dari `siap`/`gagal`; selain itu 409 "Bukti ini tidak bisa dilewati") → `item_detail`.
    - `PUT /merchants/{merchant_id}` body `{"display_name": str}` → `{"id", "name", "display_name"}`; merchant bukan dari rumah tangga user → 404.

- [ ] **Step 1: Write the failing test**

TestClient pada `FastAPI()` yang hanya memuat router ini (pola `PhotoEndpointTests` di `test_web_chat.py`), `get_db` di-override ke sesi SQLite, `get_current_user` ke user A, Redis dipalsukan (`patch("app.services.kotak_struk.intake._redis", …)` atau parameter), `KOTAK_DIR` → temp dir.

```python
    def test_upload_then_detail_then_idempotent(self):
        r = self.c.post("/kotak-struk/", data={"source": "pwa_share", "upload_id": "u1"}, files={"file": ("a.jpg", JPG, "image/jpeg")})
        self.assertEqual((r.status_code, r.json()["status"]), (201, "diterima"))
        again = self.c.post("/kotak-struk/", data={"source": "pwa_share", "upload_id": "u1"}, files={"file": ("a.jpg", JPG, "image/jpeg")})
        self.assertEqual((again.status_code, again.json()["id"]), (200, r.json()["id"]))

    def test_bad_type_and_missing_input(self):
        self.assertEqual(self.c.post("/kotak-struk/", data={"source": "pwa_share"}, files={"file": ("a.html", b"<html>", "text/html")}).status_code, 415)
        self.assertEqual(self.c.post("/kotak-struk/", data={"source": "pwa_share"}).status_code, 422)

    def test_ready_item_detail_shape(self):
        item = self.ready_qris()   # item siap: SITI AMINAH Rp25.000, peta merchant Makan ×1
        d = self.c.get(f"/kotak-struk/{item.id}").json()
        self.assertEqual(d["description_preview"], "Siti Aminah (QRIS)")
        self.assertEqual((d["suggestion"]["envelope_name"], d["suggestion"]["confident"]), ("Makan", True))
        self.assertEqual(d["flags"], {"duplicate_of": None, "skip_suggestion": None, "blocked": None, "warnings": []})
        self.assertEqual(d["merchant"]["name"], "Siti Aminah")

    def test_other_users_item_is_404(self):
        item = self.ready_qris(owner=self.b)
        self.assertEqual(self.c.get(f"/kotak-struk/{item.id}").status_code, 404)

    def test_saran_with_note(self):
        item = self.ready_qris()
        d = self.c.post(f"/kotak-struk/{item.id}/saran", json={"note": "bakso 2, es teh"}).json()
        self.assertEqual((d["description_preview"], d["suggestion"]["source"]), ("bakso 2, es teh (Siti Aminah)", "note"))

    def test_flags_blocked_skip_and_soft_dup(self):
        failed = self.ready_transfer(CORPUS[3]["lines"])
        self.assertEqual(self.c.get(f"/kotak-struk/{failed.id}").json()["flags"]["blocked"], "transaksi_gagal")
        topup = self.ready_transfer(CORPUS[4]["lines"])
        self.assertEqual(self.c.get(f"/kotak-struk/{topup.id}").json()["flags"]["skip_suggestion"], "top_up")
        self.add_txn(amount=25000, description="bakso 25rb", created_at=PAID + timedelta(hours=2), on=PAID.date())
        dup = self.c.get(f"/kotak-struk/{self.ready_qris().id}").json()["flags"]["duplicate_of"]
        self.assertEqual((dup["kind"], dup["transaction"]["description"]), ("soft", "bakso 25rb"))

    def test_skip_and_rename_merchant(self):
        item = self.ready_qris()
        self.assertEqual(self.c.post(f"/kotak-struk/{item.id}/lewati", json={"reason": "bukan_pengeluaran"}).json()["status"], "dilewati")
        mid = self.merchant_id("nmid:ID1024358806544")
        r = self.c.put(f"/kotak-struk/merchants/{mid}", json={"display_name": "Warung Bakso Bu Siti<script>"})
        self.assertEqual(r.json()["display_name"], "Warung Bakso Bu Siti")
        self.assertEqual(self.c.put(f"/kotak-struk/merchants/{self.other_household_merchant()}", json={"display_name": "x"}).status_code, 404)

    def test_list_only_own_ready_items(self):
        mine, theirs = self.ready_qris(), self.ready_qris(owner=self.b)
        ids = [i["id"] for i in self.c.get("/kotak-struk/?status=siap").json()["items"]]
        self.assertIn(str(mine.id), ids); self.assertNotIn(str(theirs.id), ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_api -v`
Expected: FAIL — router belum ada.

- [ ] **Step 3: Implement `soft_duplicate`, `view.py`, router; daftarkan di `main.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_api -v && python -m app.scripts.openapi_cek`
Expected: PASS (8 tes); cek API tidak melaporkan perubahan yang memutus (hanya penambahan).

- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/view.py app/services/kotak_struk/dedup.py app/api/routes/kotak_struk.py app/main.py app/tests/test_kotak_api.py
git commit -m "feat(kotak): API Kotak Struk (unggah, daftar, detail, saran, lewati, nama merchant)"
```

---

### Task A10: `scan-receipt` lewat Kotak Struk, kuota scan dihapus, `receipt_item_id`

**Files:**
- Modify: `app/services/receipt_scan.py` (`scan_receipt`, `get_quota`; `ScanQuotaExceeded` tetap didefinisikan)
- Modify: `app/services/kotak_struk/document.py` (`scan_receipt_response`)
- Modify: `app/api/routes/transactions.py` (`RECEIPT_MIME`, `_read_receipt_upload`, `run_receipt_scan`, `TransactionCreate`, `BatchTransactionItem`, `create_transaction` ±baris 154–235, `batch_create_transactions` ±baris 293–390)
- Modify: `app/tests/test_receipt_scan.py` (`TestScanFlow`, `TestUploadValidation`)
- Modify: `docs/scan-struk.md` (bagian Alur, Konfigurasi, Batas)
- Test: `app/tests/test_kotak_transactions.py`

**Interfaces:**
- Consumes: A6, A7 (`wait_for_item`, `process_item`), A8 (`check_recordable`, `learn_text_for_item`, `mark_recorded`), A9 (`item_detail`).
- Produces:
  - `class ScanBusy(Exception)` di `receipt_scan.py`.
  - `receipt_scan.scan_receipt(user, data: bytes, content_type: str, db, *, waiter=None) -> dict` (async) — `create_item(source="web_form")` → `waiter(item.id, WAIT_FORM_S)` (default `wait_for_item`) → status masih `diterima`/`diproses` → `ScanBusy`; `gagal` → `OcrFailed(item.error)`; selain itu `scan_receipt_response(item, detail)`.
  - `document.scan_receipt_response(item, detail: dict) -> dict` — bentuk lama (`scan_id`=`str(item.id)`, `merchant`, `date`, `total`, `confidence`, `confidence_source`, `evidence`, `engine`, `ocr_seconds: 0`, `quota: {"limit": None, "used": 0, "remaining": None}`, `items`, `adjustments`, `reconciliation`) ditambah `item_id`, `doc_type`, `counterparty`, `paid_at`, `flags`, `suggestion`, `description_preview`. Untuk struk belanja, `items/adjustments/reconciliation` dibangun dari `lines` + `parsed.extra` lewat `receipt_scan.items_payload` (perilaku lama).
  - `receipt_scan.get_quota(user, db) -> Quota` → `Quota(limit=None, used=<jumlah scan bulan ini>)`.
  - `RECEIPT_MIME` + `"application/pdf"`; `_read_receipt_upload` memakai batas `PDF_MAX_BYTES` untuk PDF ("PDF terlalu besar (maks 10 MB)") dan `MAX_RECEIPT_BYTES` untuk gambar; pesan 415: "Format tidak didukung. Pakai JPG, PNG, WebP, atau PDF."
  - `run_receipt_scan`: `ScanBusy` → 503 "Scan struk sedang ramai. Coba lagi beberapa detik lagi."; cabang `ScanQuotaExceeded` dihapus.
  - `TransactionCreate.receipt_item_id: UUID | None = None`; `BatchTransactionItem.receipt_item_id: UUID | None = None`.
  - `create_transaction`: setelah cek idempotensi dan sebelum cek amplop → bila `receipt_item_id`: `await check_recordable(...)`; `NotRecordable` → 409 `detail`. Setelah commit: `learn = await learn_text_for_item(db, rid, req.description)`; `after_expense_recorded(db, user, req.envelope_id, req.description, learn_text=learn)`; `await mark_recorded(db, rid, user_id=user.id, transaction_id=txn.id, envelope_id=req.envelope_id)` dalam `try` (gagal → log, transaksi tetap sukses).
  - `batch_create_transactions`: per item sama; `NotRecordable` → hasil item `ok: False, error: detail`. Item struk belanja dengan `receipt_item_id` sama boleh lebih dari satu.
  - `docs/scan-struk.md`: hapus `RECEIPT_SCAN_LIMIT_BASIC` dari tabel konfigurasi (tulis "dihapus sejak Kotak Struk; kuota scan tidak ada"), alur menunjuk ke `docs/kotak-struk.md` (dibuat di "Selesai Bagian A").

- [ ] **Step 1: Write the failing test**

Di `test_receipt_scan.py`: ganti `test_basic_quota_exceeded` dengan `test_basic_has_no_scan_quota` dan sesuaikan `test_pro_unlimited_and_result_shape` / `test_low_confidence_uses_llm_fallback` ke jalur baru (SQLite, `waiter` yang menjalankan `process_item` dengan `extract` palsu); hapus assert `quota == {"limit": 15, …}`. Tes baru `test_kotak_transactions.py`:

```python
    async def test_scan_receipt_returns_old_shape_plus_new_fields(self):
        out = await scan_receipt(self.a, b"\xff\xd8\xffimg", "image/jpeg", self.db, waiter=self.run_inline(CORPUS[0]["lines"]))
        self.assertEqual((out["total"], out["doc_type"], out["quota"]["limit"]), (25000, "qris", None))
        self.assertEqual(out["scan_id"], out["item_id"])
        self.assertEqual(out["description_preview"], "Siti Aminah (QRIS)")

    async def test_scan_receipt_busy_when_not_done(self):
        with self.assertRaises(ScanBusy):   # penunggu habis waktu: item masih "diterima"
            await scan_receipt(self.a, b"\xff\xd8\xffimg", "image/jpeg", self.db, waiter=self.return_unprocessed)

    def test_pdf_upload_accepted_and_limits(self):
        data, ct = asyncio.run(_read_receipt_upload(Up(b"%PDF-1.4 x", "application/pdf")))
        self.assertEqual(ct, "application/pdf")
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(_read_receipt_upload(Up(b"%PDF" + b"0" * (10 * 1024 * 1024), "application/pdf")))
        self.assertEqual(cm.exception.status_code, 413)

    def test_create_with_receipt_item_records_and_learns(self):
        item = self.ready_qris()
        r = self.c.post("/transactions/", json={"envelope_id": str(self.env["Makan"].id), "amount": 25000,
                                                "description": "bakso 2 (Siti Aminah)", "receipt_item_id": str(item.id),
                                                "client_ref": "r1"})
        self.assertEqual(r.status_code, 201)
        got = self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", [r.json()["id"]]))
        self.assertEqual(self.learned_keywords(), {"bakso"})        # tanpa "siti"/"aminah"

    def test_second_record_of_same_proof_is_409_but_resend_is_same(self):
        item = self.ready_qris()
        body = {"envelope_id": str(self.env["Makan"].id), "amount": 25000, "description": "x", "receipt_item_id": str(item.id)}
        first = self.c.post("/transactions/", json={**body, "client_ref": "r1"})
        self.assertEqual(self.c.post("/transactions/", json={**body, "client_ref": "r1"}).json()["id"], first.json()["id"])
        dup = self.c.post("/transactions/", json={**body, "client_ref": "r2"})
        self.assertEqual((dup.status_code, dup.json()["detail"]), (409, "Bukti ini sudah tercatat"))

    def test_failed_transfer_cannot_be_recorded(self):
        item = self.ready_transfer(CORPUS[3]["lines"])
        r = self.c.post("/transactions/", json={"envelope_id": str(self.env["Makan"].id), "amount": 50000,
                                                "description": "x", "receipt_item_id": str(item.id)})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Transaksi gagal, tidak bisa dicatat"))

    def test_batch_store_receipt_items_share_one_receipt_item(self):
        item = self.ready_store_receipt()
        r = self.c.post("/transactions/batch", json={"items": [
            {"envelope_id": str(self.env["Makan"].id), "amount": 10000, "description": "ROTI (Indomaret)", "receipt_item_id": str(item.id), "client_ref": "a"},
            {"envelope_id": str(self.env["Jajan"].id), "amount": 5000, "description": "PERMEN (Indomaret)", "receipt_item_id": str(item.id), "client_ref": "b"}]})
        self.assertTrue(all(x["ok"] for x in r.json()))
        self.assertEqual(len(self.get(item.id).transaction_ids), 2)

    def test_quota_endpoint_unlimited(self):
        self.assertEqual(self.c.get("/transactions/scan-receipt/quota").json()["limit"], None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_transactions app.tests.test_receipt_scan -v`
Expected: FAIL.

- [ ] **Step 3: Implement perubahan di atas; perbarui `docs/scan-struk.md`**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_transactions app.tests.test_receipt_scan app.tests.test_web_chat -v && python -m app.scripts.openapi_cek`
Expected: PASS; cek API hanya melaporkan penambahan.

- [ ] **Step 5: Commit**

```bash
git add app/services/receipt_scan.py app/services/kotak_struk/document.py app/api/routes/transactions.py app/tests/test_receipt_scan.py app/tests/test_kotak_transactions.py docs/scan-struk.md
git commit -m "feat(kotak): scan-receipt lewat Kotak Struk, kuota scan dihapus, receipt_item_id"
```

---

### Task A11: Bot Telegram dan chat bot web

**Files:**
- Modify: `app/bot/receipt_cmd.py`
- Modify: `app/bot/handlers.py` (`handle_non_text` ±1640, `handle_message` ±1055, `cmd_batal`, `_receipt_feedback_saved` ±408 dan tiga pemanggilnya ±550/±796/±1445, tiga pemanggil `after_expense_recorded` yang membawa `scan_id` ±549/±795/±1441, `bot_callbacks` ±1704)
- Modify: `app/tests/test_receipt_scan.py` (`TestBotReceipt`: baris kuota hilang)
- Test: `app/tests/test_kotak_bot.py`

**Interfaces:**
- Consumes: A6 (`create_item`), A7 (`wait_for_item`), A9 (`item_detail`), A8 (`set_display_name` tidak dipakai di bot), A10 (`learn_text_for_item`, `mark_recorded`).
- Produces (`receipt_cmd.py`):
  - `looks_like_proof_text(text: str) -> bool` — ≥2 baris non-kosong **dan** ada nominal `Rp`/`IDR` **dan** kata status (`berhasil`, `sukses`, `successful`) **dan** ≥1 label (`referensi`, `ref`, `rrn`, `merchant`, `penerima`, `tujuan`, `nmid`).
  - `async def handle_receipt_document(update, context)` — pengganti `handle_receipt_photo` (alias `handle_receipt_photo = handle_receipt_document` tetap ada). Foto / dokumen gambar / dokumen PDF (≤ `PDF_MAX_BYTES`); balas "🧾 Membaca bukti..."; `create_item(source="web_chat" if is_web() else "telegram", channel_meta={"chat_id": …, "status_message_id": …})`; `wait_for_item(WAIT_BOT_S)`; lalu `_render(status_msg, item)`. Belum siap → Telegram: edit "⏳ Masih dibaca, nanti kukabari." dan set `channel_meta["notify"] = True`; web: edit "⏳ Masih dibaca. Cek Bukti menunggu di beranda nanti." (tanpa `notify`). `IntakeRejected` → edit pesan dengan `detail`. Batas bot lama `_rate_limited` (20/jam, `bot:scan:{tg_id}`) tidak dipakai lagi; batas berlaku dari intake (`kotak:rate:{user_id}`).
  - `async def handle_proof_text(update, context, text: str) -> None` — sama, `text=…`.
  - `def proof_message(detail: dict) -> str` — murni; teks persis:
    - QRIS/transfer siap: `"{QRIS|Transfer} · {merchant.name} · {kota}\n{Rp total} · {tgl jam} · {Berhasil|Pending}\n\nMasuk ke amplop mana?"` (tanpa kota → bagian kota dibuang; tanggal format `26 Okt 08.12`).
    - `blocked == "sudah_tercatat"`: `"✅ Bukti ini sudah tercatat {tgl} di {amplop}."` (tanggal & amplop dari transaksi; tanpa tombol catat).
    - `blocked == "transaksi_gagal"`: `"⚠️ Transaksi ini gagal di bank, jadi tidak dicatat."`
    - `skip_suggestion == "top_up"`: `"ℹ️ Ini top-up saldo, bukan pengeluaran."`; `"masuk"`: `"ℹ️ Ini uang masuk, bukan pengeluaran."`; `"antar_rekening_sendiri"`: `"ℹ️ Sepertinya transfer ke rekeningmu sendiri. Bukan pengeluaran?"`
    - Duplikat lunak: `"🤔 Mirip \"{deskripsi}\" yang dicatat {jam}. Sama?"`
    - Peringatan (`warnings`) ditambahkan sebagai baris `⚠️ …`.
  - Tombol (callback ≤64 byte): amplop `t_{key}_{idx}` (yang disarankan teratas; `⭐ ` bila `confident`), `✏️ Tambah catatan` → `kn_{key}`, `🚫 Bukan pengeluaran` → `kx_{item_id}`, `❌ Batal` → `struk_no_{item_id}`; skip_suggestion: `Oke, lewati` → `kx_{item_id}` dan `Tetap catat` → `ko_{key}` (menampilkan tombol amplop); lunak: `Sama, lewati` → `kd_{item_id}` dan `Beda, catat` → `ko_{key}`. Payload Redis `txn:{key}` (TTL 600) seperti sekarang + `"kind": "proof"`, `"item_id"`, `"note"`; `"desc"` = `description_preview`; `"date"` = tanggal bayar; `"scan_id"` = item id.
  - `async def handle_kotak_callback(update, context)` — `kn_`: simpan `kotak:note:{tg_user_id}` = `{"key", "item_id", "message_id"}` (TTL `NOTE_TTL_S`), balas "Ketik isi belanjaannya (atau /batal)"; `kx_`/`kd_`: item → `dilewati`, edit "❌ Dilewati."; `ko_`: edit pesan menampilkan tombol amplop.
  - `async def capture_note(update, context) -> bool` — bila ada `kotak:note:{tg}`: hapus kunci, `item_detail(note=text)`, perbarui payload (`desc`, `note`, urutan amplop), edit pesan tombol aslinya, kembalikan `True`.
  - `async def send_ready_message(item_id)` — untuk item `telegram` ber-`notify`: kirim/edit pesan via `telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)` ke `channel_meta["chat_id"]` (edit `status_message_id`; gagal edit → kirim pesan baru).
  - `async def learn_text_for_scan(db, scan_id, description) -> str | None` — membungkus `record.learn_text_for_item` (None bila `scan_id` kosong).
- Produces (`handlers.py`):
  - `handle_non_text`: foto, dokumen `image/*`, dokumen `application/pdf` → `handle_receipt_document`; dokumen lain → pesan lama "📄 File belum didukung…".
  - `handle_message`: sebelum guard 500 karakter → `if await capture_note(update, context): return`; lalu `if looks_like_proof_text(text) and len(text) <= TEXT_MAX_CHARS: await handle_proof_text(update, context, text); return`.
  - `cmd_batal`: hapus `kotak:note:{tg}` juga.
  - `_receipt_feedback_saved(user_id, scan_id, amount, txn_date, description, *, transaction_id=None, envelope_id=None)`: item `doc_type` bukti → `mark_recorded(...)`; selain itu `apply_feedback` seperti sekarang. Tiga pemanggil mengoper `transaction_id=txn.id, envelope_id=<amplop yang dicatat>`.
  - Tiga `after_expense_recorded(...)` yang punya `scan_id` → `learn_text=await learn_text_for_scan(db, scan_id, description)`.
  - `bot_callbacks`: tambah `(r"^k[nxdo]_", handle_kotak_callback)` sebelum `(r"^t_", …)`.
  - Baris "📸 Sisa scan bulan ini" dihapus dari semua pesan; `ScanQuotaExceeded` tidak lagi ditangani.

- [ ] **Step 1: Write the failing test**

Pola `TestBotReceipt` (patch `AsyncSessionLocal`, `get_or_create_user`, `_is_setup_complete`, `get_household_id`, `get_envelopes_with_spent`, `redis.asyncio.from_url`), plus patch `create_item`, `wait_for_item`, `item_detail`.

```python
class ProofTextTests(unittest.TestCase):
    def test_proof_text_detected(self):
        self.assertTrue(looks_like_proof_text("Transfer berhasil\nPenerima BUDI\nRp150.000\nNo. Ref 123"))

    def test_plain_text_is_not_proof(self):
        for t in ["kopi 35k", "kopi 20k\nroti 15k", "berhasil hemat hari ini", "bayar listrik 200rb berhasil"]:
            with self.subTest(t):
                self.assertFalse(looks_like_proof_text(t))

class MessageTests(unittest.TestCase):
    def test_ready_qris_message(self):
        self.assertEqual(proof_message(DETAIL_QRIS),
                         "QRIS · Siti Aminah · Bandung\nRp 25.000 · 26 Okt 08.12 · Berhasil\n\nMasuk ke amplop mana?")

    def test_recorded_and_failed_messages(self):
        self.assertEqual(proof_message(with_flags(DETAIL_QRIS, blocked="transaksi_gagal")), "⚠️ Transaksi ini gagal di bank, jadi tidak dicatat.")
        self.assertIn("sudah tercatat", proof_message(with_flags(DETAIL_QRIS, blocked="sudah_tercatat", duplicate_of=RECORDED)))

class BotFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_qris_photo_offers_star_envelope_and_note_button(self):
        await self.send_photo(detail=DETAIL_QRIS)
        rows = self.keyboard()
        self.assertEqual(rows[0][0].text, "⭐ 🍜 Makan")
        self.assertIn("✏️ Tambah catatan", self.button_texts())
        stored = self.stored_payload()
        self.assertEqual((stored["kind"], stored["desc"], stored["date"], stored["scan_id"]), ("proof", "Siti Aminah (QRIS)", "2026-10-26", DETAIL_QRIS["id"]))
        self.assertNotIn("Sisa scan", self.text())

    async def test_store_receipt_photo_keeps_old_message_without_quota(self):
        await self.send_photo(detail=DETAIL_STRUK)
        self.assertIn("🧾 Struk Indomaret", self.text()); self.assertNotIn("Sisa scan", self.text())

    async def test_slow_item_promises_notification(self):
        await self.send_photo(detail=DETAIL_PENDING)
        self.assertEqual(self.text(), "⏳ Masih dibaca, nanti kukabari.")
        self.assertTrue(self.saved_channel_meta()["notify"])

    async def test_note_capture_updates_payload_and_message(self):
        await self.send_photo(detail=DETAIL_QRIS)
        await self.press(f"kn_{self.key}")
        captured = await self.reply_text("bakso 2, es teh", detail_after_note=DETAIL_QRIS_NOTE)
        self.assertTrue(captured)
        self.assertEqual(self.stored_payload()["desc"], "bakso 2, es teh (Siti Aminah)")

    async def test_pdf_document_goes_to_kotak(self):
        await self.send_document(b"%PDF-1.4 x", "application/pdf", detail=DETAIL_TRANSFER)
        self.assertEqual(self.created_request().data, b"%PDF-1.4 x")
        self.assertTrue(self.text().startswith("Transfer · Budi Santoso"))

    async def test_feedback_hook_marks_proof_recorded(self):
        with patch("app.services.kotak_struk.record.mark_recorded", new=AsyncMock()) as mark, \
             patch("app.services.receipt_scan.apply_feedback", new=AsyncMock()) as fb:
            await handlers._receipt_feedback_saved(UID, PROOF_ITEM_ID, 25000, date(2026, 10, 26), "x",
                                                   transaction_id=TXN, envelope_id=ENV)
        mark.assert_awaited_once(); fb.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_bot -v`
Expected: FAIL.

- [ ] **Step 3: Implement perubahan bot**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_bot app.tests.test_receipt_scan app.tests.test_web_chat app.tests.test_fund_shift_integration -v`
Expected: PASS (tes lama tetap lulus).

- [ ] **Step 5: Commit**

```bash
git add app/bot/receipt_cmd.py app/bot/handlers.py app/tests/test_receipt_scan.py app/tests/test_kotak_bot.py
git commit -m "feat(bot): bukti bayar QRIS/transfer lewat Kotak Struk, catatan, PDF, teks bukti"
```

---

### Task A12: Pemeliharaan, hapus akun, statistik Admin

**Files:**
- Create: `app/services/kotak_struk/maintenance.py`
- Modify: `app/services/scheduler.py` (job baru di `start_scheduler`)
- Modify: `app/services/account_deletion.py` (`_delete_household` ±baris 93)
- Modify: `app/services/receipt_scan.py` (`accuracy_stats`)
- Test: `app/tests/test_kotak_maintenance.py`, perluas `app/tests/test_account_deletion.py`

**Interfaces:**
- Produces:
  - `maintenance.expire_items(db, *, now) -> int` (async) — `siap`/`gagal` dengan `expires_at < now` → `kedaluwarsa`, `ocr_lines=None`.
  - `maintenance.delete_orphan_files(kotak_dir: str, db, *, now) -> int` (async) — hapus file di `kotak_dir` yang lebih tua dari `ORPHAN_FILE_AGE` dan id-nya tidak dimiliki item `diterima`/`diproses`.
  - `scheduler.kotak_maintenance()` (async, interval 1 jam, id `kotak_maintenance`) menjalankan keduanya, error di-log.
  - `_delete_household`: hapus `MerchantEnvelopeMap` (via merchant id) dan `HouseholdMerchant` rumah tangga itu sebelum amplop dihapus.
  - `accuracy_stats` mendapat `by_doc_type: {doc_type: n}`, `by_issuer: {issuer: {"total": n, "corrected": n}}` (dari `document->>'issuer'`; dihitung di Python dari baris bulan ini supaya jalan di SQLite), `unrecognized: n`.

- [ ] **Step 1: Write the failing test**

```python
    async def test_expire_only_old_unconfirmed(self):
        old = await self.item(status="siap", expires_at=NOW - timedelta(minutes=1))
        fresh = await self.item(status="siap", expires_at=NOW + timedelta(days=1))
        done = await self.item(status="tercatat", expires_at=NOW - timedelta(days=1))
        self.assertEqual(await expire_items(self.db, now=NOW), 1)
        self.assertEqual([(await self.get(i.id)).status for i in (old, fresh, done)], ["kedaluwarsa", "siap", "tercatat"])

    async def test_orphan_files_removed_but_queued_kept(self):
        queued = await self.item(status="diterima", file=True)
        orphan = self.write_file("deadbeef", age=timedelta(hours=2))
        young = self.write_file("cafe", age=timedelta(minutes=5))
        self.assertEqual(await delete_orphan_files(self.dir, self.db, now=NOW), 1)
        self.assertTrue(Path(queued.file_path).exists()); self.assertFalse(orphan.exists()); self.assertTrue(young.exists())

    async def test_stats_breakdown(self):
        await self.item(status="siap", doc_type="qris", document={"issuer": "bca_mobile"})
        await self.item(status="siap", doc_type="tidak_dikenali", document={})
        s = await accuracy_stats(self.db, since=NOW - timedelta(days=1))
        self.assertEqual((s["by_doc_type"]["qris"], s["unrecognized"], s["by_issuer"]["bca_mobile"]["total"]), (1, 1, 1))
```

Di `test_account_deletion.py`: user tunggal dengan merchant + peta → `delete_account` → kedua tabel kosong.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_maintenance app.tests.test_account_deletion -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_maintenance app.tests.test_account_deletion app.tests.test_receipt_scan -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/kotak_struk/maintenance.py app/services/scheduler.py app/services/account_deletion.py app/services/receipt_scan.py app/tests/test_kotak_maintenance.py app/tests/test_account_deletion.py
git commit -m "feat(kotak): kedaluwarsa item, file yatim, hapus akun, statistik Admin per jenis"
```

---

### Task A13: Alat korpus dan gerbang akurasi

**Files:**
- Create: `app/scripts/kotak_corpus.py`
- Test: `app/tests/test_kotak_corpus.py`

**Interfaces:**
- Consumes: A3 (`extract_text`), A4/A5 (`read_document`), fixture `app/tests/fixtures/kotak/corpus.json`.
- Produces:
  - `python -m app.scripts.kotak_corpus add <file> --id <id> [--real]` — ekstrak teks (OCR/PDF/teks), samarkan (`mask_line`), jalankan pembaca, tambahkan sampel ke `corpus.json` dengan `expect` = hasil pembaca saat ini dan `"reviewed": false`; cetak baris dan `expect` untuk diperiksa manusia. File asli tidak disalin.
  - `mask_line(line: str) -> str` — deret ≥6 digit (boleh berspasi/strip) yang bukan nominal (`Rp`/`IDR` di baris itu, atau format ribuan `x.xxx`) → `…` + 4 digit terakhir; NMID (`ID` + ≥10 digit) dibiarkan (publik).
  - `python -m app.scripts.kotak_corpus eval [--real-only]` — cetak tabel per sampel + ringkasan: `% total/tanggal/status benar`, `% pihak benar`, `% doc_type benar`; kode keluar 1 bila di bawah gerbang.
  - `def evaluate(samples: list[dict]) -> dict` — `{"n", "amount_date_status_pct", "counterparty_pct", "doc_type_pct", "failures": [id…]}`.
  - Gerbang: `GATE = {"amount_date_status_pct": 95.0, "counterparty_pct": 90.0, "doc_type_pct": 98.0}`.

- [ ] **Step 1: Write the failing test**

```python
class CorpusTests(unittest.TestCase):
    def test_mask_line(self):
        self.assertEqual(mask_line("Rekening Tujuan 0123 0100 1234 567"), "Rekening Tujuan …4567")
        self.assertEqual(mask_line("No. Referensi 612345678812"), "No. Referensi …8812")
        self.assertEqual(mask_line("Nominal Rp1.500.000"), "Nominal Rp1.500.000")
        self.assertEqual(mask_line("NMID ID1024358806544"), "NMID ID1024358806544")

    def test_synthetic_corpus_passes_gate(self):
        r = evaluate([s for s in SAMPLES if not s["real"]])
        self.assertEqual(r["failures"], [])

    def test_real_corpus_meets_release_gate(self):
        real = [s for s in SAMPLES if s["real"] and s.get("reviewed")]
        if not real:
            self.skipTest("korpus nyata belum ada (FS.5, Task A14)")
        r = evaluate(real)
        for k, v in GATE.items():
            self.assertGreaterEqual(r[k], v, f"{k} {r[k]}% < {v}% — gagal: {r['failures']}")
```

(`evaluate` dijalankan sinkron lewat `asyncio.run` di dalamnya.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_kotak_corpus -v`
Expected: FAIL — modul belum ada.

- [ ] **Step 3: Implement `kotak_corpus.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_kotak_corpus -v && python -m app.scripts.kotak_corpus eval`
Expected: 2 PASS, 1 skipped ("korpus nyata belum ada"); `eval` mencetak 6 sampel sintetis, semua benar.

- [ ] **Step 5: Commit**

```bash
git add app/scripts/kotak_corpus.py app/tests/test_kotak_corpus.py
git commit -m "feat(kotak): alat korpus bukti bayar dan gerbang akurasi rilis"
```

---

### Task A14: Kalibrasi dengan korpus nyata (butuh sampel dari pemilik produk)

Task ini **menunggu sampel**: bukti QRIS dan transfer dari 8 aplikasi bank + 4 e-wallet teratas (≥3 per aplikasi per jenis) serta contoh negatif (top-up, transfer gagal, uang masuk, transfer ke rekening sendiri), dikirim pemilik produk ke sesi ini sebagai lampiran. File asli tidak pernah di-commit.

**Files:**
- Modify: `app/tests/fixtures/kotak/corpus.json` (sampel `real: true`, `reviewed: true`)
- Modify: `app/services/kotak_struk/readers/profiles.py` (label/marker per aplikasi)
- Modify (hanya bila tata letak menyimpang): pembaca khusus baru `readers/<app>.py` + daftar di `registry.py`

- [ ] **Step 1: Tambahkan tiap sampel**

Run (per file): `python -m app.scripts.kotak_corpus add <lampiran> --id <app>-<jenis>-<n> --real`
Expected: sampel tertulis dengan `reviewed: false`.

- [ ] **Step 2: Tinjau dan perbaiki `expect` tiap sampel dengan melihat bukti aslinya**

Pastikan tidak ada nama orang pribadi selain penerima/merchant yang dibutuhkan (samarkan nama pengirim), lalu set `"reviewed": true`.

- [ ] **Step 3: Jalankan evaluasi**

Run: `python -m app.scripts.kotak_corpus eval --real-only`
Expected: daftar sampel yang gagal (kemungkinan besar ada di awal).

- [ ] **Step 4: Perbaiki profil/pembaca sampai gerbang lulus, tanpa merusak sampel sintetis dan struk Indomaret**

Run: `python -m unittest app.tests.test_kotak_corpus app.tests.test_kotak_readers app.tests.test_kotak_registry app.tests.test_receipt_scan -v`
Expected: PASS, termasuk `test_real_corpus_meets_release_gate` (tidak lagi skipped).

- [ ] **Step 5: Commit**

```bash
git add app/tests/fixtures/kotak/corpus.json app/services/kotak_struk/readers/profiles.py
git commit -m "feat(kotak): kalibrasi profil aplikasi dengan korpus bukti nyata"
```

---

### Selesai Bagian A: dokumentasi, verifikasi, PR

- [ ] **Dokumentasi**
  - `docs/kotak-struk.md` (baru): alur, status, API, saklar `features.receipt_inbox`, konstanta, privasi, langkah deploy manual (di bawah), alat korpus.
  - `docs/mobile/02-adr.md`: ADR-M17 (teks dari spec bagian "Dampak ke rencana mobile").
  - `docs/mobile/01-kajian.md`: bagian Paket Pro → kuota scan dihapus (K4).
  - `docs/mobile/03-workflow.md` + `PROGRESS.md`: pecah FS menjadi FS-1 (spec ini; FS.1 tanpa service terpisah, FS.2, FS.3, FS.4a, QRIS/transfer dari FS.4b, FS.5, FS.6, FS.7, FS.8 sebagian, FS.9, FS.11) dan FS-2 (sisa FS.4b, FS.4c, invoice umum, worker terpisah, FS.10, 6.7); tandai paket FS-1 Bagian A sesuai status.
  - `AGENTS.md`: tambah "Deploy Checklist — Kotak Struk (a7c4e2b9d1f3)" berisi langkah deploy di bawah.

  ```bash
  git add docs/kotak-struk.md docs/mobile/02-adr.md docs/mobile/01-kajian.md docs/mobile/03-workflow.md docs/mobile/PROGRESS.md AGENTS.md
  git commit -m "docs(kotak): dokumentasi Kotak Struk, ADR-M17, pemecahan FS-1/FS-2"
  ```

- [ ] **Verifikasi:** `DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python -m unittest discover -s app/tests -t .` → semua PASS (bandingkan jumlah gagal dengan `git stash` bila ada kegagalan lingkungan lokal yang sudah ada sebelumnya); `python -m app.scripts.openapi_cek` → hanya penambahan.
- [ ] **PR** `feat/bagikan-ke-jatahku-server` dengan label `migrasi`. Deskripsi: ringkasan, saklar default mati, dan checklist deploy:
  1. Sebelum merge: `sudo -u jatahku /opt/jatahku/venv/bin/pip install pypdfium2==5.13.0`; `sudo install -d -m 0700 -o jatahku -g jatahku /var/lib/jatahku/kotak`; tambah `KOTAK_HMAC_KEY=<openssl rand -hex 32>` ke `/opt/jatahku/.env`.
  2. Merge → tunggu deploy (`api.jatahku.com/health` → commit baru). Kolom dan tabel dibuat `lifespan` saat restart.
  3. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head` → `alembic current` = `a7c4e2b9d1f3`; `sudo systemctl restart jatahku`.
  4. Uji: kirim foto struk Indomaret ke bot (pesan struk lama tanpa baris kuota), kirim PDF → "📄 …" tidak muncul lagi; saklar masih mati → bukti QRIS dibaca sebagai `tidak_dikenali`.
  5. Setelah gerbang korpus (A14) lulus: AppSetting `app_config` → `{"features": {"receipt_inbox": {"web": true}}}`; kirim bukti QRIS ke bot → tombol ⭐.
- [ ] Setelah merge: perbarui Project doc `claude/scan-struk-keputusan.md` (kuota scan dihapus, Kotak Struk) dan `claude/bagikan-ke-jatahku-desain.md` (status).

---

# Bagian B — PWA dan web (`feat/bagikan-ke-jatahku-web`)

Prasyarat: PR Bagian A sudah di-merge; rencana kamera sudah di-merge (`api.uploadForm`, `xhrUpload.js`, `receiptProgress.js`, `useReceiptScan`, `ReceiptInput size="sm"|"lg"`, `native.camera` dengan fungsi internal `open({ capture })` di `web.js`).

### Task B1: Klien API dan baris bukti di form Catat

**Files:**
- Modify: `frontend/src/lib/api.js` (metode baru di kelas `ApiClient`)
- Modify: `frontend/src/lib/receiptScan.js` (`receiptToItem`, `scanMessage`, ekspor baru)
- Modify: `frontend/src/components/MultiAddTransaction.jsx` (`toPayload` ±baris 461, `isReady`/validasi baris)
- Test: `frontend/src/lib/receiptScan.test.js`

**Interfaces:**
- Produces:
  - `api.kotakUpload(formData, { onProgress, onUploaded } = {}) → { ok, status, data, timedOut }` (lewat `uploadForm('/kotak-struk/', …)`), `api.kotakItem(id) → item|null`, `api.kotakPending() → item[]` (`GET /kotak-struk/?status=siap`; gagal → `[]`), `api.kotakSuggest(id, note) → {suggestion, description_preview}|null`, `api.kotakSkip(id, reason) → {ok, data}`, `api.kotakRenameMerchant(merchantId, displayName) → {ok, data}`.
  - `receiptToItem(result, key)` untuk `result.doc_type` ∈ `qris|transfer|tidak_dikenali`: `{ …bentuk lama, receiptItemId: result.item_id, description: result.description_preview || result.merchant || 'Belanja', transactionDate: (result.paid_at || '').slice(0, 10) || result.date || null, envelopeId: suggestion?.confident ? suggestion.envelope_id : '', suggested: !!suggestion?.confident, receiptItems: [], blockedReason: proofBlockReason(result.flags) }`. Struk belanja: bentuk lama + `receiptItemId: result.item_id`.
  - `proofBlockReason(flags) → string|null` — `blocked === 'transaksi_gagal'` → `'Transaksi ini gagal di bank, jadi tidak bisa dicatat.'`; `blocked === 'sudah_tercatat'` → `'Bukti ini sudah tercatat.'`; selain itu `null`.
  - `scanMessage(result)` tanpa kalimat "Sisa scan bulan ini"; untuk bukti: `"Bukti {QRIS|transfer} {nama} terbaca: Rp{total}. Pilih amplop lalu simpan."` + peringatan pertama dari `flags.warnings` / duplikat lunak (`"Mirip \"{deskripsi}\" yang sudah dicatat — cek dulu sebelum menyimpan."`) / skip (`"Ini {top-up saldo|uang masuk|transfer ke rekening sendiri}, biasanya bukan pengeluaran."`), `type: 'mixed'` bila ada peringatan.
  - `toPayload(item)` menambah `receipt_item_id: item.receiptItemId` bila ada (juga untuk bagian rencana struk belanja di `toParts`). Baris dengan `blockedReason` tidak siap disimpan dan menampilkan `blockedReason` sebagai error baris.

- [ ] **Step 1: Write the failing test**

```js
test('receiptToItem: bukti QRIS → satu baris dengan saran yakin dan tanggal bayar', () => {
  const item = receiptToItem({ item_id: 'i1', scan_id: 'i1', doc_type: 'qris', total: 25000, merchant: 'SITI AMINAH',
    description_preview: 'Siti Aminah (QRIS)', paid_at: '2026-10-26T08:12:00+07:00',
    suggestion: { envelope_id: 'e1', confident: true }, flags: { blocked: null, warnings: [] }, items: [] }, 'k1');
  assert.deepEqual([item.receiptItemId, item.description, item.transactionDate, item.envelopeId, item.suggested, item.blockedReason],
    ['i1', 'Siti Aminah (QRIS)', '2026-10-26', 'e1', true, null]);
});

test('receiptToItem: transfer gagal diblokir; saran tidak yakin tidak dipilihkan', () => {
  const item = receiptToItem({ item_id: 'i2', doc_type: 'transfer', total: 50000, suggestion: { envelope_id: 'e1', confident: false },
    flags: { blocked: 'transaksi_gagal', warnings: [] }, items: [] }, 'k2');
  assert.equal(item.envelopeId, '');
  assert.equal(item.blockedReason, 'Transaksi ini gagal di bank, jadi tidak bisa dicatat.');
});

test('scanMessage: tanpa sisa kuota; bukti dengan duplikat lunak memberi peringatan', () => {
  assert.doesNotMatch(scanMessage({ total: 51000, merchant: 'Indomaret', confidence: 'tinggi', quota: { limit: 15, remaining: 3 } }).text, /Sisa scan/);
  const m = scanMessage({ doc_type: 'qris', total: 25000, merchant: 'SITI AMINAH', counterparty: { name: 'SITI AMINAH' },
    flags: { duplicate_of: { kind: 'soft', transaction: { description: 'bakso 25rb' } }, warnings: [] } });
  assert.equal(m.type, 'mixed');
  assert.match(m.text, /Mirip "bakso 25rb" yang sudah dicatat/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && node --test src/lib/receiptScan.test.js`
Expected: FAIL.

- [ ] **Step 3: Implement di `receiptScan.js`, `api.js`, dan `MultiAddTransaction.jsx`**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`
Expected: PASS, build sukses.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.js frontend/src/lib/receiptScan.js frontend/src/lib/receiptScan.test.js frontend/src/components/MultiAddTransaction.jsx
git commit -m "feat(web): klien API Kotak Struk dan baris bukti bayar di form Catat"
```

---

### Task B2: PDF di form Catat dan teks tahap "bukti"

**Files:**
- Modify: `frontend/src/native/index.js`, `frontend/src/native/web.js`, `frontend/src/native/web.test.js`
- Modify: `frontend/src/lib/receiptProgress.js`, `frontend/src/lib/receiptProgress.test.js`
- Modify: `frontend/src/hooks/useReceiptScan.js`, `frontend/src/components/ReceiptInput.jsx`, `frontend/src/components/MultiAddTransaction.jsx` (oper `allowPdf`)
- Modify: `docs/mobile/03-workflow.md` (baris B20–B22: `files.pickDocument`)

**Interfaces:**
- Consumes: rencana kamera (`open({ capture })` internal di `web.js`, `stageLabel`, `useReceiptScan`, `ReceiptInput`).
- Produces:
  - `native.files.pickDocument() → Promise<File|null>` — web: fungsi internal kamera diperluas menjadi `open({ capture, accept })`; `pickDocument` memakai `accept = 'image/*,application/pdf'`, tanpa `capture`; penanda kamera (`jatahku_camera_open`) **tidak** ditulis untuk dokumen.
  - `stageLabel({ …, noun = 'struk' })` — `noun === 'bukti'`: `'Menyiapkan bukti…'`, `'Mengunggah bukti… 40%'`, `'Membaca bukti…'`, gabungan `'Mengirim dan membaca bukti…'`, hint lambat `'Dokumen panjang butuh waktu lebih lama.'`; `noun` default menjaga teks lama persis.
  - `useReceiptScan.scanFile(file)` menerima `application/pdf`: tanpa `compressImage`, ditolak `{ text: 'PDF terlalu besar (maks 10 MB)', canRetry: false, canRetake: true }` bila `file.size > 10 * 1024 * 1024`, dikirim ke `api.scanReceipt(file, …)` dengan nama asli.
  - `ReceiptInput size="sm"`: tombol ketiga **PDF** (ikon `file`) memanggil `native.files.pickDocument()` sinkron dari handler ketukan; tampil hanya bila prop `allowPdf` true (dioper `MultiAddTransaction` dari `useAppConfig().features.receipt_inbox`).

- [ ] **Step 1: Write the failing test**

```js
// web.test.js
test('files.pickDocument: input menerima gambar dan PDF, tanpa capture, tanpa penanda kamera', () => {
  const { doc, win } = fakeDom(); const storage = memStorage();
  const n = createWebNative({ storage, window: win, document: doc, navigator: {} });
  n.files.pickDocument();
  const input = doc.body.children.at(-1);
  assert.equal(input.accept, 'image/*,application/pdf');
  assert.equal(input.attrs.capture, undefined);
  assert.equal(CAMERA_MARK_KEY in storage.data, false);
});

// receiptProgress.test.js
test('stageLabel: kata benda bukti', () => {
  assert.equal(stageLabel({ stage: STAGE.READING, elapsedMs: 0, noun: 'bukti' }).title, 'Membaca bukti…');
  assert.equal(stageLabel({ stage: STAGE.UPLOADING, percent: 40, progressSeen: true, noun: 'bukti' }).title, 'Mengunggah bukti… 40%');
  assert.equal(stageLabel({ stage: STAGE.READING, elapsedMs: 8000, noun: 'bukti' }).hint, 'Dokumen panjang butuh waktu lebih lama.');
  assert.equal(stageLabel({ stage: STAGE.READING, elapsedMs: 0 }).title, 'Membaca struk…');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && node --test src/native/web.test.js src/lib/receiptProgress.test.js`
Expected: FAIL.

- [ ] **Step 3: Implement; perbarui baris B20–B22 di `docs/mobile/03-workflow.md`**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`
Expected: PASS, build sukses.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/native/index.js frontend/src/native/web.js frontend/src/native/web.test.js frontend/src/lib/receiptProgress.js frontend/src/lib/receiptProgress.test.js frontend/src/hooks/useReceiptScan.js frontend/src/components/ReceiptInput.jsx frontend/src/components/MultiAddTransaction.jsx docs/mobile/03-workflow.md
git commit -m "feat(web): pilih PDF bukti di form Catat, teks tahap untuk bukti"
```

---

### Task B3: Kotak share lokal, service worker, manifest

**Files:**
- Create: `frontend/src/lib/shareInbox.js`, `frontend/src/lib/shareInbox.test.js`
- Modify: `frontend/src/sw.js`, `frontend/public/manifest.json`, `frontend/src/lib/api.js` (`logout`)

**Interfaces:**
- Produces (`shareInbox.js`):
  - `SHARE_DB = 'jatahku-share'`, `SHARE_STORE = 'shares'`, `MAX_FILES = 10`.
  - `shareStore(idb = globalThis.indexedDB) → { all(), put(entry), del(id), clear() }` (objek store `keyPath: 'id'`; bila IndexedDB tidak ada → store memori kosong yang tidak melempar).
  - `async saveShare(store, formData, { now = Date.now, newId }) → batchId` — entri `{ id: newId(), batchId, name, type, blob, createdAt }` untuk tiap `formData.getAll('files')` (maks `MAX_FILES`, sisanya diabaikan), plus satu entri teks `{ id, batchId, text, type: 'text/plain', createdAt }` bila `text`/`title`/`url` tidak kosong (gabung dengan `\n`, `url` hanya bila tidak ada teks lain). Tanpa file dan teks → tidak menyimpan apa pun, tetap mengembalikan `batchId`.
  - `async handleShareTarget(request, { store, now, newId }) → Response` — `Response.redirect('/bagikan?s=' + batchId, 303)`; `formData()` gagal → `Response.redirect('/bagikan?err=baca', 303)`.
  - `nextToUpload(entries) → entry|null` (tertua dulu).
  - `uploadFormFor(entry, { wait = 10 }) → FormData` — `file` (Blob + nama) atau `text`, `source = 'pwa_share'`, `upload_id = entry.id`, `wait`.
  - `async clearShares(store)`.
- `sw.js`: di awal handler `fetch` (sebelum `request.method !== 'GET'` return): `if (request.method === 'POST' && url.pathname === '/bagikan') { event.respondWith(handleShareTarget(request, { store: shareStore(), newId: newRef })); return; }`.
- `manifest.json`: tambah `share_target` persis seperti spec 5b.
- `api.logout()`: setelah `clearAllHistory()` → `clearShares(shareStore()).catch(() => {})`.

- [ ] **Step 1: Write the failing test**

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { saveShare, handleShareTarget, nextToUpload, uploadFormFor, clearShares, MAX_FILES } from './shareInbox.js';

function memStore() {
  const map = new Map();
  return { map, all: async () => [...map.values()], put: async e => { map.set(e.id, e); }, del: async id => { map.delete(id); }, clear: async () => map.clear() };
}
let n = 0; const newId = () => `id-${++n}`;

test('saveShare: file (maks 10) dan teks disimpan dengan batch yang sama', async () => {
  const store = memStore(); const fd = new FormData();
  for (let i = 0; i < 12; i++) fd.append('files', new Blob(['x'], { type: 'image/jpeg' }), `b${i}.jpg`);
  fd.append('text', 'Transfer berhasil Rp150.000');
  const batch = await saveShare(store, fd, { now: () => 5, newId });
  const all = await store.all();
  assert.equal(all.filter(e => e.blob).length, MAX_FILES);
  assert.equal(all.find(e => e.text).text, 'Transfer berhasil Rp150.000');
  assert.ok(all.every(e => e.batchId === batch && e.createdAt === 5));
});

test('handleShareTarget: 303 ke /bagikan dengan batch; form rusak → err', async () => {
  const fd = new FormData(); fd.append('files', new Blob(['%PDF'], { type: 'application/pdf' }), 'a.pdf');
  const res = await handleShareTarget(new Request('https://jatahku.com/bagikan', { method: 'POST', body: fd }), { store: memStore(), newId });
  assert.equal(res.status, 303);
  assert.match(res.headers.get('location'), /\/bagikan\?s=/);
  const bad = await handleShareTarget({ formData: async () => { throw new Error('x'); } }, { store: memStore(), newId });
  assert.match(bad.headers.get('location'), /err=baca/);
});

test('uploadFormFor dan nextToUpload', async () => {
  const fd = uploadFormFor({ id: 'e1', name: 'a.pdf', type: 'application/pdf', blob: new Blob(['%PDF']) }, { wait: 10 });
  assert.deepEqual([fd.get('source'), fd.get('upload_id'), fd.get('wait')], ['pwa_share', 'e1', '10']);
  assert.equal(fd.get('file').name, 'a.pdf');
  assert.equal(nextToUpload([{ id: 'b', createdAt: 2 }, { id: 'a', createdAt: 1 }]).id, 'a');
  const store = memStore(); await store.put({ id: 'x' }); await clearShares(store); assert.equal((await store.all()).length, 0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && node --test src/lib/shareInbox.test.js`
Expected: FAIL.

- [ ] **Step 3: Implement `shareInbox.js`, wiring `sw.js`, `manifest.json`, `api.logout`**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`
Expected: PASS, build sukses; `dist/manifest.json` memuat `share_target`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/shareInbox.js frontend/src/lib/shareInbox.test.js frontend/src/sw.js frontend/public/manifest.json frontend/src/lib/api.js
git commit -m "feat(pwa): terima share file dan teks lewat Web Share Target"
```

---

### Task B4: Format kartu bukti dan `ProofCard`

**Files:**
- Create: `frontend/src/lib/proofFormat.js`, `frontend/src/lib/proofFormat.test.js`, `frontend/src/components/ProofCard.jsx`

**Interfaces:**
- Consumes: B1 (`api.kotakSuggest`, `api.kotakSkip`, `api.kotakRenameMerchant`, `api.createTransaction`).
- Produces (`proofFormat.js`):
  - `proofHeader(item) → { badge, statusText, statusTone }` — `badge` = `'QRIS · BCA mobile'` (label penerbit dari peta `ISSUER_LABEL = { bca_mobile: 'BCA mobile', livin: "Livin' by Mandiri", brimo: 'BRImo', bni: 'wondr by BNI', bsi: 'BSI', jago: 'Jago', seabank: 'SeaBank', blu: 'blu', gopay: 'GoPay', ovo: 'OVO', dana: 'DANA', shopeepay: 'ShopeePay' }`; tanpa penerbit → `'QRIS'`/`'Transfer'`/`'Bukti bayar'`); `statusText` `'Berhasil'|'Pending'|'Gagal'|''`; `statusTone` `'success'|'warning'|'danger'|'muted'`.
  - `proofWarnings(item) → [{ tone, text }]` — urutan: blokir (`danger`; teks dari `proofBlockReason`), skip (`warning`; `'Ini top-up saldo, biasanya bukan pengeluaran.'`, `'Ini uang masuk, biasanya bukan pengeluaran.'`, `'Sepertinya transfer ke rekeningmu sendiri.'`), duplikat lunak (`warning`; `'Mirip "{deskripsi}" yang dicatat {HH.MM}. Sudah dicatat?'`), duplikat ref belum tercatat dan `warnings` server (`warning`).
  - `canSave(item, envelopeId) → { ok: boolean, reason: string|null }` — blokir → alasan; tanpa amplop → `'Pilih amplop dulu'`; status bukan `siap` → `'Bukti belum siap'`.
  - `savePayload(item, { envelopeId, description, ref, raiseLimit }) → object` — `{ envelope_id, amount: item.document.amounts.total, description, source: 'webapp', transaction_date: item.paid_at.slice(0, 10), receipt_item_id: item.id, client_ref: ref, raise_daily_limit? }`.
  - `paidLabel(item) → '26 Okt 2026, 08.12 · Bandung'`.
- `ProofCard({ item, envelopes, onSaved, onSkipped })` — tata letak mockup spec 5b: badge + status, nominal besar, nama tampilan + tautan **Ubah nama** (prompt inline, simpan lewat `kotakRenameMerchant`), `paidLabel`, chip amplop (`purpose` expense saja; yang disarankan dipilihkan bila `confident`, label "disarankan"), input catatan (placeholder `bakso 2, es teh (opsional)`, debounce 600 ms → `kotakSuggest` → perbarui `description_preview` dan saran bila user belum memilih amplop sendiri), daftar `proofWarnings`, tombol **Simpan** (`canSave`; `client_ref` dibuat sekali per kartu) dan **Bukan pengeluaran** (`kotakSkip(id, 'bukan_pengeluaran')`). Duplikat lunak menampilkan **Sama, lewati** (`kotakSkip(id, 'duplikat')`) di samping Simpan. Gagal simpan: pesan `detail`; limit harian (`/limit harian/i`) → tombol **Catat, naikkan limit hari ini** (ulang dengan `raiseLimit: true`); dana kurang → teks + pilih amplop lain (pola `OfflineQueueCenter`). Tidak ada geser dana di kartu ini.

- [ ] **Step 1: Write the failing test**

```js
const ITEM = { id: 'i1', status: 'siap', paid_at: '2026-10-26T08:12:00+07:00', description_preview: 'Siti Aminah (QRIS)',
  document: { doc_type: 'qris', issuer: 'bca_mobile', status: 'berhasil', counterparty: { city: 'BANDUNG' }, amounts: { total: 25000 } },
  flags: { duplicate_of: null, skip_suggestion: null, blocked: null, warnings: [] } };

test('proofHeader dan paidLabel', () => {
  assert.deepEqual(proofHeader(ITEM), { badge: 'QRIS · BCA mobile', statusText: 'Berhasil', statusTone: 'success' });
  assert.equal(paidLabel(ITEM), '26 Okt 2026, 08.12 · Bandung');
});

test('proofWarnings: blokir lebih dulu, lalu skip dan duplikat lunak', () => {
  const w = proofWarnings({ ...ITEM, flags: { blocked: 'transaksi_gagal', skip_suggestion: 'top_up',
    duplicate_of: { kind: 'soft', transaction: { description: 'bakso 25rb', created_at: '2026-10-26T10:05:00+07:00' } }, warnings: [] } });
  assert.deepEqual(w.map(x => x.tone), ['danger', 'warning', 'warning']);
  assert.equal(w[2].text, 'Mirip "bakso 25rb" yang dicatat 10.05. Sudah dicatat?');
});

test('canSave dan savePayload', () => {
  assert.deepEqual(canSave(ITEM, ''), { ok: false, reason: 'Pilih amplop dulu' });
  assert.equal(canSave({ ...ITEM, flags: { ...ITEM.flags, blocked: 'sudah_tercatat' } }, 'e1').reason, 'Bukti ini sudah tercatat.');
  assert.deepEqual(savePayload(ITEM, { envelopeId: 'e1', description: 'Siti Aminah (QRIS)', ref: 'r1' }), {
    envelope_id: 'e1', amount: 25000, description: 'Siti Aminah (QRIS)', source: 'webapp',
    transaction_date: '2026-10-26', receipt_item_id: 'i1', client_ref: 'r1' });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && node --test src/lib/proofFormat.test.js`
Expected: FAIL.

- [ ] **Step 3: Implement `proofFormat.js` dan `ProofCard.jsx`**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`
Expected: PASS, build sukses.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/proofFormat.js frontend/src/lib/proofFormat.test.js frontend/src/components/ProofCard.jsx
git commit -m "feat(web): kartu konfirmasi bukti bayar (ProofCard)"
```

---

### Task B5: Halaman `/bagikan`

**Files:**
- Create: `frontend/src/pages/Bagikan.jsx`
- Modify: `frontend/src/App.jsx` (route di dalam `<Route element={<Layout />}>`)
- Modify: `frontend/src/lib/shareInbox.js` + tes (fungsi murni alur halaman)

**Interfaces:**
- Consumes: B3 (`shareStore`, `nextToUpload`, `uploadFormFor`), B1 (`api.kotakUpload`, `api.kotakItem`, `api.kotakPending`), B4 (`ProofCard`), rencana kamera (`stageLabel` dengan `noun: 'bukti'`).
- Produces:
  - `shareInbox.uploadOutcome(res) → { action: 'done'|'keep'|'drop', item?: object, message?: string }` — `ok` → `done` dengan `item = res.data`; `status === 0`/`timedOut`/`>= 500`/`401` → `keep` (`message: 'Bukti belum terkirim. Akan dikirim lagi saat online.'`); 413/415/422 → `drop` dengan `message = res.data.detail`; 429 → `keep` dengan `message = res.data.detail`.
  - `shareInbox.needsPolling(item, startedAt, now) → boolean` — `item.status` ∈ `diterima|diproses` dan `now - startedAt < 30000`.
  - `Bagikan.jsx`: saat dibuka (dan saat event `online`): ambil entri lokal; bila `!navigator.onLine` → banner `'{n} bukti menunggu dikirim. Akan dikirim saat online.'`; selain itu unggah satu per satu (`uploadFormFor` + `api.kotakUpload` dengan progres `stageLabel(noun 'bukti')`), terapkan `uploadOutcome` (`done`/`drop` → `store.del(entry.id)`); item yang masih diproses dipantau `api.kotakItem` tiap 1500 ms sampai `needsPolling` false. Setelah antrean lokal habis, tampilkan juga `api.kotakPending()` (item siap lain) sebagai `ProofCard` bertumpuk (tanpa duplikat id). `?err=sw` → teks `'Buka Jatahku sekali, lalu bagikan lagi.'`; `?err=baca` → `'File yang dibagikan tidak bisa dibaca. Coba bagikan lagi.'`. Saklar `features.receipt_inbox` mati → `'Fitur ini segera hadir.'` (entri lokal tidak diunggah). Semua kartu selesai → tombol **Ke Transaksi**.

- [ ] **Step 1: Write the failing test**

```js
test('uploadOutcome: sukses, simpan untuk nanti, buang', () => {
  assert.equal(uploadOutcome({ ok: true, status: 201, data: { id: 'i1' } }).action, 'done');
  for (const r of [{ ok: false, status: 0, data: {} }, { ok: false, status: 503, data: {} }, { ok: false, status: 0, timedOut: true, data: {} }])
    assert.equal(uploadOutcome(r).action, 'keep');
  assert.deepEqual(uploadOutcome({ ok: false, status: 415, data: { detail: 'Kirim foto (JPG/PNG/WebP), PDF, atau teks' } }),
    { action: 'drop', message: 'Kirim foto (JPG/PNG/WebP), PDF, atau teks' });
  assert.equal(uploadOutcome({ ok: false, status: 429, data: { detail: 'Terlalu banyak bukti. Coba lagi sebentar.' } }).action, 'keep');
});

test('needsPolling: berhenti saat siap atau lewat 30 detik', () => {
  assert.equal(needsPolling({ status: 'diproses' }, 0, 29999), true);
  assert.equal(needsPolling({ status: 'diproses' }, 0, 30000), false);
  assert.equal(needsPolling({ status: 'siap' }, 0, 10), false);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && node --test src/lib/shareInbox.test.js`
Expected: FAIL (fungsi baru belum ada).

- [ ] **Step 3: Implement fungsi murni, `Bagikan.jsx`, dan route `<Route path="/bagikan" element={<Bagikan />} />`**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`
Expected: PASS, build sukses.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Bagikan.jsx frontend/src/App.jsx frontend/src/lib/shareInbox.js frontend/src/lib/shareInbox.test.js
git commit -m "feat(pwa): halaman Bagikan — unggah bukti yang dibagikan dan konfirmasi"
```

---

### Task B6: Banner bukti menunggu dan tips Settings

**Files:**
- Create: `frontend/src/components/PendingProofsBanner.jsx`
- Modify: `frontend/src/components/Layout.jsx` (render di samping `<OfflineQueueCenter />` ±baris 660)
- Modify: `frontend/src/pages/Settings.jsx`
- Modify: `frontend/src/lib/proofFormat.js` + tes (`pendingBannerText`)

**Interfaces:**
- Consumes: B1 (`api.kotakPending`), B3 (`shareStore`), `useAppConfig`.
- Produces:
  - `proofFormat.pendingBannerText({ unsent, ready }) → string|null` — `unsent > 0 && ready > 0` → `'{unsent} bukti menunggu dikirim, {ready} menunggu dicatat · Tinjau'`; hanya `unsent` → `'{unsent} bukti menunggu dikirim · Kirim'`; hanya `ready` → `'{ready} bukti menunggu dicatat · Tinjau'`; keduanya 0 → `null`.
  - `PendingProofsBanner` — tampil hanya bila `features.receipt_inbox`; hitung saat mount, saat event `online`, `jatahku:txn-added`, dan `visibilitychange` (terlihat); sembunyi di route `/bagikan`; ketuk → `navigate('/bagikan')`.
  - `Settings.jsx`: baris tips (di bagian bantuan/Telegram yang sudah ada): `'Bagikan bukti bayar ke Jatahku: di Android, pasang Jatahku dari browser lalu pilih Jatahku di menu Bagikan. Di iPhone, bagikan bukti ke bot Telegram Jatahku.'`; tampil hanya bila `features.receipt_inbox`.

- [ ] **Step 1: Write the failing test**

```js
test('pendingBannerText', () => {
  assert.equal(pendingBannerText({ unsent: 0, ready: 0 }), null);
  assert.equal(pendingBannerText({ unsent: 2, ready: 0 }), '2 bukti menunggu dikirim · Kirim');
  assert.equal(pendingBannerText({ unsent: 0, ready: 3 }), '3 bukti menunggu dicatat · Tinjau');
  assert.equal(pendingBannerText({ unsent: 1, ready: 2 }), '1 bukti menunggu dikirim, 2 menunggu dicatat · Tinjau');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && node --test src/lib/proofFormat.test.js`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`
Expected: PASS, build sukses.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PendingProofsBanner.jsx frontend/src/components/Layout.jsx frontend/src/pages/Settings.jsx frontend/src/lib/proofFormat.js frontend/src/lib/proofFormat.test.js
git commit -m "feat(web): banner bukti menunggu dan tips berbagi bukti"
```

---

### Selesai Bagian B: verifikasi dan PR

- [ ] `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build` → semua PASS; `git checkout -- frontend/dist`.
- [ ] Cek manual `npm run dev` (desktop, DevTools mode HP): form Catat → PDF transfer → baris terisi (keterangan, tanggal bayar, amplop disarankan) → Simpan; screenshot QRIS dari Galeri → baris bukti; `/bagikan?err=sw` dan `?err=baca` menampilkan pesan; banner muncul setelah membuat item lewat bot.
- [ ] `docs/kotak-struk.md`: bagian PWA (share target, IndexedDB `jatahku-share`, halaman `/bagikan`, banner) dan aturan nginx:

  ```nginx
  location = /bagikan {
      if ($request_method = POST) { return 303 /bagikan?err=sw; }
      try_files /app.html =404;
  }
  ```

  ```bash
  git add docs/kotak-struk.md
  git commit -m "docs(kotak): PWA share target dan aturan nginx"
  ```

- [ ] `git fetch origin main && git rebase origin/main`, push `feat/bagikan-ke-jatahku-web`, buka PR. Deskripsi memuat ringkasan, langkah server (pasang aturan nginx di template HestiaCP jatahku.com lalu `nginx -t && systemctl reload nginx`), dan checklist uji HP dari spec bagian 7c: PWA terpasang di Android Chrome (share dari beberapa aplikasi bank dan e-wallet, saat belum login, saat offline), bot Telegram di Android dan iPhone, chat bot web, PDF dari tombol PDF di desktop, screenshot QRIS dari Galeri.
- [ ] Setelah merge dan saklar `receipt_inbox` aktif: perbarui `docs/mobile/PROGRESS.md` (FS-1 selesai) dan Project doc `claude/scan-struk-keputusan.md`.
