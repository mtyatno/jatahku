"""Endpoint pemicu manual (ringkasan harian/mingguan, proses langganan) khusus admin.

Run: python -m unittest app.tests.test_admin_triggers -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.core import deps
from app.api.routes import admin as admin_routes
from app.main import app

TRIGGERS = ("/snapshots/daily-summary", "/snapshots/weekly-summary", "/snapshots/process-recurring")


def _dependency_calls(route):
    return {d.call for d in route.dependant.dependencies}


class RequireAdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_admin_gets_403(self):
        with self.assertRaises(HTTPException) as ctx:
            await deps.require_admin(user=SimpleNamespace(is_admin=False))
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_missing_flag_gets_403(self):
        with self.assertRaises(HTTPException) as ctx:
            await deps.require_admin(user=SimpleNamespace())
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_admin_passes_through(self):
        u = SimpleNamespace(is_admin=True)
        self.assertIs(await deps.require_admin(user=u), u)


class TriggerRoutesTests(unittest.TestCase):
    def test_trigger_routes_require_admin(self):
        routes = {r.path: r for r in app.routes if getattr(r, "path", None) in TRIGGERS}
        self.assertEqual(set(routes), set(TRIGGERS))
        for path, route in routes.items():
            calls = _dependency_calls(route)
            self.assertIn(deps.require_admin, calls, path)
            self.assertNotIn(deps.get_current_user, calls, path)

    def test_admin_router_uses_shared_dependency(self):
        self.assertIs(admin_routes.require_admin, deps.require_admin)


if __name__ == "__main__":
    unittest.main()
