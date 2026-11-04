"""Plugin R1 — model ruang: `households.type`, `incomes.kind` beserta backfill, dan
keanggotaan unik per (user, household) sehingga satu user boleh menjadi anggota
beberapa household. Belum ada perubahan perilaku (docs/plugin/03-workflow.md, baris R1).

Integrasi memakai SQLite in-memory (butuh `aiosqlite`); dilewati bila tidak ada.
Run: python -m unittest app.tests.test_ruang_model -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import date
from decimal import Decimal as D
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.api.routes import envelopes as envelopes_routes, household as household_routes
from app.api.routes import incomes as incomes_routes
from app.core.database import Base
from app.models.models import (
    Allocation, BalanceCheck, Envelope, Household, HouseholdMember, HouseholdRole,
    HouseholdType, Income, IncomeKind, User,
)
from app.services import fund_shift
from app.services.ruang_schema import KIND_BACKFILL, RUANG_DDL

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


class KonstantaTests(unittest.TestCase):
    def test_nilai_type_household(self):
        self.assertEqual(HouseholdType.RUMAH_TANGGA, "rumah_tangga")
        self.assertEqual(HouseholdType.USAHA, "usaha")
        self.assertEqual(HouseholdType.ALL, ("rumah_tangga", "usaha"))

    def test_nilai_kind_income(self):
        self.assertEqual(IncomeKind.ALL, ("pemasukan", "transfer", "top-up", "penyesuaian", "prive"))  # prive: R8

    def test_ddl_hanya_aditif_dan_idempoten(self):
        for stmt in RUANG_DDL:
            self.assertIn("ADD COLUMN IF NOT EXISTS", stmt)
        joined = " ".join(RUANG_DDL)
        self.assertIn("households", joined)
        self.assertIn("incomes", joined)

    def test_backfill_hanya_menyentuh_baris_pemasukan(self):
        # Kind yang sudah ditulis kode baru tidak pernah ditimpa backfill.
        for stmt in KIND_BACKFILL:
            self.assertIn("kind = 'pemasukan'", stmt)


class SkemaApiTests(unittest.TestCase):
    def test_income_create_kind_bawaan_pemasukan(self):
        req = incomes_routes.IncomeCreate(amount=D("100000"))
        self.assertEqual(req.kind, "pemasukan")

    def test_income_create_menerima_top_up(self):
        req = incomes_routes.IncomeCreate(amount=D("100000"), kind="top-up")
        self.assertEqual(req.kind, "top-up")

    def test_income_create_menolak_kind_internal(self):
        # transfer dan penyesuaian hanya ditulis server lewat jalurnya sendiri.
        for kind in ("transfer", "penyesuaian", "penjualan", ""):
            with self.assertRaises(ValidationError, msg=kind):
                incomes_routes.IncomeCreate(amount=D("100000"), kind=kind)

    def test_income_response_punya_kind(self):
        self.assertIn("kind", incomes_routes.IncomeResponse.model_fields)

    def test_household_response_punya_type(self):
        self.assertIn("type", household_routes.HouseholdResponse.model_fields)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RuangIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.Session() as db:
            self.user = User(name="Tes")
            self.hh = Household(name="Rumah Tes")
            db.add_all([self.user, self.hh])
            await db.flush()
            db.add(HouseholdMember(user_id=self.user.id, household_id=self.hh.id,
                                   role=HouseholdRole.owner))
            self.makan = Envelope(household_id=self.hh.id, name="Makan", emoji="🍜",
                                  budget_amount=D("0"))
            self.jajan = Envelope(household_id=self.hh.id, name="Jajan", emoji="🍬",
                                  budget_amount=D("0"))
            self.tabungan = Envelope(household_id=self.hh.id, name="Tabungan", emoji="💰",
                                     budget_amount=D("0"), purpose="saving")
            db.add_all([self.makan, self.jajan, self.tabungan])
            await db.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _kinds(self):
        async with self.Session() as db:
            rows = (await db.execute(select(Income.description, Income.kind))).all()
        return dict(rows)

    # ── bawaan ──────────────────────────────────────────────────────────────
    async def test_household_baru_bertipe_rumah_tangga(self):
        async with self.Session() as db:
            hh = await db.get(Household, self.hh.id)
            self.assertEqual(hh.type, "rumah_tangga")
            raw = (await db.execute(text("SELECT type FROM households"))).scalar_one()
            self.assertEqual(raw, "rumah_tangga")

    async def test_income_baru_berjenis_pemasukan(self):
        async with self.Session() as db:
            db.add(Income(household_id=self.hh.id, user_id=self.user.id, amount=D("1000"),
                          description="Gaji"))
            await db.commit()
        self.assertEqual(await self._kinds(), {"Gaji": "pemasukan"})

    # ── keanggotaan ─────────────────────────────────────────────────────────
    async def test_user_boleh_anggota_dua_household(self):
        async with self.Session() as db:
            usaha = Household(name="Dapur Nusa", type=HouseholdType.USAHA)
            db.add(usaha)
            await db.flush()
            db.add(HouseholdMember(user_id=self.user.id, household_id=usaha.id,
                                   role=HouseholdRole.owner))
            await db.commit()
            n = len((await db.execute(select(HouseholdMember).where(
                HouseholdMember.user_id == self.user.id))).scalars().all())
        self.assertEqual(n, 2)

    async def test_keanggotaan_ganda_di_household_sama_ditolak(self):
        async with self.Session() as db:
            db.add(HouseholdMember(user_id=self.user.id, household_id=self.hh.id,
                                   role=HouseholdRole.member))
            with self.assertRaises(IntegrityError):
                await db.commit()

    # ── jalur penulis Income ────────────────────────────────────────────────
    async def test_record_transfer_berjenis_transfer(self):
        async with self.Session() as db:
            fund_shift.record_transfer(db, self.hh.id, self.user.id, self.makan, self.jajan, D("5000"))
            await db.commit()
        self.assertEqual(list((await self._kinds()).values()), ["transfer"])

    async def test_record_topup_berjenis_top_up(self):
        async with self.Session() as db:
            fund_shift.record_topup(db, self.hh.id, self.user.id, self.makan, D("5000"))
            await db.commit()
        self.assertEqual(await self._kinds(), {"Top-up Makan": "top-up"})

    async def test_post_incomes_menyimpan_kind(self):
        notif = "app.services.goal_notify"
        for req in (incomes_routes.IncomeCreate(amount=D("100000"), source="Gaji"),
                    incomes_routes.IncomeCreate(amount=D("20000"), source="Uang saku",
                                                kind="top-up")):
            async with self.Session() as db:
                with patch(f"{notif}.goal_snapshot", AsyncMock(return_value={})), \
                     patch(f"{notif}.notify_goals_reached", AsyncMock()):
                    out = await incomes_routes.create_income(req, user=self.user, db=db, hid=self.hh.id)
            self.assertEqual(out.kind, req.kind)
        self.assertEqual(await self._kinds(), {"Gaji": "pemasukan", "Uang saku": "top-up"})

    async def test_list_incomes_menyertakan_kind(self):
        async with self.Session() as db:
            db.add(Income(household_id=self.hh.id, user_id=self.user.id, amount=D("1000"),
                          description="Gaji", income_date=date(2026, 10, 25)))
            await db.commit()
            rows = await incomes_routes.list_incomes(
                period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
                user=self.user, db=db, hid=self.hh.id)
        self.assertEqual(rows[0]["kind"], "pemasukan")
        self.assertEqual(rows[0]["type"], "income")  # field lama tetap

    async def test_hapus_amplop_bersisa_berjenis_transfer(self):
        async with self.Session() as db:
            inc = Income(household_id=self.hh.id, user_id=self.user.id, amount=D("30000"),
                         description="Gaji")
            db.add(inc)
            await db.flush()
            db.add(Allocation(income_id=inc.id, envelope_id=self.jajan.id, amount=D("30000")))
            await db.commit()
        notif = "app.services.goal_notify"
        async with self.Session() as db:
            with patch(f"{notif}.goal_snapshot", AsyncMock(return_value={})), \
                 patch(f"{notif}.notify_goals_reached", AsyncMock()):
                await envelopes_routes.delete_envelope(self.jajan.id, user=self.user, db=db)
        kinds = await self._kinds()
        self.assertEqual(kinds["Gaji"], "pemasukan")
        self.assertEqual(kinds["Refund: hapus amplop Jajan"], "transfer")

    async def test_penyesuaian_cocokkan_saldo_berjenis_penyesuaian(self):
        from app.services.balance_check import apply_balance_check
        async with self.Session() as db:
            await apply_balance_check(self.user, db, actual_amount=D("15000"),
                                      expected_app_amount=D("0"),
                                      lines=[(self.makan.id, D("15000"))], household_id=self.hh.id)
        async with self.Session() as db:
            row = (await db.execute(select(Income))).scalar_one()
        self.assertIsNotNone(row.balance_check_id)
        self.assertEqual(row.kind, "penyesuaian")

    async def test_get_household_menyertakan_type(self):
        async with self.Session() as db:
            out = await household_routes.get_household(user=self.user, db=db, hid=self.hh.id)
        self.assertEqual(out.type, "rumah_tangga")

    # ── backfill data lama ──────────────────────────────────────────────────
    async def test_backfill_mengklasifikasi_income_lama(self):
        async with self.Session() as db:
            check = BalanceCheck(household_id=self.hh.id, user_id=self.user.id,
                                 actual_amount=D("1"), app_amount=D("0"), gap=D("1"))
            db.add(check)
            await db.flush()
            base = dict(household_id=self.hh.id, user_id=self.user.id)
            # Semua baris lama tersimpan dengan kind bawaan 'pemasukan' (kolom baru).
            db.add_all([
                Income(**base, amount=D("3000000"), description="Gaji"),
                Income(**base, amount=D("0"), description="Transfer: Makan → Jajan"),
                Income(**base, amount=D("0"), description="Refund: hapus amplop Hobi"),
                Income(**base, amount=D("50000"), description="Top-up Makan"),
                Income(**base, amount=D("50000"), description="Top-up"),
                Income(**base, amount=D("50000"), description="Top-upan arisan"),
                Income(**base, amount=D("1"), description="Penyesuaian saldo",
                       balance_check_id=check.id),
            ])
            await db.commit()
            for stmt in KIND_BACKFILL:
                await db.execute(text(stmt))
            await db.commit()
        self.assertEqual(await self._kinds(), {
            "Gaji": "pemasukan",
            "Transfer: Makan → Jajan": "transfer",
            "Refund: hapus amplop Hobi": "transfer",
            "Top-up Makan": "top-up",
            "Top-up": "top-up",
            "Top-upan arisan": "pemasukan",
            "Penyesuaian saldo": "penyesuaian",
        })

    async def test_backfill_tidak_menimpa_kind_yang_sudah_ada_dan_idempoten(self):
        async with self.Session() as db:
            db.add(Income(household_id=self.hh.id, user_id=self.user.id, amount=D("0"),
                          description="Top-up aneh", kind=IncomeKind.TOPUP))
            await db.commit()
            for _ in range(2):
                for stmt in KIND_BACKFILL:
                    await db.execute(text(stmt))
                await db.commit()
        self.assertEqual(await self._kinds(), {"Top-up aneh": "top-up"})


if __name__ == "__main__":
    unittest.main()
