# Payday Allocation Reminder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a Telegram reminder at 08:00 local time when a user's new budget period starts, nudging them to allocate their salary in the webapp, re-nudging H+1/H+2 until they have allocated.

**Architecture:** A pure window helper in `app/core/period.py` decides if today is within the first 3 days of the user's budget period. A new service `app/services/payday_reminder.py` gates on preference + allocation status + a Redis dedup guard, then sends a Telegram message with an inline button to `jatahku.com/allocate`. It is invoked from the existing hourly, timezone-aware `run_user_summaries` job. A new `payday_reminder_tg` preference (default on) gives users an opt-out, surfaced in Settings.

**Tech Stack:** FastAPI, SQLAlchemy (async), Alembic, python-telegram-bot, Redis (`redis.asyncio`), APScheduler, React/Vite. Tests use stdlib `unittest` (no pytest in this repo): `python -m unittest`.

---

## Task 1: Pure window helper `payday_reminder_day_index`

**Files:**
- Modify: `app/core/period.py`
- Test: `app/tests/test_payday_reminder.py`

- [ ] **Step 1: Write the failing test**

Create `app/tests/test_payday_reminder.py`:

```python
"""Tests for payday_reminder_day_index (app/core/period.py).

Run from repo root:  python -m unittest app.tests.test_payday_reminder
"""
import unittest
from datetime import date, timedelta

from app.core.period import payday_reminder_day_index, get_budget_period

PAYDAYS = [1, 15, 28, 29, 30, 31]


def _iter_year(year):
    d = date(year, 1, 1)
    while d <= date(year, 12, 31):
        yield d
        d += timedelta(days=1)


class TestPaydayReminderDayIndex(unittest.TestCase):
    def test_first_three_days_payday_1(self):
        self.assertEqual(payday_reminder_day_index(1, date(2026, 3, 1)), 0)
        self.assertEqual(payday_reminder_day_index(1, date(2026, 3, 2)), 1)
        self.assertEqual(payday_reminder_day_index(1, date(2026, 3, 3)), 2)
        self.assertIsNone(payday_reminder_day_index(1, date(2026, 3, 4)))
        self.assertIsNone(payday_reminder_day_index(1, date(2026, 3, 31)))

    def test_capped_payday_31_february(self):
        # payday 31 in Feb 2026 -> period starts Feb 28
        self.assertEqual(payday_reminder_day_index(31, date(2026, 2, 28)), 0)
        self.assertEqual(payday_reminder_day_index(31, date(2026, 3, 1)), 1)
        self.assertEqual(payday_reminder_day_index(31, date(2026, 3, 2)), 2)
        self.assertIsNone(payday_reminder_day_index(31, date(2026, 3, 3)))

    def test_property_matches_period_start(self):
        for payday in PAYDAYS:
            for today in _iter_year(2026):
                idx = payday_reminder_day_index(payday, today)
                start, _ = get_budget_period(payday, today)
                offset = (today - start).days
                if idx is None:
                    self.assertGreater(offset, 2,
                        f"payday={payday} today={today}: None but offset={offset}")
                else:
                    self.assertEqual(idx, offset)
                    self.assertTrue(0 <= idx <= 2)
                    self.assertEqual(today, start + timedelta(days=idx))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest app.tests.test_payday_reminder -v`
Expected: FAIL — `ImportError: cannot import name 'payday_reminder_day_index'`.

- [ ] **Step 3: Write minimal implementation**

In `app/core/period.py`, add after `get_closed_periods` (keep `timedelta`/`date` imports already present at top):

```python
def payday_reminder_day_index(payday_day: int, user_today: date) -> int | None:
    """0/1/2 if user_today is within the first 3 days of the current budget
    period, else None. Drives the payday-reminder re-nudge window (day 0 =
    payday, days 1-2 = follow-up nudges)."""
    period_start, _ = get_budget_period(payday_day, user_today)
    idx = (user_today - period_start).days
    return idx if 0 <= idx <= 2 else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest app.tests.test_payday_reminder -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full period test suite (no regressions)**

Run: `python -m unittest discover -s app/tests -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/core/period.py app/tests/test_payday_reminder.py
git commit -m "feat: payday_reminder_day_index window helper

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Add `payday_reminder_tg` preference column + migration

**Files:**
- Modify: `app/models/models.py` (class `NotificationPreference`, ~line 286-304)
- Create: `alembic/versions/c2f4a8d6e1b9_add_payday_reminder_pref.py`

- [ ] **Step 1: Add the column to the model**

In `app/models/models.py`, inside `class NotificationPreference`, add the field after `cooling_ready_web`:

```python
    cooling_ready_tg: Mapped[bool] = mapped_column(Boolean, default=True)
    cooling_ready_web: Mapped[bool] = mapped_column(Boolean, default=True)
    payday_reminder_tg: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_summary_time: Mapped[str | None] = mapped_column(String(5), default="20:00")
```

(Only the `payday_reminder_tg` line is new; the surrounding lines show placement.)

- [ ] **Step 2: Create the migration**

Create `alembic/versions/c2f4a8d6e1b9_add_payday_reminder_pref.py`:

```python
"""add payday_reminder_tg to notification_preferences

Revision ID: c2f4a8d6e1b9
Revises: b7e1d9c4a2f8
Create Date: 2026-05-29 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c2f4a8d6e1b9'
down_revision: Union[str, None] = 'b7e1d9c4a2f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'notification_preferences',
        sa.Column('payday_reminder_tg', sa.Boolean(),
                  server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('notification_preferences', 'payday_reminder_tg')
```

- [ ] **Step 3: Verify both files compile**

Run: `python -m py_compile app/models/models.py alembic/versions/c2f4a8d6e1b9_add_payday_reminder_pref.py`
Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add app/models/models.py alembic/versions/c2f4a8d6e1b9_add_payday_reminder_pref.py
git commit -m "feat: add payday_reminder_tg notification preference

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Payday reminder service

**Files:**
- Create: `app/services/payday_reminder.py`

- [ ] **Step 1: Write the service**

Create `app/services/payday_reminder.py`:

```python
import logging
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.period import get_budget_period, payday_reminder_day_index
from app.models.models import HouseholdMember, Income

logger = logging.getLogger("jatahku.payday_reminder")
settings = get_settings()

MONTHS_ID = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
             "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

ALLOCATE_URL = "https://jatahku.com/allocate"


def _fmt(d) -> str:
    return f"{d.day} {MONTHS_ID[d.month]}"


async def _has_allocated_this_period(user, period_start, period_end, db: AsyncSession) -> bool:
    """True if the user's household already has a positive income in this period."""
    hid = (await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )).scalar_one_or_none()
    if not hid:
        return False
    cnt = (await db.execute(
        select(func.count()).select_from(Income).where(
            Income.household_id == hid,
            Income.amount > 0,
            Income.income_date >= period_start,
            Income.income_date <= period_end,
        )
    )).scalar()
    return (cnt or 0) > 0


async def send_payday_reminder(user, user_now: datetime, prefs, db: AsyncSession) -> bool:
    """Send a payday allocation reminder to one Telegram user if due.

    Returns True if a message was sent. Caller (scheduler) gates on the user's
    local hour == 08:00; this function handles pref + window + allocation +
    dedup, then sends."""
    if not settings.TELEGRAM_BOT_TOKEN or not user.telegram_id:
        return False
    # Missing prefs row -> default opt-in
    if prefs is not None and not getattr(prefs, "payday_reminder_tg", True):
        return False

    payday_day = getattr(user, "payday_day", 1) or 1
    today = user_now.date()
    idx = payday_reminder_day_index(payday_day, today)
    if idx is None:
        return False

    period_start, period_end = get_budget_period(payday_day, today)
    if await _has_allocated_this_period(user, period_start, period_end, db):
        return False

    # Dedup guard: at most one send per (user, period, day-index)
    import redis.asyncio as aioredis
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        key = f"payday_nudge:{user.id}:{period_start.isoformat()}:{idx}"
        first = await r.set(key, "1", ex=3456000, nx=True)  # 40-day TTL
        if not first:
            return False
    finally:
        await r.close()

    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    if idx == 0:
        text = (
            "💰 <b>Gajian tiba!</b> Saatnya kasih jatah tiap rupiah biar "
            "terkendali sampai gajian berikutnya.\n\n"
            f"Periode baru: <b>{_fmt(period_start)} → {_fmt(period_end)}</b>\n"
            "Tap di bawah untuk alokasikan gajimu 👇"
        )
    else:
        text = (
            "🔔 Gaji belum dialokasikan nih. Yuk bagi jatahnya dulu biar "
            "nggak kebablasan bulan ini."
        )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📥 Alokasikan Gaji", url=ALLOCATE_URL)]]
    )
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    await bot.send_message(
        chat_id=int(user.telegram_id),
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    logger.info(f"Payday reminder (day {idx}) sent to {user.telegram_id}")
    return True
```

- [ ] **Step 2: Verify it compiles**

Run: `python -m py_compile app/services/payday_reminder.py`
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add app/services/payday_reminder.py
git commit -m "feat: payday reminder service (Telegram + dedup guard)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Wire into the hourly scheduler job

**Files:**
- Modify: `app/services/scheduler.py` (`run_user_summaries`, the weekly-summary block ~line 173-177)

- [ ] **Step 1: Add the payday-reminder call**

In `app/services/scheduler.py`, inside `run_user_summaries`, immediately after the weekly-summary `if` block and before the loop ends, add:

```python
            # Payday allocation reminder (08:00 local, first 3 days of period)
            if user_hour == "08:00":
                try:
                    from app.services.payday_reminder import send_payday_reminder
                    await send_payday_reminder(user, user_now, prefs, db)
                except Exception as e:
                    logger.error(f"Payday reminder failed for {user.id}: {e}")
```

The surrounding context (existing code) for placement:

```python
            # Weekly summary (Monday only)
            if user_now.weekday() == 0 and prefs and prefs.weekly_summary_tg and user_hour == weekly_time.split(':')[0] + ':00':
                try:
                    await send_weekly_summary(user_id=user.id)
                except Exception as e:
                    logger.error(f"Weekly summary failed for {user.id}: {e}")

            # Payday allocation reminder (08:00 local, first 3 days of period)
            if user_hour == "08:00":
                try:
                    from app.services.payday_reminder import send_payday_reminder
                    await send_payday_reminder(user, user_now, prefs, db)
                except Exception as e:
                    logger.error(f"Payday reminder failed for {user.id}: {e}")
```

- [ ] **Step 2: Verify it compiles**

Run: `python -m py_compile app/services/scheduler.py`
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add app/services/scheduler.py
git commit -m "feat: dispatch payday reminder from hourly summary job

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Expose the preference in the API

**Files:**
- Modify: `app/api/routes/notifications.py` (`PrefsUpdate` ~line 95, `get_preferences` ~line 117)

- [ ] **Step 1: Add the field to `PrefsUpdate`**

In `app/api/routes/notifications.py`, add to `class PrefsUpdate` after `cooling_ready_web`:

```python
    cooling_ready_tg: bool = True
    cooling_ready_web: bool = True
    payday_reminder_tg: bool = True
    daily_summary_time: str = "20:00"
```

(Only the `payday_reminder_tg` line is new.)

- [ ] **Step 2: Return it from `get_preferences`**

In the `get_preferences` return dict, add after `cooling_ready_web`:

```python
        "cooling_ready_tg": prefs.cooling_ready_tg,
        "cooling_ready_web": prefs.cooling_ready_web,
        "payday_reminder_tg": prefs.payday_reminder_tg,
        "daily_summary_time": prefs.daily_summary_time or "20:00",
```

(Only the `payday_reminder_tg` line is new. The PUT handler already does
`setattr(prefs, key, val)` for every field, so no change needed there.)

- [ ] **Step 3: Verify it compiles**

Run: `python -m py_compile app/api/routes/notifications.py`
Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add app/api/routes/notifications.py
git commit -m "feat: expose payday_reminder_tg in notification preferences API

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Settings UI toggle

**Files:**
- Modify: `frontend/src/pages/Settings.jsx` (`NotifPrefs`, the rows table ~line 76-82)

- [ ] **Step 1: Add a dedicated TG-only toggle row**

In `frontend/src/pages/Settings.jsx`, the generic `rows` render both a `_tg` and `_web` checkbox. The payday reminder is TG-only, so add it as a separate row right after the `{rows.map(...)}` block closes (after the `))}` of the rows map, still inside the same container `<div>`):

```jsx
      ))}
      <div className="grid grid-cols-3 gap-2 items-center pt-1 border-t border-gray-100">
        <span className="text-sm text-gray-600">Pengingat alokasi gaji</span>
        <label className="flex justify-center">
          <input
            type="checkbox"
            checked={!!prefs.payday_reminder_tg}
            onChange={() => toggle('payday_reminder_tg')}
            className="w-4 h-4 rounded border-gray-300 text-brand-600"
          />
        </label>
        <span className="text-center text-xs text-gray-300">—</span>
      </div>
```

(The third column shows "—" because there is no web channel for this reminder.)

- [ ] **Step 2: Verify the frontend builds**

Run: `cd frontend && npx vite build`
Expected: `✓ built` with no errors. Then return to repo root: `cd ..`

- [ ] **Step 3: Commit (source only, not dist)**

```bash
git add frontend/src/pages/Settings.jsx
git commit -m "feat: payday reminder opt-out toggle in Settings

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Deploy + manual verification

**Files:** none (operational)

- [ ] **Step 1: Merge to main and deploy**

```bash
git checkout main
git merge --no-ff feat/payday-allocation-reminder
git push origin main
```

GitHub Actions runs `sudo /opt/jatahku/deploy.sh` (pull, restart backend, rebuild frontend).

- [ ] **Step 2: Run the migration manually on the VPS**

deploy.sh does NOT run Alembic. On the server:

```bash
cd /opt/jatahku/app
sudo -u jatahku bash -c 'source /opt/jatahku/venv/bin/activate && alembic upgrade head'
sudo -u jatahku bash -c 'source /opt/jatahku/venv/bin/activate && alembic current'
```

Expected: `alembic current` shows `c2f4a8d6e1b9 (head)`.

- [ ] **Step 3: Smoke-test the reminder for one user**

On the server, run a one-off that bypasses the 08:00 hour gate by calling the
service directly for a Telegram-linked test user (replace EMAIL):

```bash
cd /opt/jatahku/app
sudo -u jatahku bash -c 'source /opt/jatahku/venv/bin/activate && python3 - <<PY
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import User, NotificationPreference
from app.services.payday_reminder import send_payday_reminder

EMAIL = "REPLACE_WITH_TEST_USER_EMAIL"

async def main():
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == EMAIL))).scalar_one_or_none()
        if not user:
            print("user not found"); return
        prefs = (await db.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user.id)
        )).scalar_one_or_none()
        tz = ZoneInfo(user.timezone or "Asia/Jakarta")
        now = datetime.now(tz)
        sent = await send_payday_reminder(user, now, prefs, db)
        print("sent:", sent, "(False is expected unless today is in the first 3 days of the period and no income yet)")
asyncio.run(main())
PY'
```

Expected: prints `sent: True` and a Telegram message arrives **only if** today is
within the first 3 days of that user's period and they have no positive income yet;
otherwise `sent: False`. To force a visible send for testing, pick a user whose
period started in the last 3 days, or temporarily widen the window in the helper
on a scratch branch.

- [ ] **Step 4: Verify the Settings toggle**

Open the webapp Settings → Notifications, confirm "Pengingat alokasi gaji" toggle
appears, toggles, and persists (reload keeps the value).

---

## Notes for the implementer
- Run all backend tests with `python -m unittest discover -s app/tests` (no pytest).
- `sqlalchemy`/Telegram/Redis are NOT installed locally on the dev Windows box — only Task 1 is unit-testable locally; Tasks 2-6 are verified with `py_compile` / `vite build`; Task 7 covers real runtime verification on the server.
- Frontend builds regenerate `frontend/dist/` — never commit those; commit only `frontend/src/**`.
