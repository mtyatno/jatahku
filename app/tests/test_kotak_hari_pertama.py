"""Kotak Struk, Task L0: perintah sekali jalan "hari pertama" (`app.scripts.kotak_hari_pertama`, spec 2026-11-01
§12.3 opsi B). Item `siap` lama dari form Catat dilewati (`batal`) tepat sebelum saklar `receipt_inbox` menyala; item
bot/chat/share dan item `gagal` tidak disentuh. SQLite in-memory (pola test_kotak_maintenance); tes CLI memakai berkas
SQLite sementara karena `main` memakai `asyncio.run` (loop sendiri).
Run: DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret \
     python -m unittest app.tests.test_kotak_hari_pertama -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import io
import shutil
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core.database import Base
from app.models.models import Household, ReceiptScan, User

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
NOW = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)  # 10:00 WIB
DAY = timedelta(hours=24)


def _script():
    """Modul yang diuji, diimpor saat tes berjalan: sebelum Step 3 tes gagal karena modulnya belum ada."""
    from app.scripts import kotak_hari_pertama
    return kotak_hari_pertama


def _engine(url, **kw):
    from sqlalchemy.ext.asyncio import create_async_engine
    return create_async_engine(url, connect_args={"check_same_thread": False}, **kw)


async def _seed_user(Session, name):
    async with Session() as db:
        user, hh = User(name=name), Household(name=f"Rumah {name}")
        db.add_all([user, hh])
        await db.commit()
        return user.id, hh.id


async def _add_item(Session, user_id, hh_id, *, source="web_form", status="siap", created_at=NOW,
                    doc_type="qris", **cols):
    async with Session() as db:
        cols.setdefault("id", uuid.uuid4())
        it = ReceiptScan(user_id=user_id, household_id=hh_id, source=source, status=status,
                         created_at=created_at, doc_type=doc_type, engine="rapidocr", confidence="tinggi", **cols)
        db.add(it)
        await db.commit()
        return it


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class HariPertamaTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        from sqlalchemy.pool import StaticPool
        self.engine = _engine("sqlite+aiosqlite://", poolclass=StaticPool)
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.db = self.Session()
        self.addAsyncCleanup(self.db.close)
        self.user_id, self.hh_id = await _seed_user(self.Session, "Rina")

    async def item(self, user_id=None, **cols):
        return await _add_item(self.Session, user_id or self.user_id, self.hh_id, **cols)

    async def get(self, item_id):
        async with self.Session() as db:
            return await db.get(ReceiptScan, item_id)

    async def test_dry_run_counts_only_old_web_form_siap(self):
        run = _script().run
        old = await self.item(source="web_form", status="siap", created_at=NOW - timedelta(hours=30), doc_type="qris")
        await self.item(source="web_form", status="siap", created_at=NOW - timedelta(hours=2))  # terlalu baru
        await self.item(source="telegram", status="siap", created_at=NOW - timedelta(days=3))  # bot: tidak
        await self.item(source="web_chat", status="siap", created_at=NOW - timedelta(days=3))
        await self.item(source="pwa_share", status="siap", created_at=NOW - timedelta(days=3))
        await self.item(source="web_form", status="gagal", created_at=NOW - timedelta(days=3))  # bukan siap
        await self.item(source="web_form", status="tercatat", created_at=NOW - timedelta(days=3))
        await self.item(source=None, status=None, created_at=NOW - timedelta(days=3))  # riwayat scan lama
        s = await run(self.db, now=NOW, older_than=DAY, apply=False)
        self.assertEqual((s.found, s.by_doc_type, s.users, s.skipped, s.lost), (1, {"qris": 1}, 1, 0, 0))
        self.assertEqual((await self.get(old.id)).status, "siap")

    async def test_dry_run_writes_nothing_even_with_skip_patched(self):
        await self.item(created_at=NOW - timedelta(days=2))
        with patch("app.services.kotak_struk.record.skip_item", new=AsyncMock(return_value=True)) as skip:
            s = await _script().run(self.db, now=NOW, older_than=DAY, apply=False)
        skip.assert_not_called()
        self.assertEqual((s.found, s.skipped, s.lost), (1, 0, 0))

    async def test_candidates_are_oldest_first_with_user_and_doc_type(self):
        other_id, _ = await _seed_user(self.Session, "Bayu")
        # id sengaja berurutan terbalik dari umur, supaya urutan menurut id tidak kebetulan lolos
        b = await self.item(id=uuid.UUID(int=2), created_at=NOW - timedelta(days=2), doc_type="transfer")
        a = await self.item(id=uuid.UUID(int=3), user_id=other_id, created_at=NOW - timedelta(days=5),
                            doc_type="struk_belanja")
        c = await self.item(id=uuid.UUID(int=1), created_at=NOW - timedelta(hours=25), doc_type=None)
        rows = await _script().candidates(self.db, now=NOW, older_than=DAY)
        self.assertEqual(rows, [(a.id, other_id, "struk_belanja"), (b.id, self.user_id, "transfer"),
                                (c.id, self.user_id, None)])

    async def test_cutoff_is_strictly_older(self):
        await self.item(created_at=NOW - DAY)  # tepat di batas: tidak
        s = await _script().run(self.db, now=NOW, older_than=DAY, apply=False)
        self.assertEqual(s.found, 0)

    async def test_apply_skips_with_reason_batal_and_is_idempotent(self):
        run = _script().run
        other_id, _ = await _seed_user(self.Session, "Bayu")
        q = await self.item(created_at=NOW - timedelta(days=2), doc_type="qris", channel_meta={"form": 1})
        t = await self.item(user_id=other_id, created_at=NOW - timedelta(days=3), doc_type="transfer")
        bot = await self.item(source="telegram", created_at=NOW - timedelta(days=3))
        new = await self.item(created_at=NOW - timedelta(hours=1))
        failed = await self.item(status="gagal", created_at=NOW - timedelta(days=3))
        s = await run(self.db, now=NOW, older_than=DAY, apply=True)
        self.assertEqual((s.found, s.by_doc_type, s.users, s.skipped, s.lost),
                         (2, {"qris": 1, "transfer": 1}, 2, 2, 0))
        for item in (q, t):
            got = await self.get(item.id)
            self.assertEqual(got.status, "dilewati")
            self.assertEqual(got.channel_meta["skip_reason"], "batal")
        self.assertEqual((await self.get(q.id)).channel_meta["form"], 1)  # meta lama dipertahankan
        for item, status in ((bot, "siap"), (new, "siap"), (failed, "gagal")):
            self.assertEqual((await self.get(item.id)).status, status)
        again = await run(self.db, now=NOW, older_than=DAY, apply=True)
        self.assertEqual((again.found, again.by_doc_type, again.users, again.skipped, again.lost), (0, {}, 0, 0, 0))

    async def test_zero_cutoff_takes_every_web_form_siap(self):
        a = await self.item(created_at=NOW - timedelta(seconds=1))
        b = await self.item(created_at=NOW - timedelta(days=9), doc_type="tidak_dikenali")
        await self.item(source="pwa_share", created_at=NOW - timedelta(seconds=1))
        s = await _script().run(self.db, now=NOW, older_than=timedelta(0), apply=True)
        self.assertEqual((s.found, s.skipped, s.by_doc_type), (2, 2, {"qris": 1, "tidak_dikenali": 1}))
        for item in (a, b):
            self.assertEqual((await self.get(item.id)).status, "dilewati")

    async def test_lost_race_is_counted_not_raised(self):
        it = await self.item(created_at=NOW - timedelta(days=2))
        skip = AsyncMock(return_value=False)  # dicatat/dilewati bersamaan: UPDATE bersyarat kalah
        with patch("app.services.kotak_struk.record.skip_item", new=skip):
            s = await _script().run(self.db, now=NOW, older_than=DAY, apply=True)
        skip.assert_awaited_once_with(self.db, it.id, self.user_id, "batal")
        self.assertEqual((s.found, s.skipped, s.lost), (1, 0, 1))
        self.assertEqual((await self.get(it.id)).status, "siap")

    async def test_real_race_item_recorded_after_listing_is_lost(self):
        """Item yang dicatat di antara daftar dan UPDATE: `skip_item` mengembalikan False, statusnya tetap tercatat."""
        script = _script()
        it = await self.item(created_at=NOW - timedelta(days=2))
        real_candidates = script.candidates

        async def then_record(db, **kw):
            rows = await real_candidates(db, **kw)
            async with self.Session() as other:
                (await other.get(ReceiptScan, it.id)).status = "tercatat"
                await other.commit()
            return rows

        with patch.object(script, "candidates", new=then_record):
            s = await script.run(self.db, now=NOW, older_than=DAY, apply=True)
        self.assertEqual((s.found, s.skipped, s.lost), (1, 0, 1))
        self.assertEqual((await self.get(it.id)).status, "tercatat")


class ParserTest(unittest.TestCase):
    def parse_error(self, argv):
        err = io.StringIO()
        with patch("app.core.database.AsyncSessionLocal", side_effect=AssertionError("sesi dibuka")), \
                redirect_stdout(io.StringIO()), redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            _script().main(argv)
        return raised.exception.code, err.getvalue()

    def test_cli_rejects_negative_hours(self):
        code, err = self.parse_error(["--lebih-lama-dari", "-1"])
        self.assertEqual(code, 2)
        self.assertIn("--lebih-lama-dari", err)

    def test_cli_rejects_non_number(self):
        code, _ = self.parse_error(["--lebih-lama-dari", "sehari"])
        self.assertEqual(code, 2)

    def test_cli_caps_hours_at_ten_years(self):
        """Batas 10 tahun (24 x 3650 jam): angka raksasa ditolak argparse, bukan OverflowError saat menghitung batas waktu."""
        script = _script()
        self.assertEqual(script.MAX_HOURS, 24 * 3650)
        args = script._parser().parse_args(["--lebih-lama-dari", str(script.MAX_HOURS)])
        self.assertEqual(args.lebih_lama_dari, script.MAX_HOURS)
        for value in (str(script.MAX_HOURS + 1), "20000000"):
            with self.subTest(value):
                code, err = self.parse_error(["--lebih-lama-dari", value])
                self.assertEqual(code, 2)
                self.assertIn("--lebih-lama-dari", err)
                self.assertNotIn("Traceback", err)

    def test_cli_defaults_and_zero(self):
        parser = _script()._parser()
        args = parser.parse_args([])
        self.assertEqual((args.apply, args.lebih_lama_dari), (False, 24))
        args = parser.parse_args(["--apply", "--lebih-lama-dari", "0"])
        self.assertEqual((args.apply, args.lebih_lama_dari), (True, 0))

    def test_help_tells_how_to_run_on_the_vps(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            _script().main(["--help"])
        text = out.getvalue()
        self.assertIn("sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.kotak_hari_pertama", text)
        self.assertIn("antrean", text)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class CliTest(unittest.TestCase):
    """`main(argv)` ujung ke ujung pada berkas SQLite: `AsyncSessionLocal` dan `engine` di-patch di
    `app.core.database` (skrip mengimpornya saat dipakai, pola test_siklus_household_script)."""

    def setUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        from sqlalchemy.pool import NullPool
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.url = f"sqlite+aiosqlite:///{Path(self.dir) / 'tes.db'}"
        self.engine = _engine(self.url, poolclass=NullPool)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        now = datetime.now(timezone.utc)

        async def seed():
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            rina, hh = await _seed_user(self.Session, "Rina Sukmawati")
            bayu, _ = await _seed_user(self.Session, "Bayu Pratama")
            items = [
                await _add_item(self.Session, rina, hh, created_at=now - timedelta(days=2), doc_type="qris",
                                parsed_total=Decimal("98765"), merchant="Warung Kopi Senja"),
                await _add_item(self.Session, rina, hh, created_at=now - timedelta(days=3), doc_type="qris"),
                await _add_item(self.Session, bayu, hh, created_at=now - timedelta(days=4), doc_type="transfer",
                                parsed_total=Decimal("43210")),
                await _add_item(self.Session, bayu, hh, created_at=now - timedelta(hours=3), doc_type="transfer"),
            ]
            await self.engine.dispose()
            return items

        self.items = asyncio.run(seed())

    def run_main(self, argv):
        out = io.StringIO()
        disposer = AsyncMock()
        fake_engine = type("E", (), {"dispose": disposer})()
        with patch("app.core.database.AsyncSessionLocal", new=self.Session), \
                patch("app.core.database.engine", new=fake_engine), redirect_stdout(out):
            code = _script().main(argv)
        disposer.assert_awaited_once()
        return code, out.getvalue()

    def statuses(self):
        async def read():
            async with self.Session() as db:
                got = [(await db.get(ReceiptScan, it.id)).status for it in self.items]
            await self.engine.dispose()
            return got
        return asyncio.run(read())

    def assert_numbers_only(self, out):
        for it in self.items:
            self.assertNotIn(str(it.id), out)
            self.assertNotIn(str(it.user_id), out)
        for secret in ("Rina", "Sukmawati", "Bayu", "Pratama", "Warung", "Senja", "98765", "98.765", "43210",
                       "43.210"):
            self.assertNotIn(secret, out)

    def test_output_has_no_ids_or_names(self):
        code, out = self.run_main([])
        self.assertEqual(code, 0)
        self.assert_numbers_only(out)
        self.assertIn("qris: 2", out)
        self.assertIn("transfer: 1", out)
        self.assertIn("2 user", out)
        self.assertIn("Dry-run", out)
        self.assertEqual(self.statuses(), ["siap"] * 4)

    def test_apply_prints_counts_and_second_apply_finds_nothing(self):
        code, out = self.run_main(["--apply"])
        self.assertEqual(code, 0)
        self.assert_numbers_only(out)
        self.assertIn("3 dilewati", out)
        self.assertIn("0 kalah", out)
        self.assertEqual(self.statuses(), ["dilewati", "dilewati", "dilewati", "siap"])
        code, out = self.run_main(["--apply"])
        self.assertEqual(code, 0)
        self.assertIn(": 0", out.splitlines()[0])
        self.assertIn("0 dilewati", out)
        code, out = self.run_main(["--apply", "--lebih-lama-dari", "0"])
        self.assertEqual(code, 0)
        self.assertIn("1 dilewati", out)
        self.assertEqual(self.statuses(), ["dilewati"] * 4)


if __name__ == "__main__":
    unittest.main()
