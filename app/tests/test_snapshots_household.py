"""Siklus household, Task 8: `POST /snapshots/recompute` hanya untuk yang boleh mengubah siklus rumah (owner/admin, atau
member yang sendirian) dan menghitung ulang lewat `recompute_history` dengan tanggal gajian rumah; `POST /snapshots/run`
(admin/debug) menghitung tiap household dengan tanggal gajiannya sendiri, bukan tanggal si pemanggil.

Tanpa Postgres: handler dipanggil langsung; `payday_context`, `recompute_history`, `household_payday`, dan
`create_monthly_snapshots` di-patch pada modul route `snapshots` (diimpor di level modul); `db_with(...)` / `FakeResult`
dari app/tests/fakes.py. Konteks memakai `PaydayContext` asli supaya nama fieldnya ikut terkunci.
Run: python -m unittest app.tests.test_snapshots_household -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from fastapi import HTTPException

from app.api.routes import snapshots
from app.models.models import HouseholdRole
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


class RunTests(unittest.IsolatedAsyncioTestCase):
    def stub_service(self, *, paydays, created):
        """Ganti `household_payday` (satu tanggal per household, berurutan) dan `create_monthly_snapshots` (satu hasil
        untuk semua panggilan bila `created` dict, selain itu satu hasil per panggilan berurutan)."""
        self.household_payday = AsyncMock(side_effect=paydays)
        if isinstance(created, dict):
            self.create = AsyncMock(return_value=created)
        else:
            self.create = AsyncMock(side_effect=created)
        self.enterContext(patch.object(snapshots, "household_payday", self.household_payday))
        self.enterContext(patch.object(snapshots, "create_monthly_snapshots", self.create))

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
        # `force` diteruskan ke setiap household.
        self.assertEqual([c.kwargs["force"] for c in self.create.await_args_list], [True, True, True])

    async def test_run_without_year_month_uses_current_month(self):
        # Tanpa year/month: periode yang MULAI di bulan berjalan menurut tanggal rumah (25 Sep–24 Okt), bukan periode
        # yang sedang berjalan (25 Agu–24 Sep).
        h = make_household()
        db = db_with(FakeResult(rows=[h]))
        self.stub_service(paydays=[25], created=NOTHING_DONE)

        with patch.object(snapshots, "date", fixed_date(date(2026, 9, 15))):
            await self.run_snapshot(db, year=None, month=None)

        self.create.assert_awaited_once_with(
            date(2026, 9, 25), date(2026, 10, 24), force=False, household_ids=[h.id]
        )

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
        # `create_monthly_snapshots` bekerja lewat sesinya sendiri. Pengisian disimpan lebih dulu (kontrak R7 seperti
        # recompute): semua tanggal dihitung, satu commit, baru snapshot dibuat; sesi lain tidak pernah berhadapan
        # dengan UPDATE yang belum di-commit, dan koneksi request tidak menganggur menunggu hitungan snapshot.
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
