"""Siklus household, Task 4: `household_cycle` — peringkat payday (murni), izin ubah, resolver `household_payday`,
konteks `payday_context`, `adopt_household_payday`, dan `heal`.

Tanpa Postgres: `db_with(...)` / `FakeResult` dari app/tests/fakes.py; user/household/keanggotaan memakai SimpleNamespace.
Run: python -m unittest app.tests.test_household_cycle -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import dataclasses
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.models import HouseholdRole
from app.services import household_cycle as hc
from app.tests.fakes import FakeResult, db_with, executed_sql


def at(month: int, day: int = 1) -> datetime:
    """`created_at` seperti dari DB: timestamptz (aware)."""
    return datetime(2026, month, day, tzinfo=timezone.utc)


def member(role, created_at, payday, name="Anggota") -> "hc.MemberRow":
    return hc.MemberRow(user_id=uuid.uuid4(), name=name, role=role, created_at=created_at, payday_day=payday)


def norm(statement: str) -> str:
    """SQL hasil compile berisi newline antar klausa; rapatkan supaya assert tidak bergantung pada tata letak."""
    return " ".join(statement.split())


class PickPaydayTests(unittest.TestCase):
    def test_pick_payday_prefers_owner_then_admin_then_oldest(self):
        m = member(HouseholdRole.member, at(1), 5)
        a = member(HouseholdRole.admin, at(2), 10)
        o = member(HouseholdRole.owner, at(3), 25)
        # owner menang walau bergabung paling baru; admin menang atas member yang lebih lama.
        self.assertEqual(hc.pick_payday([m, a, o]), 25)
        self.assertEqual(hc.pick_payday([o, a, m]), 25)
        self.assertEqual(hc.pick_payday([m, a]), 10)
        self.assertEqual(hc.pick_payday([a, m]), 10)
        # sesama peran: yang created_at tertua, bukan yang pertama di daftar.
        old, new = member(HouseholdRole.member, at(1), 7), member(HouseholdRole.member, at(2), 9)
        for rows in ([old, new], [new, old]):
            with self.subTest(order=[r.payday_day for r in rows]):
                self.assertEqual(hc.pick_payday(rows), 7)
        old_admin, new_admin = member(HouseholdRole.admin, at(4), 11), member(HouseholdRole.admin, at(5), 12)
        for rows in ([old_admin, new_admin], [new_admin, old_admin]):
            with self.subTest(admins=[r.payday_day for r in rows]):
                self.assertEqual(hc.pick_payday(rows), 11)

    def test_pick_payday_accepts_string_roles(self):
        # Kolom role SAEnum mengembalikan enum, tetapi pemanggil lain bisa membawa string (AGENTS.md: enum vs string).
        rows = [member("member", at(1), 5), member("admin", at(2), 10), member("owner", at(3), 25)]
        self.assertEqual(hc.pick_payday(rows), 25)
        self.assertEqual(hc.pick_payday(rows[:2]), 10)

    def test_pick_payday_without_members_is_1(self):
        self.assertEqual(hc.pick_payday([]), 1)
        self.assertEqual(hc.pick_payday(()), 1)

    def test_pick_payday_missing_payday_of_chosen_member_counts_as_1(self):
        # Yang berhak (owner) belum punya tanggal: dianggap 1, tidak jatuh ke payday anggota lain.
        for missing in (None, 0):
            with self.subTest(missing=missing):
                rows = [member(HouseholdRole.owner, at(3), missing), member(HouseholdRole.admin, at(2), 10)]
                self.assertEqual(hc.pick_payday(rows), 1)


class CanChangePaydayTests(unittest.TestCase):
    def test_can_change_payday_matrix(self):
        for role in (HouseholdRole.owner, "owner", HouseholdRole.admin, "admin"):
            for count in (1, 3):
                with self.subTest(role=role, count=count):
                    self.assertIs(hc.can_change_payday(role, count), True)
        for role in (HouseholdRole.member, "member"):
            with self.subTest(role=role, count=1):
                self.assertIs(hc.can_change_payday(role, 1), True)
            for count in (2, 3):
                with self.subTest(role=role, count=count):
                    self.assertIs(hc.can_change_payday(role, count), False)
        # Peran yang tidak dikenal tidak pernah boleh, juga bila sendirian.
        for role in ("viewer", "", None):
            with self.subTest(role=role):
                self.assertIs(hc.can_change_payday(role, 1), False)


class MemberRowTests(unittest.IsolatedAsyncioTestCase):
    def test_member_row_is_frozen(self):
        row = member(HouseholdRole.owner, at(1), 25)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            row.payday_day = 1

    async def test_member_rows_maps_columns_in_select_order(self):
        hid, uid1, uid2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        db = db_with(FakeResult(rows=[
            (HouseholdRole.owner, at(1), uid1, "Ani", 25),
            (HouseholdRole.member, at(2), uid2, "Budi", 5),
        ]))
        rows = await hc.member_rows(db, hid)
        self.assertEqual(rows, [
            hc.MemberRow(user_id=uid1, name="Ani", role=HouseholdRole.owner, created_at=at(1), payday_day=25),
            hc.MemberRow(user_id=uid2, name="Budi", role=HouseholdRole.member, created_at=at(2), payday_day=5),
        ])
        (stmt,) = executed_sql(db)  # tepat satu kueri
        self.assertEqual(norm(stmt), (
            "SELECT household_members.role, household_members.created_at, users.id, users.name, users.payday_day "
            "FROM household_members JOIN users ON users.id = household_members.user_id "
            "WHERE household_members.household_id = %(household_id_1)s::UUID"
        ))


class HouseholdPaydayTests(unittest.IsolatedAsyncioTestCase):
    async def test_household_payday_stored_value_no_query(self):
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=25)
        db = db_with()
        self.assertEqual(await hc.household_payday(db, household), 25)
        db.execute.assert_not_called()
        db.flush.assert_not_awaited()

    async def test_household_payday_stored_value_wins_over_rows(self):
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=25)
        db = db_with()
        rows = [member(HouseholdRole.owner, at(1), 10)]
        self.assertEqual(await hc.household_payday(db, household, rows), 25)
        self.assertEqual(household.payday_day, 25)
        db.execute.assert_not_called()
        db.flush.assert_not_awaited()

    async def test_household_payday_fills_null_from_owner(self):
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=None)
        uid1, uid2 = uuid.uuid4(), uuid.uuid4()
        db = db_with(FakeResult(rows=[
            (HouseholdRole.member, at(1), uid1, "Budi", 1),
            (HouseholdRole.owner, at(2), uid2, "Ani", 25),
        ]))
        self.assertEqual(await hc.household_payday(db, household), 25)
        self.assertEqual(household.payday_day, 25)
        db.flush.assert_awaited_once()
        db.commit.assert_not_awaited()  # pemanggil yang commit
        self.assertEqual(db.execute.await_count, 1)  # hanya member_rows

    async def test_household_payday_uses_given_rows_without_query(self):
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=None)
        db = db_with()
        rows = [member(HouseholdRole.member, at(2), 3), member(HouseholdRole.admin, at(1), 10)]
        self.assertEqual(await hc.household_payday(db, household, rows), 10)
        self.assertEqual(household.payday_day, 10)
        db.execute.assert_not_called()
        db.flush.assert_awaited_once()

    async def test_household_payday_explicit_empty_rows_is_1_without_query(self):
        # `rows=[]` berarti "tanpa anggota", bukan "belum dimuat": tidak ada kueri tambahan.
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=None)
        db = db_with()
        self.assertEqual(await hc.household_payday(db, household, []), 1)
        self.assertEqual(household.payday_day, 1)
        db.execute.assert_not_called()
        db.flush.assert_awaited_once()


class PaydayContextTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _db(role, user_id, rows, *, household_payday=25):
        hid = uuid.uuid4()
        household = SimpleNamespace(id=hid, name="Rumah Ani", payday_day=household_payday)
        db = db_with(
            FakeResult(SimpleNamespace(household_id=hid, role=role)),
            FakeResult(household),
            FakeResult(rows=rows),
        )
        return db, household

    async def test_payday_context_member_of_two(self):
        user = SimpleNamespace(id=uuid.uuid4())
        db, household = self._db(HouseholdRole.member, user.id, [
            (HouseholdRole.owner, at(1), uuid.uuid4(), "Ani", 25),
            (HouseholdRole.member, at(2), user.id, "Budi", 25),
        ])
        ctx = await hc.payday_context(db, user)
        self.assertIs(ctx.household, household)
        self.assertEqual(ctx.role, HouseholdRole.member)
        self.assertEqual(ctx.payday_day, 25)
        self.assertEqual(ctx.member_count, 2)
        self.assertIs(ctx.can_change, False)
        self.assertEqual(ctx.owner_name, "Ani")
        # Tiga kueri persis, urutan: keanggotaan, household, anggota (payday tanpa kueri tambahan).
        first, second, third = executed_sql(db)
        self.assertTrue(norm(first).endswith("FROM household_members WHERE household_members.user_id = %(user_id_1)s::UUID"))
        self.assertIn("household_members.household_id, household_members.role", norm(first))  # select(HouseholdMember)
        self.assertTrue(norm(second).endswith("FROM households WHERE households.id = %(id_1)s::UUID"))
        self.assertIn("JOIN users ON users.id = household_members.user_id", norm(third))
        self.assertIn("WHERE household_members.household_id =", norm(third))
        db.flush.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_payday_context_owner_has_no_owner_name(self):
        user = SimpleNamespace(id=uuid.uuid4())
        db, _ = self._db(HouseholdRole.owner, user.id, [
            (HouseholdRole.owner, at(1), user.id, "Ani", 25),
            (HouseholdRole.member, at(2), uuid.uuid4(), "Budi", 25),
        ])
        ctx = await hc.payday_context(db, user)
        self.assertIsNone(ctx.owner_name)
        self.assertIs(ctx.can_change, True)
        self.assertEqual(ctx.role, HouseholdRole.owner)
        self.assertEqual(ctx.member_count, 2)

    async def test_payday_context_admin_sees_owner_name_and_can_change(self):
        user = SimpleNamespace(id=uuid.uuid4())
        db, _ = self._db(HouseholdRole.admin, user.id, [
            (HouseholdRole.owner, at(1), uuid.uuid4(), "Ani", 25),
            (HouseholdRole.admin, at(2), user.id, "Budi", 25),
            (HouseholdRole.member, at(3), uuid.uuid4(), "Cici", 25),
        ])
        ctx = await hc.payday_context(db, user)
        self.assertEqual(ctx.owner_name, "Ani")
        self.assertIs(ctx.can_change, True)
        self.assertEqual(ctx.member_count, 3)

    async def test_payday_context_without_owner_row_has_no_owner_name(self):
        user = SimpleNamespace(id=uuid.uuid4())
        db, _ = self._db(HouseholdRole.member, user.id, [
            (HouseholdRole.admin, at(1), uuid.uuid4(), "Ani", 25),
            (HouseholdRole.member, at(2), user.id, "Budi", 25),
        ])
        ctx = await hc.payday_context(db, user)
        self.assertIsNone(ctx.owner_name)
        self.assertIs(ctx.can_change, False)

    async def test_payday_context_solo_member_can_change(self):
        user = SimpleNamespace(id=uuid.uuid4())
        db, _ = self._db(HouseholdRole.member, user.id, [(HouseholdRole.member, at(1), user.id, "Budi", 25)])
        ctx = await hc.payday_context(db, user)
        self.assertEqual(ctx.member_count, 1)
        self.assertIs(ctx.can_change, True)
        self.assertIsNone(ctx.owner_name)

    async def test_payday_context_derives_null_payday_from_the_same_rows(self):
        user = SimpleNamespace(id=uuid.uuid4())
        db, household = self._db(HouseholdRole.member, user.id, [
            (HouseholdRole.member, at(2), user.id, "Budi", 1),
            (HouseholdRole.owner, at(1), uuid.uuid4(), "Ani", 25),
        ], household_payday=None)
        ctx = await hc.payday_context(db, user)
        self.assertEqual(ctx.payday_day, 25)
        self.assertEqual(household.payday_day, 25)
        self.assertEqual(db.execute.await_count, 3)  # tidak ada kueri anggota kedua
        db.flush.assert_awaited_once()
        db.commit.assert_not_awaited()

    async def test_payday_context_without_membership_is_none(self):
        db = db_with(FakeResult(None))
        self.assertIsNone(await hc.payday_context(db, SimpleNamespace(id=uuid.uuid4())))
        self.assertEqual(db.execute.await_count, 1)  # berhenti di keanggotaan


class AdoptTests(unittest.IsolatedAsyncioTestCase):
    async def test_adopt_sets_user_payday_without_commit(self):
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=25)
        user = SimpleNamespace(id=uuid.uuid4(), payday_day=1)
        db = db_with()
        self.assertEqual(await hc.adopt_household_payday(db, user, household), 25)
        self.assertEqual(user.payday_day, 25)
        db.commit.assert_not_awaited()
        db.execute.assert_not_called()

    async def test_adopt_derives_when_household_payday_is_null(self):
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=None)
        user = SimpleNamespace(id=uuid.uuid4(), payday_day=1)
        db = db_with(FakeResult(rows=[(HouseholdRole.owner, at(1), uuid.uuid4(), "Ani", 25)]))
        self.assertEqual(await hc.adopt_household_payday(db, user, household), 25)
        self.assertEqual((user.payday_day, household.payday_day), (25, 25))
        db.flush.assert_awaited_once()
        db.commit.assert_not_awaited()


class HealTests(unittest.IsolatedAsyncioTestCase):
    async def test_heal_fixes_diverged_members_and_warns(self):
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=25)
        u1 = SimpleNamespace(id=uuid.uuid4(), payday_day=25)
        u2 = SimpleNamespace(id=uuid.uuid4(), payday_day=1)
        db = db_with(FakeResult(rows=[u1, u2]))
        with self.assertLogs("jatahku.household_cycle", "WARNING") as logs:
            fixed = await hc.heal(db, household)
        self.assertEqual(fixed, [u2])
        self.assertEqual((u1.payday_day, u2.payday_day), (25, 25))
        db.commit.assert_awaited_once()
        self.assertEqual([r.getMessage() for r in logs.records], [f"payday anggota {u2.id} menyimpang (1 → 25)"])
        self.assertIn("menyimpang", logs.output[0])
        (stmt,) = executed_sql(db)  # muat User anggota household ini, satu kueri
        self.assertTrue(norm(stmt).startswith("SELECT users.id, users.email"))
        self.assertIn("FROM users JOIN household_members ON household_members.user_id = users.id", norm(stmt))
        self.assertIn("WHERE household_members.household_id = %(household_id_1)s::UUID", norm(stmt))

    async def test_heal_logs_and_returns_every_diverged_member(self):
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=25)
        a = SimpleNamespace(id=uuid.uuid4(), payday_day=1)
        b = SimpleNamespace(id=uuid.uuid4(), payday_day=None)  # kolom belum terisi juga menyimpang
        c = SimpleNamespace(id=uuid.uuid4(), payday_day=25)
        db = db_with(FakeResult(rows=[a, b, c]))
        with self.assertLogs("jatahku.household_cycle", "WARNING") as logs:
            fixed = await hc.heal(db, household)
        self.assertEqual(fixed, [a, b])
        self.assertEqual((a.payday_day, b.payday_day, c.payday_day), (25, 25, 25))
        self.assertEqual([r.getMessage() for r in logs.records], [
            f"payday anggota {a.id} menyimpang (1 → 25)",
            f"payday anggota {b.id} menyimpang (None → 25)",
        ])
        db.commit.assert_awaited_once()  # satu commit untuk semua

    async def test_heal_noop_when_aligned(self):
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=25)
        users = [SimpleNamespace(id=uuid.uuid4(), payday_day=25) for _ in range(2)]
        db = db_with(FakeResult(rows=users))
        with self.assertNoLogs("jatahku.household_cycle", "WARNING"):
            fixed = await hc.heal(db, household)
        self.assertEqual(fixed, [])
        self.assertEqual([u.payday_day for u in users], [25, 25])
        db.commit.assert_not_awaited()

    async def test_heal_skips_household_without_payday(self):
        household = SimpleNamespace(id=uuid.uuid4(), payday_day=None)
        db = db_with()
        self.assertEqual(await hc.heal(db, household), [])
        db.execute.assert_not_called()
        db.commit.assert_not_awaited()
        self.assertIsNone(household.payday_day)  # heal tidak mengisi household yang belum dimigrasi


if __name__ == "__main__":
    unittest.main()
