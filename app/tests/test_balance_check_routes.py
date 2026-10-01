"""Router /balance-check (service di-patch).

Run: python -m unittest app.tests.test_balance_check_routes -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import balance_check as route
from app.services import balance_check as svc

USER = SimpleNamespace(id=uuid.uuid4(), payday_day=1)
DB = object()


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_rejects_negative(self):
        with self.assertRaises(HTTPException) as ctx:
            await route.balance_check_preview(route.PreviewRequest(actual_amount=D("-1")), user=USER, db=DB)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_preview_maps_service_error(self):
        err = svc.BalanceCheckError(400, "Nominal uang riil tidak valid")
        with patch.object(svc, "build_preview", new=AsyncMock(side_effect=err)):
            with self.assertRaises(HTTPException) as ctx:
                await route.balance_check_preview(route.PreviewRequest(actual_amount=D("5")), user=USER, db=DB)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, "Nominal uang riil tidak valid"))

    async def test_preview_delegates(self):
        with patch.object(svc, "build_preview", new=AsyncMock(return_value={"direction": "match"})) as m:
            out = await route.balance_check_preview(route.PreviewRequest(actual_amount=D("5")), user=USER, db=DB)
        self.assertEqual(out, {"direction": "match"})
        m.assert_awaited_once_with(USER, DB, D("5"))

    async def test_apply_passes_lines_as_tuples(self):
        eid = uuid.uuid4()
        req = route.ApplyRequest(actual_amount=D("1"), expected_app_amount=D("2"),
                                 lines=[{"envelope_id": str(eid), "amount": "1"}])
        with patch.object(svc, "apply_balance_check", new=AsyncMock(return_value={"id": "x"})) as m:
            await route.balance_check_apply(req, user=USER, db=DB)
        m.assert_awaited_once_with(USER, DB, D("1"), D("2"), [(eid, D("1"))])

    async def test_apply_maps_service_error(self):
        req = route.ApplyRequest(actual_amount=D("1"), expected_app_amount=D("2"))
        err = svc.BalanceCheckError(409, "Data berubah, cek ulang selisihnya")
        with patch.object(svc, "apply_balance_check", new=AsyncMock(side_effect=err)):
            with self.assertRaises(HTTPException) as ctx:
                await route.balance_check_apply(req, user=USER, db=DB)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (409, "Data berubah, cek ulang selisihnya"))

    async def test_undo_maps_service_error(self):
        with patch.object(svc, "undo_balance_check", new=AsyncMock(side_effect=svc.BalanceCheckError(403, "x"))):
            with self.assertRaises(HTTPException) as ctx:
                await route.balance_check_undo(uuid.uuid4(), user=USER, db=DB)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_status_delegates(self):
        with patch.object(svc, "get_status", new=AsyncMock(return_value={"member_count": 1})):
            self.assertEqual(await route.balance_check_status(user=USER, db=DB), {"member_count": 1})


class ApplyLineTests(unittest.TestCase):
    def test_amount_constraints(self):
        eid = uuid.uuid4()
        for bad in (D("0.001"), D("0"), D("1e30")):
            with self.subTest(amount=bad):
                with self.assertRaises(ValidationError):
                    route.ApplyLine(envelope_id=eid, amount=bad)
        for ok in (D("340000"), D("340000.50")):
            with self.subTest(amount=ok):
                self.assertEqual(route.ApplyLine(envelope_id=eid, amount=ok).amount, ok)


class RegistrationTests(unittest.TestCase):
    def test_routes_mounted(self):
        from app.main import app
        paths = {r.path for r in app.routes}
        for p in ("/balance-check/status", "/balance-check/preview",
                  "/balance-check/apply", "/balance-check/{check_id}/undo"):
            self.assertIn(p, paths)


class AuthTests(unittest.TestCase):
    """Semua endpoint membaca/menulis uang household → wajib login (pola test_admin_triggers)."""

    def test_every_balance_check_route_requires_login(self):
        from app.core import deps
        from app.main import app
        expected = {"/balance-check/status", "/balance-check/preview",
                    "/balance-check/apply", "/balance-check/{check_id}/undo"}
        routes = [r for r in app.routes if getattr(r, "path", "").startswith("/balance-check/")]
        self.assertTrue(expected <= {r.path for r in routes})  # keempat endpoint ada (tes tak kosong)
        for r in routes:  # dan endpoint baru di prefix ini pun harus ikut wajib login
            calls = {d.call for d in r.dependant.dependencies}
            self.assertIn(deps.get_current_user, calls, r.path)


if __name__ == "__main__":
    unittest.main()
