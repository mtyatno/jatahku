"""Service cocokkan saldo (DB di-mock).

Run: python -m unittest app.tests.test_balance_check_service -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.models import BalanceCheck, Transaction, Income, Allocation
from app.services import balance_check as svc
from app.tests.fakes import FakeResult, db_with, sql, executed_sql

HID, USER_ID, CHECK_ID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
USER = SimpleNamespace(id=USER_ID, payday_day=1)
MAKAN, TRANS, TAB, CICIL = (uuid.uuid4() for _ in range(4))
TODAY = date(2026, 9, 30)


def row(eid, name, purpose, remaining, budget="0"):
    return {"id": eid, "name": name, "emoji": "", "purpose": purpose,
            "remaining": D(remaining), "budget_amount": D(budget)}


ROWS = [  # app_amount = 2.000.000
    row(MAKAN, "Makan", "expense", "500000", "1000000"),
    row(TRANS, "Transport", "expense", "200000", "400000"),
    row(TAB, "Tabungan", "saving", "1000000"),
    row(CICIL, "Cicilan", "debt", "300000", "300000"),
]


def recording_db(*results):
    """db mock yang mencatat db.add() dan memberi id saat flush (meniru INSERT)."""
    db = db_with(*results)
    added = []
    db.add = MagicMock(side_effect=added.append)

    async def flush():
        for obj in added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    db.flush = AsyncMock(side_effect=flush)
    db.added = added
    return db


@patch.object(svc, "compute_envelope_summaries", new=AsyncMock(return_value=ROWS))
class PreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_match(self):
        p = await svc.build_preview(USER, db_with(), D("2000000"), today=TODAY)
        self.assertEqual((p["direction"], p["app_amount"], p["gap"]), ("match", D("2000000"), D("0")))
        self.assertEqual(p["suggestions"], [])
        self.assertEqual(p["default_target_envelope_id"], TAB)
        self.assertEqual([t["envelope_id"] for t in p["expense_targets"]], [MAKAN, TRANS, CICIL])
        self.assertEqual(len(p["income_targets"]), 4)

    async def test_unrecorded_expense_suggests_by_recent_spending(self):
        weights = {str(MAKAN): D("600000"), str(TRANS): D("300000")}
        with patch.object(svc, "load_expense_weights", new=AsyncMock(return_value=weights)):
            p = await svc.build_preview(USER, db_with(), D("1660000"), today=TODAY)
        self.assertEqual((p["direction"], p["gap"]), ("unrecorded_expense", D("-340000")))
        got = {s["envelope_id"]: (s["amount"], s["remaining_after"]) for s in p["suggestions"]}
        self.assertEqual(got, {MAKAN: (D("227000"), D("273000")), TRANS: (D("113000"), D("87000"))})

    async def test_surplus_has_no_suggestions(self):
        p = await svc.build_preview(USER, db_with(), D("2200000"), today=TODAY)
        self.assertEqual((p["direction"], p["gap"], p["suggestions"]), ("surplus", D("200000"), []))

    async def test_default_target_falls_back_to_first_saving(self):
        rows = [row(MAKAN, "Makan", "expense", "1"), row(TAB, "Dana Darurat", "saving", "1")]
        with patch.object(svc, "compute_envelope_summaries", new=AsyncMock(return_value=rows)):
            p = await svc.build_preview(USER, db_with(), D("2"), today=TODAY)
        self.assertEqual(p["default_target_envelope_id"], TAB)


class WeightQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_excludes_adjustments(self):
        db = db_with(FakeResult(rows=[(MAKAN, D("5000"))]))
        w = await svc.load_expense_weights([MAKAN], db, TODAY)
        self.assertEqual(w, {str(MAKAN): D("5000")})
        self.assertIn("transactions.balance_check_id IS NULL", sql(db.execute.call_args.args[0]))

    async def test_no_envelopes_skips_query(self):
        db = db_with()
        self.assertEqual(await svc.load_expense_weights([], db, TODAY), {})
        db.execute.assert_not_called()


@patch.object(svc, "get_household_id", new=AsyncMock(return_value=HID))
@patch.object(svc, "compute_envelope_summaries", new=AsyncMock(return_value=ROWS))
class ApplyTests(unittest.IsolatedAsyncioTestCase):
    async def assert_error(self, status, *args):
        with self.assertRaises(svc.BalanceCheckError) as ctx:
            await svc.apply_balance_check(USER, recording_db(), *args, today=TODAY)
        self.assertEqual(ctx.exception.status_code, status)

    async def test_stale_app_amount_409(self):
        await self.assert_error(409, D("1660000"), D("1999000"), [])

    async def test_invalid_lines_400(self):
        await self.assert_error(400, D("1660000"), D("2000000"), [(MAKAN, D("100000"))])

    async def test_saving_envelope_not_allowed_for_expense_400(self):
        await self.assert_error(400, D("1660000"), D("2000000"), [(TAB, D("340000"))])

    async def test_negative_actual_400(self):
        await self.assert_error(400, D("-1"), D("2000000"), [])

    async def test_absurd_actual_400(self):
        await self.assert_error(400, D("10000000000000"), D("2000000"), [])

    async def test_no_household_400(self):
        with patch.object(svc, "get_household_id", new=AsyncMock(return_value=None)):
            await self.assert_error(400, D("1"), D("2000000"), [])

    async def test_unrecorded_expense_creates_tagged_transactions(self):
        db = recording_db()
        out = await svc.apply_balance_check(
            USER, db, D("1660000"), D("2000000"),
            [(MAKAN, D("227000")), (TRANS, D("113000"))], today=TODAY,
        )
        check = db.added[0]
        self.assertIsInstance(check, BalanceCheck)
        self.assertEqual((check.app_amount, check.actual_amount, check.gap, check.household_id),
                         (D("2000000"), D("1660000"), D("-340000"), HID))
        txns = [o for o in db.added if isinstance(o, Transaction)]
        self.assertEqual([(t.envelope_id, t.amount) for t in txns], [(MAKAN, D("227000")), (TRANS, D("113000"))])
        for t in txns:
            self.assertEqual((t.balance_check_id, t.description, t.transaction_date, t.user_id),
                             (check.id, svc.ADJ_TXN_DESC, TODAY, USER_ID))
        self.assertEqual(out["transaction_ids"], [t.id for t in txns])
        self.assertIsNone(out["income_id"])
        db.commit.assert_awaited_once()

    async def test_surplus_creates_tagged_income_and_allocation(self):
        db = recording_db()
        out = await svc.apply_balance_check(USER, db, D("2200000"), D("2000000"), [(TAB, D("200000"))], today=TODAY)
        check = db.added[0]
        income = next(o for o in db.added if isinstance(o, Income))
        alloc = next(o for o in db.added if isinstance(o, Allocation))
        self.assertEqual((income.amount, income.balance_check_id, income.description, income.household_id, income.income_date),
                         (D("200000"), check.id, svc.ADJ_INCOME_DESC, HID, TODAY))
        self.assertEqual((alloc.income_id, alloc.envelope_id, alloc.amount), (income.id, TAB, D("200000")))
        self.assertEqual(out["income_id"], income.id)
        self.assertFalse(any(isinstance(o, Transaction) for o in db.added))

    async def test_match_logs_check_only(self):
        db = recording_db()
        out = await svc.apply_balance_check(USER, db, D("2000000"), D("2000000"), [], today=TODAY)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].gap, D("0"))
        self.assertEqual(out["transaction_ids"], [])

    async def test_expected_amount_compared_to_the_cent(self):
        db = recording_db()
        await svc.apply_balance_check(USER, db, D("2000000"), D("2000000.0"), [], today=TODAY)
        db.commit.assert_awaited_once()


@patch.object(svc, "get_household_id", new=AsyncMock(return_value=HID))
class UndoTests(unittest.IsolatedAsyncioTestCase):
    def latest(self, user_id=USER_ID, check_id=CHECK_ID):
        return SimpleNamespace(id=check_id, user_id=user_id, undone_at=None)

    async def assert_error(self, status, db, check_id=CHECK_ID):
        with self.assertRaises(svc.BalanceCheckError) as ctx:
            await svc.undo_balance_check(USER, db, check_id)
        self.assertEqual(ctx.exception.status_code, status)

    async def test_not_latest_400(self):
        await self.assert_error(400, db_with(FakeResult(self.latest())), check_id=uuid.uuid4())

    async def test_nothing_to_undo_400(self):
        await self.assert_error(400, db_with(FakeResult(None)))

    async def test_other_member_403(self):
        await self.assert_error(403, db_with(FakeResult(self.latest(user_id=uuid.uuid4()))))

    async def test_no_household_404(self):
        with patch.object(svc, "get_household_id", new=AsyncMock(return_value=None)):
            await self.assert_error(404, db_with())

    async def test_undo_soft_deletes_txns_and_removes_income(self):
        latest = self.latest()
        db = db_with(FakeResult(latest), FakeResult(), FakeResult(rows=[uuid.uuid4()]), FakeResult(), FakeResult())
        out = await svc.undo_balance_check(USER, db, CHECK_ID)
        stmts = executed_sql(db)
        self.assertIn("balance_checks.undone_at IS NULL", stmts[0])
        self.assertIn("UPDATE transactions SET is_deleted", stmts[1])
        self.assertIn("DELETE FROM allocations", stmts[3])
        self.assertIn("DELETE FROM incomes", stmts[4])
        self.assertIsNotNone(latest.undone_at)
        db.commit.assert_awaited_once()
        self.assertEqual(out["status"], "undone")

    async def test_undo_without_income(self):
        latest = self.latest()
        db = db_with(FakeResult(latest), FakeResult(), FakeResult(rows=[]))
        await svc.undo_balance_check(USER, db, CHECK_ID)
        self.assertEqual(db.execute.await_count, 3)
        self.assertIsNotNone(latest.undone_at)


@patch.object(svc, "get_household_id", new=AsyncMock(return_value=HID))
class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_with_history(self):
        when = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
        db = db_with(FakeResult(SimpleNamespace(created_at=when, gap=D("-340000"))), FakeResult(2))
        s = await svc.get_status(USER, db)
        self.assertEqual(s, {"last_checked_at": when, "last_gap": D("-340000"), "member_count": 2})
        self.assertIn("balance_checks.undone_at IS NULL", sql(db.execute.call_args_list[0].args[0]))

    async def test_status_never_checked(self):
        s = await svc.get_status(USER, db_with(FakeResult(None), FakeResult(1)))
        self.assertEqual(s, {"last_checked_at": None, "last_gap": None, "member_count": 1})

    async def test_status_without_household(self):
        with patch.object(svc, "get_household_id", new=AsyncMock(return_value=None)):
            s = await svc.get_status(USER, db_with())
        self.assertEqual(s, {"last_checked_at": None, "last_gap": None, "member_count": 0})


if __name__ == "__main__":
    unittest.main()
