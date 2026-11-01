"""Siklus household, Task 8: `POST /snapshots/recompute` hanya untuk yang boleh mengubah siklus rumah (owner/admin, atau
member yang sendirian) dan menghitung ulang lewat `recompute_history` dengan tanggal gajian rumah; `POST /snapshots/run`
(admin/debug) menghitung tiap household dengan tanggal gajiannya sendiri, bukan tanggal si pemanggil, di dalam
`household_lock` dengan tanggal yang dibaca di dalam kunci, dan hanya untuk periode yang sudah tertutup.

Tanpa Postgres: handler dipanggil langsung; `payday_context`, `recompute_history`, `household_payday`, `current_payday`,
`create_monthly_snapshots`, dan `date` di-patch pada modul route `snapshots` (diimpor di level modul); `db_with(...)` /
`FakeResult` dari app/tests/fakes.py. Konteks memakai `PaydayContext` asli supaya nama fieldnya ikut terkunci. Kunci
household asli (`household_cycle.household_lock`) terikat ke event loop tempat ia pertama kali diperebutkan, jadi tiap
tes memakai id household baru.
Run: python -m unittest app.tests.test_snapshots_household -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import unittest
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from fastapi import HTTPException

from app.api.routes import snapshots
from app.models.models import HouseholdRole
from app.services import household_cycle
from app.services.household_cycle import PaydayContext
from app.tests.fakes import FakeResult, db_with, executed_sql, fixed_date

RECOMPUTE_403 = "Hanya owner atau admin rumah tangga yang bisa menghitung ulang riwayat."
NOTHING_DONE = {"processed": 0, "snapshots_created": 0, "errors": []}


def make_user(**override):
    """Pemanggil endpoint. Tanggal gajiannya (10) sengaja berbeda dari semua tanggal rumah di tes ini: tanggal
    pemanggil tidak boleh ikut menentukan periode."""
    fields = dict(id=uuid.uuid4(), name="Budi", payday_day=10, is_admin=False)
    fields.update(override)
    return SimpleNamespace(**fields)


def rumah_ani(*, can_change, payday=25, members=2, owner_name="Ani", role=HouseholdRole.member):
    """`PaydayContext` rumah "Rumah Ani". Bawaan: member di rumah beranggota dua, jadi tidak boleh mengubah siklus."""
    household = SimpleNamespace(id=uuid.uuid4(), name="Rumah Ani", payday_day=payday)
    return PaydayContext(
        household=household, role=role, payday_day=payday, member_count=members,
        can_change=can_change, owner_name=owner_name,
    )


def make_household():
    return SimpleNamespace(id=uuid.uuid4(), name="Rumah", payday_day=None)


class RecomputeTests(unittest.IsolatedAsyncioTestCase):
    def stub_service(self, context, history=None):
        """Ganti `payday_context` (mengembalikan `context`) dan `recompute_history` di modul route.
        `create_monthly_snapshots` ikut di-patch: rute tidak boleh lagi menghitung sendiri per periode, semuanya
        lewat service."""
        self.payday_context = AsyncMock(return_value=context)
        self.history = AsyncMock(return_value=[] if history is None else history)
        self.create = AsyncMock()
        self.enterContext(patch.object(snapshots, "payday_context", self.payday_context))
        self.enterContext(patch.object(snapshots, "recompute_history", self.history))
        self.enterContext(patch.object(snapshots, "create_monthly_snapshots", self.create))

    async def test_recompute_member_of_two_403(self):
        user, db = make_user(), db_with()
        self.stub_service(rumah_ani(can_change=False))
        with self.assertRaises(HTTPException) as caught:
            await snapshots.recompute_snapshots(periods=6, user=user, db=db)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, RECOMPUTE_403)
        # Yang ditolak tidak menghitung apa pun dan tidak menyimpan apa pun (commit baru sesudah cek izin).
        self.history.assert_not_awaited()
        self.create.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_recompute_owner_uses_household_history(self):
        user, db = make_user(), db_with()
        context = rumah_ani(can_change=True, role=HouseholdRole.owner, owner_name=None)
        out = [
            {"period": "2026-07-25 → 2026-08-24", "processed": 3, "snapshots_created": 3, "errors": []},
            {"period": "2026-08-25 → 2026-09-24", "processed": 3, "snapshots_created": 2, "errors": ["Makan: x"]},
        ]
        self.stub_service(context, out)

        result = await snapshots.recompute_snapshots(periods=6, user=user, db=db)

        self.payday_context.assert_awaited_once_with(db, user)
        self.history.assert_awaited_once_with(context.household.id, 6)
        self.create.assert_not_awaited()
        # `recomputed` = jumlah periode yang dikembalikan service (2), bukan `periods` yang diminta (6).
        self.assertEqual(result, {"recomputed": 2, "periods": out})

    async def test_recompute_forwards_requested_periods(self):
        user, db = make_user(), db_with()
        context = rumah_ani(can_change=True, role=HouseholdRole.admin, owner_name="Ani")
        self.stub_service(context)

        await snapshots.recompute_snapshots(periods=24, user=user, db=db)

        self.history.assert_awaited_once_with(context.household.id, 24)

    async def test_recompute_without_household(self):
        user, db = make_user(), db_with()
        self.stub_service(None)

        result = await snapshots.recompute_snapshots(periods=6, user=user, db=db)

        self.assertEqual(result, {"recomputed": 0, "periods": []})
        self.history.assert_not_awaited()
        self.create.assert_not_awaited()

    async def test_recompute_commits_before_history(self):
        # R7: `recompute_history` membaca lewat sesinya sendiri dan tidak boleh berhadapan dengan tulisan sesi request
        # yang belum di-commit. `payday_context` bisa mengisi tanggal rumah yang NULL (flush), jadi urutannya: konteks
        # (dan cek izin), commit, baru recompute.
        user, db = make_user(), db_with()
        context = rumah_ani(can_change=True, role=HouseholdRole.owner, owner_name=None)
        self.stub_service(context)
        order = []

        async def get_context(_db, _user):
            order.append("payday_context")
            return context

        async def history(_household_id, _periods):
            order.append("recompute_history")
            return []

        self.payday_context.side_effect = get_context
        self.history.side_effect = history
        db.commit.side_effect = lambda: order.append("commit")

        await snapshots.recompute_snapshots(periods=6, user=user, db=db)

        self.assertEqual(order, ["payday_context", "commit", "recompute_history"])


# `POST /snapshots/run` memutuskan periode mana yang sudah tertutup dengan tanggal hari ini; tes mematoknya.
RUN_TODAY = date(2026, 11, 1)


def skipped(household, period, reason):
    """Entri household yang dilewati `POST /snapshots/run`: kunci yang sama dengan entri lain, angka nol, alasannya."""
    return {
        "household_id": str(household.id), "period": period, "processed": 0, "snapshots_created": 0, "errors": [],
        "skipped": reason,
    }


class RunTests(unittest.IsolatedAsyncioTestCase):
    """`POST /snapshots/run` (admin/debug). Tahap pertama mengisi tanggal rumah yang NULL dan commit; tahap kedua per
    household di dalam `household_lock` (kunci yang sama dengan recompute dan job harian), tanggal DIBACA ULANG di
    dalam kunci (`current_payday`), dan hanya periode TERTUTUP yang ditulis. Periode berjalan atau yang belum mulai
    dilewati dengan alasan: job harian (tanpa `force`) tidak pernah menimpa kunci yang sudah ada, jadi snapshot periode
    yang belum tutup membawa rollover yang salah ke semua periode sesudahnya."""

    def stub_service(self, *, paydays, created, fresh=None, today=RUN_TODAY):
        """`household_payday` (tahap pertama, mengisi NULL): `side_effect` `paydays`. `current_payday` (bacaan di dalam
        kunci) mengembalikan `self.stored[id]`: bawaannya nilai tahap pertama; `fresh` ({id household: tanggal, None
        (household sudah dihapus), atau exception}) menggantinya. `self.read_under_lock` mencatat, untuk tiap bacaan
        itu, apakah kunci household-nya dipegang. `create_monthly_snapshots`: satu hasil untuk semua panggilan bila
        `created` dict, selain itu `side_effect`. `date.today()` di route dipatok ke `today`."""
        self.household_payday = AsyncMock(side_effect=paydays)
        self.create = AsyncMock(return_value=created) if isinstance(created, dict) else AsyncMock(side_effect=created)
        self.stored = dict(fresh or {})
        self.read_under_lock = []

        async def first_read(db, household):
            value = await self.household_payday(db, household)
            self.stored.setdefault(household.id, value)
            return value

        async def read_inside_lock(household_id):
            self.read_under_lock.append(household_cycle.household_lock(household_id).locked())
            value = self.stored[household_id]
            if isinstance(value, BaseException):
                raise value
            return value

        self.current_payday = AsyncMock(side_effect=read_inside_lock)
        self.enterContext(patch.object(snapshots, "household_payday", first_read))
        self.enterContext(patch.object(snapshots, "current_payday", self.current_payday))
        self.enterContext(patch.object(snapshots, "create_monthly_snapshots", self.create))
        self.enterContext(patch.object(snapshots, "date", fixed_date(today)))

    async def run_snapshot(self, db, **params):
        params = {"year": 2026, "month": 9, "force": False, **params}
        return await snapshots.run_monthly_snapshot(user=make_user(is_admin=True), db=db, **params)

    async def test_run_uses_each_household_payday(self):
        h1, h2 = make_household(), make_household()
        db = db_with(FakeResult(rows=[h1, h2]))
        self.stub_service(
            paydays=[1, 25], created={"processed": 2, "snapshots_created": 2, "errors": []}
        )

        result = await self.run_snapshot(db)

        self.assertEqual(self.household_payday.await_args_list, [call(db, h1), call(db, h2)])
        # Tanggal si admin (10) tidak dipakai: tiap household dihitung dengan tanggalnya sendiri.
        self.assertEqual(self.create.await_args_list, [
            call(date(2026, 9, 1), date(2026, 9, 30), force=False, household_ids=[h1.id]),
            call(date(2026, 9, 25), date(2026, 10, 24), force=False, household_ids=[h2.id]),
        ])
        self.assertEqual(result["processed"], 4)
        self.assertEqual(result["snapshots_created"], 4)
        self.assertEqual(result["households"][1]["period"], "2026-09-25 → 2026-10-24")
        self.assertEqual(result, {
            "households": [
                {"household_id": str(h1.id), "period": "2026-09-01 → 2026-09-30",
                 "processed": 2, "snapshots_created": 2, "errors": []},
                {"household_id": str(h2.id), "period": "2026-09-25 → 2026-10-24",
                 "processed": 2, "snapshots_created": 2, "errors": []},
            ],
            "processed": 4,
            "snapshots_created": 4,
            "errors": [],
        })
        db.commit.assert_awaited()

    async def test_run_combines_results_of_all_households(self):
        h1, h2, h3 = make_household(), make_household(), make_household()
        db = db_with(FakeResult(rows=[h1, h2, h3]))
        results = [
            {"processed": 3, "snapshots_created": 1, "errors": ["Makan: x"]},
            {"processed": 0, "snapshots_created": 0, "errors": []},
            {"processed": 5, "snapshots_created": 4, "errors": ["Listrik: y", "Air: z"]},
        ]
        self.stub_service(paydays=[1, 1, 25], created=results)

        result = await self.run_snapshot(db, force=True)

        self.assertEqual(result["processed"], 8)
        self.assertEqual(result["snapshots_created"], 5)
        self.assertEqual(result["errors"], ["Makan: x", "Listrik: y", "Air: z"])
        self.assertEqual([entry["household_id"] for entry in result["households"]], [str(h.id) for h in (h1, h2, h3)])
        self.assertEqual([entry["errors"] for entry in result["households"]], [r["errors"] for r in results])
        # `force` diteruskan ke setiap household (periode tertutup).
        self.assertEqual([c.kwargs["force"] for c in self.create.await_args_list], [True, True, True])

    async def test_run_without_year_month_uses_the_current_month_and_skips_it(self):
        # Tanpa year/month: periode yang MULAI di bulan berjalan menurut tanggal rumah (25 Sep–24 Okt pada 15 Sep),
        # bukan periode yang sedang berjalan (25 Agu–24 Sep). Periode yang mulai bulan ini tidak pernah tertutup (sedang
        # berjalan, atau belum mulai), jadi dilewati.
        h = make_household()
        db = db_with(FakeResult(rows=[h]))
        self.stub_service(paydays=[25], created=NOTHING_DONE, today=date(2026, 9, 15))

        result = await self.run_snapshot(db, year=None, month=None)

        self.create.assert_not_awaited()
        self.assertEqual(result["households"], [skipped(h, "2026-09-25 → 2026-10-24", "periode belum tertutup")])

    async def test_run_skips_the_open_period(self):
        # Tanggal 5, hari ini 10 Nov: periode yang mulai November (5 Nov–4 Des) sedang berjalan. Snapshot-nya berisi
        # angka setengah jalan, dan job (tanpa force) tidak pernah menimpanya.
        h = make_household()
        db = db_with(FakeResult(rows=[h]))
        self.stub_service(paydays=[5], created=NOTHING_DONE, today=date(2026, 11, 10))

        result = await self.run_snapshot(db, year=2026, month=11)

        self.create.assert_not_awaited()
        self.assertEqual(result, {
            "households": [skipped(h, "2026-11-05 → 2026-12-04", "periode belum tertutup")],
            "processed": 0,
            "snapshots_created": 0,
            "errors": [],
        })

    async def test_run_skips_a_future_period_even_with_force(self):
        # Tanggal 25, hari ini 10 Nov: periode yang mulai November (25 Nov–24 Des) belum mulai, dan pendahulunya
        # (kunci 2026-10) belum ada, jadi rollover masuknya akan terbaca 0.
        h = make_household()
        db = db_with(FakeResult(rows=[h]))
        self.stub_service(paydays=[25], created=NOTHING_DONE, today=date(2026, 11, 10))

        result = await self.run_snapshot(db, year=2026, month=11, force=True)

        self.create.assert_not_awaited()
        self.assertEqual(result["households"], [skipped(h, "2026-11-25 → 2026-12-24", "periode belum tertutup")])

    async def test_run_skips_a_period_on_its_last_day(self):
        # Hari terakhir periode masih periode berjalan.
        h = make_household()
        db = db_with(FakeResult(rows=[h]))
        self.stub_service(paydays=[1], created=NOTHING_DONE, today=date(2026, 11, 30))

        result = await self.run_snapshot(db, year=2026, month=11)

        self.create.assert_not_awaited()
        self.assertEqual(result["households"], [skipped(h, "2026-11-01 → 2026-11-30", "periode belum tertutup")])

    async def test_run_writes_a_period_the_day_after_it_closed(self):
        h = make_household()
        db = db_with(FakeResult(rows=[h]))
        built = {"processed": 2, "snapshots_created": 2, "errors": []}
        self.stub_service(paydays=[1], created=built, today=date(2026, 12, 1))

        result = await self.run_snapshot(db, year=2026, month=11)

        self.create.assert_awaited_once_with(date(2026, 11, 1), date(2026, 11, 30), force=False, household_ids=[h.id])
        self.assertEqual(
            result["households"], [{"household_id": str(h.id), "period": "2026-11-01 → 2026-11-30", **built}]
        )

    async def test_run_builds_the_window_from_the_payday_read_inside_the_lock(self):
        # Tahap pertama membaca tanggal baris household (1), tetapi saat kunci dipegang tanggal tersimpan sudah 25
        # (owner mengubahnya di antaranya). Bulan lalu sudah tertutup pada 26 Nov menurut kedua tanggal (1–31 Okt
        # maupun 25 Okt–24 Nov): jendela yang ditulis harus yang dari dalam kunci.
        h = make_household()
        db = db_with(FakeResult(rows=[h]))
        built = {"processed": 2, "snapshots_created": 2, "errors": []}
        self.stub_service(paydays=[1], fresh={h.id: 25}, created=built, today=date(2026, 11, 26))

        result = await self.run_snapshot(db, year=2026, month=10)

        self.current_payday.assert_awaited_once_with(h.id)
        self.create.assert_awaited_once_with(
            date(2026, 10, 25), date(2026, 11, 24), force=False, household_ids=[h.id]
        )
        self.assertEqual(
            result["households"], [{"household_id": str(h.id), "period": "2026-10-25 → 2026-11-24", **built}]
        )

    async def test_run_decides_closed_with_the_payday_read_inside_the_lock(self):
        # Balapan dari review, 10 Nov 2026: menurut tanggal tahap pertama (1) Oktober sudah tertutup, tetapi owner
        # baru memindahkannya ke 25, dan di bawah tanggal 25 kunci 2026-10 adalah periode BERJALAN (25 Okt–24 Nov) yang
        # baru dibuang recompute-nya. Menulisnya dengan jendela 1–31 Okt = kerusakan yang sama dengan jendela basi di
        # job.
        h = make_household()
        db = db_with(FakeResult(rows=[h]))
        self.stub_service(paydays=[1], fresh={h.id: 25}, created=NOTHING_DONE, today=date(2026, 11, 10))

        result = await self.run_snapshot(db, year=2026, month=10, force=True)

        self.create.assert_not_awaited()
        self.assertEqual(result["households"], [skipped(h, "2026-10-25 → 2026-11-24", "periode belum tertutup")])

    async def test_run_skips_a_household_that_no_longer_exists(self):
        # Household dihapus (merge / penghapusan akun) setelah tahap pertama: dilewati, yang lain tetap diproses.
        h1, h2 = make_household(), make_household()
        db = db_with(FakeResult(rows=[h1, h2]))
        built = {"processed": 2, "snapshots_created": 2, "errors": []}
        self.stub_service(paydays=[1, 25], fresh={h1.id: None}, created=built)

        result = await self.run_snapshot(db)

        self.create.assert_awaited_once_with(
            date(2026, 9, 25), date(2026, 10, 24), force=False, household_ids=[h2.id]
        )
        self.assertEqual(result["households"], [
            skipped(h1, None, "household tidak ada"),
            {"household_id": str(h2.id), "period": "2026-09-25 → 2026-10-24", **built},
        ])
        self.assertFalse(household_cycle.household_lock(h1.id).locked())

    async def test_run_isolates_a_failing_household(self):
        # Exception di satu household tidak menghentikan yang lain: dicatat lengkap dengan traceback, entrinya membawa
        # nama kelas exception (bukan pesannya), dan kuncinya dilepas.
        h1, h2, h3 = make_household(), make_household(), make_household()
        db = db_with(FakeResult(rows=[h1, h2, h3]))
        built = {"processed": 2, "snapshots_created": 2, "errors": []}
        self.stub_service(paydays=[1, 1, 25], created=[built, RuntimeError("db mati"), built])

        with self.assertLogs("jatahku.snapshots", "ERROR") as logs:
            result = await self.run_snapshot(db)

        self.assertEqual(self.create.await_count, 3)
        self.assertEqual(result["households"][1], {
            "household_id": str(h2.id), "period": "2026-09-01 → 2026-09-30",
            "processed": 0, "snapshots_created": 0, "errors": ["gagal: RuntimeError"],
        })
        self.assertEqual([entry["snapshots_created"] for entry in result["households"]], [2, 0, 2])
        self.assertEqual(result["processed"], 4)
        self.assertEqual(result["errors"], ["gagal: RuntimeError"])
        self.assertEqual(len(logs.records), 1)
        self.assertIn(str(h2.id), logs.records[0].getMessage())
        self.assertIn("db mati", logs.output[0])  # traceback ikut tercatat
        self.assertFalse(household_cycle.household_lock(h2.id).locked())

    async def test_run_isolates_a_failing_payday_read(self):
        # Gagal sebelum jendelanya diketahui: entri tanpa periode, household berikutnya tetap diproses.
        h1, h2 = make_household(), make_household()
        db = db_with(FakeResult(rows=[h1, h2]))
        built = {"processed": 2, "snapshots_created": 2, "errors": []}
        self.stub_service(paydays=[1, 25], fresh={h1.id: ConnectionError("putus")}, created=built)

        with self.assertLogs("jatahku.snapshots", "ERROR"):
            result = await self.run_snapshot(db)

        self.assertEqual(result["households"][0], {
            "household_id": str(h1.id), "period": None,
            "processed": 0, "snapshots_created": 0, "errors": ["gagal: ConnectionError"],
        })
        self.create.assert_awaited_once_with(
            date(2026, 9, 25), date(2026, 10, 24), force=False, household_ids=[h2.id]
        )

    async def test_run_holds_the_household_lock_while_reading_and_creating(self):
        h1, h2 = make_household(), make_household()
        db = db_with(FakeResult(rows=[h1, h2]))
        held = []

        async def create(start, end, *, force, household_ids):
            own = household_ids[0]
            other = h2.id if own == h1.id else h1.id
            held.append(
                (household_cycle.household_lock(own).locked(), household_cycle.household_lock(other).locked())
            )
            return dict(NOTHING_DONE)

        self.stub_service(paydays=[1, 25], created=create)

        await self.run_snapshot(db)

        self.assertEqual(self.read_under_lock, [True, True])  # tanggal dibaca SETELAH kunci dipegang
        self.assertEqual(held, [(True, False), (True, False)])  # kunci household sendiri saja
        for h in (h1, h2):
            self.assertFalse(household_cycle.household_lock(h.id).locked())

    async def test_run_waits_for_a_held_household_lock(self):
        # Kunci yang sama dengan recompute dan job harian: selagi salah satunya memegang kunci household ini, `run`
        # menunggu, dan baru membaca tanggalnya sesudah kunci dilepas.
        h = make_household()
        db = db_with(FakeResult(rows=[h]))
        self.stub_service(paydays=[1], created=NOTHING_DONE)
        lock = household_cycle.household_lock(h.id)

        async with lock:
            task = asyncio.create_task(self.run_snapshot(db))
            for _ in range(10):
                await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.current_payday.assert_not_awaited()
            self.create.assert_not_awaited()

        await asyncio.wait_for(task, timeout=1)
        self.create.assert_awaited_once()
        self.assertFalse(lock.locked())

    async def test_run_without_households(self):
        db = db_with(FakeResult(rows=[]))
        self.stub_service(paydays=[], created=NOTHING_DONE)

        result = await self.run_snapshot(db)

        self.assertEqual(result, {"households": [], "processed": 0, "snapshots_created": 0, "errors": []})
        self.household_payday.assert_not_awaited()
        self.create.assert_not_awaited()

    async def test_run_selects_only_households_with_members(self):
        db = db_with(FakeResult(rows=[]))
        self.stub_service(paydays=[], created=NOTHING_DONE)

        await self.run_snapshot(db)

        self.assertIn("households.id IN (SELECT household_members.household_id", executed_sql(db)[0])

    async def test_run_commits_fills_before_creating_snapshots(self):
        # `household_payday` mengisi tanggal rumah yang NULL dan flush di sesi request, sedangkan
        # `create_monthly_snapshots` (dan `current_payday`) bekerja lewat sesinya sendiri. Pengisian disimpan lebih
        # dulu (kontrak R7 seperti recompute): semua tanggal diisi, satu commit, baru snapshot dibuat; sesi lain tidak
        # pernah berhadapan dengan UPDATE yang belum di-commit.
        h1, h2 = make_household(), make_household()
        db = db_with(FakeResult(rows=[h1, h2]))
        order = []

        async def payday(_db, household):
            order.append(("payday", household.id))
            return 1

        async def create(_start, _end, *, force, household_ids):
            order.append(("create", household_ids[0]))
            return dict(NOTHING_DONE)

        self.stub_service(paydays=payday, created=create)
        db.commit.side_effect = lambda: order.append("commit")

        await self.run_snapshot(db)

        self.assertEqual(order, [
            ("payday", h1.id), ("payday", h2.id), "commit", ("create", h1.id), ("create", h2.id),
        ])


if __name__ == "__main__":
    unittest.main()
