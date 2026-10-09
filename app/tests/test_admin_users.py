import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import datetime, timezone, date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.api.routes import admin as admin_routes
from app.models.models import User, HouseholdRole
from app.tests.fakes import FakeResult


class AdminUsersTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin = MagicMock()
        self.admin.is_admin = True
        self.user_id = uuid.uuid4()
        self.user = User(
            id=self.user_id,
            email="budi@example.com",
            name="Budi Pratama",
            telegram_id="12345678",
            google_id=None,
            plan="pro",
            is_admin=False,
            income_type="monthly",
            payday_day=25,
            timezone="Asia/Jakarta",
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
            last_login=datetime.now(timezone.utc) - timedelta(hours=2),
        )

    async def test_list_users_enriched_data(self):
        db = MagicMock()
        # Query 1: users query -> returns [self.user]
        # Query 2: txn_stats_res -> returns row with txn_count=10, last_txn_at=now - 2 days
        # Query 3: month_spent_res -> returns row with month_spent=500000
        # Query 4: env_count_res -> returns row with env_count=4
        txn_row = SimpleNamespace(
            user_id=self.user_id,
            txn_count=10,
            last_txn_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        spent_row = SimpleNamespace(
            user_id=self.user_id,
            month_spent=500000.0,
        )
        env_row = SimpleNamespace(
            user_id=self.user_id,
            env_count=4,
        )

        db.execute = AsyncMock(side_effect=[
            FakeResult(rows=[self.user]),
            FakeResult(rows=[txn_row]),
            FakeResult(rows=[spent_row]),
            FakeResult(rows=[env_row]),
        ])

        users = await admin_routes.list_users(
            search=None,
            plan=None,
            status=None,
            limit=50,
            offset=0,
            admin=self.admin,
            db=db,
        )

        self.assertEqual(len(users), 1)
        u_data = users[0]
        self.assertEqual(u_data["id"], str(self.user_id))
        self.assertEqual(u_data["name"], "Budi Pratama")
        self.assertEqual(u_data["email"], "budi@example.com")
        self.assertEqual(u_data["txn_count"], 10)
        self.assertEqual(u_data["envelopes_count"], 4)
        self.assertEqual(u_data["month_spent"], 500000.0)
        self.assertEqual(u_data["auth_provider"], "email")
        self.assertEqual(u_data["status"], "active")
        self.assertEqual(u_data["payday_day"], 25)

    async def test_get_user_detail_success(self):
        db = MagicMock()
        # 1. user
        # 2. txn_stat_res -> txn_count, last_txn_at, total_spent
        # 3. month_spent_res
        # 4. hm_res -> (HouseholdMember, Household)
        # 5. member_count
        # 6. env_res -> [Envelope]
        # 7. txns_res -> [(Transaction, env_name, env_emoji)]

        txn_stat = SimpleNamespace(
            txn_count=5,
            last_txn_at=datetime.now(timezone.utc) - timedelta(days=1),
            total_spent=1200000.0,
        )

        hm = MagicMock()
        hm.role = HouseholdRole.owner
        hh = MagicMock()
        hh.id = uuid.uuid4()
        hh.name = "Rumah Budi"
        hh.currency = "IDR"

        env1 = MagicMock()
        env1.id = uuid.uuid4()
        env1.name = "Makan"
        env1.emoji = "🍔"
        env1.budget_amount = 1500000.0
        env1.purpose = "expense"
        env1.classification = "needs"
        env1.is_rollover = True
        env1.owner_id = None

        txn1 = MagicMock()
        txn1.id = uuid.uuid4()
        txn1.amount = 45000.0
        txn1.description = "Nasi Padang"
        txn1.transaction_date = date.today()
        txn1.created_at = datetime.now(timezone.utc)
        txn1.source = "webapp"
        txn1.balance_check_id = None

        db.execute = AsyncMock(side_effect=[
            FakeResult(value=self.user),
            SimpleNamespace(one=lambda: txn_stat),
            FakeResult(value=350000.0),
            SimpleNamespace(first=lambda: (hm, hh)),
            FakeResult(value=2),
            FakeResult(rows=[env1]),
            SimpleNamespace(all=lambda: [(txn1, "Makan", "🍔")]),
        ])

        detail = await admin_routes.get_user_detail(
            user_id=self.user_id,
            admin=self.admin,
            db=db,
        )

        self.assertIn("user", detail)
        self.assertIn("stats", detail)
        self.assertIn("household", detail)
        self.assertIn("envelopes", detail)
        self.assertIn("recent_transactions", detail)

        self.assertEqual(detail["stats"]["txn_count"], 5)
        self.assertEqual(detail["stats"]["month_spent"], 350000.0)
        self.assertEqual(detail["household"]["name"], "Rumah Budi")
        self.assertEqual(len(detail["envelopes"]), 1)
        self.assertEqual(detail["envelopes"][0]["name"], "Makan")
        self.assertEqual(len(detail["recent_transactions"]), 1)
        self.assertEqual(detail["recent_transactions"][0]["description"], "Nasi Padang")

    async def test_get_user_detail_not_found(self):
        db = MagicMock()
        db.execute = AsyncMock(return_value=FakeResult(value=None))

        with self.assertRaises(HTTPException) as ctx:
            await admin_routes.get_user_detail(
                user_id=uuid.uuid4(),
                admin=self.admin,
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
