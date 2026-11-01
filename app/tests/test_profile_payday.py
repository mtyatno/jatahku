"""Siklus household, Task 6: `GET /user/profile` membawa siklus rumah, dan `PUT /user/profile` mengubah tanggal gajian
lewat `household_cycle` (owner/admin atau member yang sendirian; member household beranggota lebih dari satu: 403).

Tanpa Postgres: handler dipanggil langsung; `payday_context` dan `set_household_payday` di-patch pada modul
`user_settings` (diimpor di level modul); `db_with(...)` / `FakeResult` dari app/tests/fakes.py. User memakai
SimpleNamespace, konteks memakai `PaydayContext` asli supaya nama fieldnya ikut terkunci.
Run: python -m unittest app.tests.test_profile_payday -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.routes import user_settings
from app.api.routes.user_settings import UpdateProfile
from app.models.models import HouseholdRole
from app.services.household_cycle import PaydayContext
from app.tests.fakes import FakeResult, db_with

LOCKED_403 = "Tanggal gajian mengikuti rumah tangga (Rumah Ani, tanggal 25). Minta owner yang mengubahnya."
CHANGED = {"changed": True, "members": 2, "recomputed": 12}


def make_user(**override):
    """User seperti dari DB, cukup untuk `get_profile` dan `update_profile`."""
    fields = dict(
        id=uuid.uuid4(), name="Lama", email=None, telegram_id=None, password_hash=None,
        timezone="Asia/Jakarta", payday_day=1, income_type="monthly", profile_pic=None, plan="basic",
        default_cooling_threshold=None, default_daily_limit=None, default_is_locked=False,
        last_login=None, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    fields.update(override)
    return SimpleNamespace(**fields)


def rumah_ani(*, can_change, payday=25, members=2, owner_name="Ani", role=HouseholdRole.member):
    """`PaydayContext` rumah "Rumah Ani". Bawaan: member di rumah beranggota dua, jadi terkunci, owner-nya Ani."""
    household = SimpleNamespace(id=uuid.uuid4(), name="Rumah Ani", payday_day=payday)
    return PaydayContext(
        household=household, role=role, payday_day=payday, member_count=members,
        can_change=can_change, owner_name=owner_name,
    )


class UpdateProfileTests(unittest.IsolatedAsyncioTestCase):
    def stub_service(self, context, result=None):
        """Ganti `payday_context` (mengembalikan `context`) dan `set_household_payday` di modul route."""
        self.payday_context = AsyncMock(return_value=context)
        self.set_payday = AsyncMock(return_value=CHANGED if result is None else result)
        self.enterContext(patch.object(user_settings, "payday_context", self.payday_context))
        self.enterContext(patch.object(user_settings, "set_household_payday", self.set_payday))

    def assert_nothing_saved(self, db, user, *, name="Lama", payday=1):
        """400/403 tidak boleh menyimpan apa pun: tidak ada commit, service tidak dipanggil, field user utuh."""
        db.commit.assert_not_awaited()
        self.set_payday.assert_not_awaited()
        self.assertEqual(user.name, name)
        self.assertEqual(user.payday_day, payday)

    async def test_member_of_two_gets_403_and_nothing_saved(self):
        user, db = make_user(), db_with()
        self.stub_service(rumah_ani(can_change=False))
        with self.assertRaises(HTTPException) as caught:
            await user_settings.update_profile(UpdateProfile(name="Baru", payday_day=10), user=user, db=db)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, LOCKED_403)
        self.assert_nothing_saved(db, user)

    async def test_locked_member_repeating_the_household_payday_saves_other_fields(self):
        # Ruling R22: klien lama atau ber-cache (Onboarding sebelum fase ini mengirim {payday_day, income_type}) yang
        # mengulang tanggal rumah tidak mengubah apa pun: payday diabaikan tanpa 403 dan tanpa service, field lain
        # tersimpan. Tanggal yang berbeda tetap 403 (test_member_of_two_gets_403_and_nothing_saved).
        user, db = make_user(income_type="monthly"), db_with()
        self.stub_service(rumah_ani(can_change=False, payday=25))

        result = await user_settings.update_profile(
            UpdateProfile(payday_day=25, income_type="weekly"), user=user, db=db
        )

        self.assertEqual(result, {"status": "updated"})
        self.assertEqual(user.income_type, "weekly")
        self.set_payday.assert_not_awaited()
        db.commit.assert_awaited_once()
        self.assertEqual(user.payday_day, 1)  # cermin tidak disentuh rute

    async def test_locked_member_repeating_the_payday_still_gets_400_for_other_bad_fields(self):
        user, db = make_user(), db_with()
        self.stub_service(rumah_ani(can_change=False, payday=25))
        with self.assertRaises(HTTPException) as caught:
            await user_settings.update_profile(UpdateProfile(payday_day=25, income_type="hourly"), user=user, db=db)
        self.assertEqual(caught.exception.status_code, 400)
        self.assert_nothing_saved(db, user)

    async def test_owner_change_goes_through_service(self):
        user, db = make_user(), db_with()
        context = rumah_ani(can_change=True, role=HouseholdRole.owner, owner_name=None)
        self.stub_service(context)
        order = []

        async def service(_db, _household, _day, *, actor):
            order.append(("service", actor.name))
            return CHANGED

        self.set_payday.side_effect = service
        db.commit.side_effect = lambda: order.append(("commit", user.name))

        result = await user_settings.update_profile(UpdateProfile(name="Baru", payday_day=10), user=user, db=db)

        self.assertEqual(result, {"status": "updated"})
        self.payday_context.assert_awaited_once_with(db, user)
        self.set_payday.assert_awaited_once_with(db, context.household, 10, actor=user)
        self.assertEqual(user.name, "Baru")
        # Rute tidak menulis cermin `payday_day` sendiri: itu pekerjaan service (penulis tunggal).
        self.assertEqual(user.payday_day, 1)
        # Field lain sudah di-assign saat service dipanggil (service yang commit membawanya), dan commit akhir (R1)
        # menyusul service.
        self.assertEqual(order, [("service", "Baru"), ("commit", "Baru")])

    async def test_same_payday_still_saves_other_fields(self):
        # R1: service tidak commit saat tanggalnya sama, padahal Onboarding mengirim {payday_day: 1, income_type: "daily"}
        # untuk pekerja harian yang tanggalnya sudah 1. `set_household_payday` di sini tiruan yang tidak commit, jadi
        # hanya commit akhir rute yang bisa menyimpan income_type.
        user, db = make_user(payday_day=1, income_type="monthly"), db_with()
        context = rumah_ani(can_change=True, payday=1, members=1, owner_name=None, role=HouseholdRole.owner)
        self.stub_service(context, result={"changed": False})

        result = await user_settings.update_profile(UpdateProfile(payday_day=1, income_type="daily"), user=user, db=db)

        self.assertEqual(result, {"status": "updated"})
        self.set_payday.assert_awaited_once_with(db, context.household, 1, actor=user)
        self.assertEqual(user.income_type, "daily")
        db.commit.assert_awaited_once()

    async def test_put_payday_without_household_400(self):
        user, db = make_user(), db_with()
        self.stub_service(None)
        with self.assertRaises(HTTPException) as caught:
            await user_settings.update_profile(UpdateProfile(name="Baru", payday_day=10), user=user, db=db)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail, "Belum punya household")
        self.assert_nothing_saved(db, user)

    async def test_put_payday_out_of_range_400(self):
        self.stub_service(rumah_ani(can_change=True, role=HouseholdRole.owner, owner_name=None))
        for day in (0, 32):
            with self.subTest(day=day):
                user, db = make_user(), db_with()
                with self.assertRaises(HTTPException) as caught:
                    await user_settings.update_profile(UpdateProfile(name="Baru", payday_day=day), user=user, db=db)
                self.assertEqual(caught.exception.status_code, 400)
                self.assertEqual(caught.exception.detail, "payday_day harus antara 1 dan 31")
                self.assert_nothing_saved(db, user)

    async def test_first_and_last_day_of_month_are_accepted(self):
        for day in (1, 31):
            with self.subTest(day=day):
                user, db = make_user(), db_with()
                context = rumah_ani(can_change=True, role=HouseholdRole.owner, owner_name=None)
                self.stub_service(context)
                result = await user_settings.update_profile(UpdateProfile(payday_day=day), user=user, db=db)
                self.assertEqual(result, {"status": "updated"})
                self.set_payday.assert_awaited_once_with(db, context.household, day, actor=user)

    async def test_other_fields_without_payday_skip_service(self):
        user, db = make_user(), db_with()
        # Terkunci pun boleh mengubah nama: kunci hanya berlaku bila payday_day ikut dikirim.
        self.stub_service(rumah_ani(can_change=False))

        result = await user_settings.update_profile(UpdateProfile(name="X"), user=user, db=db)

        self.assertEqual(result, {"status": "updated"})
        self.assertEqual(user.name, "X")
        self.payday_context.assert_not_awaited()
        self.set_payday.assert_not_awaited()
        db.commit.assert_awaited_once()

    async def test_bad_timezone_with_payday_changes_nothing(self):
        # Service commit sendiri bila tanggalnya berubah, jadi semua validasi field lain harus selesai sebelum ia
        # dipanggil; kalau tidak, 400 datang setelah tanggal rumah sudah berubah untuk semua anggota.
        user, db = make_user(), db_with()
        self.stub_service(rumah_ani(can_change=True, role=HouseholdRole.owner, owner_name=None))
        with self.assertRaises(HTTPException) as caught:
            await user_settings.update_profile(UpdateProfile(timezone="Mars/Olympus", payday_day=10), user=user, db=db)
        self.assertEqual(caught.exception.status_code, 400)
        self.assert_nothing_saved(db, user)

    async def test_bad_income_type_with_payday_changes_nothing(self):
        user, db = make_user(), db_with()
        self.stub_service(rumah_ani(can_change=True, role=HouseholdRole.owner, owner_name=None))
        with self.assertRaises(HTTPException) as caught:
            await user_settings.update_profile(UpdateProfile(income_type="hourly", payday_day=10), user=user, db=db)
        self.assertEqual(caught.exception.status_code, 400)
        self.assert_nothing_saved(db, user)


class GetProfileTests(unittest.IsolatedAsyncioTestCase):
    async def profile(self, user, context):
        # Tiga kueri hitung lama (transaksi, amplop, berulang); `payday_context` di-patch, jadi tidak menambah kueri.
        db = db_with(FakeResult(0), FakeResult(0), FakeResult(0))
        stub = AsyncMock(return_value=context)
        with patch.object(user_settings, "payday_context", stub):
            result = await user_settings.get_profile(user=user, db=db)
        self.assertEqual(db.execute.await_count, 3)
        stub.assert_awaited_once_with(db, user)
        return result

    async def test_profile_includes_household_cycle_fields(self):
        # Cermin (20) sengaja berbeda dari tanggal rumah (25): kedua field punya sumber sendiri, dan `payday_day`
        # lama tetap berarti cermin user (klien lama bergantung padanya).
        profile = await self.profile(make_user(payday_day=20), rumah_ani(can_change=False))
        self.assertEqual(profile["household_payday_day"], 25)
        self.assertIs(profile["payday_locked"], True)
        self.assertEqual(profile["payday_owner_name"], "Ani")
        self.assertEqual(profile["household_name"], "Rumah Ani")
        self.assertEqual(profile["household_member_count"], 2)
        self.assertEqual(profile["payday_day"], 20)
        self.assertEqual(profile["usage"], {"envelopes": 0, "txn_this_month": 0, "recurring": 0})

    async def test_profile_of_owner_is_unlocked_without_owner_name(self):
        context = rumah_ani(can_change=True, role=HouseholdRole.owner, owner_name=None)
        profile = await self.profile(make_user(payday_day=25), context)
        self.assertEqual(profile["household_payday_day"], 25)
        self.assertIs(profile["payday_locked"], False)
        self.assertIsNone(profile["payday_owner_name"])
        self.assertEqual(profile["household_name"], "Rumah Ani")
        self.assertEqual(profile["household_member_count"], 2)

    async def test_profile_without_household_defaults(self):
        profile = await self.profile(make_user(payday_day=7), None)
        self.assertEqual(profile["household_payday_day"], 7)
        self.assertIs(profile["payday_locked"], False)
        self.assertIsNone(profile["payday_owner_name"])
        self.assertIsNone(profile["household_name"])
        self.assertEqual(profile["household_member_count"], 1)
        self.assertEqual(profile["payday_day"], 7)


if __name__ == "__main__":
    unittest.main()
