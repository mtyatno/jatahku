# Payday Allocation Reminder — Design Spec

- **Date:** 2026-05-29
- **Status:** Approved (pending spec review)
- **Author:** mtyatno + Claude

## Summary

Send a Telegram reminder when a user's new budget period begins (payday), nudging
them to allocate their salary in the webapp so the money is budgeted for the
period ahead. The reminder re-nudges for up to three days until the user has
allocated, then stops on its own.

## Goal

Increase the share of users who set up their envelope allocation each period.
Right now allocation happens only in the webapp (`jatahku.com/allocate`); there
is no proactive prompt, so users can forget and spend an unbudgeted period.

## Background / current state

- Budget periods are payday-based via `app/core/period.py::get_budget_period`
  (gap-day bug fixed 2026-05-28; periods now tile the timeline cleanly).
- The bot has **no** in-chat income/allocation flow — it only links users to
  `jatahku.com/allocate` (e.g. `app/bot/handlers.py` lines ~1008, ~1139).
- `app/services/scheduler.py::run_user_summaries` already runs **hourly**, is
  **timezone-aware**, iterates all `telegram_id`-linked users, and reads each
  user's `NotificationPreference`. Daily/weekly summaries hang off it.
- `NotificationPreference` follows a `<type>_tg` / `<type>_web` boolean pattern.
- `User` has `payday_day` (default 1), `telegram_id`, `timezone`
  (default `Asia/Jakarta`).

## Requirements

### Functional
1. On the day a user's new budget period starts (`get_budget_period(payday, today).period_start == today`, in the user's timezone), send a Telegram reminder at **08:00 local time**.
2. **Re-nudge** at H+1 and H+2 (max 3 sends per period) only while the user has **not** allocated; stop immediately once they have.
3. "Has allocated" = at least one `Income` with `amount > 0` whose `income_date` falls in the current period, for the user's household.
4. The message includes the new period range and an inline URL button to `https://jatahku.com/allocate`.
5. Users can opt out via a new `payday_reminder_tg` preference (default **on**), exposed as a toggle in Settings.
6. Only users with a linked `telegram_id` are eligible.

### Non-functional
- Reuse the existing hourly, timezone-aware dispatch; no new always-on scheduler job.
- The window/eligibility decision must be a **pure function** (unit-testable without a DB or Telegram).
- No duplicate send within the same local day even if the scheduler restarts during the 08:00 hour.

## Out of scope (this iteration)
- In-chat allocation flow (entering salary + splitting to envelopes via Telegram).
- "Repeat last period's allocation" template.
- WhatsApp/email channel and a web-bell `Notification` row (so no `NotificationType` enum change is needed now).
- Configurable send time (fixed at 08:00 local).

## Design

### Trigger logic (pure, TDD)
`app/core/period.py` (or a small helper near it):

```python
def payday_reminder_day_index(payday_day: int, user_today: date) -> int | None:
    """0/1/2 if user_today is within the first 3 days of the current budget
    period, else None. Drives the 3-day re-nudge window."""
    period_start, _ = get_budget_period(payday_day, user_today)
    idx = (user_today - period_start).days
    return idx if 0 <= idx <= 2 else None
```

- Returns `0` on payday day, `1`/`2` on the two following days, `None` otherwise.
- Relies on the fixed `get_budget_period`, so capped paydays (29–31) and leap years are handled.

### Dispatch integration
Extend `run_user_summaries` (the hourly job). Inside the existing per-user loop, after computing `user_now`/`user_hour`:

```python
if user_hour == "08:00":
    try:
        await send_payday_reminder(user, user_now, prefs, db)
    except Exception as e:
        logger.error(f"Payday reminder failed for {user.id}: {e}")
```

`run_user_summaries` currently constructs no `Bot`; it calls `send_daily_summary`
which builds its own `Bot`. To match that style, `send_payday_reminder` builds its
own `Bot` from settings (or returns early if `TELEGRAM_BOT_TOKEN` is unset).

### Service unit
`app/services/payday_reminder.py`:

```python
async def send_payday_reminder(user, user_now, prefs, db) -> bool:
    # 1. pref gate: prefs.payday_reminder_tg (treat missing prefs as default True)
    # 2. window gate: idx = payday_reminder_day_index(user.payday_day or 1, user_now.date())
    #    if idx is None: return False
    # 3. allocation gate: if await _has_positive_income_this_period(user, db): return False
    # 4. dedup guard: Redis SETNX payday_nudge:{user_id}:{period_start}:{idx}, TTL ~40d
    #    if key already set: return False
    # 5. send Telegram message (day-0 text if idx==0 else re-nudge text) with URL button
    # 6. return True
```

Keep it one purpose: decide-and-send for a single user. The window decision is
delegated to the pure helper.

### Allocation detection
Resolve `:hid` from the user's `HouseholdMember`, then:
```sql
SELECT count(*) FROM incomes
WHERE household_id = :hid AND amount > 0
  AND income_date BETWEEN :period_start AND :period_end
```
`amount > 0` excludes net-zero transfer/refund incomes. count > 0 ⇒ already allocated ⇒ skip.

### Message content
Day 0 (payday):
> 💰 *Gajian tiba!* Saatnya kasih jatah tiap rupiah biar terkendali sampai gajian berikutnya.
> Periode baru: *{period_start} → {period_end}*
> Tap di bawah untuk alokasikan gajimu 👇
>
> `[ 📥 Alokasikan Gaji ]`  → https://jatahku.com/allocate

Re-nudge (H+1, H+2):
> 🔔 Gaji belum dialokasikan nih. Yuk bagi jatahnya dulu biar nggak kebablasan bulan ini.
>
> `[ 📥 Alokasikan Gaji ]`  → https://jatahku.com/allocate

Dates formatted in Indonesian style (e.g. `29 Mei → 28 Jun`). Inline button uses
`InlineKeyboardButton(text, url=...)`.

### Anti-duplicate guard
Redis key `payday_nudge:{user_id}:{period_start_iso}:{idx}` set via `SETNX` with
~40-day TTL before sending; if it already exists, skip. Mirrors the Redis pattern
already used by `check_pending_reminders` (`reminded:{id}`). Redis loss only risks
a rare duplicate, which is acceptable.

### Data model + settings
- `NotificationPreference`: add `payday_reminder_tg: Mapped[bool] = mapped_column(Boolean, default=True)`.
- Alembic migration: `add_column('notification_preferences', 'payday_reminder_tg', Boolean, server_default='true', nullable=False)` (server_default so existing rows backfill to on).
- `app/api/routes/user_settings.py`: include `payday_reminder_tg` in the prefs read/update schema.
- Frontend `Settings` page: add a toggle "Pengingat alokasi gaji (Telegram)" alongside the existing summary toggles.

## Files touched
- `app/core/period.py` — add `payday_reminder_day_index` (+ tests).
- `app/services/payday_reminder.py` — new service.
- `app/services/scheduler.py` — call the service from `run_user_summaries`.
- `app/models/models.py` — add `payday_reminder_tg` column.
- `alembic/versions/<new>_add_payday_reminder_pref.py` — migration.
- `app/api/routes/user_settings.py` — expose the pref.
- `frontend/src/pages/Settings.jsx` — toggle.
- `app/tests/test_payday_reminder.py` — unit tests for the pure helper.

## Testing strategy
- **TDD (stdlib unittest, no pytest in repo):** `payday_reminder_day_index` — returns 0/1/2 inside the first three days, `None` elsewhere; correct across paydays 1/15/28/29/30/31 and leap/non-leap Februaries; specifically the capped-payday boundary days.
- DB/Telegram paths (`send_payday_reminder`, allocation query, Redis guard) verified manually on the server (no local `sqlalchemy`/Telegram harness). Smoke test: temporarily lower the hour gate or call the service directly for a test user and confirm a message arrives.

## Deployment
- Push branch → merge to `main` → GitHub Actions deploy.
- **Run the migration manually** on the VPS (deploy.sh does not run Alembic):
  `cd /opt/jatahku/app && sudo -u jatahku bash -c 'source /opt/jatahku/venv/bin/activate && alembic upgrade head'`
- No scheduler config change (reuses the hourly `user_summaries` cron).

## Risks
- Double-send if the scheduler restarts within the 08:00 hour → mitigated by the Redis guard.
- Timezone correctness depends on `user.timezone`; default `Asia/Jakarta` already applied in `run_user_summaries`.
- If a user's `payday_day` changes mid-period the window shifts; acceptable (rare).
