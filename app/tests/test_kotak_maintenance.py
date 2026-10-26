"""Pemeliharaan Kotak Struk (spec 2026-10-26 §2d, §7d butir 4): item kedaluwarsa, file yatim di folder sementara,
job scheduler tiap jam, dan rincian statistik Admin per jenis bukti (SQLite in-memory).
Run: python -m unittest app.tests.test_kotak_maintenance -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import contextlib
import importlib.util
import shutil
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import get_settings
from app.core.database import Base
from app.models.models import Envelope, Household, HouseholdMember, HouseholdRole, ReceiptScan, Transaction, User
from app.services import scheduler as scheduler_mod
from app.services.kotak_struk import maintenance
from app.services.kotak_struk.maintenance import delete_orphan_files, expire_items
from app.services.receipt_scan import accuracy_stats

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
NOW = datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc)  # 10:00 WIB
WIB = timezone(timedelta(hours=7))


def selects_from(spy, table: str) -> int:
    """Jumlah pemanggilan `db.execute` (spy) yang membaca dari `table`."""
    return sum(1 for c in spy.call_args_list
               if hasattr(c.args[0], "get_final_froms") and table in {f.name for f in c.args[0].get_final_froms()})


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class MaintenanceBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.db = self.Session()
        self.addAsyncCleanup(self.db.close)
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        async with self.Session() as db:
            user, hh = User(name="Rina"), Household(name="Rumah Tes")
            db.add_all([user, hh])
            await db.flush()
            db.add(HouseholdMember(user_id=user.id, household_id=hh.id, role=HouseholdRole.owner))
            env = Envelope(household_id=hh.id, name="Jajan")
            db.add(env)
            await db.commit()
            self.user_id, self.hh_id, self.env_id = user.id, hh.id, env.id

    def write_file(self, name, age, payload=b"bukti"):
        """Berkas di folder Kotak dengan mtime = NOW - age."""
        path = Path(self.dir) / name
        path.write_bytes(payload)
        ts = (NOW - age).timestamp()
        os.utime(path, (ts, ts))
        return path

    async def item(self, status, file=False, **cols):
        """Satu baris receipt_scans (dibuat NOW). file=True: berkas bernama id item, berumur 2 jam."""
        item_id = uuid.uuid4()
        cols.setdefault("created_at", NOW)
        if file:
            cols["file_path"] = str(self.write_file(str(item_id), timedelta(hours=2)))
        async with self.Session() as db:
            it = ReceiptScan(id=item_id, user_id=self.user_id, household_id=self.hh_id, status=status,
                             engine=cols.pop("engine", "rapidocr"), confidence=cols.pop("confidence", "gagal"), **cols)
            db.add(it)
            await db.commit()
            return it

    async def get(self, item_id):
        async with self.Session() as db:
            return await db.get(ReceiptScan, item_id)

    async def txn(self, amount, on):
        async with self.Session() as db:
            t = Transaction(envelope_id=self.env_id, user_id=self.user_id, amount=Decimal(amount),
                            description="bayar", transaction_date=on)
            db.add(t)
            await db.commit()
            return str(t.id)


# ── item kedaluwarsa ─────────────────────────────────────────────────────────

class ExpireItemsTests(MaintenanceBase):
    async def test_expire_only_old_unconfirmed(self):
        old = await self.item(status="siap", expires_at=NOW - timedelta(minutes=1))
        fresh = await self.item(status="siap", expires_at=NOW + timedelta(days=1))
        done = await self.item(status="tercatat", expires_at=NOW - timedelta(days=1))
        self.assertEqual(await expire_items(self.db, now=NOW), 1)
        self.assertEqual([(await self.get(i.id)).status for i in (old, fresh, done)], ["kedaluwarsa", "siap", "tercatat"])

    async def test_failed_items_expire_other_statuses_never(self):
        past = NOW - timedelta(hours=1)
        failed = await self.item(status="gagal", expires_at=past)
        others = [await self.item(status=s, expires_at=past)
                  for s in ("dilewati", "diterima", "diproses", "tercatat", "kedaluwarsa")]
        no_expiry = await self.item(status="siap", expires_at=None)
        legacy = await self.item(status=None, expires_at=past)
        self.assertEqual(await expire_items(self.db, now=NOW), 1)
        self.assertEqual((await self.get(failed.id)).status, "kedaluwarsa")
        self.assertEqual([(await self.get(i.id)).status for i in others],
                         ["dilewati", "diterima", "diproses", "tercatat", "kedaluwarsa"])
        self.assertEqual((await self.get(no_expiry.id)).status, "siap")
        self.assertIsNone((await self.get(legacy.id)).status)
        # Tepat di batas belum kedaluwarsa (expires_at < now).
        edge = await self.item(status="siap", expires_at=NOW)
        self.assertEqual(await expire_items(self.db, now=NOW), 0)
        self.assertEqual((await self.get(edge.id)).status, "siap")

    async def test_expired_row_kept_without_ocr_text_hashes_survive(self):
        # Baris tetap disimpan (spec §2d): hash file/referensi dan kolom lain tidak disentuh, hanya teks OCR dibuang.
        # dedup.py sengaja hanya melihat item terbuka (diterima/diproses/siap) dan `tercatat`, jadi tes ini cukup
        # memastikan kolom hash bertahan.
        it = await self.item(status="siap", expires_at=NOW - timedelta(days=1), ocr_lines='["QRIS", "Rp45.000"]',
                             file_sha256="a" * 64, ref_hash="b" * 64, counterparty_key="nmid:ID1020",
                             outcome="expired", transaction_ids=[], doc_type="qris", document={"issuer": "bca_mobile"})
        other = await self.item(status="siap", expires_at=NOW + timedelta(days=1), ocr_lines='["x"]')
        self.assertEqual(await expire_items(self.db, now=NOW), 1)
        got = await self.get(it.id)
        self.assertEqual((got.status, got.ocr_lines), ("kedaluwarsa", None))
        self.assertEqual((got.file_sha256, got.ref_hash, got.counterparty_key, got.outcome, got.transaction_ids,
                          got.doc_type, got.document),
                         ("a" * 64, "b" * 64, "nmid:ID1020", "expired", [], "qris", {"issuer": "bca_mobile"}))
        self.assertEqual((await self.get(other.id)).ocr_lines, '["x"]')
        # Idempoten: putaran berikutnya tidak mengubah apa pun.
        self.assertEqual(await expire_items(self.db, now=NOW + timedelta(hours=1)), 0)

    async def test_now_in_any_zone_or_naive_utc_gives_same_result(self):
        # SQLite menyimpan jam dinding UTC: `now` ber-zona lain harus dikonversi dulu, `now` tanpa zona = UTC.
        for now in (NOW, NOW.astimezone(WIB), NOW.replace(tzinfo=None)):
            with self.subTest(now=now.isoformat()):
                old = await self.item(status="siap", expires_at=NOW - timedelta(minutes=1))
                soon = await self.item(status="siap", expires_at=NOW + timedelta(hours=1))
                self.assertEqual(await expire_items(self.db, now=now), 1)
                self.assertEqual([(await self.get(i.id)).status for i in (old, soon)], ["kedaluwarsa", "siap"])


# ── file yatim ───────────────────────────────────────────────────────────────

class OrphanFileTests(MaintenanceBase):
    async def test_orphan_files_removed_but_queued_kept(self):
        # Nama berkas intake = str(item.id); nama selain UUID tidak disentuh (lihat tes berikutnya).
        queued = await self.item(status="diterima", file=True)
        orphan = self.write_file(str(uuid.uuid4()), age=timedelta(hours=2))
        young = self.write_file(str(uuid.uuid4()), age=timedelta(minutes=5))
        self.assertEqual(await delete_orphan_files(self.dir, self.db, now=NOW), 1)
        self.assertTrue(Path(queued.file_path).exists()); self.assertFalse(orphan.exists()); self.assertTrue(young.exists())

    async def test_only_old_uuid_named_regular_files_are_candidates(self):
        not_uuid = self.write_file("deadbeef", age=timedelta(days=2))
        hidden = self.write_file(".gitkeep", age=timedelta(days=2))
        # uuid.UUID() juga menerima bentuk ini; hanya bentuk kanonik str(item.id) yang ditulis intake.
        md5 = self.write_file("d41d8cd98f00b204e9800998ecf8427e", age=timedelta(days=2))
        upper = self.write_file(str(uuid.uuid4()).upper(), age=timedelta(days=2))
        braced = self.write_file("{%s}" % uuid.uuid4(), age=timedelta(days=2))
        sub = Path(self.dir) / str(uuid.uuid4())
        sub.mkdir()
        (sub / str(uuid.uuid4())).write_bytes(b"x")  # tidak rekursif
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        target = outside / "asli"
        target.write_bytes(b"x")
        link = Path(self.dir) / str(uuid.uuid4())
        link.symlink_to(target)
        os.utime(link, ((NOW - timedelta(days=2)).timestamp(),) * 2, follow_symlinks=False)
        just_old = self.write_file(str(uuid.uuid4()), age=timedelta(hours=1, seconds=1))
        exactly_one_hour = self.write_file(str(uuid.uuid4()), age=timedelta(hours=1))
        self.assertEqual(await delete_orphan_files(self.dir, self.db, now=NOW), 1)
        self.assertFalse(just_old.exists())
        for kept in (not_uuid, hidden, md5, upper, braced, sub, link, target, exactly_one_hour):
            self.assertTrue(os.path.lexists(kept), kept)

    async def test_files_of_unfinished_items_kept_everything_else_removed(self):
        kept = [await self.item(status=s, file=True) for s in ("diterima", "diproses")]
        gone = [await self.item(status=s, file=True)
                for s in ("siap", "gagal", "tercatat", "dilewati", "kedaluwarsa", None)]
        no_row = self.write_file(str(uuid.uuid4()), age=timedelta(days=3))
        self.assertEqual(await delete_orphan_files(self.dir, self.db, now=NOW), len(gone) + 1)
        self.assertTrue(all(Path(i.file_path).exists() for i in kept))
        self.assertFalse(any(Path(i.file_path).exists() for i in gone))
        self.assertFalse(no_row.exists())
        # Baris item tidak diubah oleh penyapu.
        self.assertEqual([(await self.get(i.id)).status for i in kept], ["diterima", "diproses"])

    async def test_status_lookup_is_chunked(self):
        # 3 item belum selesai + 2 tanpa baris, potongan 2 id: 3 SELECT, dan hanya berkas yang tidak dilindungi yang
        # dihapus apa pun urutan daftar folder (3 id terlindung tidak muat dalam satu potongan).
        kept = [await self.item(status=s, file=True) for s in ("diterima", "diproses", "diterima")]
        gone = [self.write_file(str(uuid.uuid4()), age=timedelta(hours=2)) for _ in range(2)]
        with patch.object(maintenance, "ID_CHUNK", 2), patch.object(self.db, "execute", wraps=self.db.execute) as spy:
            self.assertEqual(await delete_orphan_files(self.dir, self.db, now=NOW), 2)
        self.assertEqual(selects_from(spy, "receipt_scans"), 3)
        self.assertTrue(all(Path(i.file_path).exists() for i in kept))
        self.assertFalse(any(p.exists() for p in gone))

    async def test_missing_dir_is_not_an_error_and_not_created(self):
        missing = os.path.join(self.dir, "belum-ada")
        self.assertEqual(await delete_orphan_files(missing, self.db, now=NOW), 0)
        self.assertFalse(os.path.exists(missing))

    async def test_vanished_and_failing_files_do_not_stop_the_sweep(self):
        vanished = self.write_file(str(uuid.uuid4()), age=timedelta(hours=2))
        locked = self.write_file(str(uuid.uuid4()), age=timedelta(hours=2))
        normal = self.write_file(str(uuid.uuid4()), age=timedelta(hours=2))
        real_unlink = os.unlink

        def fake_unlink(path, *a, **k):
            if str(path) == str(vanished):
                real_unlink(path)  # dihapus pihak lain di antara daftar dan unlink
                raise FileNotFoundError(path)
            if str(path) == str(locked):
                raise PermissionError(path)
            return real_unlink(path, *a, **k)

        with patch.object(maintenance.os, "unlink", fake_unlink), \
                self.assertLogs(maintenance.__name__, level="WARNING") as logs:
            self.assertEqual(await delete_orphan_files(self.dir, self.db, now=NOW), 1)
        self.assertFalse(normal.exists())
        self.assertTrue(locked.exists())
        self.assertEqual(len(logs.records), 1)
        self.assertIn(locked.name, logs.output[0])

    async def test_naive_now_treated_as_utc(self):
        old = self.write_file(str(uuid.uuid4()), age=timedelta(hours=2))
        self.assertEqual(await delete_orphan_files(self.dir, self.db, now=NOW.replace(tzinfo=None)), 1)
        self.assertFalse(old.exists())


# ── job scheduler ────────────────────────────────────────────────────────────

class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class SchedulerJobTests(unittest.IsolatedAsyncioTestCase):
    def patches(self, *, expire, orphans):
        stack = contextlib.ExitStack()
        stack.enter_context(patch("app.core.database.AsyncSessionLocal", lambda: _FakeSession()))
        stack.enter_context(patch.object(maintenance, "expire_items", expire))
        stack.enter_context(patch.object(maintenance, "delete_orphan_files", orphans))
        return stack

    async def test_both_steps_run_even_when_one_fails(self):
        orphans = AsyncMock(return_value=2)
        with self.patches(expire=AsyncMock(side_effect=RuntimeError("db mati")), orphans=orphans), \
                self.assertLogs("jatahku.scheduler", level="INFO") as logs:
            await scheduler_mod.kotak_maintenance()  # tidak melempar
        orphans.assert_awaited_once()
        self.assertEqual(orphans.await_args.args[0], get_settings().KOTAK_DIR)
        self.assertIn("now", orphans.await_args.kwargs)
        self.assertTrue(any(r.levelname == "ERROR" and "expire_items" in r.getMessage() for r in logs.records))
        self.assertTrue(any(r.levelname == "INFO" and "2" in r.getMessage() for r in logs.records))

        expire = AsyncMock(return_value=3)
        with self.patches(expire=expire, orphans=AsyncMock(side_effect=OSError("disk"))), \
                self.assertLogs("jatahku.scheduler", level="INFO") as logs:
            await scheduler_mod.kotak_maintenance()
        expire.assert_awaited_once()
        self.assertIn("now", expire.await_args.kwargs)
        self.assertTrue(any(r.levelname == "ERROR" and "delete_orphan_files" in r.getMessage() for r in logs.records))
        self.assertTrue(any(r.levelname == "INFO" and "3" in r.getMessage() for r in logs.records))

    async def test_quiet_when_nothing_to_do(self):
        with self.patches(expire=AsyncMock(return_value=0), orphans=AsyncMock(return_value=0)), \
                self.assertNoLogs("jatahku.scheduler", level="INFO"):
            await scheduler_mod.kotak_maintenance()

    def test_registered_hourly(self):
        # Cron menit 17 tiap jam (bukan interval): interval baru jalan 1 jam setelah tiap restart/deploy.
        fake = MagicMock()
        with patch.object(scheduler_mod, "scheduler", fake):
            scheduler_mod.start_scheduler()
        calls = [c for c in fake.add_job.call_args_list if c.args and c.args[0] is scheduler_mod.kotak_maintenance]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs, {"trigger": "cron", "minute": 17, "id": "kotak_maintenance",
                                           "replace_existing": True})
        # Job pembersih teks OCR 24 jam tetap ada.
        self.assertTrue(any(c.kwargs.get("id") == "purge_receipt_ocr_text" for c in fake.add_job.call_args_list))


# ── statistik Admin ──────────────────────────────────────────────────────────

class StatsTests(MaintenanceBase):
    async def test_stats_breakdown(self):
        await self.item(status="siap", doc_type="qris", document={"issuer": "bca_mobile"})
        await self.item(status="siap", doc_type="tidak_dikenali", document={})
        s = await accuracy_stats(self.db, since=NOW - timedelta(days=1))
        self.assertEqual((s["by_doc_type"]["qris"], s["unrecognized"], s["by_issuer"]["bca_mobile"]["total"]), (1, 1, 1))

    async def test_breakdown_counts_only_this_period_and_kotak_rows(self):
        await self.item(status="siap", doc_type="qris", document={"issuer": "bca_mobile"})
        await self.item(status="gagal", doc_type="tidak_dikenali", document=None)
        await self.item(status="tercatat", doc_type="struk_belanja", document={"issuer": None}, outcome="accepted")
        await self.item(status="diterima")  # belum dibaca: tanpa doc_type
        # Baris lama (status NULL): tetap dihitung di kunci lama, tidak di kunci baru.
        await self.item(status=None, outcome="accepted", document={"issuer": "bca_mobile"})
        # Bulan lalu: tidak dihitung sama sekali.
        await self.item(status="siap", doc_type="qris", document={"issuer": "bca_mobile"},
                        created_at=NOW - timedelta(days=40))
        s = await accuracy_stats(self.db, since=NOW - timedelta(days=1))
        self.assertEqual(s["by_doc_type"], {"qris": 1, "tidak_dikenali": 1, "struk_belanja": 1})
        self.assertEqual(s["unrecognized"], 1)
        self.assertEqual(s["by_issuer"], {"bca_mobile": {"total": 1, "recorded": 0, "corrected": 0}})
        self.assertEqual((s["total"], s["accepted"], s["pending"]), (5, 2, 3))

    async def test_old_keys_unchanged(self):
        await self.item(status=None, outcome="accepted", merchant_key="INDOMARET")
        await self.item(status=None, outcome="corrected", merchant_key="ALFAMART", engine="llm")
        await self.item(status=None, outcome="corrected", merchant_key="ALFAMART")
        await self.item(status=None, outcome="discarded")
        await self.item(status=None, outcome="expired")
        await self.item(status="siap", doc_type="qris", document={"issuer": "dana"})
        s = await accuracy_stats(self.db, since=NOW - timedelta(days=1))
        old = {k: s[k] for k in ("total", "accepted", "corrected", "discarded", "expired", "pending", "llm",
                                 "accuracy_pct", "most_corrected")}
        self.assertEqual(old, {"total": 6, "accepted": 1, "corrected": 2, "discarded": 1, "expired": 1, "pending": 1,
                               "llm": 1, "accuracy_pct": 33.3,
                               "most_corrected": [{"merchant_key": "ALFAMART", "count": 2}]})
        self.assertEqual(set(s) - set(old), {"by_doc_type", "by_issuer", "unrecognized"})

    async def recorded(self, issuer, *, parsed_total, paid_at, txns, doc_type="qris", **cols):
        """Item tercatat dengan `transaction_ids` = txns (id transaksi, atau UUID acak untuk yang tidak ada)."""
        return await self.item(status="tercatat", doc_type=doc_type, document={"issuer": issuer},
                               parsed_total=None if parsed_total is None else Decimal(parsed_total),
                               paid_at=paid_at, transaction_ids=txns, **cols)

    async def test_proof_corrected_when_recorded_transaction_differs(self):
        today = date(2026, 10, 26)  # tanggal WIB dari NOW
        await self.recorded("bca_mobile", parsed_total=45000, paid_at=NOW, txns=[await self.txn(50000, today)])
        await self.recorded("gopay", parsed_total=45000, paid_at=NOW, txns=[await self.txn(45000, today)])
        # 18:00 UTC = 01:00 WIB keesokan harinya: tanggal transaksi = tanggal UTC berarti tanggalnya dikoreksi.
        late = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)
        await self.recorded("dana", parsed_total=45000, paid_at=late, txns=[await self.txn(45000, date(2026, 10, 25))])
        await self.recorded("ovo", parsed_total=45000, paid_at=late, txns=[await self.txn(45000, today)])
        # Nominal tidak terbaca: user mengisinya sendiri.
        await self.recorded("shopeepay", parsed_total=None, paid_at=NOW, txns=[await self.txn(45000, today)])
        # Tanpa jam bayar: hanya nominal yang dibandingkan.
        await self.recorded("livin", parsed_total=45000, paid_at=None, txns=[await self.txn(45000, date(2026, 1, 1))])
        # Transaksi pertama yang MASIH ADA yang dipakai: id pertama hilang, id kedua tidak sah, transaksi ketiga
        # (50.000 = dikoreksi) dipakai, bukan yang keempat (45.000 = cocok). Hanya aturan itu yang memberi 1.
        await self.recorded("brimo", parsed_total=45000, paid_at=NOW,
                            txns=[str(uuid.uuid4()), "bukan-uuid", await self.txn(50000, today),
                                  await self.txn(45000, today)])
        # Belum dicatat: dihitung total, bukan recorded/corrected.
        await self.item(status="siap", doc_type="qris", document={"issuer": "gopay"}, parsed_total=Decimal(1))
        s = await accuracy_stats(self.db, since=NOW - timedelta(days=1))
        self.assertEqual(s["by_issuer"], {
            "bca_mobile": {"total": 1, "recorded": 1, "corrected": 1},
            "gopay": {"total": 2, "recorded": 1, "corrected": 0},
            "dana": {"total": 1, "recorded": 1, "corrected": 1},
            "ovo": {"total": 1, "recorded": 1, "corrected": 0},
            "shopeepay": {"total": 1, "recorded": 1, "corrected": 1},
            "livin": {"total": 1, "recorded": 1, "corrected": 0},
            "brimo": {"total": 1, "recorded": 1, "corrected": 1},
        })

    async def test_transaction_lookup_is_chunked(self):
        # Semua nominal beda dari parsed_total: tiap transaksi yang TERBACA memberi corrected 1, transaksi yang tidak
        # pernah dibaca (potongan terlewat) memberi 0. Jadi irisan yang salah selalu gagal, apa pun urutan id-nya.
        today = date(2026, 10, 26)
        for i, amount in enumerate((50000, 60000, 70000, 80000, 99000)):
            await self.recorded(f"bank{i}", parsed_total=45000, paid_at=NOW, txns=[await self.txn(amount, today)])
        with patch("app.services.receipt_scan.ID_CHUNK", 2), \
                patch.object(self.db, "execute", wraps=self.db.execute) as spy:
            s = await accuracy_stats(self.db, since=NOW - timedelta(days=1))
        self.assertEqual(selects_from(spy, "transactions"), 3)
        self.assertEqual({k: v["corrected"] for k, v in s["by_issuer"].items()}, {f"bank{i}": 1 for i in range(5)})

    async def test_store_receipt_corrected_follows_outcome(self):
        today = date(2026, 10, 26)
        # Struk belanja: koreksi = outcome 'corrected' (feedback), bukan perbandingan dengan transaksi.
        await self.recorded("struk_x", doc_type="struk_belanja", parsed_total=45000, paid_at=NOW,
                            txns=[await self.txn(99000, today)], outcome="accepted")
        await self.recorded("struk_x", doc_type="struk_belanja", parsed_total=45000, paid_at=NOW,
                            txns=[await self.txn(45000, today)], outcome="corrected")
        await self.item(status="dilewati", doc_type="struk_belanja", document={"issuer": "struk_x"}, outcome="corrected")
        s = await accuracy_stats(self.db, since=NOW - timedelta(days=1))
        self.assertEqual(s["by_issuer"], {"struk_x": {"total": 3, "recorded": 2, "corrected": 2}})


if __name__ == "__main__":
    unittest.main()
