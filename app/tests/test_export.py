import unittest
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.api.routes.export import _resolve_period, _get_export_data, export_csv, export_pdf
from app.models.models import TransactionSource


class ExportPeriodTests(unittest.IsolatedAsyncioTestCase):
    def test_resolve_period_explicit_range(self):
        user = SimpleNamespace(id=uuid4(), payday_day=25)
        start = date(2026, 3, 10)
        end = date(2026, 3, 20)
        p_start, p_end = _resolve_period(user, period_start=start, period_end=end)
        self.assertEqual(p_start, start)
        self.assertEqual(p_end, end)

    def test_resolve_period_from_year_month_payday_25(self):
        user = SimpleNamespace(id=uuid4(), payday_day=25)
        p_start, p_end = _resolve_period(user, year=2026, month=3)
        self.assertEqual(p_start, date(2026, 3, 25))
        self.assertEqual(p_end, date(2026, 4, 24))

    def test_resolve_period_from_year_month_payday_1(self):
        user = SimpleNamespace(id=uuid4(), payday_day=1)
        p_start, p_end = _resolve_period(user, year=2026, month=3)
        self.assertEqual(p_start, date(2026, 3, 1))
        self.assertEqual(p_end, date(2026, 3, 31))

    def test_resolve_period_default(self):
        user = SimpleNamespace(id=uuid4(), payday_day=None)
        p_start, p_end = _resolve_period(user)
        self.assertIsInstance(p_start, date)
        self.assertIsInstance(p_end, date)
        self.assertLess(p_start, p_end)

    async def test_get_export_data_calculations(self):
        user_id = uuid4()
        user = SimpleNamespace(id=user_id, name="Budi", payday_day=1)
        env_id = uuid4()
        env = SimpleNamespace(
            id=env_id,
            name="Makan",
            emoji="🍜",
            budget_amount=Decimal("1000000"),
            is_rollover=True,
            is_active=True,
            owner_id=None,
            created_at=date(2026, 1, 1),
        )

        txn = SimpleNamespace(
            id=uuid4(),
            user_id=user_id,
            envelope_id=env_id,
            amount=Decimal("50000"),
            description="Makan Siang",
            is_private=False,
            is_deleted=False,
            transaction_date=date(2026, 3, 15),
            source=TransactionSource.webapp,
        )

        db = MagicMock()
        # 1. hid query
        hid_res = MagicMock()
        hid_res.scalar_one_or_none = MagicMock(return_value=uuid4())

        # 2. envelopes query
        env_res = MagicMock()
        env_res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[env])))

        # 3. transactions query
        txn_res = MagicMock()
        txn_res.all = MagicMock(return_value=[(txn, "Budi")])

        # 4. spent query
        spent_res = MagicMock()
        spent_res.scalar = MagicMock(return_value=Decimal("50000"))

        # 5. allocated query
        alloc_res = MagicMock()
        alloc_res.scalar = MagicMock(return_value=Decimal("800000"))

        # 6. rollover query
        snap_res = MagicMock()
        snap_res.scalar_one_or_none = MagicMock(return_value=Decimal("100000"))

        db.execute = AsyncMock(side_effect=[
            hid_res,
            env_res,
            txn_res,
            spent_res,
            alloc_res,
            snap_res,
        ])

        p_start = date(2026, 3, 1)
        p_end = date(2026, 3, 31)
        txns, summaries, env_map = await _get_export_data(user, db, p_start, p_end)

        self.assertEqual(len(txns), 1)
        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        self.assertEqual(s["name"], "Makan")
        self.assertEqual(s["spent"], Decimal("50000"))
        self.assertEqual(s["allocated"], Decimal("800000"))
        self.assertEqual(s["rollover"], Decimal("100000"))
        # effective budget = allocated + rollover (800k + 100k = 900k)
        self.assertEqual(s["budget"], Decimal("900000"))
        # remaining = (allocated + rollover) - spent = 900k - 50k = 850k
        self.assertEqual(s["remaining"], Decimal("850000"))

    async def test_get_export_data_fallback_budget(self):
        user_id = uuid4()
        user = SimpleNamespace(id=user_id, name="Budi", payday_day=1)
        env_id = uuid4()
        env = SimpleNamespace(
            id=env_id,
            name="Tabungan",
            emoji="💰",
            budget_amount=Decimal("500000"),
            is_rollover=False,
            is_active=True,
            owner_id=None,
            created_at=date(2026, 1, 1),
        )

        db = MagicMock()
        hid_res = MagicMock()
        hid_res.scalar_one_or_none = MagicMock(return_value=uuid4())
        env_res = MagicMock()
        env_res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[env])))
        txn_res = MagicMock()
        txn_res.all = MagicMock(return_value=[])
        spent_res = MagicMock()
        spent_res.scalar = MagicMock(return_value=Decimal("0"))
        alloc_res = MagicMock()
        alloc_res.scalar = MagicMock(return_value=Decimal("0"))

        db.execute = AsyncMock(side_effect=[
            hid_res,
            env_res,
            txn_res,
            spent_res,
            alloc_res,
        ])

        p_start = date(2026, 3, 1)
        p_end = date(2026, 3, 31)
        txns, summaries, env_map = await _get_export_data(user, db, p_start, p_end)

        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        # when allocated + rollover == 0 -> budget falls back to env.budget_amount
        self.assertEqual(s["budget"], Decimal("500000"))
        self.assertEqual(s["remaining"], Decimal("0"))

    async def test_export_csv_output(self):
        user_id = uuid4()
        user = SimpleNamespace(id=user_id, name="Budi", payday_day=1)
        env_id = uuid4()
        env = SimpleNamespace(
            id=env_id,
            name="Makan",
            emoji="🍜",
            budget_amount=Decimal("1000000"),
            is_rollover=False,
            is_active=True,
            owner_id=None,
            created_at=date(2026, 1, 1),
        )

        txn = SimpleNamespace(
            id=uuid4(),
            user_id=user_id,
            envelope_id=env_id,
            amount=Decimal("25000"),
            description="Bakso",
            is_private=False,
            is_deleted=False,
            transaction_date=date(2026, 3, 5),
            source=TransactionSource.webapp,
        )

        db = MagicMock()
        hid_res = MagicMock()
        hid_res.scalar_one_or_none = MagicMock(return_value=uuid4())
        env_res = MagicMock()
        env_res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[env])))
        txn_res = MagicMock()
        txn_res.all = MagicMock(return_value=[(txn, "Budi")])
        spent_res = MagicMock()
        spent_res.scalar = MagicMock(return_value=Decimal("25000"))
        alloc_res = MagicMock()
        alloc_res.scalar = MagicMock(return_value=Decimal("500000"))

        db.execute = AsyncMock(side_effect=[
            hid_res,
            env_res,
            txn_res,
            spent_res,
            alloc_res,
        ])

        response = await export_csv(
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            user=user,
            db=db,
        )

        content = ""
        async for chunk in response.body_iterator:
            content += chunk if isinstance(chunk, str) else chunk.decode("utf-8")

        self.assertIn("Periode: 01 Mar 2026 – 31 Mar 2026", content)
        self.assertIn("Makan", content)
        self.assertIn("Bakso", content)
        self.assertIn("attachment; filename=jatahku_2026-03-01_2026-03-31.csv", response.headers["content-disposition"])

    async def test_export_pdf_output(self):
        user_id = uuid4()
        user = SimpleNamespace(id=user_id, name="Budi", payday_day=1)
        env_id = uuid4()
        env = SimpleNamespace(
            id=env_id,
            name="Makan",
            emoji="🍜",
            budget_amount=Decimal("1000000"),
            is_rollover=False,
            is_active=True,
            owner_id=None,
            created_at=date(2026, 1, 1),
        )

        txn = SimpleNamespace(
            id=uuid4(),
            user_id=user_id,
            envelope_id=env_id,
            amount=Decimal("25000"),
            description="Bakso",
            is_private=False,
            is_deleted=False,
            transaction_date=date(2026, 3, 5),
            source=TransactionSource.webapp,
        )

        db = MagicMock()
        hid_res = MagicMock()
        hid_res.scalar_one_or_none = MagicMock(return_value=uuid4())
        env_res = MagicMock()
        env_res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[env])))
        txn_res = MagicMock()
        txn_res.all = MagicMock(return_value=[(txn, "Budi")])
        spent_res = MagicMock()
        spent_res.scalar = MagicMock(return_value=Decimal("25000"))
        alloc_res = MagicMock()
        alloc_res.scalar = MagicMock(return_value=Decimal("500000"))

        db.execute = AsyncMock(side_effect=[
            hid_res,
            env_res,
            txn_res,
            spent_res,
            alloc_res,
        ])

        response = await export_pdf(
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            user=user,
            db=db,
        )

        content = ""
        async for chunk in response.body_iterator:
            content += chunk if isinstance(chunk, str) else chunk.decode("utf-8", errors="ignore")

        self.assertIn("Periode: 01 Mar 2026 – 31 Mar 2026", content)
        self.assertIn("Makan", content)
        self.assertIn("Bakso", content)

    async def test_export_privacy_masking(self):
        viewer_id = uuid4()
        other_user_id = uuid4()
        user = SimpleNamespace(id=viewer_id, name="Budi", payday_day=1)
        env_id = uuid4()
        env = SimpleNamespace(
            id=env_id,
            name="Bersama",
            emoji="🏠",
            budget_amount=Decimal("1000000"),
            is_rollover=False,
            is_active=True,
            owner_id=None,
            created_at=date(2026, 1, 1),
        )

        # Other user's private transaction
        other_private_txn = SimpleNamespace(
            id=uuid4(),
            user_id=other_user_id,
            envelope_id=env_id,
            amount=Decimal("50000"),
            description="Kado Rahasia",
            is_private=True,
            is_deleted=False,
            transaction_date=date(2026, 3, 10),
            source=TransactionSource.webapp,
        )

        # Viewer's own private transaction
        my_private_txn = SimpleNamespace(
            id=uuid4(),
            user_id=viewer_id,
            envelope_id=env_id,
            amount=Decimal("30000"),
            description="Beli Buku",
            is_private=True,
            is_deleted=False,
            transaction_date=date(2026, 3, 12),
            source=TransactionSource.webapp,
        )

        db = MagicMock()
        hid_res = MagicMock()
        hid_res.scalar_one_or_none = MagicMock(return_value=uuid4())
        env_res = MagicMock()
        env_res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[env])))
        txn_res = MagicMock()
        txn_res.all = MagicMock(return_value=[(other_private_txn, "Siti"), (my_private_txn, "Budi")])
        spent_res = MagicMock()
        spent_res.scalar = MagicMock(return_value=Decimal("80000"))
        alloc_res = MagicMock()
        alloc_res.scalar = MagicMock(return_value=Decimal("1000000"))

        db.execute = AsyncMock(side_effect=[
            hid_res,
            env_res,
            txn_res,
            spent_res,
            alloc_res,
        ])

        response = await export_csv(
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            user=user,
            db=db,
        )

        content = ""
        async for chunk in response.body_iterator:
            content += chunk if isinstance(chunk, str) else chunk.decode("utf-8")

        # Siti's private description is masked
        self.assertNotIn("Kado Rahasia", content)
        self.assertIn("Transaksi privat", content)

        # Budi's own private description is visible to Budi
        self.assertIn("Beli Buku", content)


if __name__ == "__main__":
    unittest.main()
