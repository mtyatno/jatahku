"""Kotak Struk tahap 2 — donasi contoh (spec 2026-11-01 §10 Tahap 2 butir 1; pre-flight A16 §2, K1, G1, G4).

M1a: saklar `features.kotak_donasi`, persetujuan opt-in (`GET/PUT /user/kotak-donasi`), dan lupa (tarik persetujuan,
hapus akun, gabung akun). M1b: `samaran` (penyamaran nomor dipindah dari `kotak_corpus`, nama samaran), baris tersamar
`donasi.sample_lines`, dan penangkapannya di worker hanya untuk user yang setuju saat saklar menyala (pre-flight A16 §2,
K2, K5, G6). Route asli lewat httpx ASGITransport di atas SQLite in-memory; butuh `aiosqlite`.
Semua nama, nomor, dan baris di sini karangan.
Run: python -m unittest app.tests.test_kotak_donasi -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import inspect
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import configure_mappers

from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.models.models import (
    AppSetting, Household, HouseholdMember, HouseholdRole, ProofSample, ProofSampleConsent, ReceiptScan, User,
)
from app.services.kotak_struk import config as K
from app.services.kotak_struk.extract import TextDoc
from app.services.kotak_struk.readers.base import ParseContext, Secrets

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
T0 = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
LINES = ["gopay", "Pembayaran Berhasil", "Ke TOKO CONTOH", "Total Rp12.500"]   # karangan, sudah tersamar
REPO_ROOT = Path(__file__).resolve().parents[2]
SWEEP = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "sweep_lines.json").read_text())
SWEEP_TAGS = ("proof", "probe", "failed", "pending")
INVENTED_USER = "Rina Wulandari"   # nama user karangan untuk daftar sapuan tanpa nama user
# Bukti GoPay karangan: pihak lawan (RUDI HARTONO), rekening, nomor referensi, dan nama user sebagai sumber dana.
GOPAY_LINES = ["GoPay", "Transfer Berhasil", "Ditransfer ke", "RUDI HARTONO", "Mandiri 1234567890", "Jumlah Kirim Uang",
               "Rp10.000", "Tanggal 31 Okt 2026", "No. Ref 123456789012", "Sumber Dana", "Rina Wulandari"]
STORE_LINES = ["ALFAMART", "14-10-2026 08:15", "ROTI 1 15.000", "SUSU 2 30.400", "Total Belanja 45.400",
               "Non Tunai (QRIS) 45.400"]
PSEUDONYM_WORDS = {"andi", "pratama", "budi", "santoso", "siti", "aminah", "toko", "contoh"}


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class DonasiBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from app.api.routes import user_settings
        asyncio.get_running_loop().slow_callback_duration = 2.0
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        # Resep SQLAlchemy untuk pysqlite: SAVEPOINT butuh BEGIN eksplisit.
        event.listen(self.engine.sync_engine, "connect", lambda conn, _rec: setattr(conn, "isolation_level", None))
        event.listen(self.engine.sync_engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.Session() as db:
            self.user = User(name="Rina Wulandari")
            self.other = User(name="Dodi Prakoso")
            self.admin = User(name="Pemilik Tes", is_admin=True)
            db.add_all([self.user, self.other, self.admin])
            await db.commit()
        self.current = self.user

        app = FastAPI()
        app.include_router(user_settings.router, prefix="/user")
        app.dependency_overrides[get_current_user] = lambda: self.current

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        self.app = app
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    # ── pembantu ──────────────────────────────────────────────────────────
    async def flag(self, **features):
        async with self.Session() as db:
            row = await db.get(AppSetting, "app_config")
            value = json.dumps({"features": {name: {"web": on} for name, on in features.items()}})
            if row is None:
                db.add(AppSetting(key="app_config", value=value))
            else:
                row.value = value
            await db.commit()

    async def add_samples(self, user, *, statuses=("menunggu", "disetujui")):
        """Item dengan `sample_lines` dan sampel per status untuk `user` (karangan)."""
        async with self.Session() as db:
            item = ReceiptScan(user_id=user.id, status=K.ST_SIAP, doc_type="qris", sample_lines=list(LINES))
            done = ReceiptScan(user_id=user.id, status=K.ST_TERCATAT, doc_type="transfer")
            db.add_all([item, done])
            await db.flush()
            for st in statuses:
                db.add(ProofSample(user_id=user.id, item_id=uuid.uuid4(), rule_key="gopay", doc_type="qris",
                                   trigger="nominal", lines=list(LINES), user_name="ANDI PRATAMA",
                                   truth={"total": 12500, "date": "2026-11-01", "flow": None, "app": None},
                                   today=date(2026, 11, 2), status=st, created_at=T0,
                                   decided_at=T0 if st != "menunggu" else None,
                                   decided_by=self.admin.id if st != "menunggu" else None))
            db.add(ProofSampleConsent(user_id=user.id, consented_at=T0))
            await db.commit()
            return item.id, done.id

    async def count(self, model, *where):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar()

    async def sql_null_sample_lines(self, item_id):
        async with self.Session() as db:
            return (await db.execute(text("SELECT sample_lines IS NULL FROM receipt_scans WHERE id = :i"),
                                     {"i": item_id.hex})).scalar()


class ConsentApiTests(DonasiBase):
    async def test_consent_roundtrip_and_flag(self):
        await self.flag(kotak_donasi=False)
        r = await self.client.get("/user/kotak-donasi")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"available": False, "consented": False, "consented_at": None})
        res = await self.client.put("/user/kotak-donasi", json={"consented": True})
        self.assertEqual((res.status_code, res.json()["detail"]), (409, "Donasi contoh belum dibuka"))
        self.assertEqual(await self.count(ProofSampleConsent), 0)
        await self.flag(kotak_donasi=True)
        r = await self.client.put("/user/kotak-donasi", json={"consented": True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["available"], r.json()["consented"]), (True, True))
        self.assertIsNotNone(r.json()["consented_at"])
        got = (await self.client.get("/user/kotak-donasi")).json()
        self.assertEqual(got, r.json())
        # Persetujuan milik user ini saja.
        self.current = self.other
        self.assertEqual((await self.client.get("/user/kotak-donasi")).json(),
                         {"available": True, "consented": False, "consented_at": None})

    async def test_flag_is_off_by_default(self):
        self.assertEqual((await self.client.get("/user/kotak-donasi")).json()["available"], False)
        self.assertEqual((await self.client.put("/user/kotak-donasi", json={"consented": True})).status_code, 409)

    async def test_consent_twice_keeps_first_time(self):
        from app.services.kotak_struk import donasi
        await self.flag(kotak_donasi=True)
        async with self.Session() as db:
            first = await donasi.set_consent(db, self.user.id, True, now=T0)
            await db.commit()
        async with self.Session() as db:
            again = await donasi.set_consent(db, self.user.id, True, now=T0 + timedelta(days=3))
            await db.commit()
        self.assertEqual(first.replace(tzinfo=None), T0.replace(tzinfo=None))
        self.assertEqual(again.replace(tzinfo=None), T0.replace(tzinfo=None))
        r = await self.client.put("/user/kotak-donasi", json={"consented": True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["consented_at"].startswith("2026-11-02T03:00"))
        self.assertEqual(await self.count(ProofSampleConsent), 1)

    async def test_withdraw_deletes_samples(self):          # Review Focus 1, G4
        await self.flag(kotak_donasi=True)
        item, done = await self.add_samples(self.user)
        other_item, _ = await self.add_samples(self.other)
        r = await self.client.put("/user/kotak-donasi", json={"consented": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"available": True, "consented": False, "consented_at": None})
        # Semua sampel user (menunggu DAN disetujui), persetujuannya, dan baris di itemnya hilang (SQL NULL).
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.user.id), 0)
        self.assertEqual(await self.count(ProofSampleConsent, ProofSampleConsent.user_id == self.user.id), 0)
        self.assertTrue(await self.sql_null_sample_lines(item))
        self.assertTrue(await self.sql_null_sample_lines(done))
        # Item tetap ada, statusnya tidak berubah.
        async with self.Session() as db:
            self.assertEqual((await db.get(ReceiptScan, item)).status, K.ST_SIAP)
        # User lain utuh.
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.other.id), 2)
        self.assertEqual(await self.count(ProofSampleConsent, ProofSampleConsent.user_id == self.other.id), 1)
        self.assertFalse(await self.sql_null_sample_lines(other_item))

    async def test_withdraw_allowed_with_flag_off(self):
        await self.flag(kotak_donasi=False)
        item, _ = await self.add_samples(self.user)
        self.assertEqual((await self.client.get("/user/kotak-donasi")).json()["consented"], True)
        r = await self.client.put("/user/kotak-donasi", json={"consented": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"available": False, "consented": False, "consented_at": None})
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.user.id), 0)
        self.assertTrue(await self.sql_null_sample_lines(item))
        # Menarik tanpa persetujuan sebelumnya juga boleh (idempoten).
        self.assertEqual((await self.client.put("/user/kotak-donasi", json={"consented": False})).status_code, 200)

    async def test_put_rejects_extra_fields(self):
        await self.flag(kotak_donasi=True)
        for body in ({"consented": True, "user_id": str(self.other.id)}, {"consented": True, "consented_at": "x"},
                     {}, {"consented": "ya"}, {"consented": None}):
            with self.subTest(body=body):
                self.assertEqual((await self.client.put("/user/kotak-donasi", json=body)).status_code, 422)
        self.assertEqual(await self.count(ProofSampleConsent), 0)

    async def test_requires_login(self):
        del self.app.dependency_overrides[get_current_user]
        self.assertIn((await self.client.get("/user/kotak-donasi")).status_code, (401, 403))
        self.assertIn((await self.client.put("/user/kotak-donasi", json={"consented": False})).status_code, (401, 403))

    async def test_routes_have_response_model(self):
        from fastapi.routing import APIRoute
        routes = {(m, r.path): r for r in self.app.routes if isinstance(r, APIRoute) for m in r.methods}
        for key in (("GET", "/user/kotak-donasi"), ("PUT", "/user/kotak-donasi")):
            with self.subTest(key):
                self.assertEqual(routes[key].response_model.__name__, "KotakDonasiOut")


class DonasiServiceTests(DonasiBase):
    async def test_available_follows_flag(self):
        from app.services.kotak_struk import donasi
        async with self.Session() as db:
            self.assertFalse(await donasi.donation_available(db))
        await self.flag(kotak_donasi=True)
        async with self.Session() as db:
            self.assertTrue(await donasi.donation_available(db))
        await self.flag(receipt_inbox=True)   # saklar lain tidak membuka donasi
        async with self.Session() as db:
            self.assertFalse(await donasi.donation_available(db))

    async def test_set_consent_and_forget_never_commit(self):
        from app.services.kotak_struk import donasi
        async with self.Session() as db:
            await donasi.set_consent(db, self.user.id, True, now=T0)
            self.assertTrue(await donasi.consented(db, self.user.id))
            await db.rollback()
        self.assertEqual(await self.count(ProofSampleConsent), 0)
        item, _ = await self.add_samples(self.user)
        async with self.Session() as db:
            self.assertIsNone(await donasi.set_consent(db, self.user.id, False, now=T0))
            await db.rollback()
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.user.id), 2)
        self.assertFalse(await self.sql_null_sample_lines(item))
        async with self.Session() as db:
            await donasi.forget_user(db, self.user.id)
            await db.rollback()
        self.assertEqual(await self.count(ProofSampleConsent), 1)

    async def test_set_consent_off_forgets_everything(self):
        from app.services.kotak_struk import donasi
        item, _ = await self.add_samples(self.user, statuses=("menunggu", "disetujui", "ditolak"))
        async with self.Session() as db:
            self.assertIsNone(await donasi.set_consent(db, self.user.id, False, now=T0))
            self.assertFalse(await donasi.consented(db, self.user.id))
            await db.commit()
        self.assertEqual(await self.count(ProofSample), 0)
        self.assertTrue(await self.sql_null_sample_lines(item))

    async def test_forget_user_only_touches_that_user(self):
        from app.services.kotak_struk import donasi
        item, _ = await self.add_samples(self.user)
        other_item, _ = await self.add_samples(self.other)
        async with self.Session() as db:
            await donasi.forget_user(db, self.user.id)
            await db.commit()
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.user.id), 0)
        self.assertEqual(await self.count(ProofSampleConsent, ProofSampleConsent.user_id == self.user.id), 0)
        self.assertTrue(await self.sql_null_sample_lines(item))
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.other.id), 2)
        self.assertFalse(await self.sql_null_sample_lines(other_item))

    async def test_one_sample_per_item(self):
        from sqlalchemy.exc import IntegrityError
        item_id = uuid.uuid4()
        async with self.Session() as db:
            for _ in range(2):
                db.add(ProofSample(user_id=self.user.id, item_id=item_id, doc_type="qris", trigger="nominal",
                                   lines=list(LINES), today=date(2026, 11, 2), status="menunggu"))
            with self.assertRaises(IntegrityError):
                await db.commit()
        async with self.Session() as db:   # item_id NULL boleh berulang
            for _ in range(2):
                db.add(ProofSample(user_id=self.user.id, item_id=None, doc_type="qris", trigger="nominal",
                                   lines=list(LINES), today=date(2026, 11, 2), status="menunggu"))
            await db.commit()
        self.assertEqual(await self.count(ProofSample), 2)


class MergeDonationTests(DonasiBase):
    async def test_merge_users_drops_source_donation(self):          # G4: persetujuan tidak diwariskan
        from app.services.merge import merge_users
        async with self.Session() as db:
            hh_src, hh_tgt = Household(name="Rumah A"), Household(name="Rumah B")
            db.add_all([hh_src, hh_tgt])
            await db.flush()
            db.add_all([HouseholdMember(user_id=self.user.id, household_id=hh_src.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=self.other.id, household_id=hh_tgt.id, role=HouseholdRole.owner)])
            await db.commit()
        await self.add_samples(self.user)
        async with self.Session() as db:
            result = await merge_users(self.user.id, self.other.id, hh_tgt.id, db)
        self.assertEqual(result["status"], "merged")
        self.assertEqual(await self.count(ProofSample), 0)
        self.assertEqual(await self.count(ProofSampleConsent), 0)   # target tidak mewarisi persetujuan source

    async def test_merge_moves_decided_by_to_target(self):
        """Sampel milik user ketiga yang diputuskan source (admin) tetap ada; jejak keputusannya pindah ke target, sama
        dengan `ProofRule.decided_by` (merge.py langkah 7c/7d)."""
        from app.services.merge import merge_users
        async with self.Session() as db:
            hh_src, hh_tgt = Household(name="Rumah A"), Household(name="Rumah B")
            db.add_all([hh_src, hh_tgt])
            await db.flush()
            db.add_all([HouseholdMember(user_id=self.user.id, household_id=hh_src.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=self.other.id, household_id=hh_tgt.id, role=HouseholdRole.owner)])
            await db.commit()
        third = User(name="Citra Lestari")
        async with self.Session() as db:
            db.add(third)
            await db.flush()
            mine = ProofSample(user_id=third.id, item_id=uuid.uuid4(), doc_type="qris", trigger="nominal",
                               lines=list(LINES), today=date(2026, 11, 2), status="disetujui", decided_at=T0,
                               decided_by=self.user.id)
            theirs = ProofSample(user_id=third.id, item_id=uuid.uuid4(), doc_type="transfer", trigger="tanggal",
                                 lines=list(LINES), today=date(2026, 11, 2), status="disetujui", decided_at=T0,
                                 decided_by=self.admin.id)
            db.add_all([mine, theirs])
            await db.commit()
        async with self.Session() as db:
            result = await merge_users(self.user.id, self.other.id, hh_tgt.id, db)
        self.assertEqual(result["status"], "merged")
        async with self.Session() as db:
            got = {s.id: s.decided_by for s in (await db.execute(select(ProofSample))).scalars()}
        self.assertEqual(got, {mine.id: self.other.id, theirs.id: self.admin.id})

    async def test_merge_keeps_target_choice(self):
        from app.services.merge import merge_users
        async with self.Session() as db:
            hh_src, hh_tgt = Household(name="Rumah A"), Household(name="Rumah B")
            db.add_all([hh_src, hh_tgt])
            await db.flush()
            db.add_all([HouseholdMember(user_id=self.user.id, household_id=hh_src.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=self.other.id, household_id=hh_tgt.id, role=HouseholdRole.owner)])
            await db.commit()
        await self.add_samples(self.user)
        target_item, _ = await self.add_samples(self.other, statuses=("menunggu",))
        async with self.Session() as db:
            await merge_users(self.user.id, self.other.id, hh_tgt.id, db)
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.other.id), 1)
        self.assertEqual(await self.count(ProofSampleConsent, ProofSampleConsent.user_id == self.other.id), 1)
        self.assertFalse(await self.sql_null_sample_lines(target_item))


# ── M1b: samaran, baris tersamar, worker ─────────────────────────────────────

class SamaranTests(unittest.TestCase):
    def test_mask_line_moved_without_change(self):
        from app.scripts import kotak_corpus
        from app.services.kotak_struk import samaran
        # Satu fungsi yang sama (diekspor ulang), bukan salinan: MaskLineTests/NeedsReviewTests `test_kotak_corpus` yang
        # tidak diubah menguji fungsi ini.
        self.assertIs(kotak_corpus.mask_line, samaran.mask_line)
        self.assertIs(kotak_corpus.needs_review, samaran.needs_review)
        self.assertEqual(kotak_corpus.MIN_RUN_DIGITS, samaran.MIN_RUN_DIGITS)
        script = inspect.getsource(kotak_corpus)
        for name in ("def mask_line", "def needs_review", "def _kept_spans", "_DIGIT_RUN = ", "MIN_RUN_DIGITS = "):
            self.assertNotIn(name, script)
        self.assertEqual(samaran.mask_line("Rekening Tujuan 0123 0100 1234 567 Rp150.000 26/10/2026 09:30"),
                         "Rekening Tujuan …4567 Rp150.000 26/10/2026 09:30")
        self.assertTrue(samaran.needs_review("Ref …5678 …1234"))

    def test_samaran_is_pure(self):
        from app.services.kotak_struk import samaran
        source = inspect.getsource(samaran)
        self.assertFalse("os.environ" in source, "samaran tidak boleh menyentuh os.environ")
        self.assertNotRegex(source, r"(?m)^(?:from|import) (?!__future__|re\b)")
        # Dapat diimpor tanpa DATABASE_URL/JWT_SECRET (tanpa konfigurasi aplikasi).
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "JWT_SECRET")}
        out = subprocess.run([sys.executable, "-c", "import app.services.kotak_struk.samaran as s; print(s.mask_line('x'))"],
                             cwd=REPO_ROOT, env=env, capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "x"), out.stderr)

    def test_normalize_matches_merchants(self):
        from app.services.kotak_struk import samaran
        from app.services.kotak_struk.merchants import normalize_name
        for s in ("P.T. Sinar", "BUDI-SANTOSO", "  Rina   Wulandari ", "Toko_Maju 12", "Café Ñusa", "", None, "O'Neil & Co."):
            self.assertEqual(samaran._normalize(s), normalize_name(s), s)

    def test_pseudonymise_roles_case_and_whole_words(self):
        from app.services.kotak_struk.samaran import PSEUDONYMS, pseudonymise
        self.assertEqual(PSEUDONYMS, {"user": "ANDI PRATAMA", "pihak": "BUDI SANTOSO", "pengirim": "SITI AMINAH",
                                      "merchant": "TOKO CONTOH"})
        lines = ["Ke RUDI HARTONO", "Penerima: Rudi Hartono", "rudi hartono", "Ke:RUDI,", "RUDIMAN HARTONOWATI",
                 "Dari Dewi Lestari", "Merchant WARUNG SEDAP", "Rina Wulandari", "Rudi123"]
        out, user = pseudonymise(lines, {"pihak": "RUDI HARTONO", "pengirim": "Dewi Lestari",
                                         "merchant": "Warung Sedap", "user": "Rina Wulandari"})
        self.assertEqual(out, ["Ke BUDI SANTOSO", "Penerima: Budi Santoso", "budi santoso", "Ke:BUDI,",
                               "RUDIMAN HARTONOWATI", "Dari Siti Aminah", "Merchant TOKO CONTOH", "Andi Pratama",
                               "Budi123"])
        self.assertEqual(user, "Andi Pratama")

    def test_pseudonymise_long_names_punctuation_and_missing(self):
        from app.services.kotak_struk.samaran import pseudonymise
        out, user = pseudonymise(["RUDI HARTONO WIJAYA KUSUMA", "R.U.D.I.", "Rudi-Hartono", "RUDIHARTONO", "A B"],
                                 {"pihak": "Rudi-Hartono Wijaya Kusuma", "pengirim": None, "user": "A"})
        self.assertEqual(out, ["BUDI SANTOSO SANTOSO SANTOSO", "BUDI.", "Budi-Santoso", "BUDI", "A B"])
        self.assertIsNone(user)   # nama satu huruf bukan kata nama
        self.assertEqual(pseudonymise(["Ke RUDI"], {}), (["Ke RUDI"], None))
        self.assertEqual(pseudonymise([], {"user": "rina wulandari putri"}), ([], "andi pratama pratama"))
        # Satu kata di dua nama: peran pihak lawan menang (urutan ROLES).
        self.assertEqual(pseudonymise(["Ke Rudi"], {"user": "Rudi Hartono", "pihak": "Rudi"})[0], ["Ke Budi"])


# Kata yang tidak dihitung sebagai kata nama pada tebakan pihak lawan bukti yang tak terbaca: HANYA kosakata label/status
# (`LABEL_WORDS | _TITLE_EXTRA`), bukan seluruh `TITLE_WORDS` (kata penyedia/logo seperti "mega", "jago" bisa nama orang;
# review M1b temuan 1). Dihitung di sini, tidak memakai `donasi._VOCAB_WORDS`.
def _label_status_words() -> frozenset[str]:
    from app.services.kotak_struk import kerangka
    return kerangka.LABEL_WORDS | frozenset(kerangka._TITLE_EXTRA.split())


def _known_name_words(lines, doc, user_name) -> set[str]:
    """Kata nama yang dikenal untuk satu bukti, dihitung terpisah dari `donasi`: pihak lawan (bukti yang tidak dibaca
    pembaca QRIS/transfer: tebakan yang semua katanya `kerangka.TITLE_WORDS` bukan nama; selain itu semua kata kecuali
    kosakata label/status), pengirim tercetak, merchant berlabel, user. Kata nama samaran (publik) tidak dihitung."""
    from app.services.kotak_struk import kerangka
    from app.services.kotak_struk.merchants import normalize_name
    from app.services.kotak_struk.readers import proof_common as pc
    clean = pc.clean_lines(lines)
    profile = kerangka._profile_of(doc, clean)
    party = doc.counterparty.name
    party_words = normalize_name(party).split()
    if doc.doc_type not in K.PROOF_TYPES:
        raw = [kerangka.words(w)[0] for w in (party or "").split() if kerangka.words(w)]
        if all(w in kerangka.TITLE_WORDS for w in raw):
            party_words = []
        else:
            keep = [w for w in (party or "").split() if kerangka.words(w)
                    and kerangka.words(w)[0] not in _label_status_words()]
            party_words = normalize_name(" ".join(keep)).split()
    names = [pc.read_sender_name(clean, profile), pc.read_name(pc.body_lines(clean), profile, "merchant"), user_name]
    words = set(party_words) | {w for name in names for w in normalize_name(name).split()}
    return {w for w in words if sum(c.isalpha() for c in w) >= 2} - PSEUDONYM_WORDS


async def _sweep_cases():
    """Setiap daftar sapuan bertanda proof/probe/failed/pending, saklar bukti mati dan menyala, dibaca seperti worker
    (tanggal tetap, tanpa aturan) dengan nama user daftar itu atau nama karangan."""
    from app.services.kotak_struk.registry import read_document
    for item in SWEEP:
        if not set(SWEEP_TAGS) & set(item["tags"]):
            continue
        user_name = item["user_name"] or INVENTED_USER
        for proofs in (False, True):
            text = TextDoc(lines=list(item["lines"]), kind="image")
            res = await read_document(text, ParseContext(today=date(2026, 11, 1), user_name=user_name),
                                      proofs_enabled=proofs)
            yield item["id"], proofs, item["lines"], res.parsed.doc, res.parsed.secrets, user_name


class SampleLinesTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, lines, proofs=True, user_name=INVENTED_USER):
        from app.services.kotak_struk.registry import read_document
        res = await read_document(TextDoc(lines=list(lines), kind="image"),
                                  ParseContext(today=date(2026, 11, 1), user_name=user_name), proofs_enabled=proofs)
        return res.parsed.doc, res.parsed.secrets

    async def test_samples_hold_no_long_digits_or_known_names(self):   # Review Focus 2
        from app.services.kotak_struk.donasi import sample_lines
        from app.services.kotak_struk.merchants import normalize_name
        cases = with_sample = 0
        async for case_id, proofs, lines, doc, secrets, user_name in _sweep_cases():
            cases += 1
            got = sample_lines(lines, doc, secrets, user_name=user_name)
            with_sample += bool(got)
            dumped = "\n".join(got or [])
            with self.subTest(case=case_id, proofs=proofs):
                self.assertNotRegex(dumped, r"\d{6,}")
                for value in (*secrets.ref_values, secrets.account_number, secrets.nmid):
                    if value and len(value) >= 4:
                        self.assertNotIn(value.lower(), dumped.lower())
                words = normalize_name(dumped).split()
                for word in _known_name_words(lines, doc, user_name):
                    self.assertNotIn(word, words)
                    self.assertNotRegex(dumped.lower(), rf"(?<![^\W\d_]){re.escape(word)}(?![^\W\d_])")
                self.assertLessEqual(len(got or []), K.SAMPLE_MAX_LINES)
                self.assertTrue(all(len(line) <= K.SAMPLE_LINE_MAX for line in got or []))
        self.assertGreater(cases, 600)              # 330 daftar x 2 posisi saklar
        self.assertGreater(with_sample, cases * 0.9)   # hampir semua bukti menghasilkan baris

    async def test_store_receipt_has_no_sample(self):
        # G6: struk belanja biasa tidak pernah (jenis `struk_belanja` dan teksnya tidak tampak bukti bayar). Daftar sapuan
        # bertanda store yang terbaca QRIS, atau struk yang tampak bukti, diperlakukan seperti bukti (sama dengan worker).
        from app.scripts.kotak_corpus import receipt_samples
        from app.services.kotak_struk.donasi import sample_lines
        from app.services.kotak_struk.registry import looks_like_proof
        always = [STORE_LINES] + [s["lines"] for s in receipt_samples()]
        stores = always + [i["lines"] for i in SWEEP if set(i["tags"]) & {"store", "store_void", "store_pending"}]
        plain = 0
        for n, lines in enumerate(stores):
            for proofs in (False, True):
                doc, secrets = await self.read(lines, proofs)
                text = TextDoc(lines=list(lines), kind="image")
                if n < len(always):
                    self.assertEqual(doc.doc_type, "struk_belanja")
                    self.assertFalse(looks_like_proof(text))
                if doc.doc_type != "struk_belanja" or looks_like_proof(text):
                    continue
                plain += 1
                with self.subTest(first=lines[0], proofs=proofs):
                    self.assertIsNone(sample_lines(lines, doc, secrets, user_name=INVENTED_USER))
        self.assertGreater(plain, 300)

    async def test_sample_masks_numbers_and_names(self):
        from app.services.kotak_struk.donasi import sample_lines
        for proofs in (True, False):   # pembaca transfer, dan bukti yang dibaca pembaca struk/tidak dikenali
            doc, secrets = await self.read(GOPAY_LINES, proofs)
            got = sample_lines(GOPAY_LINES, doc, secrets, user_name=INVENTED_USER)
            with self.subTest(proofs=proofs, doc_type=doc.doc_type):
                self.assertIn("Transfer Berhasil", got)   # judul status bukan nama: tetap
                self.assertIn("Mandiri …7890", got)
                self.assertIn("No. Ref …9012", got)
                self.assertIn("Rp10.000", got)
                self.assertIn("Tanggal 31 Okt 2026", got)
                dumped = "\n".join(got).lower()
                for word in ("rudi", "hartono", "rina", "wulandari", "1234567890", "123456789012"):
                    self.assertNotIn(word, dumped)

    async def test_unread_proof_title_words_are_not_names(self):
        # Saklar mati: pembaca struk "membaca" judul status sebagai nama merchant; kata itu bukan nama.
        from app.services.kotak_struk.donasi import sample_lines
        lines = ["Transfer Berhasil", "Ke RUDI 0812 3456 7890", "Nominal Rp150.000", "Total Rp150.000"]
        doc, secrets = await self.read(lines, proofs=False)
        self.assertEqual((doc.doc_type, doc.counterparty.name), ("struk_belanja", "Transfer Berhasil"))
        got = sample_lines(lines, doc, secrets, user_name=None)
        self.assertEqual(got, ["Transfer Berhasil", "Ke TOKO …7890", "Nominal Rp150.000", "Total Rp150.000"])

    def test_known_name_helper_has_no_provider_exemption(self):
        # Helper Review Focus 2 bukan tautologi: kata penyedia/logo yang juga nama orang TIDAK dikecualikan.
        from app.services.kotak_struk import kerangka
        from app.services.kotak_struk.document import Counterparty, DokumenBayar
        provider_names = {"mega", "neo", "jago", "mandiri", "permata", "jenius", "blu", "allo"}
        self.assertTrue(provider_names <= kerangka.TITLE_WORDS)
        self.assertFalse(provider_names & _label_status_words())
        doc = DokumenBayar(doc_type="struk_belanja", counterparty=Counterparty(name="Mega Lestari"))
        self.assertEqual(_known_name_words(["MEGA LESTARI"], doc, None), {"mega", "lestari"})
        doc = DokumenBayar(doc_type="struk_belanja", counterparty=Counterparty(name="Jago Neo"))
        self.assertEqual(_known_name_words(["Jago Neo"], doc, None), set())   # semua kata judul: bukan nama

    async def test_title_word_next_to_name_is_pseudonymised(self):
        # Review M1b temuan 1: "Mega" (kata penyedia) di samping kata nama tetap disamarkan.
        from app.services.kotak_struk.donasi import sample_lines
        lines = ["MEGA LESTARI", "Transfer Berhasil", "Rp50.000", "Total Rp50.000"]
        for proofs in (False, True):
            doc, secrets = await self.read(lines, proofs, user_name=None)
            got = sample_lines(lines, doc, secrets, user_name=None)
            with self.subTest(proofs=proofs, doc_type=doc.doc_type, name=doc.counterparty.name):
                self.assertTrue(got)
                dumped = "\n".join(got).lower()
                self.assertNotIn("mega", dumped)
                self.assertNotIn("lestari", dumped)
                self.assertIn("Transfer Berhasil", got)

    async def test_sender_who_is_not_the_user_is_pseudonymised(self):
        # Review M1b temuan 4: pengirim tercetak (bukan user) memakai nama samaran pengirim.
        from app.services.kotak_struk.donasi import sample_lines
        lines = ["GoPay", "Transfer Berhasil", "Ditransfer ke", "RUDI HARTONO", "Jumlah Kirim Uang", "Rp10.000",
                 "Tanggal 31 Okt 2026", "Sumber Dana", "DEWI LESTARI"]
        doc, secrets = await self.read(lines, True, user_name=INVENTED_USER)
        self.assertEqual(doc.doc_type, "transfer")
        got = sample_lines(lines, doc, secrets, user_name=INVENTED_USER)
        self.assertIn("SITI AMINAH", got)
        self.assertIn("BUDI SANTOSO", got)
        self.assertNotIn("dewi", "\n".join(got).lower())
        self.assertNotIn("lestari", "\n".join(got).lower())

    def test_email_and_grouped_account_lines_dropped(self):
        # Review M1b temuan 2 dan 3 (M1d memakai aturan yang sama saat menyetujui).
        from app.services.kotak_struk.document import Counterparty, DokumenBayar
        from app.services.kotak_struk.donasi import sample_lines
        doc = DokumenBayar(doc_type="transfer", counterparty=Counterparty(name=None))
        lines = ["Transfer Berhasil", "Email fajar.nugroho88@contoh.co.id", "rinawulandari99@contoh.com",
                 "Rek 1.234.567.890", "Rek 1-234-567-890 BCA", "Nominal Rp 1.234.567", "Total IDR 1.234.567.890,00",
                 "Biaya 2.500", "1.500.000,00"]
        self.assertEqual(sample_lines(lines, doc, Secrets(), user_name=None),
                         ["Transfer Berhasil", "Rek …7890 BCA", "Nominal Rp 1.234.567", "Total IDR 1.234.567.890,00",
                          "Biaya 2.500", "1.500.000,00"])

    def test_secret_and_long_digit_lines_dropped_and_capped(self):
        from app.services.kotak_struk.document import Counterparty, DokumenBayar
        from app.services.kotak_struk.donasi import sample_lines
        doc = DokumenBayar(doc_type="transfer", counterparty=Counterparty(name=None))
        secrets = Secrets(ref_values=["A1B2C3D4E5"], account_number="98AB76CD", nmid="ID1234567890123")
        lines = ["Transfer Berhasil", "Ref A1B2C3D4E5", "Rekening 98ab76cd", "Total Rp150000", "Total Rp150.000",
                 "NMID ID1234567890123", "Merchant ID1234567890123"]
        self.assertEqual(sample_lines(lines, doc, secrets, user_name=None),
                         ["Transfer Berhasil", "Total Rp150.000", "Merchant ID…0123"])
        many = ["Transfer Berhasil"] + [f"Baris {'x' * 300}"] + [f"Catatan {n}" for n in range(200)]
        got = sample_lines(many, doc, Secrets(), user_name=None)
        self.assertEqual(len(got), K.SAMPLE_MAX_LINES)
        self.assertEqual(len(got[1]), K.SAMPLE_LINE_MAX)
        # Tidak ada baris tersisa: None, bukan daftar kosong.
        self.assertIsNone(sample_lines(["Ref A1B2C3D4E5"], doc, secrets, user_name=None))


class WorkerDonationTests(DonasiBase):
    """Penangkapan di worker: hanya saklar `kotak_donasi` menyala DAN user setuju (Review Focus 1)."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        from app.api.routes import kotak_struk
        self.app.include_router(kotak_struk.router, prefix="/kotak-struk")
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    async def set_consent(self, on: bool):
        async with self.Session() as db:
            row = await db.get(ProofSampleConsent, self.user.id)
            if on and row is None:
                db.add(ProofSampleConsent(user_id=self.user.id, consented_at=T0))
            elif not on and row is not None:
                await db.delete(row)
            await db.commit()

    async def process(self, lines, *, flag: bool, consent: bool, **kw):
        from app.services.kotak_struk.worker import process_item
        await self.flag(kotak_donasi=flag)
        await self.set_consent(consent)
        item_id = uuid.uuid4()
        path = Path(self.dir) / item_id.hex
        path.write_bytes(b"\xff\xd8\xff\xe0jpeg")
        async with self.Session() as db:
            db.add(ReceiptScan(id=item_id, user_id=self.user.id, status=K.ST_DITERIMA, source="telegram",
                               file_path=str(path), content_type="image/jpeg", file_sha256=item_id.hex * 2))
            await db.commit()
        extract = AsyncMock(return_value=TextDoc(lines=list(lines), kind="image"))
        status = await process_item(item_id, session_factory=self.Session, extract=extract, now=T0,
                                    proofs_enabled=True, **kw)
        async with self.Session() as db:
            item = await db.get(ReceiptScan, item_id)
        return status, item

    async def test_donation_requires_consent_and_flag(self):      # Review Focus 1
        from app.services.kotak_struk.view import item_detail
        for flag, consent in ((False, True), (True, False), (False, False)):
            with self.subTest(flag=flag, consent=consent):
                status, item = await self.process(GOPAY_LINES, flag=flag, consent=consent)
                self.assertEqual(status, "siap")
                self.assertIsNone(item.sample_lines)
                self.assertTrue(await self.sql_null_sample_lines(item.id))   # SQL NULL, bukan JSON 'null'
                self.assertIsNotNone(item.layout)   # kerangka tetap seperti biasa
        status, item = await self.process(GOPAY_LINES, flag=True, consent=True)
        self.assertEqual(status, "siap")
        self.assertIn("BUDI SANTOSO", item.sample_lines)
        dumped = "\n".join(item.sample_lines).lower()
        for word in ("rudi", "hartono", "rina", "wulandari", "1234567890", "123456789012"):
            self.assertNotIn(word, dumped)
        self.assertEqual(await self.count(ProofSample), 0)   # baris baru pindah ke antrean saat dikoreksi (M1c)
        async with self.Session() as db:
            user = await db.get(User, self.user.id)
            detail = await item_detail(db, item, user)
        self.assertNotIn("sample_lines", json.dumps(detail, default=str))
        self.assertNotIn("BUDI SANTOSO", json.dumps(detail, default=str))
        # Tidak ada respons API yang memuatnya (daftar dan detail item).
        for url in ("/kotak-struk/", f"/kotak-struk/{item.id}"):
            r = await self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertNotIn("sample_lines", r.text)
            self.assertNotIn("BUDI SANTOSO", r.text)

    async def test_store_receipt_has_no_sample(self):
        status, item = await self.process(STORE_LINES, flag=True, consent=True)
        self.assertEqual((status, item.doc_type, item.sample_lines), ("siap", "struk_belanja", None))

    async def test_flag_off_reads_no_consent(self):
        from app.services.kotak_struk import donasi
        with patch.object(donasi, "consented", AsyncMock(return_value=True)) as spy:
            status, item = await self.process(GOPAY_LINES, flag=False, consent=True)
        self.assertEqual(status, "siap")
        spy.assert_not_awaited()   # saklar mati: tidak ada kueri persetujuan
        self.assertIsNone(item.sample_lines)
        with patch.object(donasi, "consented", AsyncMock(return_value=False)) as spy:
            await self.process(GOPAY_LINES, flag=True, consent=False)
        spy.assert_awaited_once()

    async def test_consent_read_error_reads_without_donation(self):
        from app.services.kotak_struk import donasi, worker
        with patch.object(donasi, "consented", AsyncMock(side_effect=RuntimeError("db putus"))), \
                self.assertLogs(worker.__name__, level="WARNING") as logs:
            status, item = await self.process(GOPAY_LINES, flag=True, consent=True)
        self.assertEqual((status, item.doc_type, item.sample_lines), ("siap", "transfer", None))
        self.assertTrue(any("persetujuan donasi Kotak Struk tidak terbaca (RuntimeError)" in line
                            for line in logs.output))

    async def test_sample_error_keeps_item_siap(self):
        from app.services.kotak_struk import donasi, worker
        with patch.object(donasi, "sample_lines", side_effect=RuntimeError("RUDI HARTONO 1234567890")), \
                self.assertLogs(worker.__name__, level="WARNING") as logs:
            status, item = await self.process(GOPAY_LINES, flag=True, consent=True)
        self.assertEqual((status, item.status, item.doc_type, item.sample_lines, int(item.parsed_total)),
                         ("siap", "siap", "transfer", None, 10000))
        self.assertIsNotNone(item.layout)
        self.assertTrue(any("baris donasi Kotak Struk tidak dibuat (RuntimeError)" in line for line in logs.output))
        self.assertFalse(any("RUDI" in line or "1234567890" in line for line in logs.output))
        self.assertTrue(all(r.exc_info is None for r in logs.records))


# ── M1c: koreksi -> antrean tinjauan ───────────────────────────────────────

def _item(doc_type="transfer", *, total=10000, flow="keluar", paid_at="2026-10-31T02:00:00+00:00", **over):
    """Item karangan untuk `correction_trigger` (murni)."""
    from types import SimpleNamespace
    document = {"doc_type": doc_type, "flow": flow, "amounts": {"total": total}, "paid_at": paid_at}
    return SimpleNamespace(doc_type=doc_type, document=document, **over)


class CorrectionTriggerTests(unittest.TestCase):
    def test_recorded_triggers(self):
        from app.services.kotak_struk.belajar import Final
        from app.services.kotak_struk.donasi import correction_trigger
        today = date(2026, 11, 2)
        doc_day = date(2026, 10, 31)   # 31 Okt 09:00 WIB
        cases = [
            (_item(), Final(10000, doc_day, "kirim", today), None),             # bacaan benar
            (_item(), Final(10000, today, "kirim", today), None),               # dicatat hari ini
            (_item(), Final(12500, doc_day, "kirim", today), "nominal"),
            (_item(total=None), Final(10000, doc_day, None, today), "nominal"),  # total tidak terbaca
            (_item(), Final(None, doc_day, None, today), "nominal"),            # nominal pecahan
            (_item(), Final(10000, date(2026, 10, 20), None, today), "tanggal"),
            (_item(paid_at=None), Final(10000, date(2026, 10, 20), None, today), "tanggal"),
            (_item("tidak_dikenali"), Final(10000, doc_day, None, today), "tidak_dikenali"),
            (_item("tidak_dikenali", total=None), Final(10000, doc_day, None, today), "nominal"),
            (_item(), None, None),
        ]
        for item, final, want in cases:
            with self.subTest(final=final, doc=item.document):
                self.assertEqual(correction_trigger(item, final), want)

    def test_skip_app_and_bot_triggers(self):
        from app.services.kotak_struk.belajar import Final
        from app.services.kotak_struk.donasi import correction_trigger
        final = Final(12500, None, None, date(2026, 11, 2))
        for reason in ("batal", "duplikat"):
            for doc in (_item(), _item("tidak_dikenali")):
                self.assertIsNone(correction_trigger(doc, None, skip_reason=reason))
                self.assertIsNone(correction_trigger(doc, final, skip_reason=reason))   # lewati menang atas final
        skip = "bukan_pengeluaran"
        self.assertEqual(correction_trigger(_item(), None, skip_reason=skip, alasan="top_up"), "arah")
        self.assertEqual(correction_trigger(_item(), None, skip_reason=skip), "arah")          # keluar tanpa alasan
        self.assertIsNone(correction_trigger(_item(flow="top_up"), None, skip_reason=skip, alasan="top_up"))
        self.assertIsNone(correction_trigger(_item(flow="masuk"), None, skip_reason=skip))
        self.assertEqual(correction_trigger(_item(flow="masuk"), None, skip_reason=skip, alasan="top_up"), "arah")
        self.assertEqual(correction_trigger(_item("tidak_dikenali", flow=None), None, skip_reason=skip),
                         "tidak_dikenali")
        self.assertEqual(correction_trigger(_item(), None, app="bsi"), "aplikasi")
        self.assertEqual(correction_trigger(_item(), None, typed_amount=11000), "nominal_bot")
        self.assertEqual(correction_trigger(SimpleNamespaceItem(), None, typed_amount=1), "nominal_bot")

    def test_truth_shape(self):
        from app.services.kotak_struk.donasi import truth_of
        self.assertEqual(truth_of(), {"total": None, "date": None, "flow": None, "app": None})
        self.assertEqual(truth_of(total=5, day=date(2026, 11, 1), flow="keluar", app="bsi"),
                         {"total": 5, "date": "2026-11-01", "flow": "keluar", "app": "bsi"})


class SimpleNamespaceItem:
    """Item tanpa dokumen (pertahanan: jalur bot/aplikasi tidak butuh dokumen)."""
    doc_type = None
    document = None


class DonateServiceTests(DonasiBase):
    """`donasi.donate`: persetujuan dan saklar dicek lagi, baris selalu dikosongkan, tidak meng-commit, tidak
    melempar."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.flag(kotak_donasi=True)
        async with self.Session() as db:
            db.add(ProofSampleConsent(user_id=self.user.id, consented_at=T0))
            await db.commit()

    async def captured_item(self, user=None, **cols):
        cols.setdefault("processed_at", datetime(2026, 10, 31, 18, 30, tzinfo=timezone.utc))   # 1 Nov 01:30 WIB
        async with self.Session() as db:
            item = ReceiptScan(user_id=(user or self.user).id, status=K.ST_TERCATAT, doc_type="transfer",
                               sample_lines=list(LINES), layout={"v": 1, "key": "gopay", "lines": []}, **cols)
            db.add(item)
            await db.commit()
            return item.id

    async def donate(self, item_id, trigger="nominal", *, commit=True, **kw):
        from app.services.kotak_struk import donasi
        async with self.Session() as db:
            item = await db.get(ReceiptScan, item_id)
            got = await donasi.donate(db, item, trigger, truth=donasi.truth_of(total=12500), now=T0, **kw)
            self.assertIsNone(item.sample_lines)
            self.assertNotIn(item, db.dirty)   # objek tidak kotor: baris dikosongkan lewat UPDATE
            if commit:
                await db.commit()
            else:
                await db.rollback()
            return got

    async def test_donate_stores_one_sample_and_clears_lines(self):
        item_id = await self.captured_item()
        self.assertTrue(await self.donate(item_id))
        [sample] = (await self._samples())
        self.assertEqual((sample.status, sample.trigger, sample.rule_key, sample.doc_type, sample.lines, sample.today),
                         ("menunggu", "nominal", "gopay", "transfer", LINES, date(2026, 11, 1)))
        self.assertEqual((sample.user_name, sample.truth["total"]), ("Andi Pratama", 12500))
        self.assertTrue(await self.sql_null_sample_lines(item_id))
        # Item yang sama dengan baris baru (mis. kirim ulang yang menangkap lagi): tetap satu sampel.
        async with self.Session() as db:
            (await db.get(ReceiptScan, item_id)).sample_lines = list(LINES)
            await db.commit()
        self.assertFalse(await self.donate(item_id))
        self.assertEqual(await self.count(ProofSample), 1)
        self.assertTrue(await self.sql_null_sample_lines(item_id))

    async def test_donate_never_commits(self):
        item_id = await self.captured_item()
        self.assertTrue(await self.donate(item_id, commit=False))
        self.assertEqual(await self.count(ProofSample), 0)
        self.assertFalse(await self.sql_null_sample_lines(item_id))

    async def test_no_trigger_consent_or_flag_clears_lines_and_stores_nothing(self):
        from app.services.kotak_struk import donasi
        item_id = await self.captured_item()
        self.assertFalse(await self.donate(item_id, trigger=None))
        self.assertTrue(await self.sql_null_sample_lines(item_id))
        # Persetujuan ditarik sesudah dibaca (review M1b temuan 5): dicek lagi di `donate`.
        other = await self.captured_item(self.other)   # Dodi tidak pernah setuju
        self.assertFalse(await self.donate(other))
        self.assertTrue(await self.sql_null_sample_lines(other))
        await self.flag(kotak_donasi=False)
        off = await self.captured_item()
        with patch.object(donasi, "consented", AsyncMock(return_value=True)):
            self.assertFalse(await self.donate(off))
        self.assertTrue(await self.sql_null_sample_lines(off))
        self.assertEqual(await self.count(ProofSample), 0)

    async def test_without_lines_no_query(self):
        from app.services.kotak_struk import donasi
        statements = []
        event.listen(self.engine.sync_engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
        async with self.Session() as db:
            item = ReceiptScan(user_id=self.user.id, status=K.ST_SIAP, doc_type="qris")
            self.assertFalse(await donasi.donate(db, item, "nominal", truth={}, now=T0))
        self.assertEqual(statements, [])

    async def test_error_is_swallowed_without_proof_text(self):
        from app.services.kotak_struk import donasi
        item_id = await self.captured_item()
        with patch.object(donasi, "consented", AsyncMock(side_effect=RuntimeError("BUDI SANTOSO 1234567890"))), \
                self.assertLogs(donasi.__name__, "WARNING") as logs:
            self.assertFalse(await self.donate(item_id))
        self.assertTrue(all("BUDI" not in line and "1234" not in line for line in logs.output))
        self.assertTrue(all(r.exc_info is None for r in logs.records))
        self.assertTrue(any("(RuntimeError)" in line for line in logs.output))
        self.assertEqual(await self.count(ProofSample), 0)
        self.assertTrue(await self.sql_null_sample_lines(item_id))   # dikosongkan di savepoint baru

    async def _samples(self):
        async with self.Session() as db:
            return list((await db.execute(select(ProofSample))).scalars())


if __name__ == "__main__":
    unittest.main()
