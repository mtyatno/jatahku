"""Siklus household, Task 5: `set_household_payday`, `recompute_history` (diserialkan per household) dan
`notify_payday_changed`.

Tanpa Postgres: `db_with(...)` / `FakeResult` dari app/tests/fakes.py; user/household memakai SimpleNamespace; IO di
sekeliling (`recompute_history`, `advisor_cache.invalidate`, `notification_service.kirim`, `_current_payday`,
`rollover.recompute_household`, `AsyncSessionLocal`) di-patch. Kunci recompute terikat ke event loop pertama yang
memperebutkannya, jadi tiap tes yang berebut kunci memakai id household baru.
Run: python -m unittest app.tests.test_household_cycle_change -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.models import HouseholdRole, NotificationType
from app.services import household_cycle as hc
from app.tests.fakes import FakeResult, db_with, executed_sql

TITLE = "Siklus anggaran rumah berubah"
OWNER_MESSAGE = (
    "Tanggal gajian Rumah Budi kini tanggal 25 (diubah Budi). Riwayat 12 periode terakhir dihitung ulang."
)
SCRIPT_MESSAGE = (
    "Siklus anggaranmu kini mengikuti Rumah Ani: tanggal 25. Riwayat 12 periode terakhir dihitung ulang."
)
OWNER_ROW_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)  # `created_at` seperti dari DB: timestamptz (aware)


class FakeSession:
    """Pengganti `AsyncSessionLocal()`: `async with` menghasilkan `db` tiruan (pola test_summary_senders)."""
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def norm(statement: str) -> str:
    """SQL hasil compile berisi newline antar klausa; rapatkan supaya assert tidak bergantung pada tata letak."""
    return " ".join(statement.split())


def person(name, payday=1):
    return SimpleNamespace(id=uuid.uuid4(), name=name, payday_day=payday)


def rumah_budi(payday=1):
    """Household "Rumah Budi" dengan dua anggota: Budi (pelaku) dan Ani. `db` mengembalikan keduanya untuk kueri
    anggota (`scalars().all()`)."""
    household = SimpleNamespace(id=uuid.uuid4(), name="Rumah Budi", payday_day=payday)
    budi, ani = person("Budi", payday), person("Ani", payday)
    return household, budi, ani, db_with(FakeResult(rows=[budi, ani]))


class SetHouseholdPaydayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Semua IO di sekitar langkah `set_household_payday` diganti; tiap tes memeriksa panggilannya.
        self.recompute = AsyncMock(return_value=[{}] * 12)
        self.invalidate = AsyncMock()
        self.kirim = AsyncMock(return_value={"web"})
        self.enterContext(patch.object(hc, "recompute_history", self.recompute))
        self.enterContext(patch.object(hc.advisor_cache, "invalidate", self.invalidate))
        self.enterContext(patch.object(hc.notification_service, "kirim", self.kirim))

    async def test_rejects_out_of_range(self):
        household, budi, _, _ = rumah_budi()
        db = db_with()
        for day in (-1, 0, 32, 100):
            with self.subTest(day=day):
                with self.assertRaisesRegex(ValueError, "payday_day harus antara 1 dan 31"):
                    await hc.set_household_payday(db, household, day, actor=budi)
        db.execute.assert_not_called()  # ditolak sebelum kueri apa pun
        db.commit.assert_not_awaited()
        self.recompute.assert_not_awaited()
        self.kirim.assert_not_awaited()
        self.assertEqual(household.payday_day, 1)

    async def test_accepts_boundary_days(self):
        for day in (1, 31):
            with self.subTest(day=day):
                household, budi, ani, db = rumah_budi(payday=15)
                result = await hc.set_household_payday(db, household, day, actor=budi)
                self.assertIs(result["changed"], True)
                self.assertEqual((household.payday_day, budi.payday_day, ani.payday_day), (day, day, day))

    async def test_same_day_is_noop(self):
        household, budi, _, _ = rumah_budi(payday=25)
        db = db_with()
        self.assertEqual(await hc.set_household_payday(db, household, 25, actor=budi), {"changed": False})
        self.recompute.assert_not_awaited()
        self.kirim.assert_not_awaited()
        self.invalidate.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.execute.assert_not_called()  # anggota pun tidak dimuat

    async def test_change_syncs_all_members_and_recomputes_12(self):
        household, budi, ani, db = rumah_budi(payday=1)
        result = await hc.set_household_payday(db, household, 25, actor=budi)
        self.assertEqual(household.payday_day, 25)
        self.assertEqual((budi.payday_day, ani.payday_day), (25, 25))
        db.commit.assert_awaited_once()
        self.invalidate.assert_awaited_once_with(household.id)
        self.recompute.assert_awaited_once_with(household.id, 12)
        self.assertEqual(result, {"changed": True, "members": 2, "recomputed": 12})
        (stmt,) = executed_sql(db)  # satu kueri: `User` anggota household ini (kueri yang sama dengan heal)
        self.assertTrue(norm(stmt).startswith("SELECT users.id, users.email"))
        self.assertIn("FROM users JOIN household_members ON household_members.user_id = users.id", norm(stmt))
        self.assertIn("WHERE household_members.household_id = %(household_id_1)s::UUID", norm(stmt))

    async def test_steps_run_in_spec_order(self):
        # commit dulu (recompute membaca lewat sesi lain), baru hapus cache, hitung ulang, lalu beri tahu.
        household, budi, ani, db = rumah_budi(payday=1)
        events, days_at_commit = [], []

        async def on_commit():
            events.append("commit")
            days_at_commit.append((household.payday_day, budi.payday_day, ani.payday_day))

        def recorder(name, result=None):
            async def record(*args, **kwargs):
                events.append(name)
                return result
            return record

        db.commit.side_effect = on_commit
        self.invalidate.side_effect = recorder("invalidate")
        self.recompute.side_effect = recorder("recompute", [{}] * 12)
        self.kirim.side_effect = recorder("kirim", {"web"})
        await hc.set_household_payday(db, household, 25, actor=budi)
        self.assertEqual(events, ["commit", "invalidate", "recompute", "kirim"])
        self.assertEqual(days_at_commit, [(25, 25, 25)])  # household dan semua cermin sudah di-assign saat commit

    async def test_null_household_payday_equal_to_derived_is_noop(self):
        # Household belum dimigrasi: tanggalnya diturunkan dari anggota (owner 25), bukan dibandingkan sebagai None.
        household = SimpleNamespace(id=uuid.uuid4(), name="Rumah Budi", payday_day=None)
        budi = person("Budi", 25)
        db = db_with(FakeResult(rows=[(HouseholdRole.owner, OWNER_ROW_DATE, budi.id, "Budi", 25)]))
        self.assertEqual(await hc.set_household_payday(db, household, 25, actor=budi), {"changed": False})
        self.assertEqual(household.payday_day, 25)  # terisi oleh household_payday
        db.commit.assert_not_awaited()
        self.recompute.assert_not_awaited()
        self.kirim.assert_not_awaited()

    async def test_null_household_payday_differing_from_derived_changes(self):
        household = SimpleNamespace(id=uuid.uuid4(), name="Rumah Budi", payday_day=None)
        budi, ani = person("Budi", 25), person("Ani", 1)
        db = db_with(
            FakeResult(rows=[(HouseholdRole.owner, OWNER_ROW_DATE, budi.id, "Budi", 25)]),  # member_rows (turunan)
            FakeResult(rows=[budi, ani]),  # User anggota
        )
        result = await hc.set_household_payday(db, household, 10, actor=budi)
        self.assertEqual(result, {"changed": True, "members": 2, "recomputed": 12})
        self.assertEqual((household.payday_day, budi.payday_day, ani.payday_day), (10, 10, 10))
        self.assertEqual(db.execute.await_count, 2)
        db.commit.assert_awaited_once()

    async def test_notifies_members_except_actor(self):
        household, budi, ani, db = rumah_budi(payday=1)
        await hc.set_household_payday(db, household, 25, actor=budi)
        self.kirim.assert_awaited_once()  # hanya Ani; Budi sendiri yang mengubahnya
        call = self.kirim.await_args
        self.assertIs(call.args[0], ani)
        self.assertEqual(call.args[1:], (NotificationType.system, TITLE, OWNER_MESSAGE))
        self.assertEqual(call.kwargs, {"link": "/settings"})
        self.assertNotIn("telegram_html", call.kwargs)  # kirim yang meng-escape judul/pesan untuk Telegram

    async def test_solo_household_sends_no_notification(self):
        household = SimpleNamespace(id=uuid.uuid4(), name="Rumah Budi", payday_day=1)
        budi = person("Budi")
        db = db_with(FakeResult(rows=[budi]))
        result = await hc.set_household_payday(db, household, 25, actor=budi)
        self.assertEqual(result, {"changed": True, "members": 1, "recomputed": 12})
        self.recompute.assert_awaited_once_with(household.id, 12)
        self.kirim.assert_not_awaited()

    async def test_notification_failure_keeps_change(self):
        household, budi, ani, db = rumah_budi(payday=1)
        self.kirim.side_effect = RuntimeError("telegram mati")
        with self.assertLogs("jatahku.household_cycle", "ERROR") as logs:
            result = await hc.set_household_payday(db, household, 25, actor=budi)
        self.assertEqual(result, {"changed": True, "members": 2, "recomputed": 12})
        self.assertEqual((household.payday_day, budi.payday_day, ani.payday_day), (25, 25, 25))
        db.commit.assert_awaited_once()
        self.recompute.assert_awaited_once_with(household.id, 12)
        self.assertEqual(len(logs.records), 1)
        self.assertIn(str(ani.id), logs.output[0])  # siapa yang gagal diberi tahu
        self.assertIn("telegram mati", logs.output[0])  # dan sebabnya


class NotifyPaydayChangedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.kirim = AsyncMock(return_value={"web"})
        self.enterContext(patch.object(hc.notification_service, "kirim", self.kirim))

    async def test_notify_payday_changed_script_message(self):
        ani = person("Ani")
        sent = await hc.notify_payday_changed([ani], household_name="Rumah Ani", day=25, changed_by=None, periods=12)
        self.assertEqual(sent, 1)
        self.kirim.assert_awaited_once()
        call = self.kirim.await_args
        self.assertIs(call.args[0], ani)
        self.assertEqual(call.args[1:], (NotificationType.system, TITLE, SCRIPT_MESSAGE))
        self.assertEqual(call.kwargs, {"link": "/settings"})
        self.assertNotIn("telegram_html", call.kwargs)

    async def test_notify_payday_changed_owner_message_uses_given_periods(self):
        await hc.notify_payday_changed(
            [person("Ani")], household_name="Rumah Ani", day=5, changed_by="Budi", periods=6
        )
        self.assertEqual(
            self.kirim.await_args.args[3],
            "Tanggal gajian Rumah Ani kini tanggal 5 (diubah Budi). Riwayat 6 periode terakhir dihitung ulang.",
        )

    async def test_notify_payday_changed_counts_successes_and_continues_after_failure(self):
        first, second, third = person("A"), person("B"), person("C")
        self.kirim.side_effect = [RuntimeError("gagal"), {"web"}, {"web", "telegram"}]
        with self.assertLogs("jatahku.household_cycle", "ERROR") as logs:
            sent = await hc.notify_payday_changed(
                [first, second, third], household_name="Rumah Ani", day=25, changed_by="Ani", periods=12
            )
        self.assertEqual(sent, 2)  # yang gagal tidak dihitung, dan tidak menghentikan yang berikutnya
        self.assertEqual([c.args[0] for c in self.kirim.await_args_list], [first, second, third])
        self.assertEqual(len(logs.records), 1)
        self.assertIn(str(first.id), logs.output[0])


class RecomputeHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recompute_history_uses_latest_payday(self):
        hid = uuid.uuid4()
        periods = [{"period": "2026-09-25 → 2026-10-24", "processed": 3, "snapshots_created": 3, "errors": []}]
        current = AsyncMock(return_value=25)
        recompute = AsyncMock(return_value=periods)
        with patch.object(hc, "_current_payday", current), patch.object(hc.rollover, "recompute_household", recompute):
            with self.assertNoLogs("jatahku.household_cycle", "ERROR"):  # periode tanpa error tidak dicatat
                result = await hc.recompute_history(hid, 12)
        current.assert_awaited_once_with(hid)
        recompute.assert_awaited_once_with(hid, 25, 12)
        self.assertEqual(result, periods)

    async def test_recompute_history_serialises_and_reads_latest_payday(self):
        hid = uuid.uuid4()  # kunci terikat ke loop tes ini: id baru per tes
        log = []

        async def fake_recompute(household_id, payday, periods):
            log.append(("start", payday))
            await asyncio.sleep(0.01)
            log.append(("end", payday))
            return []

        with patch.object(hc, "_current_payday", AsyncMock(side_effect=[2, 25])), \
                patch.object(hc.rollover, "recompute_household", fake_recompute):
            await asyncio.gather(hc.recompute_history(hid, 12), hc.recompute_history(hid, 12))
        self.assertEqual(log, [("start", 2), ("end", 2), ("start", 25), ("end", 25)])

    async def test_recompute_history_reads_payday_inside_the_lock(self):
        # Tanggal dibaca SETELAH recompute sebelumnya selesai: yang berebut kunci tidak membawa tanggal basi.
        hid = uuid.uuid4()
        log = []

        async def read_payday(household_id):
            log.append("read")
            return 25

        async def fake_recompute(household_id, payday, periods):
            log.append("start")
            await asyncio.sleep(0.01)
            log.append("end")
            return []

        with patch.object(hc, "_current_payday", read_payday), \
                patch.object(hc.rollover, "recompute_household", fake_recompute):
            await asyncio.gather(hc.recompute_history(hid, 12), hc.recompute_history(hid, 12))
        self.assertEqual(log, ["read", "start", "end", "read", "start", "end"])

    async def test_recompute_history_does_not_block_other_households(self):
        first, second = uuid.uuid4(), uuid.uuid4()
        log = []

        async def fake_recompute(household_id, payday, periods):
            log.append("start")
            await asyncio.sleep(0.01)
            log.append("end")
            return []

        with patch.object(hc, "_current_payday", AsyncMock(return_value=25)), \
                patch.object(hc.rollover, "recompute_household", fake_recompute):
            await asyncio.gather(hc.recompute_history(first, 12), hc.recompute_history(second, 12))
        self.assertEqual(log, ["start", "start", "end", "end"])  # berjalan bersamaan: kunci per household

    async def test_recompute_history_releases_lock_after_failure(self):
        hid = uuid.uuid4()
        recompute = AsyncMock(side_effect=[RuntimeError("db mati"), []])
        with patch.object(hc, "_current_payday", AsyncMock(return_value=25)), \
                patch.object(hc.rollover, "recompute_household", recompute):
            with self.assertRaises(RuntimeError):
                await hc.recompute_history(hid, 12)
            # Kunci yang tertahan membuat panggilan kedua menggantung; timeout mengubahnya jadi kegagalan tes.
            self.assertEqual(await asyncio.wait_for(hc.recompute_history(hid, 12), timeout=1), [])

    async def test_recompute_history_logs_period_errors(self):
        hid = uuid.uuid4()
        results = [
            {"period": "2026-08-25 → 2026-09-24", "processed": 2, "snapshots_created": 1, "errors": ["Makan: boom"]},
            {"period": "2026-09-25 → 2026-10-24", "processed": 2, "snapshots_created": 2, "errors": []},
        ]
        with patch.object(hc, "_current_payday", AsyncMock(return_value=25)), \
                patch.object(hc.rollover, "recompute_household", AsyncMock(return_value=results)):
            with self.assertLogs("jatahku.household_cycle", "ERROR") as logs:
                returned = await hc.recompute_history(hid, 12)
        self.assertEqual(returned, results)  # daftar penuh tetap dikembalikan; tidak raise
        self.assertEqual(len(logs.records), 1)  # hanya periode yang bermasalah
        message = logs.records[0].getMessage()
        for part in (str(hid), "2026-08-25 → 2026-09-24", "Makan: boom"):
            self.assertIn(part, message)


class CurrentPaydayTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_payday_reads_in_own_session_and_commits(self):
        hid = uuid.uuid4()
        household = SimpleNamespace(id=hid, name="Rumah Ani", payday_day=25)
        db = db_with(FakeResult(household))
        with patch.object(hc, "AsyncSessionLocal", new=lambda: FakeSession(db)):
            self.assertEqual(await hc._current_payday(hid), 25)
        (stmt,) = executed_sql(db)
        self.assertTrue(norm(stmt).endswith("FROM households WHERE households.id = %(id_1)s::UUID"))
        db.flush.assert_not_awaited()  # terisi: dikembalikan apa adanya
        db.commit.assert_awaited_once()

    async def test_current_payday_fills_null_and_commits(self):
        hid = uuid.uuid4()
        household = SimpleNamespace(id=hid, name="Rumah Ani", payday_day=None)
        db = db_with(
            FakeResult(household),
            FakeResult(rows=[(HouseholdRole.owner, OWNER_ROW_DATE, uuid.uuid4(), "Ani", 25)]),
        )
        with patch.object(hc, "AsyncSessionLocal", new=lambda: FakeSession(db)):
            self.assertEqual(await hc._current_payday(hid), 25)
        self.assertEqual(household.payday_day, 25)
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()  # sesi ini yang menyimpan pengisian NULL


if __name__ == "__main__":
    unittest.main()
