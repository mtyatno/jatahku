"""Intake Kotak Struk + duplikat lapis 1-3 (SQLite in-memory, tanpa Redis sungguhan).
Run: python -m unittest app.tests.test_kotak_intake -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import hashlib
import importlib.util
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import event, func, select

from app.core.database import Base
from app.models.models import Household, HouseholdMember, HouseholdRole, ReceiptScan, User
from app.services.kotak_struk import dedup, intake as intake_mod
from app.services.kotak_struk.dedup import pending_ref_duplicate, recorded_duplicate
from app.services.kotak_struk.intake import IntakeRejected, IntakeRequest, create_item

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
JPG = b"\xff\xd8\xff\xe0jpeg"
PNG = b"\x89PNG\r\n\x1a\nxx"
WORKER = "app.services.kotak_struk.worker"


class FakeRedis:
    def __init__(self):
        self.counts = {}
        self.expiries = {}
        self.closed = False

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, ttl):
        self.expiries[key] = ttl
        return True

    async def aclose(self):
        self.closed = True


class BrokenRedis(FakeRedis):
    async def incr(self, key):
        raise ConnectionError("redis mati")


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class KotakIntakeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        # Resep SQLAlchemy untuk pysqlite: tanpa ini SAVEPOINT terluar tidak punya BEGIN dan
        # RELEASE-nya langsung meng-commit (Postgres tidak begitu).
        event.listen(self.engine.sync_engine, "connect", lambda conn, _rec: setattr(conn, "isolation_level", None))
        event.listen(self.engine.sync_engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.db = self.Session()
        self.dir = tempfile.mkdtemp()
        self.redis = FakeRedis()
        self.user = User(name="Tes")
        self.hh = Household(name="Rumah Tes")
        self.db.add_all([self.user, self.hh])
        await self.db.flush()
        self.db.add(HouseholdMember(user_id=self.user.id, household_id=self.hh.id, role=HouseholdRole.owner))
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def add_member(self, name):
        u = User(name=name)
        self.db.add(u)
        await self.db.flush()
        self.db.add(HouseholdMember(user_id=u.id, household_id=self.hh.id, role=HouseholdRole.member))
        await self.db.commit()
        return u

    async def make(self, req, **kw):
        return await create_item(self.db, req, redis=kw.pop("redis", self.redis),
                                 kotak_dir=kw.pop("kotak_dir", self.dir), **kw)

    async def count_items(self, *where):
        return (await self.db.execute(select(func.count()).select_from(ReceiptScan).where(*where))).scalar()

    # --- brief ---------------------------------------------------------

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

    # --- item dan file -------------------------------------------------

    async def test_item_fields_and_messages(self):
        item, _ = await self.make(IntakeRequest(self.user, "web_chat", upload_id="u9", data=PNG,
                                                content_type="image/jpeg", channel_meta={"chat_id": 7}))
        self.assertEqual((item.content_type, item.upload_id, item.channel_meta), ("image/png", "u9", {"chat_id": 7}))
        self.assertEqual((item.engine, item.confidence, item.attempts), ("rapidocr", "gagal", 0))
        self.assertEqual(item.file_sha256, hashlib.sha256(PNG).hexdigest())
        self.assertEqual(Path(item.file_path), Path(self.dir) / str(item.id))
        messages = {}
        for name, req in [("kosong", IntakeRequest(self.user, "telegram")),
                          ("tipe", IntakeRequest(self.user, "telegram", data=b"<html>")),
                          ("teks", IntakeRequest(self.user, "telegram", text="x" * 4001)),
                          ("foto", IntakeRequest(self.user, "telegram", data=JPG + b"0" * 10)),
                          ("pdf", IntakeRequest(self.user, "telegram", data=b"%PDF-1.4" + b"0" * 10)),
                          ("both", IntakeRequest(self.user, "telegram", data=JPG, text="kopi"))]:
            with patch.object(intake_mod, "IMAGE_MAX_BYTES", 8), patch.object(intake_mod, "PDF_MAX_BYTES", 8):
                with self.assertRaises(IntakeRejected) as cm:
                    await self.make(req)
            messages[name] = (cm.exception.status_code, cm.exception.detail)
        self.assertEqual(messages, {
            "kosong": (422, "Kirim satu file atau teks"),
            "both": (422, "Kirim satu file atau teks"),
            "tipe": (415, "Kirim foto (JPG/PNG/WebP), PDF, atau teks"),
            "teks": (413, "Teks terlalu panjang"),
            "foto": (413, "Foto terlalu besar (maks 8 MB)"),
            "pdf": (413, "PDF terlalu besar (maks 10 MB)"),
        })
        self.assertEqual(await self.count_items(), 1)

    async def test_text_item_is_normalized_and_stored_utf8(self):
        item, created = await self.make(IntakeRequest(self.user, "web_form", text="  Transfer berhasil \n\n   Rp 25.000  \n"))
        self.assertTrue(created)
        self.assertEqual(item.content_type, "text/plain")
        self.assertEqual(Path(item.file_path).read_bytes(), "Transfer berhasil\nRp 25.000".encode())
        self.assertEqual(item.file_sha256, hashlib.sha256("Transfer berhasil\nRp 25.000".encode()).hexdigest())
        again, created = await self.make(IntakeRequest(self.user, "telegram", text="Transfer berhasil\r\nRp 25.000"))
        self.assertEqual((again.id, created), (item.id, False))

    async def test_blank_text_or_empty_data_is_rejected(self):
        for req in (IntakeRequest(self.user, "telegram", text="  \n "), IntakeRequest(self.user, "telegram", text=""),
                    IntakeRequest(self.user, "telegram", data=b"")):
            with self.subTest(req=req):
                with self.assertRaises(IntakeRejected) as cm:
                    await self.make(req)
                self.assertEqual((cm.exception.status_code, cm.exception.detail), (422, "Kirim satu file atau teks"))

    async def test_kotak_dir_created_with_mode_0700(self):
        sub = os.path.join(self.dir, "belum", "ada")
        item, _ = await self.make(IntakeRequest(self.user, "telegram", data=JPG), kotak_dir=sub)
        self.assertEqual(oct(Path(sub).stat().st_mode & 0o777), "0o700")
        self.assertEqual(Path(item.file_path).read_bytes(), JPG)

    async def test_pdf_is_accepted(self):
        item, _ = await self.make(IntakeRequest(self.user, "pwa_share", data=b"%PDF-1.7 isi"))
        self.assertEqual(item.content_type, "application/pdf")

    async def test_default_kotak_dir_comes_from_settings(self):
        with patch("app.services.kotak_struk.intake.get_settings", return_value=types.SimpleNamespace(KOTAK_DIR=self.dir, REDIS_URL="redis://x")):
            item, _ = await create_item(self.db, IntakeRequest(self.user, "telegram", data=JPG), redis=self.redis)
        self.assertEqual(Path(item.file_path).parent, Path(self.dir))

    # --- idempotensi dan lingkup ---------------------------------------

    async def test_open_statuses_return_existing_closed_statuses_make_new(self):
        sha = hashlib.sha256(JPG).hexdigest()
        for status, reuse in [("diterima", True), ("diproses", True), ("siap", True),
                              ("gagal", False), ("tercatat", False), ("dilewati", False), ("kedaluwarsa", False)]:
            with self.subTest(status=status):
                old = ReceiptScan(user_id=self.user.id, household_id=self.hh.id, status=status, file_sha256=sha)
                self.db.add(old); await self.db.commit()
                item, created = await self.make(IntakeRequest(self.user, "telegram", data=JPG))
                self.assertEqual((item.id == old.id, created), (reuse, not reuse))
                if reuse:
                    await self.db.delete(old); await self.db.commit()
                else:
                    await self.db.delete(old); await self.db.delete(item); await self.db.commit()

    async def test_same_file_or_upload_id_of_another_user_is_a_new_item(self):
        other = await self.add_member("Dewi")
        a, _ = await self.make(IntakeRequest(other, "pwa_share", upload_id="u1", data=JPG))
        b, created = await self.make(IntakeRequest(self.user, "pwa_share", upload_id="u1", data=JPG))
        self.assertEqual((b.id == a.id, created, b.household_id), (False, True, self.hh.id))

    async def test_empty_upload_id_is_not_a_key(self):
        a, _ = await self.make(IntakeRequest(self.user, "telegram", upload_id="", data=JPG))
        b, created = await self.make(IntakeRequest(self.user, "telegram", upload_id="", data=PNG))
        self.assertEqual((a.upload_id, b.upload_id, created), (None, None, True))

    async def test_upload_id_race_returns_existing_item(self):
        """Dua permintaan dengan upload_id sama: yang kalah lolos pencarian awal, lalu ditolak
        indeks unik saat flush -> item yang menang dikembalikan, tanpa file yatim."""
        a, _ = await self.make(IntakeRequest(self.user, "pwa_share", upload_id="u1", data=JPG))
        real, calls = dedup.find_by_upload, []

        async def miss_once(db, user_id, upload_id):
            calls.append(upload_id)
            return None if len(calls) == 1 else await real(db, user_id, upload_id)

        with patch.object(dedup, "find_by_upload", miss_once):
            b, created = await self.make(IntakeRequest(self.user, "pwa_share", upload_id="u1", data=PNG))
        self.assertEqual((b.id, created), (a.id, False))
        self.assertEqual(calls, ["u1", "u1"])
        self.assertEqual(os.listdir(self.dir), [str(a.id)])
        self.assertEqual(await self.count_items(), 1)
        self.assertEqual(self.user.name, "Tes")  # objek sesi tidak ter-expire oleh rollback

    async def test_unique_index_survives_without_existing_item(self):
        """IntegrityError tanpa item pemenang yang ditemukan -> galat naik, bukan ditelan."""
        a, _ = await self.make(IntakeRequest(self.user, "pwa_share", upload_id="u1", data=JPG))
        async def always_miss(db, user_id, upload_id):
            return None
        with patch.object(dedup, "find_by_upload", always_miss):
            from sqlalchemy.exc import IntegrityError
            with self.assertRaises(IntegrityError):
                await self.make(IntakeRequest(self.user, "pwa_share", upload_id="u1", data=PNG))
        self.assertEqual(os.listdir(self.dir), [str(a.id)])

    # --- batas ---------------------------------------------------------

    async def test_rate_counter_expires_in_an_hour_and_ignores_duplicates(self):
        key = f"kotak:rate:{self.user.id}"
        await self.make(IntakeRequest(self.user, "telegram", data=JPG))
        self.assertEqual((self.redis.counts[key], self.redis.expiries[key]), (1, 3600))
        await self.make(IntakeRequest(self.user, "telegram", data=JPG))  # duplikat: tidak dihitung
        self.assertEqual(self.redis.counts[key], 1)
        await self.make(IntakeRequest(self.user, "telegram", data=PNG))
        self.assertEqual((self.redis.counts[key], self.redis.expiries[key]), (2, 3600))

    async def test_rate_limit_boundary_is_per_hour_limit(self):
        key = f"kotak:rate:{self.user.id}"
        self.redis.counts[key] = 29
        await self.make(IntakeRequest(self.user, "telegram", text="ke-30"))  # 30 masih boleh
        with self.assertRaises(IntakeRejected) as cm:
            await self.make(IntakeRequest(self.user, "telegram", text="ke-31"))
        self.assertEqual((cm.exception.status_code, cm.exception.detail), (429, "Terlalu banyak bukti. Coba lagi sebentar."))

    async def test_pending_limit_message_and_scope(self):
        other = await self.add_member("Dewi")
        self.db.add_all([ReceiptScan(user_id=self.user.id, household_id=self.hh.id, status="siap") for _ in range(25)]
                        + [ReceiptScan(user_id=other.id, household_id=self.hh.id, status="diterima") for _ in range(25)]
                        + [ReceiptScan(user_id=self.user.id, household_id=self.hh.id, status="diterima") for _ in range(10)]
                        + [ReceiptScan(user_id=self.user.id, household_id=self.hh.id, status="diproses") for _ in range(9)])
        await self.db.commit()
        await self.make(IntakeRequest(self.user, "telegram", text="yang ke-20"))  # siap & milik orang lain tidak dihitung
        with self.assertRaises(IntakeRejected) as cm:
            await self.make(IntakeRequest(self.user, "telegram", text="yang ke-21"))
        self.assertEqual((cm.exception.status_code, cm.exception.detail), (429, "Masih ada bukti yang sedang dibaca. Tunggu sebentar."))

    async def test_redis_error_skips_the_rate_limit(self):
        with self.assertLogs(intake_mod.log, "WARNING"):
            item, created = await self.make(IntakeRequest(self.user, "telegram", data=JPG), redis=BrokenRedis())
        self.assertTrue(created)
        self.assertEqual(item.status, "diterima")

    async def test_own_redis_client_is_created_and_closed(self):
        fake = FakeRedis()
        with patch("redis.asyncio.from_url", return_value=fake) as from_url:
            await create_item(self.db, IntakeRequest(self.user, "telegram", data=JPG), kotak_dir=self.dir)
        from_url.assert_called_once()
        self.assertEqual(fake.counts[f"kotak:rate:{self.user.id}"], 1)
        self.assertTrue(fake.closed)

    async def test_own_redis_client_is_closed_when_rate_limited(self):
        fake = FakeRedis()
        fake.counts[f"kotak:rate:{self.user.id}"] = 30
        with patch("redis.asyncio.from_url", return_value=fake):
            with self.assertRaises(IntakeRejected):
                await create_item(self.db, IntakeRequest(self.user, "telegram", data=JPG), kotak_dir=self.dir)
        self.assertTrue(fake.closed)

    async def test_given_redis_client_is_not_closed(self):
        await self.make(IntakeRequest(self.user, "telegram", data=JPG))
        self.assertFalse(self.redis.closed)

    async def test_own_redis_client_that_cannot_be_created_fails_open(self):
        with patch("redis.asyncio.from_url", side_effect=ValueError("url buruk")), \
                self.assertLogs(intake_mod.log, "WARNING"):
            item, created = await create_item(self.db, IntakeRequest(self.user, "telegram", data=JPG), kotak_dir=self.dir)
        self.assertTrue(created)

    # --- kegagalan tulis file ------------------------------------------

    async def test_file_open_failure_leaves_no_row(self):
        with patch("app.services.kotak_struk.intake.os.open", side_effect=OSError("disk penuh")):
            with self.assertRaises(OSError):
                await self.make(IntakeRequest(self.user, "telegram", data=JPG))
        self.assertEqual(await self.count_items(), 0)
        self.assertEqual(os.listdir(self.dir), [])
        item, created = await self.make(IntakeRequest(self.user, "telegram", data=JPG))  # sesi masih dipakai
        self.assertTrue(created)
        self.assertEqual(self.user.name, "Tes")

    async def test_partial_write_failure_removes_file_and_row(self):
        with patch("app.services.kotak_struk.intake.os.write", side_effect=OSError("disk penuh")):
            with self.assertRaises(OSError):
                await self.make(IntakeRequest(self.user, "telegram", data=JPG))
        self.assertEqual(await self.count_items(), 0)
        self.assertEqual(os.listdir(self.dir), [])

    async def test_commit_failure_removes_file(self):
        async def boom():
            raise RuntimeError("commit gagal")
        with patch.object(self.db, "commit", boom):
            with self.assertRaises(RuntimeError):
                await self.make(IntakeRequest(self.user, "telegram", data=JPG))
        self.assertEqual(os.listdir(self.dir), [])
        await self.db.rollback()
        self.assertEqual(await self.count_items(), 0)

    # --- worker.wake ---------------------------------------------------

    async def test_wake_is_called_when_worker_module_exists(self):
        fake = types.ModuleType(WORKER)
        fake.wake = MagicMock()
        with patch.dict(sys.modules, {WORKER: fake}):
            await self.make(IntakeRequest(self.user, "telegram", data=JPG))
            fake.wake.assert_called_once_with()
            await self.make(IntakeRequest(self.user, "telegram", data=JPG))  # duplikat: tidak membangunkan lagi
            fake.wake.assert_called_once_with()

    async def test_missing_worker_module_is_ignored(self):
        with patch.dict(sys.modules, {WORKER: None}):
            item, created = await self.make(IntakeRequest(self.user, "telegram", data=JPG))
        self.assertTrue(created)

    async def test_failing_wake_does_not_fail_intake(self):
        fake = types.ModuleType(WORKER)
        fake.wake = MagicMock(side_effect=RuntimeError("loop lain"))
        with patch.dict(sys.modules, {WORKER: fake}):
            with self.assertLogs(intake_mod.log, "WARNING"):
                item, created = await self.make(IntakeRequest(self.user, "telegram", data=JPG))
        self.assertTrue(created)

    # --- dedup.py ------------------------------------------------------

    async def test_find_helpers(self):
        a, _ = await self.make(IntakeRequest(self.user, "pwa_share", upload_id="u1", data=JPG))
        other = await self.add_member("Dewi")
        self.assertEqual((await dedup.find_by_upload(self.db, self.user.id, "u1")).id, a.id)
        self.assertIsNone(await dedup.find_by_upload(self.db, other.id, "u1"))
        self.assertIsNone(await dedup.find_by_upload(self.db, self.user.id, "u2"))
        sha = hashlib.sha256(JPG).hexdigest()
        self.assertEqual((await dedup.find_open_by_file(self.db, self.user.id, sha)).id, a.id)
        self.assertIsNone(await dedup.find_open_by_file(self.db, other.id, sha))
        a.status = "tercatat"; await self.db.commit()
        self.assertIsNone(await dedup.find_open_by_file(self.db, self.user.id, sha))

    async def test_recorded_duplicate_scope_and_exclusion(self):
        other = await self.add_member("Dewi")
        outsider_hh = Household(name="Lain"); self.db.add(outsider_hh); await self.db.flush()
        outsider = User(name="Orang Lain"); self.db.add(outsider); await self.db.flush()
        rec = ReceiptScan(user_id=other.id, household_id=self.hh.id, status="tercatat", ref_hash="h1", file_sha256="f1")
        foreign = ReceiptScan(user_id=outsider.id, household_id=outsider_hh.id, status="tercatat", ref_hash="h9", file_sha256="f9")
        not_yet = ReceiptScan(user_id=other.id, household_id=self.hh.id, status="siap", ref_hash="h3", file_sha256="f3")
        orphan = ReceiptScan(user_id=outsider.id, household_id=None, status="tercatat", ref_hash="h8", file_sha256="f8")
        self.db.add_all([rec, foreign, not_yet, orphan]); await self.db.commit()
        got = await recorded_duplicate(self.db, self.hh.id, file_sha="f1", ref_hash="h1", exclude_id=None)
        self.assertEqual(got, {"kind": "file", "item_id": str(rec.id), "recorded": True})
        got = await recorded_duplicate(self.db, self.hh.id, file_sha="zzz", ref_hash="h1", exclude_id=None)
        self.assertEqual(got, {"kind": "ref", "item_id": str(rec.id), "recorded": True})
        self.assertIsNone(await recorded_duplicate(self.db, self.hh.id, file_sha="f1", ref_hash="h1", exclude_id=rec.id))
        for kw in ({"file_sha": "f9", "ref_hash": "h9"}, {"file_sha": "f3", "ref_hash": "h3"},
                   {"file_sha": "f8", "ref_hash": "h8"}, {"file_sha": None, "ref_hash": None}):
            with self.subTest(kw=kw):
                self.assertIsNone(await recorded_duplicate(self.db, self.hh.id, exclude_id=None, **kw))
        self.assertIsNone(await recorded_duplicate(self.db, None, file_sha="f8", ref_hash="h8", exclude_id=None))

    async def test_pending_ref_duplicate_is_about_other_members_only(self):
        other = await self.add_member("Dewi")
        theirs = ReceiptScan(user_id=other.id, household_id=self.hh.id, status="siap", ref_hash="h2")
        mine = ReceiptScan(user_id=self.user.id, household_id=self.hh.id, status="siap", ref_hash="h2")
        done = ReceiptScan(user_id=other.id, household_id=self.hh.id, status="tercatat", ref_hash="h4")
        self.db.add_all([theirs, mine, done]); await self.db.commit()
        got = await pending_ref_duplicate(self.db, self.hh.id, "h2", mine.id)
        self.assertEqual(got, {"kind": "ref", "item_id": str(theirs.id), "recorded": False, "by": "Dewi"})
        self.assertEqual((await pending_ref_duplicate(self.db, self.hh.id, "h2", theirs.id))["by"], "Tes")
        solo = ReceiptScan(user_id=self.user.id, household_id=self.hh.id, status="siap", ref_hash="h5")
        self.db.add(solo); await self.db.commit()
        self.assertIsNone(await pending_ref_duplicate(self.db, self.hh.id, "h5", solo.id))  # milik sendiri bukan duplikat
        self.assertIsNone(await pending_ref_duplicate(self.db, self.hh.id, "h4", None))  # sudah tercatat -> urusan recorded_duplicate
        self.assertIsNone(await pending_ref_duplicate(self.db, self.hh.id, None, None))
        self.assertIsNone(await pending_ref_duplicate(self.db, None, "h2", None))


if __name__ == "__main__":
    unittest.main()
