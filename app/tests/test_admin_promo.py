import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.api.routes import admin as admin_routes
from app.models.models import PromoCode
from app.tests.fakes import FakeResult, db_with


class AdminPromoCodeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin = MagicMock()
        self.admin.is_admin = True
        self.promo_id = uuid.uuid4()
        self.existing_promo = PromoCode(
            id=self.promo_id,
            code="EXISTING50",
            discount_pct=50,
            is_free=False,
            max_uses=10,
            used_count=2,
            event_name="Early Bird",
            is_active=True,
            valid_from=datetime.now(timezone.utc),
            valid_until=datetime.now(timezone.utc) + timedelta(days=5),
            created_at=datetime.now(timezone.utc),
        )

    async def test_toggle_active_deactivates_and_activates(self):
        db = MagicMock()
        db.execute = AsyncMock(return_value=FakeResult(self.existing_promo))
        db.commit = AsyncMock()

        # Toggle from True -> False
        res = await admin_routes.toggle_promo_active(
            promo_id=self.promo_id,
            admin=self.admin,
            db=db,
        )
        self.assertEqual(res["status"], "updated")
        self.assertFalse(res["is_active"])
        self.assertFalse(self.existing_promo.is_active)

        # Toggle from False -> True
        res2 = await admin_routes.toggle_promo_active(
            promo_id=self.promo_id,
            admin=self.admin,
            db=db,
        )
        self.assertTrue(res2["is_active"])
        self.assertTrue(self.existing_promo.is_active)

    async def test_update_promo_details_success(self):
        # 1st execute finds promo, 2nd execute checks code uniqueness (None)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[
            FakeResult(self.existing_promo),
            FakeResult(None),
        ])
        db.commit = AsyncMock()

        req = admin_routes.PromoUpdate(
            code="NEWCODE100",
            is_free=True,
            max_uses=50,
            event_name="Mega Sale",
            valid_days=14,
        )

        res = await admin_routes.update_promo(
            promo_id=self.promo_id,
            req=req,
            admin=self.admin,
            db=db,
        )

        self.assertEqual(res["code"], "NEWCODE100")
        self.assertEqual(self.existing_promo.code, "NEWCODE100")
        self.assertTrue(self.existing_promo.is_free)
        self.assertEqual(self.existing_promo.discount_pct, 100)
        self.assertEqual(self.existing_promo.max_uses, 50)
        self.assertEqual(self.existing_promo.event_name, "Mega Sale")
        self.assertIsNotNone(self.existing_promo.valid_until)

    async def test_update_promo_code_duplicate_raises_400(self):
        other_promo = PromoCode(id=uuid.uuid4(), code="TAKENCODE")
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[
            FakeResult(self.existing_promo),
            FakeResult(other_promo),  # duplicate found!
        ])
        db.commit = AsyncMock()

        req = admin_routes.PromoUpdate(code="TAKENCODE")
        with self.assertRaises(HTTPException) as ctx:
            await admin_routes.update_promo(
                promo_id=self.promo_id,
                req=req,
                admin=self.admin,
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("sudah digunakan", ctx.exception.detail)

    async def test_update_promo_valid_days_zero_clears_expiration(self):
        db = MagicMock()
        db.execute = AsyncMock(return_value=FakeResult(self.existing_promo))
        db.commit = AsyncMock()

        req = admin_routes.PromoUpdate(valid_days=0)
        await admin_routes.update_promo(
            promo_id=self.promo_id,
            req=req,
            admin=self.admin,
            db=db,
        )
        self.assertIsNone(self.existing_promo.valid_until)


if __name__ == "__main__":
    unittest.main()
