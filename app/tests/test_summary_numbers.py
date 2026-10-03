"""Angka ringkasan harian/mingguan Telegram = dashboard (rollover, cadangan, sisa
bebas), nama amplop aman untuk parse_mode HTML, "Minggu ini" = 7 hari.

Run: python -m unittest app.tests.test_summary_numbers -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import summary
from app.tests.fakes import FakeResult, executed_sql


def row(name="Makan", emoji="🍜", purpose="expense", allocated=0, rollover=0,
        spent=0, reserved=0, env_id=None):
    """Bentuk baris compute_envelope_summaries (rumus yang sama)."""
    allocated, rollover, spent, reserved = D(allocated), D(rollover), D(spent), D(reserved)
    remaining = allocated + rollover - spent
    total = allocated + rollover
    return {
        "id": env_id or uuid.uuid4(), "name": name, "emoji": emoji, "purpose": purpose,
        "allocated": allocated, "rollover": rollover, "spent": spent,
        "reserved": reserved, "remaining": remaining, "free": remaining - reserved,
        "spent_ratio": round(float(spent / total), 4) if total > 0 else 0.0,
    }


class PeriodTotalsTests(unittest.TestCase):
    def test_totals_match_dashboard_kpi(self):
        rows = [
            # expense + rollover: free = 100k + 50k - 30k = 120k
            row("Makan", allocated=100_000, rollover=50_000, spent=30_000),
            # expense + cadangan langganan: free = 200k - 50k - 80k = 70k
            row("Hiburan", allocated=200_000, spent=50_000, reserved=80_000),
            # saving: free 500k - 0 = 500k (bukan sisa bebas)
            row("Tabungan", purpose="saving", allocated=500_000, rollover=100_000, spent=100_000),
            # sinking fund: free 300k + 20k - 0 - 0 = 320k (bukan sisa bebas)
            row("Servis", purpose="sinking_fund", allocated=300_000, rollover=20_000),
        ]
        dana, terpakai, sisa_bebas = summary._period_totals(rows)
        # dana = (100k+50k) + 200k + (500k+100k) + (300k+20k) = 1.270k
        self.assertEqual(dana, D("1270000"))
        self.assertEqual(terpakai, D("180000"))
        # sisa bebas = 120k + 70k (tanpa saving/sinking_fund)
        self.assertEqual(sisa_bebas, D("190000"))

    def test_empty(self):
        self.assertEqual(summary._period_totals([]), (D(0), D(0), D(0)))

    def test_purpose_enum_value_is_recognised(self):
        from app.models.models import PurposeType
        rows = [row("Tabungan", purpose=PurposeType.saving, allocated=100_000),
                row("Makan", allocated=40_000)]
        self.assertEqual(summary._period_totals(rows)[2], D("40000"))


class EnvelopeLineTests(unittest.TestCase):
    def test_uses_free_including_rollover(self):
        line = summary._envelope_line(
            row("Makan", allocated=100_000, rollover=50_000, spent=30_000, reserved=20_000))
        # free = 100k + 50k - 30k - 20k = 100k ; 30k/150k = 20% → 🟢
        self.assertIn("<b>Rp100rb</b>", line)
        self.assertTrue(line.startswith("🟢 🍜 Makan · "))
        self.assertIn("20%", line)

    def test_indicator_uses_dana_with_rollover(self):
        # 80k / (50k + 50k) = 0.8 → 🟡 (tanpa rollover akan 1.6 → 🔴)
        line = summary._envelope_line(row(allocated=50_000, rollover=50_000, spent=80_000))
        self.assertTrue(line.startswith("🟡"))
        self.assertIn("80%", line)

    def test_name_is_html_escaped(self):
        line = summary._envelope_line(row("Makan & <Jajan>", allocated=100_000))
        self.assertIn("Makan &amp; &lt;Jajan&gt;", line)
        self.assertNotIn("<Jajan>", line)

    def test_no_funds_is_white(self):
        line = summary._envelope_line(row(allocated=0, spent=0))
        self.assertTrue(line.startswith("⚪"))
        self.assertIn("<b>habis</b>", line)

    def test_free_not_positive_is_habis(self):
        line = summary._envelope_line(row(allocated=100_000, spent=60_000, reserved=40_000))
        self.assertIn("<b>habis</b>", line)


class WeekWindowTests(unittest.TestCase):
    def test_seven_days_inclusive(self):
        self.assertEqual(summary._week_window(date(2026, 10, 5)),
                         (date(2026, 9, 29), date(2026, 10, 5)))


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


class SenderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Loop per-user: user Telegram melewati sender penuh; DB & Bot di-mock."""

    def setUp(self):
        self.env_id = uuid.uuid4()
        self.user = SimpleNamespace(id=uuid.uuid4(), telegram_id="777",
                                    payday_day=1, timezone=None)
        self.rows = [
            # free = 100k + 50k - 30k - 20k = 100k (Rp100rb; tanpa rollover akan Rp50rb)
            row("Kopi&Teh & Jajan", allocated=100_000, rollover=50_000, spent=30_000,
                reserved=20_000, env_id=self.env_id),
            row("Tabungan", emoji="💰", purpose="saving", allocated=500_000),
        ]
        self.txn = SimpleNamespace(envelope_id=self.env_id, amount=D("30000"),
                                   transaction_date=date.today())

    def make_db(self):
        hid = uuid.uuid4()
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[
            FakeResult(rows=[self.user]),     # users ter-link
            FakeResult(hid),                  # household_id
            FakeResult(rows=[self.txn]),      # transaksi hari ini / minggu ini
        ])
        db.get = AsyncMock(return_value=None)  # get_streak → tanpa streak
        return db

    async def run_sender(self, sender):
        db = self.make_db()
        compute = AsyncMock(return_value=self.rows)
        bot_cls = MagicMock()
        bot_cls.return_value.send_message = AsyncMock()
        with patch.object(summary, "AsyncSessionLocal", new=lambda: FakeSession(db)), \
                patch.object(summary, "compute_envelope_summaries", new=compute), \
                patch.object(summary, "Bot", new=bot_cls), \
                patch.object(summary.settings, "TELEGRAM_BOT_TOKEN", "token"), \
                patch.object(summary.logger, "error") as log_error:
            await sender(user_id=self.user.id)
        log_error.assert_not_called()
        compute.assert_awaited_once_with(self.user, db)
        self.assertEqual(db.execute.await_count, 3)
        self.assertIn("FROM users", executed_sql(db)[0])
        send = bot_cls.return_value.send_message
        send.assert_awaited_once()
        kwargs = send.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], 777)
        self.assertEqual(kwargs["parse_mode"], "HTML")
        return kwargs["text"]

    async def test_daily(self):
        text = await self.run_sender(summary.send_daily_summary)
        self.assertIn("🍜 Kopi&amp;Teh &amp; Jajan · <b>Rp100rb</b>", text)
        self.assertNotIn("Kopi&Teh", text)  # '&' mentah merusak parse_mode HTML
        self.assertIn("🍜 Kopi&amp;Teh Rp30rb", text)  # top-2 hari ini

    async def test_weekly(self):
        text = await self.run_sender(summary.send_weekly_summary)
        # dana = 150k + 500k ; terpakai 30k ; sisa bebas = 100k (tabungan tidak ikut)
        self.assertIn("Dana:     <b>Rp650rb</b>", text)
        self.assertIn("Terpakai: <b>Rp30rb</b>", text)
        self.assertIn("Sisa:     <b>Rp100rb</b>", text)
        self.assertIn("🍜 Kopi&amp;Teh Rp30rb", text)
        self.assertNotIn("Kopi&Teh", text)
        self.assertIn("1/7 hari", text)
        ws, we = summary._week_window(date.today())
        self.assertIn(f"Minggu ini · {ws.strftime('%d')}–{we.strftime('%d %b')}", text)


if __name__ == "__main__":
    unittest.main()
