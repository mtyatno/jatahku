"""Mengunci rumus /envelopes/summary sebelum & sesudah ekstraksi ke service.

Run: python -m unittest app.tests.test_envelope_balance -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from app.tests.fakes import FakeResult, db_with, executed_sql

USER_ID, HID, G1, E1, E2 = (uuid.uuid4() for _ in range(5))
USER = SimpleNamespace(id=USER_ID, payday_day=1)
PS, PE = date(2026, 9, 1), date(2026, 9, 30)


def env(**kw):
    base = dict(id=None, name="", emoji="", budget_amount=D("0"), is_rollover=True,
                owner_id=None, is_locked=False, daily_limit=None, cooling_threshold=None,
                group_id=None, purpose="expense", classification=None)
    base.update(kw)
    return SimpleNamespace(**base)


ENV_A = env(id=E1, name="Makan", emoji="🍜", budget_amount=D("1000000"),
            is_rollover=True, group_id=G1, classification="needs")
ENV_B = env(id=E2, name="Hobi", emoji="🎮", budget_amount=D("500000"),
            is_rollover=False, owner_id=USER_ID)
REC = SimpleNamespace(frequency=SimpleNamespace(value="monthly"),
                      amount=D("100000"), next_run=date(2026, 9, 15))


def fake_db():
    return db_with(
        FakeResult(HID),                                          # household id
        FakeResult([ENV_A, ENV_B]),                               # envelopes
        FakeResult([(G1, "Kebutuhan")]),                          # groups
        FakeResult(D("300000")),                                  # A spent
        FakeResult(D("1000000")),                                 # A allocated
        FakeResult(SimpleNamespace(rollover_amount=D("50000"))),  # A snapshot
        FakeResult([REC]),                                        # A recurring
        FakeResult(D("100000")),                                  # B spent
        FakeResult(D("200000")),                                  # B allocated (non-rollover: tanpa snapshot)
        FakeResult([]),                                           # B recurring
    )


class EnvelopeSummaryCharacterizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_output(self):
        from app.api.routes.envelopes import envelope_summary
        a, b = await envelope_summary(period_start=PS, period_end=PE, user=USER, db=fake_db())
        self.assertEqual((a.allocated, a.rollover, a.spent), (D("1000000"), D("50000"), D("300000")))
        self.assertEqual((a.remaining, a.reserved, a.free), (D("750000"), D("100000"), D("650000")))
        self.assertEqual(a.group_name, "Kebutuhan")
        self.assertAlmostEqual(a.funded_ratio, 1.0)
        self.assertAlmostEqual(a.spent_ratio, 0.2857, places=4)
        self.assertFalse(a.is_personal)
        self.assertEqual((b.remaining, b.rollover, b.free), (D("100000"), D("0"), D("100000")))
        self.assertTrue(b.is_personal)
        self.assertAlmostEqual(b.funded_ratio, 0.4)
        self.assertAlmostEqual(b.spent_ratio, 0.5)

    async def test_route_without_household_returns_empty(self):
        from app.api.routes.envelopes import envelope_summary
        out = await envelope_summary(period_start=PS, period_end=PE, user=USER, db=db_with(FakeResult(None)))
        self.assertEqual(out, [])

    async def test_service_returns_same_numbers_as_dicts(self):
        from app.services.envelope_balance import compute_envelope_summaries
        rows = await compute_envelope_summaries(USER, fake_db(), PS, PE)
        self.assertEqual([r["remaining"] for r in rows], [D("750000"), D("100000")])
        self.assertEqual([r["free"] for r in rows], [D("650000"), D("100000")])
        self.assertEqual(rows[0]["purpose"], "expense")
        self.assertEqual(rows[1]["is_personal"], True)

    async def test_envelope_query_keeps_privacy_and_active_filters(self):
        # Batas privasi (amplop personal anggota lain tak boleh ikut terhitung di saldo/cocokkan saldo)
        # dan filter aktif hidup di SATU query amplop ini — kunci teks WHERE-nya.
        from app.services.envelope_balance import compute_envelope_summaries
        db = fake_db()
        await compute_envelope_summaries(USER, db, PS, PE)
        stmts = executed_sql(db)  # [0] = household id, [1] = amplop
        self.assertIn("FROM household_members", stmts[0])
        self.assertIn("FROM envelopes", stmts[1])
        self.assertIn("envelopes.household_id = ", stmts[1])
        self.assertIn("envelopes.is_active = true", stmts[1])
        self.assertIn("envelopes.owner_id IS NULL OR envelopes.owner_id = ", stmts[1])


if __name__ == "__main__":
    unittest.main()
