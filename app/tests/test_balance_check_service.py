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

from sqlalchemy.dialects import postgresql

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

    async def test_invalid_actual_400(self):
        for bad in (D("NaN"), D("Infinity"), D("-Infinity"), D("-1"), D("1e30")):
            with self.subTest(actual=bad):
                with self.assertRaises(svc.BalanceCheckError) as ctx:
                    await svc.build_preview(USER, db_with(), bad, today=TODAY)
                self.assertEqual(ctx.exception.status_code, 400)

    async def test_sub_cent_actual_is_normalized(self):
        p = await svc.build_preview(USER, db_with(), D("2000000.004"), today=TODAY)
        self.assertEqual((p["direction"], p["gap"], p["actual_amount"]),
                         ("match", D("0"), D("2000000.00")))

    async def test_actual_at_the_numeric_limit(self):
        p = await svc.build_preview(USER, db_with(), D("9999999999999.99"), today=TODAY)  # muat Numeric(15, 2)
        self.assertEqual(p["actual_amount"], D("9999999999999.99"))
        with self.assertRaises(svc.BalanceCheckError) as ctx:  # membulat ke 10^13 → meluap
            await svc.build_preview(USER, db_with(), D("9999999999999.995"), today=TODAY)
        self.assertEqual(ctx.exception.status_code, 400)


class WeightQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_excludes_adjustments(self):
        db = db_with(FakeResult(rows=[(MAKAN, D("5000"))]))
        w = await svc.load_expense_weights([MAKAN], db, TODAY)
        self.assertEqual(w, {str(MAKAN): D("5000")})
        stmt = db.execute.call_args.args[0]
        text = sql(stmt)
        self.assertIn("transactions.balance_check_id IS NULL", text)
        self.assertIn("transactions.is_deleted = false", text)
        self.assertIn("transactions.envelope_id IN", text)
        # jendela 30 hari inklusif: [TODAY - 29 hari, TODAY]
        self.assertIn("transactions.transaction_date >= %(transaction_date_1)s", text)
        self.assertIn("transactions.transaction_date <= %(transaction_date_2)s", text)
        params = stmt.compile(dialect=postgresql.dialect()).params
        self.assertEqual(params["transaction_date_1"], date(2026, 9, 1))
        self.assertEqual(params["transaction_date_2"], TODAY)

    async def test_no_envelopes_skips_query(self):
        db = db_with()
        self.assertEqual(await svc.load_expense_weights([], db, TODAY), {})
        db.execute.assert_not_called()


@patch.object(svc, "get_household_id", new=AsyncMock(return_value=HID))
@patch.object(svc, "compute_envelope_summaries", new=AsyncMock(return_value=ROWS))
class ApplyTests(unittest.IsolatedAsyncioTestCase):
    async def assert_error(self, status, *args):
        """Error apa pun tidak menulis apa-apa. Hasil antrean db = kunci baris household."""
        db = recording_db(FakeResult(HID))
        with self.assertRaises(svc.BalanceCheckError) as ctx:
            await svc.apply_balance_check(USER, db, *args, today=TODAY)
        self.assertEqual(ctx.exception.status_code, status)
        self.assertEqual(db.added, [])
        db.commit.assert_not_awaited()
        return db

    async def test_stale_app_amount_409(self):
        db = await self.assert_error(409, D("1660000"), D("1999000"), [])
        self.assertEqual(db.execute.await_count, 1)  # dikunci dulu, baru ketahuan basi

    async def test_one_cent_off_is_stale_409(self):
        await self.assert_error(409, D("1660000"), D("1999999.99"), [])

    async def test_negative_expected_is_not_invalid(self):
        # total app boleh negatif (overspend): bukan 400 "tidak valid", melainkan basi → 409
        await self.assert_error(409, D("1660000"), D("-5"), [])

    async def test_invalid_lines_400(self):
        await self.assert_error(400, D("1660000"), D("2000000"), [(MAKAN, D("100000"))])

    async def test_saving_envelope_not_allowed_for_expense_400(self):
        await self.assert_error(400, D("1660000"), D("2000000"), [(TAB, D("340000"))])

    async def test_negative_actual_400(self):
        db = await self.assert_error(400, D("-1"), D("2000000"), [])
        db.execute.assert_not_called()  # ditolak sebelum kunci household

    async def test_absurd_actual_400(self):
        db = await self.assert_error(400, D("10000000000000"), D("2000000"), [])
        db.execute.assert_not_called()

    async def test_non_finite_or_huge_actual_400(self):
        for bad in (D("NaN"), D("Infinity"), D("-Infinity"), D("1e30")):
            with self.subTest(actual=bad):
                db = await self.assert_error(400, bad, D("2000000"), [])
                db.execute.assert_not_called()

    async def test_non_finite_or_huge_expected_400(self):
        for bad in (D("NaN"), D("Infinity"), D("1e30"), D("-1e30")):
            with self.subTest(expected=bad):
                db = await self.assert_error(400, D("1660000"), bad, [])
                db.execute.assert_not_called()

    async def test_no_household_400(self):
        with patch.object(svc, "get_household_id", new=AsyncMock(return_value=None)):
            db = await self.assert_error(400, D("1"), D("2000000"), [])
        db.execute.assert_not_called()  # tanpa household tak ada yang bisa dikunci

    async def test_unrecorded_expense_creates_tagged_transactions(self):
        db = recording_db(FakeResult(HID))
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
        # satu-satunya statement ke DB = kunci baris household (kueri saldo di-patch)
        stmts = executed_sql(db)
        self.assertEqual(len(stmts), 1)
        self.assertIn("FROM households", stmts[0])
        self.assertIn("households.id = ", stmts[0])
        self.assertIn("FOR NO KEY UPDATE", stmts[0])

    async def test_household_locked_before_app_amount_is_recomputed(self):
        # Penerus kunci harus menghitung ulang SETELAH kunci: ia melihat data yang sudah
        # di-commit pemegang sebelumnya (READ COMMITTED) → 409, bukan double-apply.
        db = recording_db(FakeResult(HID))
        at_recompute = []

        async def recompute(user, session):
            at_recompute.extend(executed_sql(session))
            return ROWS

        with patch.object(svc, "compute_envelope_summaries", new=recompute):
            await svc.apply_balance_check(USER, db, D("2000000"), D("2000000"), [], today=TODAY)
        self.assertEqual(len(at_recompute), 1)
        self.assertIn("FOR NO KEY UPDATE", at_recompute[0])

    async def test_actual_normalized_to_the_cent(self):
        db = recording_db(FakeResult(HID))
        await svc.apply_balance_check(
            USER, db, D("1660000.004"), D("2000000"),
            [(MAKAN, D("227000")), (TRANS, D("113000"))], today=TODAY,
        )
        check = db.added[0]
        self.assertEqual((check.actual_amount, check.gap), (D("1660000.00"), D("-340000.00")))

    async def test_sub_cent_surplus_is_a_match_without_zero_value_rows(self):
        db = recording_db(FakeResult(HID))
        out = await svc.apply_balance_check(USER, db, D("2000000.004"), D("2000000"), [], today=TODAY)
        self.assertEqual((len(db.added), out["gap"]), (1, D("0")))
        self.assertFalse(any(isinstance(o, (Income, Allocation)) for o in db.added))

    async def test_surplus_creates_tagged_income_and_allocation(self):
        db = recording_db(FakeResult(HID))
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
        db = recording_db(FakeResult(HID))
        out = await svc.apply_balance_check(USER, db, D("2000000"), D("2000000"), [], today=TODAY)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].gap, D("0"))
        self.assertEqual(out["transaction_ids"], [])

    async def test_expected_amount_compared_to_the_cent(self):
        db = recording_db(FakeResult(HID))
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

    # Statement pertama setiap undo = kunci baris household (hasilnya tak dipakai) → FakeResult() kosong.

    async def test_not_latest_400(self):
        await self.assert_error(400, db_with(FakeResult(), FakeResult(self.latest())), check_id=uuid.uuid4())

    async def test_nothing_to_undo_400(self):
        await self.assert_error(400, db_with(FakeResult(), FakeResult(None)))

    async def test_other_member_403(self):
        await self.assert_error(403, db_with(FakeResult(), FakeResult(self.latest(user_id=uuid.uuid4()))))

    async def test_no_household_404(self):
        with patch.object(svc, "get_household_id", new=AsyncMock(return_value=None)):
            await self.assert_error(404, db_with())

    async def test_household_locked_before_latest_check_is_read(self):
        # Kunci dulu, baru baca "cek terakhir": undo & apply bersamaan tak boleh saling menyalip
        # (undo membatalkan cek yang sudah bukan yang terakhir). Berlaku juga di jalur penolakan.
        db = db_with(FakeResult(), FakeResult(None))
        await self.assert_error(400, db)
        stmts = executed_sql(db)
        self.assertEqual(len(stmts), 2)
        self.assertIn("FROM households", stmts[0])
        self.assertIn("FOR NO KEY UPDATE", stmts[0])
        self.assertIn("FROM balance_checks", stmts[1])

    async def test_undo_soft_deletes_txns_and_removes_income(self):
        latest = self.latest()
        db = db_with(FakeResult(), FakeResult(latest), FakeResult(), FakeResult(rows=[uuid.uuid4()]),
                     FakeResult(), FakeResult())
        out = await svc.undo_balance_check(USER, db, CHECK_ID)
        stmts = executed_sql(db)
        # kunci household dulu (sama dengan apply) — undo tak boleh menyalip apply yang sedang jalan
        self.assertIn("FROM households", stmts[0])
        self.assertIn("households.id = ", stmts[0])
        self.assertIn("FOR NO KEY UPDATE", stmts[0])
        # "terakhir" = cek household ini yang belum di-undo, terbaru dulu
        self.assertIn("balance_checks.undone_at IS NULL", stmts[1])
        self.assertIn("balance_checks.household_id = ", stmts[1])
        self.assertIn("ORDER BY balance_checks.created_at DESC", stmts[1])
        # tiap penulisan dibatasi ke baris milik cek ini saja
        self.assertIn("UPDATE transactions SET is_deleted", stmts[2])
        self.assertIn("transactions.balance_check_id = ", stmts[2])
        self.assertIn("incomes.balance_check_id = ", stmts[3])
        self.assertIn("DELETE FROM allocations", stmts[4])
        self.assertIn("allocations.income_id IN", stmts[4])
        self.assertIn("DELETE FROM incomes", stmts[5])
        self.assertIn("incomes.id IN", stmts[5])
        self.assertIsNotNone(latest.undone_at)
        db.commit.assert_awaited_once()
        self.assertEqual(out["status"], "undone")

    async def test_undo_without_income(self):
        latest = self.latest()
        db = db_with(FakeResult(), FakeResult(latest), FakeResult(), FakeResult(rows=[]))
        await svc.undo_balance_check(USER, db, CHECK_ID)
        self.assertEqual(db.execute.await_count, 4)  # kunci + cek terakhir + update txn + cari income
        self.assertIsNotNone(latest.undone_at)


@patch.object(svc, "get_household_id", new=AsyncMock(return_value=HID))
class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_with_history(self):
        when = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
        db = db_with(FakeResult(SimpleNamespace(created_at=when, gap=D("-340000"))), FakeResult(2))
        s = await svc.get_status(USER, db)
        self.assertEqual(s, {"last_checked_at": when, "last_gap": D("-340000"), "member_count": 2})
        stmts = executed_sql(db)
        self.assertIn("balance_checks.undone_at IS NULL", stmts[0])
        self.assertIn("balance_checks.household_id = ", stmts[0])
        self.assertIn("household_members.household_id = ", stmts[1])

    async def test_status_never_checked(self):
        s = await svc.get_status(USER, db_with(FakeResult(None), FakeResult(1)))
        self.assertEqual(s, {"last_checked_at": None, "last_gap": None, "member_count": 1})

    async def test_status_without_household(self):
        with patch.object(svc, "get_household_id", new=AsyncMock(return_value=None)):
            s = await svc.get_status(USER, db_with())
        self.assertEqual(s, {"last_checked_at": None, "last_gap": None, "member_count": 0})


if __name__ == "__main__":
    unittest.main()
