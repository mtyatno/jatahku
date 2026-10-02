"""send_checkin_nudge: pengingat "belum ada catatan hari ini" hanya untuk akun
yang bisa mencatat. Akun bot dari /start yang belum punya amplop dulu tetap
diminta mencatat tiap malam padahal pencatatannya diblok.

Run: python -m unittest app.tests.test_checkin_nudge -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.scheduler import send_checkin_nudge

USER = SimpleNamespace(id=uuid.uuid4(), telegram_id="777", email=None)
TODAY = date(2026, 10, 2)


class CheckinNudgeTests(unittest.IsolatedAsyncioTestCase):
    async def nudge(self, ready):
        db = MagicMock()
        db.get = AsyncMock(return_value=None)  # belum ada streak: belum mencatat & belum di-nudge
        db.commit = AsyncMock()
        bot_cls = MagicMock()
        bot_cls.return_value.send_message = AsyncMock()
        setup = AsyncMock(return_value=(True, "ok") if ready else (False, "no_envelopes"))
        with patch("telegram.Bot", bot_cls), \
             patch("app.core.config.get_settings", return_value=SimpleNamespace(TELEGRAM_BOT_TOKEN="token")), \
             patch("app.bot.handlers._is_setup_complete", new=setup):
            await send_checkin_nudge(USER, TODAY, db)
        return bot_cls.return_value.send_message

    async def test_account_without_envelopes_is_not_nudged(self):
        send = await self.nudge(ready=False)
        send.assert_not_awaited()

    async def test_ready_account_that_has_not_logged_is_nudged(self):
        send = await self.nudge(ready=True)
        send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
